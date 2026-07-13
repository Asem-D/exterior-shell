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

    # Remove interior products
    removed_count = 0
    kept_count = 0
    for gid in interior_global_ids:
        product = products_by_gid.get(gid)
        if product is None:
            logger.warning("Interior element GlobalId %s not found in IFC", gid)
            continue
        product_name = product.Name or gid
        try:
            ifcopenshell.api.run("root.remove_product", model, product=product)
            removed_count += 1
            logger.debug("Removed %s (%s)", gid, product_name)
        except Exception as exc:
            logger.warning("Failed to remove %s: %s", gid, exc)

    # Count kept products
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
