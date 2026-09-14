"""Stripped IFC export: clone original IFC and remove interior elements.

Produces a structurally valid IFC file containing only exterior
(and optionally ambiguous) elements, with orphaned relationships cleaned up.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

import ifcopenshell
import ifcopenshell.api
import ifcopenshell.util.element

from ..core.models import Classification, Element

logger = logging.getLogger(__name__)


def _child_representations(entity) -> list:
    """Child representations of a shape or representation entity.

    IfcProductDefinitionShape uses 'Items' (IFC2X3/IFC4) or 'Representations'
    (IFC4X3); IfcShapeRepresentation always uses 'Items'.
    """
    for attr in ("Items", "Representations"):
        try:
            children = getattr(entity, attr, None)
        except Exception:
            children = None
        if children:
            return list(children)
    return []


def _remove_orphaned_representations(model: ifcopenshell.file) -> int:
    """Remove representation-tree entities no product references anymore.

    Covers IfcRepresentation subtypes and IfcProductDefinitionShape (which is
    NOT an IfcRepresentation subtype in IFC4/IFC4X3, so a plain
    by_type("IfcRepresentation") scan misses it). Orphaned shapes are
    cascaded: their sub-representations and geometry items are removed too,
    unless still referenced by a surviving owner.

    Returns the count of removed roots (shapes + representations).
    """
    # 1. Orphaned roots: zero inverses means no product/map/aspect references.
    orphan_ids = set()
    for rep in model.by_type("IfcRepresentation"):
        try:
            if model.get_total_inverses(rep) == 0:
                orphan_ids.add(rep.id())
        except Exception:
            continue
    for shape in model.by_type("IfcProductDefinitionShape"):
        try:
            if model.get_total_inverses(shape) == 0:
                orphan_ids.add(shape.id())
        except Exception:
            continue
    if not orphan_ids:
        return 0

    # 2. Sub-representations owned by a SURVIVING shape/map/aspect must stay.
    owned_subrep_ids = set()
    for shape in model.by_type("IfcProductDefinitionShape"):
        if shape.id() in orphan_ids:
            continue
        for child in _child_representations(shape):
            owned_subrep_ids.add(child.id())
    for rep_map in model.by_type("IfcRepresentationMap"):
        try:
            owned_subrep_ids.add(rep_map.MappedRepresentation.id())
        except Exception:
            continue
    for aspect in model.by_type("IfcShapeAspect"):
        try:
            for rep in aspect.Representations or []:
                owned_subrep_ids.add(rep.id())
        except Exception:
            continue

    # 3. Cascade each orphan: delete sub-reps not owned elsewhere, then
    #    geometry items with no remaining inverses (keeps shared geometry).
    removed = 0
    for rid in sorted(orphan_ids):
        try:
            root = model.by_id(rid)
        except Exception:
            continue
        stack = _child_representations(root)
        while stack:
            child = stack.pop()
            try:
                if child.is_a("IfcRepresentation"):
                    if child.id() in owned_subrep_ids:
                        continue  # shared with a surviving owner
                    stack.extend(_child_representations(child))
                    model.remove(child)
                elif model.get_total_inverses(child) == 0:
                    model.remove(child)
            except Exception:
                continue
        try:
            model.remove(root)
            removed += 1
        except Exception:
            continue
    return removed


def _remove_orphaned_contexts(model: ifcopenshell.file) -> int:
    """Remove IfcGeometricRepresentationContext/SubContext with no representations."""
    # Collect IDs first
    ctx_ids = []
    sub_parent_ids = set()
    for sub in model.by_type("IfcGeometricRepresentationSubContext"):
        try:
            if sub.ParentContext:
                sub_parent_ids.add(sub.ParentContext.id())
        except Exception:
            continue

    for ctx in model.by_type("IfcGeometricRepresentationContext"):
        try:
            if ctx.id() not in sub_parent_ids:
                reps = ctx.RepresentationsInContext
                if reps is None or len(reps) == 0:
                    ctx_ids.append(ctx.id())
        except Exception:
            continue

    removed = 0
    for cid in ctx_ids:
        try:
            model.remove(model.by_id(cid))
            removed += 1
        except Exception:
            continue
    return removed


def _remove_orphaned_owner_history(model: ifcopenshell.file) -> int:
    """Remove orphaned IfcOwnerHistory entries (no remaining inverses)."""
    orphan_ids = []
    for history in model.by_type("IfcOwnerHistory"):
        try:
            if model.get_total_inverses(history) == 0:
                orphan_ids.append(history.id())
        except Exception:
            continue

    removed = 0
    for hid in orphan_ids:
        try:
            model.remove(model.by_id(hid))
            removed += 1
        except Exception:
            continue
    return removed


def export_stripped_ifc(
    input_path: str | Path,
    output_path: str | Path,
    elements: list[Element],
    *,
    keep_ambiguous: bool = True,
) -> dict:
    """Export a stripped IFC file containing only exterior elements.

    Clones the original IFC to ``output_path``, then removes all
    interior-classified elements using ifcopenshell's ``remove_product``
    API for clean relationship teardown.

    Args:
        input_path: Path to the original IFC file.
        output_path: Path for the stripped output IFC file.
        elements: Classified elements from the extraction pipeline.
        keep_ambiguous: If True (default), ambiguous elements are kept
            (they default to exterior in the pipeline).

    Returns:
        dict with removal stats: ``removed_count``, ``kept_count``,
        ``orphaned_reps_removed``, ``orphaned_contexts_removed``,
        ``orphaned_history_removed``.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    if not input_path.exists():
        raise FileNotFoundError(f"Input IFC not found: {input_path}")

    # Collect interior element GlobalIds
    interior_global_ids = {
        e.global_id for e in elements
        if e.classification == Classification.INTERIOR
    }
    if not keep_ambiguous:
        interior_global_ids |= {
            e.global_id for e in elements
            if e.classification == Classification.AMBIGUOUS
        }

    logger.info(
        "Stripping IFC: %d interior elements to remove out of %d total",
        len(interior_global_ids), len(elements),
    )

    # Copy original to output path
    shutil.copy2(str(input_path), str(output_path))

    # Open the copy and remove interior elements
    model = ifcopenshell.open(str(output_path))

    # Map GlobalIds to IFC products
    products_by_gid: dict[str, ifcopenshell.entity_instance] = {}
    for product in model.by_type("IfcProduct"):
        if product.GlobalId:
            products_by_gid[product.GlobalId] = product

    # Collect products to remove
    products_to_remove = []
    for gid in interior_global_ids:
        product = products_by_gid.get(gid)
        if product is not None:
            products_to_remove.append(product)
        else:
            logger.warning("Interior element GlobalId %s not found in IFC", gid)

    # Spatial structure anchors are never removed, even if classified interior
    # (e.g. by AI or a custom rule): IfcProject → IfcSite → IfcBuilding →
    # IfcBuildingStorey is the hierarchy every IFC viewer requires. Stripping
    # any of them leaves dangling containment relations and empty aggregations,
    # which strict viewers (BIMvision, BIMcollab) reject on load.
    spatial_anchors = [
        p for p in products_to_remove
        if p.is_a("IfcSite") or p.is_a("IfcBuilding") or p.is_a("IfcBuildingStorey")
    ]
    if spatial_anchors:
        logger.info(
            "Keeping %d spatial structure elements (never stripped)",
            len(spatial_anchors),
        )
        protected_ids = {p.id() for p in spatial_anchors}
        products_to_remove = [
            p for p in products_to_remove if p.id() not in protected_ids
        ]

    # IMPORTANT: use IFC entity ids (stable), NOT Python id() — ifcopenshell
    # creates a new wrapper object per attribute access, so Python id() never
    # matches across lookups.
    remove_ids = {p.id() for p in products_to_remove}

    # Capture each removed container's parent so elements contained in a
    # removed IfcSpace can be reassigned to the nearest surviving ancestor.
    parent_of: dict[int, ifcopenshell.entity_instance] = {}
    for rel in model.by_type("IfcRelAggregates"):
        for child in rel.RelatedObjects or []:
            if child.id() in remove_ids:
                parent_of[child.id()] = rel.RelatingObject

    def _surviving_ancestor(removed_id: int):
        """Walk up the aggregation chain to the nearest container that survives."""
        seen: set[int] = set()
        current = parent_of.get(removed_id)
        while current is not None and current.id() not in seen:
            if current.id() not in remove_ids:
                return current
            seen.add(current.id())
            current = parent_of.get(current.id())
        return None

    # Step 1: Fix spatial containment (IfcRelContainedInSpatialStructure).
    # - Filter removed elements out of RelatedElements.
    # - If the RelatingStructure was removed (e.g. an IfcSpace), reassign the
    #   relation to the nearest surviving ancestor so kept elements stay
    #   contained; drop the relation if there is none.
    # - Drop relations left with no elements (RelatedElements is SET [1:?]).
    orphaned_elements = 0
    empty_containment_ids = []
    for rel in model.by_type("IfcRelContainedInSpatialStructure"):
        related = list(rel.RelatedElements or [])
        keep = [e for e in related if e.id() not in remove_ids]
        structure = rel.RelatingStructure
        if structure is not None and structure.id() in remove_ids:
            target = _surviving_ancestor(structure.id())
            if target is not None and keep:
                rel.RelatingStructure = target
                rel.RelatedElements = keep
            else:
                orphaned_elements += len(keep)
                empty_containment_ids.append(rel.id())
        elif len(keep) != len(related):
            if keep:
                rel.RelatedElements = keep
            else:
                empty_containment_ids.append(rel.id())
    for rel_id in empty_containment_ids:
        try:
            model.remove(model.by_id(rel_id))
        except Exception:
            pass
    if orphaned_elements:
        logger.warning(
            "%d kept elements lost spatial containment (no surviving ancestor)",
            orphaned_elements,
        )

    # Step 2: Clean decomposition relationships referencing these products.
    # If the RelatingObject (parent) was removed, drop the whole relationship
    # (children become standalone). Otherwise filter removed children out;
    # drop the relationship if nothing remains (empty sets are invalid IFC).
    # Note: in IFC4X3 IfcRelDecomposes is abstract and by_type also matches
    # IfcRelVoidsElement, which has no RelatingObject/RelatedObjects — skip it
    # here (voids are deleted in step 2.5).
    for rel_type in ("IfcRelDecomposes", "IfcRelNests", "IfcRelAggregates"):
        for rel in model.by_type(rel_type):
            if not (hasattr(rel, "RelatingObject") and hasattr(rel, "RelatedObjects")):
                continue
            try:
                if rel.RelatingObject is not None and rel.RelatingObject.id() in remove_ids:
                    model.remove(rel)
                    continue
                objs = list(rel.RelatedObjects or [])
                keep = [o for o in objs if o.id() not in remove_ids]
                if len(keep) != len(objs):
                    if keep:
                        rel.RelatedObjects = keep
                    else:
                        model.remove(rel)
            except Exception:
                pass

    # Step 2.5: Remove relationships that reference removed products
    # (voids, fills, connections, boundaries). If left behind, they hold
    # Blank references after model.remove() and break the geometry engine
    # ("Type held at index N is class Blank"). Removing the relationship
    # is correct: a kept wall with a removed opening simply becomes solid.
    # Note: do NOT skip IfcRelDecomposes here — in IFC4X3 it is abstract and
    # is_a("IfcRelDecomposes") also matches IfcRelVoidsElement, which would
    # silently keep void relations with dangling opening references.
    rels_to_delete = []
    skip_types = ("IfcRelContainedInSpatialStructure", "IfcRelAggregates",
                  "IfcRelNests")
    for rel in model.by_type("IfcRelationship"):
        if any(rel.is_a(t) for t in skip_types):
            continue  # already filtered above
        try:
            for attr_value in rel:
                if attr_value is None:
                    continue
                if isinstance(attr_value, (list, tuple)):
                    if any(getattr(e, "id", lambda: -1)() in remove_ids
                           for e in attr_value):
                        rels_to_delete.append(rel.id())
                        break
                elif (hasattr(attr_value, "id")
                      and attr_value.id() in remove_ids):
                    rels_to_delete.append(rel.id())
                    break
        except Exception:
            continue

    for rel_id in rels_to_delete:
        try:
            model.remove(model.by_id(rel_id))
        except Exception:
            pass
    logger.info("Removed %d relationships referencing interior products",
                len(rels_to_delete))

    # Step 3: Remove the products themselves (model.remove is fast)
    removed_count = 0
    for product in products_to_remove:
        try:
            model.remove(product)
            removed_count += 1
        except Exception:
            pass

    kept_count = len(model.by_type("IfcProduct"))

    # Clean up orphaned entities
    orphaned_reps = _remove_orphaned_representations(model)
    orphaned_ctx = _remove_orphaned_contexts(model)
    orphaned_hist = _remove_orphaned_owner_history(model)

    # Drop presentation layer assignments left with no items
    # (AssignedItems is SET [1:?]; an empty assignment is invalid IFC).
    empty_layers = 0
    for layer in model.by_type("IfcPresentationLayerAssignment"):
        if not (layer.AssignedItems or []):
            try:
                model.remove(layer)
                empty_layers += 1
            except Exception:
                pass

    logger.info(
        "Orphan cleanup: %d representations, %d contexts, %d owner histories, "
        "%d empty layer assignments",
        orphaned_reps, orphaned_ctx, orphaned_hist, empty_layers,
    )

    # Write the stripped file
    model.write(str(output_path))
    output_size = output_path.stat().st_size
    input_size = input_path.stat().st_size

    result = {
        "removed_count": removed_count,
        "kept_count": kept_count,
        "orphaned_reps_removed": orphaned_reps,
        "orphaned_contexts_removed": orphaned_ctx,
        "orphaned_history_removed": orphaned_hist,
        "input_size": input_size,
        "output_size": output_size,
        "size_reduction_pct": round((1 - output_size / input_size) * 100, 1) if input_size > 0 else 0.0,
    }

    logger.info(
        "Stripped IFC written: %s (%d KB, %.1f%% reduction)",
        output_path, output_size // 1024, result["size_reduction_pct"],
    )

    return result
