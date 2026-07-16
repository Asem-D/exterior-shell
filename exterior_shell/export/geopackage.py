"""GeoPackage exporter — writes shell geometry to GeoPackage format."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union

from ..core.models import ExtractionResult, ShellGeometry, Face, ClassificationReport

logger = logging.getLogger(__name__)


def _faces_to_polygons(faces: list[Face]) -> list[Polygon]:
    """Convert triangulated faces to 3D polygons.

    Ensures Z coordinates are preserved. Each face becomes a triangle
    polygon with explicit 3D semantics for Multipatch output.
    """
    polygons = []
    for face in faces:
        try:
            coords = [tuple(v) for v in face.vertices]
            # Ensure all coordinates are 3-tuples (x, y, z)
            coords = [(c[0], c[1], c[2] if len(c) > 2 else 0.0) for c in coords]
            # Close the ring
            if coords[0] != coords[-1]:
                coords.append(coords[0])
            poly = Polygon(coords)
            if poly.is_valid and not poly.is_empty:
                polygons.append(poly)
        except Exception:
            continue
    return polygons


def _ensure_3d(geom) -> bool:
    """Check whether a geometry has Z coordinates."""
    if geom is None:
        return False
    if geom.geom_type == "Polygon":
        return len(geom.exterior.coords[0]) >= 3
    if geom.geom_type == "MultiPolygon":
        for p in geom.geoms:
            if len(p.exterior.coords[0]) >= 3:
                return True
        return False
    return False


def _shell_to_single_polygon(faces: list[Face]) -> MultiPolygon | Polygon | None:
    """Merge shell faces into a single 3D multipolygon.

    Preserves Z coordinates through unary_union for proper 3D GIS
    visualization in ArcGIS Pro and other platforms.
    """
    polygons = _faces_to_polygons(faces)
    if not polygons:
        return None

    # Verify all inputs have Z before merge
    all_3d = all(
        len(p.exterior.coords[0]) >= 3 for p in polygons
    )

    try:
        merged = unary_union(polygons)
        # Verify Z survived the union
        if all_3d and not _ensure_3d(merged):
            logger.warning(
                "Z coordinates lost during unary_union, "
                "falling back to MultiPolygon of originals"
            )
            return MultiPolygon(polygons) if len(polygons) > 1 else polygons[0]
        return merged
    except Exception:
        return MultiPolygon(polygons) if len(polygons) > 1 else polygons[0]


def export_geopackage(
    shell: ShellGeometry,
    report: ClassificationReport,
    output_path: str | Path,
    input_file: str = "",
    crs: str = "EPSG:4326",
) -> ExtractionResult:
    """Export shell geometry to GeoPackage.

    Creates three layers:
    1. 'shell' — the merged exterior shell as a 3D multipolygon (PolygonZ)
    2. 'faces' — individual triangular faces with element metadata (PolygonZ)
    3. 'elements' — element summary as an attribute-only table (no geometry)

    Args:
        shell: Assembled shell geometry.
        report: Classification report.
        output_path: Path for output .gpkg file.
        input_file: Original input file path (for report).
        crs: Output coordinate reference system (default: EPSG:4326).

    Returns:
        ExtractionResult with statistics.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    result = ExtractionResult(
        classification_report=report,
        shell=shell,
        input_file=input_file,
        output_file=str(output_path),
        input_element_count=report.total_elements,
        output_face_count=shell.total_face_count,
    )

    # ── Layer 1: Merged shell (3D) ──────────────────────────────────
    merged = _shell_to_single_polygon(shell.faces)
    if merged is not None:
        has_z = _ensure_3d(merged)
        shell_data = gpd.GeoDataFrame(
            {
                "id": [1],
                "name": ["exterior_shell"],
                "element_count": [shell.element_count],
                "face_count": [shell.total_face_count],
            },
            geometry=[merged],
            crs=crs,
        )
        shell_data.to_file(str(output_path), layer="shell", driver="GPKG")
        logger.info(f"Written 'shell' layer with 1 feature (3D={has_z})")

    # ── Layer 2: Individual faces (3D) ───────────────────────────────
    if shell.faces:
        faces_data = []
        for i, face in enumerate(shell.faces):
            try:
                coords = [tuple(v) for v in face.vertices]
                # Ensure 3D coordinates
                coords = [
                    (c[0], c[1], c[2] if len(c) > 2 else 0.0)
                    for c in coords
                ]
                if coords[0] != coords[-1]:
                    coords.append(coords[0])
                poly = Polygon(coords)
                if poly.is_valid and not poly.is_empty:
                    faces_data.append({
                        "face_id": i + 1,
                        "normal_x": float(face.normal[0]),
                        "normal_y": float(face.normal[1]),
                        "normal_z": float(face.normal[2]),
                        "area": float(poly.area),
                        "geometry": poly,
                    })
            except Exception:
                continue

        if faces_data:
            faces_df = gpd.GeoDataFrame(faces_data, crs=crs)
            faces_df.to_file(
                str(output_path),
                layer="faces",
                driver="GPKG",
            )
            logger.info(
                f"Written 'faces' layer with {len(faces_data)} features (3D=True)"
            )

    # ── Layer 3: Element summary (attribute-only) ────────────────────
    element_rows = []
    for elem in shell.source_elements:
        element_rows.append({
            "global_id": elem.global_id,
            "name": elem.name,
            "ifc_type": elem.ifc_type,
            "face_count": elem.face_count,
            "confidence": elem.confidence,
            "classification_source": elem.classification_source.value,
        })

    if element_rows:
        elem_df = pd.DataFrame(element_rows)
        # Write as attribute-only table in the same GPKG
        conn = sqlite3.connect(str(output_path))
        elem_df.to_sql("elements", conn, if_exists="replace", index=False)
        # Register in gpkg_contents so the GPKG driver knows about it
        cursor = conn.execute(
            "INSERT OR REPLACE INTO gpkg_contents "
            "(table_name, data_type, srs_id) "
            "VALUES (?, 'attributes', 4326)",
            ("elements",),
        )
        conn.commit()
        conn.close()
        logger.info(
            f"Written 'elements' layer with {len(element_rows)} records "
            f"(attribute-only, no geometry)"
        )

    # Calculate file size
    if output_path.exists():
        result.file_size_reduction = 0.0  # Will be calculated by CLI

    return result


def export_geojson(
    shell: ShellGeometry,
    report: ClassificationReport,
    output_path: str | Path,
    input_file: str = "",
    crs: str = "EPSG:4326",
) -> ExtractionResult:
    """Export shell geometry to GeoJSON format.

    Creates a single merged multipolygon feature with metadata.
    Supports 3D coordinates per RFC 7946 Section 3.2.

    Args:
        shell: Assembled shell geometry.
        report: Classification report.
        output_path: Path for output .geojson file.
        input_file: Original input file path (for report).

    Returns:
        ExtractionResult with statistics.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    result = ExtractionResult(
        classification_report=report,
        shell=shell,
        input_file=input_file,
        output_file=str(output_path),
        input_element_count=report.total_elements,
        output_face_count=shell.total_face_count,
    )

    merged = _shell_to_single_polygon(shell.faces)
    if merged is None:
        logger.warning("No geometry to export")
        return result

    # GeoJSON spec (RFC 7946) supports 3D coordinates natively
    feature = {
        "type": "Feature",
        "properties": {
            "name": "exterior_shell",
            "element_count": shell.element_count,
            "face_count": shell.total_face_count,
            "input_file": str(input_file),
        },
        "geometry": _shapely_to_geojson(merged),
    }

    geojson = {
        "type": "FeatureCollection",
        "features": [feature],
    }

    with open(output_path, "w") as f:
        json.dump(geojson, f, indent=2)

    logger.info(f"Written GeoJSON to {output_path}")
    return result


def _shapely_to_geojson(geom) -> dict:
    """Convert shapely geometry to GeoJSON dict."""
    from shapely.geometry import mapping
    return mapping(geom)


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
        "## Ambiguous Elements (defaulted to exterior)",
        "",
    ]

    for elem in result.classification_report.ambiguous_elements:
        lines.append(f"- **{elem.name}** ({elem.ifc_type}) — {elem.face_count} faces")

    if not result.classification_report.ambiguous_elements:
        lines.append("_No ambiguous elements._")

    lines.extend([
        "",
        "## Interior Elements (stripped)",
        "",
        f"- {result.classification_report.interior_count} elements removed",
        "",
        "---",
        "_Generated by exterior-shell v0.1.0_",
    ])

    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"Written extraction report to {output_path}")
