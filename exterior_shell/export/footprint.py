"""2D footprint exporter — project exterior shell to floor plan with elevation."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
from shapely.geometry import Polygon, mapping
from shapely.ops import unary_union

from ..core.models import ShellGeometry, ExtractionResult, ClassificationReport

logger = logging.getLogger(__name__)


def compute_footprint(faces):
    """Project 3D shell faces to a 2D building outline with elevation attributes.

    Takes triangulated exterior faces, projects each triangle to the XY plane,
    unions them into a single outline polygon, and computes base_elevation and
    height from the original Z coordinates.

    Args:
        faces: List of Face objects (3D triangulated exterior faces).

    Returns:
        Dict with keys: polygon (shapely Polygon), base_elevation (float),
        height (float), bbox_2d (tuple), area (float). Or None if no valid
        geometry.
    """
    if not faces:
        return None

    polygons_2d = []
    all_z = []

    for face in faces:
        try:
            verts = face.vertices  # (3, 3) array
            # Extract 2D coordinates (drop Z)
            coords_2d = [(float(v[0]), float(v[1])) for v in verts]
            # Collect Z values
            all_z.extend(float(v[2]) for v in verts)
            # Close ring if needed
            if coords_2d[0] != coords_2d[-1]:
                coords_2d.append(coords_2d[0])
            poly = Polygon(coords_2d)
            if poly.is_valid and not poly.is_empty:
                polygons_2d.append(poly)
        except Exception:
            continue

    if not polygons_2d:
        return None

    # Union all 2D triangles into a single outline
    try:
        outline = unary_union(polygons_2d)
    except Exception:
        outline = unary_union(polygons_2d)

    if outline is None or outline.is_empty:
        return None

    # Compute elevation stats from original 3D coordinates
    base_elevation = min(all_z) if all_z else 0.0
    max_elevation = max(all_z) if all_z else 0.0
    height = max_elevation - base_elevation

    # Bounding box (2D)
    bounds = outline.bounds  # (minx, miny, maxx, maxy)

    return {
        "polygon": outline,
        "base_elevation": round(base_elevation, 6),
        "height": round(height, 6),
        "min_elevation": round(base_elevation, 6),
        "max_elevation": round(max_elevation, 6),
        "bbox_2d": bounds,
        "area": round(outline.area, 6),
    }


def export_footprint_geojson(
    shell: ShellGeometry,
    output_path: str | Path,
    crs: str = "EPSG:4326",
) -> dict | None:
    """Export a 2D building footprint as GeoJSON with elevation attributes.

    Projects exterior shell faces to 2D, unions into a single outline,
    and attaches base_elevation, height, area, and bbox attributes.
    Output is a GeoJSON FeatureCollection with one feature.

    Args:
        shell: Assembled shell geometry with 3D faces.
        output_path: Path for output .geojson file.
        crs: Output coordinate reference system (default: EPSG:4326).

    Returns:
        Dict with footprint attributes, or None if no valid geometry.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fp = compute_footprint(shell.faces)
    if fp is None:
        logger.warning("No valid footprint geometry to export")
        return None

    feature = {
        "type": "Feature",
        "properties": {
            "name": "exterior_footprint",
            "element_count": shell.element_count,
            "face_count": shell.total_face_count,
            "base_elevation": fp["base_elevation"],
            "height": fp["height"],
            "min_elevation": fp["min_elevation"],
            "max_elevation": fp["max_elevation"],
            "area": fp["area"],
            "crs": crs,
            "contributing_global_ids": shell.contributing_global_ids,
        },
        "geometry": mapping(fp["polygon"]),
    }

    geojson = {
        "type": "FeatureCollection",
        "name": "exterior_footprint",
        "crs": {
            "type": "name",
            "properties": {"name": f"urn:ogc:def:crs::{crs}"},
        },
        "features": [feature],
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(geojson, f, indent=2)

    logger.info(
        f"Written footprint GeoJSON to {output_path} "
        f"(base={fp['base_elevation']}, height={fp['height']}, "
        f"area={fp['area']})"
    )
    return fp


def write_extraction_report(
    result: ExtractionResult,
    output_path: str | Path,
) -> None:
    """Write a human-readable extraction report to a markdown file.

    Args:
        result: Complete extraction result.
        output_path: Path for output report file.
    """
    output_path = Path(output_path)

    lines = [
        "# Exterior Shell Extraction Report",
        "",
        result.summary(),
        "",
    ]

    if hasattr(result, 'params') and result.params:
        lines.extend([
            "## Provenance",
            "",
            "```json",
            json.dumps(result.params.to_dict(), indent=2),
            "```",
            "",
        ])

    lines.extend([
        "## Ambiguous Elements (defaulted to exterior)",
        "",
    ])

    for elem in result.classification_report.ambiguous_elements:
        lines.append(
            f"- **{elem.name}** ({elem.ifc_type}) -- {elem.face_count} faces -- ID: {elem.global_id}"
        )

    if not result.classification_report.ambiguous_elements:
        lines.append("_No ambiguous elements._")

    # Contributing element IDs for traceability
    if result.shell.contributing_global_ids:
        lines.extend([
            "",
            "## Contributing Element IDs",
            "",
            f"Total: {len(result.shell.contributing_global_ids)} elements",
            "",
        ])
        # Group in columns for readability
        ids = result.shell.contributing_global_ids
        for i in range(0, len(ids), 4):
            chunk = ids[i:i+4]
            lines.append("  ".join(f"`{gid}`" for gid in chunk))

    lines.extend([
        "",
        "## Interior Elements (stripped)",
        "",
        f"- {result.classification_report.interior_count} elements removed",
        "",
        "---",
        f"_Generated by exterior-shell v{result.params.version if hasattr(result, 'params') and result.params else '1.5.0'}_",
    ])

    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"Written extraction report to {output_path}")
