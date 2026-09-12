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


def _remove_orphaned_representations(model: ifcopenshell.file) -> int:
    """Remove IfcRepresentation entities with no remaining products.

    Returns the count of removed representations.
    """
    # Collect IDs first to avoid modifying during iteration
    orphan_ids = []
    for rep in model.by_type("IfcRepresentation"):
        try:
            if model.get_total_inverses(rep) == 0:
                orphan_ids.append(rep.id())
        except Exception:
            continue

    removed = 0
    for rid in orphan_ids:
        try:
            rep = model.by_id(rid)
            # Also remove orphaned items
            try:
                for item in rep.Items or []:
                    try:
                        if model.get_total_inverses(item) == 0:
                            model.remove(item)
                    except Exception:
                        pass
            except Exception:
                pass
            model.remove(rep)
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

    # IMPORTANT: use IFC entity ids (stable), NOT Python id() — ifcopenshell
    # creates a new wrapper object per attribute access, so Python id() never
    # matches across lookups.
    remove_ids = {p.id() for p in products_to_remove}

    # Step 1: Detach from spatial containment (fast batch)
    for rel in model.by_type("IfcRelContainedInSpatialStructure"):
        related = list(rel.RelatedElements or [])
        keep = [e for e in related if e.id() not in remove_ids]
        if len(keep) != len(related):
            rel.RelatedElements = keep

    # Step 2: Clean decomposition relationships referencing these products.
    # If the RelatingObject (parent) was removed, drop the whole relationship
    # (children become standalone). Otherwise filter removed children out.
    for rel_type in ("IfcRelDecomposes", "IfcRelNests", "IfcRelAggregates"):
        for rel in model.by_type(rel_type):
            try:
                if rel.RelatingObject is not None and rel.RelatingObject.id() in remove_ids:
                    model.remove(rel)
                    continue
                objs = list(rel.RelatedObjects or [])
                keep = [o for o in objs if o.id() not in remove_ids]
                if len(keep) != len(objs):
                    rel.RelatedObjects = keep
            except Exception:
                pass

    # Step 2.5: Remove relationships that reference removed products
    # (voids, fills, connections, boundaries). If left behind, they hold
    # Blank references after model.remove() and break the geometry engine
    # ("Type held at index N is class Blank"). Removing the relationship
    # is correct: a kept wall with a removed opening simply becomes solid.
    rels_to_delete = []
    skip_types = ("IfcRelContainedInSpatialStructure", "IfcRelAggregates",
                  "IfcRelNests", "IfcRelDecomposes")
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

    logger.info(
        "Orphan cleanup: %d representations, %d contexts, %d owner histories",
        orphaned_reps, orphaned_ctx, orphaned_hist,
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
