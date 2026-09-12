"""CLI entry point for exterior-shell."""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Optional

import click

from . import __version__
from .core.parser import parse_ifc
from .core.classifier import classify_all, resolve_ambiguities
from .core.assembler import assemble_shell, get_shell_stats
from .core.models import Classification, ExtractionResult, ExtractionParams
from .export.stripped_ifc import export_stripped_ifc
from .export.footprint import export_footprint_geojson, write_extraction_report
from .export.tiles3d import export_tiles3d


def _setup_logging(verbose: bool) -> None:
    """Configure logging based on verbosity."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)-8s %(name)s: %(message)s",
        stream=sys.stderr,
    )


# ── Shared extract pipeline ──────────────────────────────────────────────────

def _run_extract_pipeline(
    input_file: str,
    output_dir: Optional[str],
    *,
    ai: bool,
    api_key: Optional[str],
    ai_model: Optional[str],
    no_filter: bool,
    report: bool,
    crs: str,
    keep_interior: bool,
    no_stripped_ifc: bool,
    footprint: bool,
    tiles3d: bool,
    json_stats: bool,
    verbose: bool,
) -> tuple[ExtractionResult, Optional[dict], Optional[dict], Optional[Path], Optional[Path], float, int]:
    """Run the full extract pipeline for a single IFC file.

    Returns a tuple of:
        (result, stripped_result, footprint_data, stripped_output_path,
         footprint_output_path, elapsed_seconds, input_size_bytes)
    """
    _setup_logging(verbose)
    logger = logging.getLogger("exterior_shell.cli")

    input_path = Path(input_file)
    stem = input_path.stem

    if output_dir is not None:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
    else:
        out_dir = input_path.parent

    start_time = time.time()

    click.echo(f"Parsing {input_path}...", err=True)
    elements = parse_ifc(input_path)
    click.echo(f"  Found {len(elements)} elements", err=True)

    report_data = None
    if no_filter:
        click.echo("Skipping classification (--no-filter)", err=True)
        for e in elements:
            e.classification = Classification.EXTERIOR
    else:
        click.echo("Classifying elements...", err=True)
        report_data = classify_all(elements)

        if report_data.ambiguous_count > 0:
            if ai:
                from .ai import classify_ambiguous_with_ai, resolve_ai_config
                ai_config = resolve_ai_config(api_key=api_key, model=ai_model)
                if ai_config is None:
                    click.echo(
                        "  ERROR: --ai requires an API key. Provide via:\n"
                        "    --api-key flag, EXTERIOR_SHELL_AI_KEY env var,\n"
                        "    or ~/.exterior-shell/config.json",
                        err=True,
                    )
                    sys.exit(1)
                click.echo(
                    f"  {report_data.ambiguous_count} ambiguous elements "
                    f"(using AI: {ai_config.model})",
                    err=True,
                )
                report_data = classify_ambiguous_with_ai(
                    report=report_data,
                    ifc_path=input_path,
                    config=ai_config,
                )
            else:
                click.echo(
                    f"  {report_data.ambiguous_count} ambiguous elements "
                    f"(defaulting to exterior)",
                    err=True,
                )
                report_data = resolve_ambiguities(report_data, use_ai=False)

        click.echo(
            f"  {report_data.exterior_count} exterior, "
            f"{report_data.interior_count} interior",
            err=True,
        )

    exterior_elements = (
        report_data.exterior_elements if report_data else elements
    )
    if keep_interior:
        click.echo("Assembling shell geometry (keeping interior faces)...", err=True)
    else:
        click.echo("Assembling shell geometry...", err=True)
    shell = assemble_shell(
        exterior_elements,
        remove_interior_faces=not keep_interior,
    )
    stats = get_shell_stats(shell)
    click.echo(
        f"  {stats['face_count']} faces, "
        f"area: {stats['total_area']:.1f} sq units",
        err=True,
    )

    stripped_result = None
    stripped_output = out_dir / f"{stem}_stripped.ifc"
    if not no_stripped_ifc:
        click.echo(f"Exporting stripped IFC to {stripped_output}...", err=True)
        try:
            all_elements = elements
            if report_data:
                all_elements = (
                    report_data.exterior_elements
                    + report_data.interior_elements
                    + report_data.ambiguous_elements
                )
            stripped_result = export_stripped_ifc(
                input_path=input_path,
                output_path=stripped_output,
                elements=all_elements,
            )
            click.echo(
                f"  Removed {stripped_result['removed_count']} interior elements, "
                f"{stripped_result['kept_count']} kept",
                err=True,
            )
            click.echo(
                f"  Size: {stripped_result['output_size'] / 1024:.1f} KB "
                f"({stripped_result['size_reduction_pct']:.1f}% reduction)",
                err=True,
            )
        except Exception as exc:
            click.echo(f"  Stripped IFC export failed: {exc}", err=True)
    else:
        click.echo("Skipping stripped IFC (--no-stripped-ifc)", err=True)

    footprint_data = None
    footprint_path = None
    if footprint:
        footprint_path = out_dir / f"{stem}_footprint.geojson"
        click.echo(f"Exporting 2D footprint to {footprint_path}...", err=True)
        try:
            footprint_data = export_footprint_geojson(
                shell=shell,
                output_path=footprint_path,
                crs=crs,
            )
            if footprint_data:
                click.echo(
                    f"  base_elevation: {footprint_data['base_elevation']}, "
                    f"height: {footprint_data['height']}, "
                    f"area: {footprint_data['area']:.1f} sq units",
                    err=True,
                )
            else:
                click.echo("  No valid footprint geometry found", err=True)
        except Exception as exc:
            click.echo(f"  Footprint export failed: {exc}", err=True)

    tiles3d_data = None
    tiles3d_path = None
    if tiles3d:
        tiles3d_path = out_dir / f"{stem}_3dtiles"
        # When a stripped IFC was generated, build 3D Tiles from it so
        # the tileset geometry exactly matches the stripped IFC.
        tiles3d_shell = shell
        if stripped_result and stripped_output.exists():
            click.echo(
                "Rebuilding 3D Tiles from stripped IFC (no face removal)...",
                err=True,
            )
            try:
                stripped_elements = parse_ifc(stripped_output)
                # All elements in stripped IFC are already exterior
                tiles3d_shell = assemble_shell(
                    stripped_elements,
                    remove_interior_faces=False,
                )
                ts = get_shell_stats(tiles3d_shell)
                click.echo(
                    f"  Stripped shell: {ts['face_count']} faces "
                    f"from {ts['element_count']} elements",
                    err=True,
                )
            except Exception as exc:
                click.echo(
                    f"  Warning: could not rebuild from stripped IFC ({exc}), "
                    f"using original shell",
                    err=True,
                )
        click.echo(f"Exporting 3D Tiles to {tiles3d_path}...", err=True)
        try:
            tiles3d_data = export_tiles3d(
                shell=tiles3d_shell,
                output_dir=tiles3d_path,
                crs=crs,
            )
            bbox = tiles3d_data["bounding_box"]
            click.echo(
                f"  {tiles3d_data['face_count']} faces, "
                f"GLB: {tiles3d_data['glb_size'] / 1024:.1f} KB, "
                f"tileset: {tiles3d_data['tileset_size'] / 1024:.1f} KB",
                err=True,
            )
            click.echo(
                f"  bbox min={bbox[0]} max={bbox[1]}",
                err=True,
            )
        except Exception as exc:
            click.echo(f"  3D Tiles export failed: {exc}", err=True)

    elapsed = time.time() - start_time
    input_size = input_path.stat().st_size

    from . import __version__
    params = ExtractionParams(
        version=__version__,
        crs=crs,
        keep_interior=keep_interior,
        simplify=False,
        ai_enabled=ai,
        ai_model=ai_model if ai else None,
        classification_mode="ai" if ai else "rule_based",
    )

    placeholder_report = report_data or type('obj', (object,), {
        'total_elements': len(elements),
        'exterior_count': len(elements),
        'interior_count': 0,
        'ambiguous_count': 0,
        'ambiguous_elements': [],
        'exterior_elements': [],
        'interior_elements': [],
        'ambiguity_score': 0.0,
        'summary': lambda self: "No classification",
    })()

    result = ExtractionResult(
        classification_report=placeholder_report,
        shell=shell,
        input_file=str(input_path),
        output_file=str(stripped_output if stripped_result else (footprint_path or "")),
        input_element_count=len(elements),
        output_face_count=stats['face_count'],
        params=params,
    )

    if report and report_data:
        report_path = out_dir / f"{stem}.report.md"
        write_extraction_report(result, report_path)
        click.echo(f"Report written to {report_path}", err=True)

    stripped_size = (
        stripped_output.stat().st_size
        if stripped_result and stripped_output.exists()
        else 0
    )
    footprint_size = (
        footprint_path.stat().st_size
        if footprint_path and footprint_path.exists()
        else 0
    )
    tiles3d_size = (
        tiles3d_data["glb_size"] + tiles3d_data["tileset_size"]
        if tiles3d_data else 0
    )

    click.echo("", err=True)
    click.echo(f"Done in {elapsed:.1f}s", err=True)
    click.echo(f"Input:  {input_size / 1024:.1f} KB ({input_file})", err=True)
    if stripped_result:
        click.echo(
            f"Stripped IFC: {stripped_size / 1024:.1f} KB "
            f"({stripped_output.name})",
            err=True,
        )
        click.echo(
            f"  Reduction: {stripped_result['size_reduction_pct']:.1f}%",
            err=True,
        )
    if footprint_data and footprint_path:
        click.echo(
            f"Footprint:  {footprint_size / 1024:.1f} KB "
            f"({footprint_path.name})",
            err=True,
        )
    if tiles3d_data and tiles3d_path:
        click.echo(
            f"3D Tiles:   {tiles3d_size / 1024:.1f} KB "
            f"({tiles3d_path.name}/)",
            err=True,
        )

    click.echo("", err=True)
    click.echo(result.summary())

    if json_stats:
        stats_output = {
            "input_file": str(input_path),
            "input_size_kb": input_size / 1024,
            "elements": {
                "total": len(elements),
                "exterior": (
                    report_data.exterior_count if report_data else len(elements)
                ),
                "interior": report_data.interior_count if report_data else 0,
                "ambiguous": (
                    report_data.ambiguous_count if report_data else 0
                ),
            },
            "shell": stats,
            "stripped_ifc": stripped_result,
            "footprint": {k: v for k, v in footprint_data.items() if k != "polygon"} if footprint_data else None,
            "tiles3d": {k: v for k, v in tiles3d_data.items() if k != "bounding_box"} | {
                "bounding_box": {
                    "min": list(tiles3d_data["bounding_box"][0]),
                    "max": list(tiles3d_data["bounding_box"][1]),
                }
            } if tiles3d_data else None,
            "params": params.to_dict(),
            "elapsed_seconds": round(elapsed, 2),
        }
        click.echo(json.dumps(stats_output, indent=2))

    return (
        result,
        stripped_result,
        footprint_data,
        stripped_output,
        footprint_path,
        elapsed,
        input_size,
    )


# ── CLI group ────────────────────────────────────────────────────────────────

@click.group()
@click.version_option(__version__, prog_name="exterior-shell")
def main():
    """Extract lightweight exterior shells from BIM models (IFC).

    Produces a stripped IFC (interior elements removed) and optionally a
    2D building footprint with elevation attributes for GIS use.
    """
    pass


# ── extract ──────────────────────────────────────────────────────────────────

@main.command()
@click.argument("input_file", type=click.Path(exists=True))
@click.option(
    "-o", "--output", "output_dir",
    type=click.Path(file_okay=False),
    default=None,
    help="Output directory. Defaults to same directory as input file.",
)
@click.option(
    "--ai",
    is_flag=True,
    default=False,
    help="Enable AI-assisted classification for ambiguous elements",
)
@click.option(
    "--api-key",
    default=None,
    help="API key for AI classification (or set EXTERIOR_SHELL_AI_KEY env var)",
)
@click.option(
    "--ai-model",
    default=None,
    help="AI model name (default: openai/gpt-4o-mini)",
)
@click.option(
    "--no-filter",
    is_flag=True,
    default=False,
    help="Include all elements (skip rule-based filtering)",
)
@click.option(
    "--report/--no-report",
    default=None,
    help="Generate extraction report (defaults from config file)",
)
@click.option(
    "-v", "--verbose",
    is_flag=True,
    default=False,
    help="Enable debug logging",
)
@click.option(
    "--crs",
    default=None,
    help="Output coordinate reference system for footprint (default: EPSG:4326)",
)
@click.option(
    "--keep-interior",
    is_flag=True,
    default=None,
    help="Keep interior-facing faces in the shell",
)
@click.option(
    "--no-stripped-ifc",
    is_flag=True,
    default=None,
    help="Skip stripped IFC export (only useful with --footprint)",
)
@click.option(
    "--footprint",
    is_flag=True,
    default=None,
    help="Also export a 2D building footprint GeoJSON with elevation attributes",
)
@click.option(
    "--tiles3d",
    is_flag=True,
    default=None,
    help="Export 3D Tiles (tileset.json + model.glb) for CesiumJS/web visualization",
)
@click.option(
    "--json-stats",
    is_flag=True,
    default=False,
    help="Output stats as JSON to stdout",
)
def extract(
    input_file: str,
    output_dir: str | None,
    ai: bool,
    api_key: str | None,
    ai_model: str | None,
    no_filter: bool,
    report: bool | None,
    verbose: bool,
    crs: str | None,
    keep_interior: bool | None,
    no_stripped_ifc: bool | None,
    footprint: bool | None,
    tiles3d: bool | None,
    json_stats: bool,
):
    """Extract exterior shell from an IFC file.

    \b
    Examples:
        exterior-shell extract building.ifc
        exterior-shell extract building.ifc -o /output/
        exterior-shell extract building.ifc --footprint
        exterior-shell extract building.ifc --footprint --no-stripped-ifc
        exterior-shell extract building.ifc --footprint --crs EPSG:3857
        exterior-shell extract building.ifc --ai --api-key sk-or-v1-xxx
    """
    # Apply config-file defaults for flags the user didn't set explicitly.
    from .config import resolve_config
    cli_overrides: dict[str, Any] = {}
    if crs is not None:
        cli_overrides["default_crs"] = crs
    if footprint is not None:
        cli_overrides["default_footprint"] = footprint
    if tiles3d is not None:
        cli_overrides["default_tiles3d"] = tiles3d
    if no_stripped_ifc is not None:
        cli_overrides["default_no_stripped_ifc"] = no_stripped_ifc
    if keep_interior is not None:
        cli_overrides["default_keep_interior"] = keep_interior
    if report is not None:
        cli_overrides["default_report"] = report
    resolved, _sources = resolve_config(cli_overrides)

    crs = resolved["default_crs"]
    footprint = bool(resolved["default_footprint"])
    tiles3d = bool(resolved["default_tiles3d"])
    no_stripped_ifc = bool(resolved["default_no_stripped_ifc"])
    keep_interior = bool(resolved["default_keep_interior"])
    report = bool(resolved["default_report"])

    _run_extract_pipeline(
        input_file=input_file,
        output_dir=output_dir,
        ai=ai,
        api_key=api_key,
        ai_model=ai_model,
        no_filter=no_filter,
        report=report,
        crs=crs,
        keep_interior=keep_interior,
        no_stripped_ifc=no_stripped_ifc,
        footprint=footprint,
        tiles3d=tiles3d,
        json_stats=json_stats,
        verbose=verbose,
    )
    return 0


# ── batch ────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("directory", type=click.Path(exists=True, file_okay=False))
@click.option(
    "-o", "--output", "output_dir",
    type=click.Path(file_okay=False),
    default=None,
    help="Output directory. Defaults to a subdirectory per input file.",
)
@click.option("--ai", is_flag=True, default=False, help="Enable AI-assisted classification.")
@click.option("--api-key", default=None, help="API key for AI classification.")
@click.option("--ai-model", default=None, help="AI model name.")
@click.option("--footprint", is_flag=True, default=None, help="Also export footprint GeoJSON.")
@click.option("--tiles3d", is_flag=True, default=None, help="Also export 3D Tiles (tileset.json + model.glb).")
@click.option("--no-stripped-ifc", is_flag=True, default=None, help="Skip stripped IFC export.")
@click.option("--crs", default=None, help="Output CRS for footprint.")
@click.option("--keep-interior", is_flag=True, default=None, help="Keep interior-facing faces.")
@click.option("--no-report", "no_report_flag", is_flag=True, default=False,
              help="Suppress extraction reports.")
@click.option("-v", "--verbose", is_flag=True, default=False, help="Enable debug logging.")
@click.option("--json-stats", is_flag=True, default=False, help="Output stats as JSON array.")
@click.option("--workers", default=1, show_default=True,
              help="Number of parallel workers (future; currently sequential).")
def batch(
    directory: str,
    output_dir: str | None,
    ai: bool,
    api_key: str | None,
    ai_model: str | None,
    footprint: bool | None,
    tiles3d: bool | None,
    no_stripped_ifc: bool | None,
    crs: str | None,
    keep_interior: bool | None,
    no_report_flag: bool,
    verbose: bool,
    json_stats: bool,
    workers: int,
):
    """Batch-process all IFC files in a directory (recursively).

    \b
    Examples:
        exterior-shell batch ./models
        exterior-shell batch ./models -o ./output --footprint
        exterior-shell batch ./models --json-stats
    """
    if workers != 1:
        click.echo(
            f"Note: --workers={workers} is reserved for future parallel "
            "execution; processing sequentially.",
            err=True,
        )

    # Resolve config defaults for the flags the user didn't set explicitly.
    from .config import resolve_config
    cli_overrides: dict[str, Any] = {}
    if crs is not None:
        cli_overrides["default_crs"] = crs
    if footprint is not None:
        cli_overrides["default_footprint"] = footprint
    if tiles3d is not None:
        cli_overrides["default_tiles3d"] = tiles3d
    if no_stripped_ifc is not None:
        cli_overrides["default_no_stripped_ifc"] = no_stripped_ifc
    if keep_interior is not None:
        cli_overrides["default_keep_interior"] = keep_interior
    resolved, _sources = resolve_config(cli_overrides)
    crs = resolved["default_crs"]
    footprint = bool(resolved["default_footprint"])
    tiles3d = bool(resolved["default_tiles3d"])
    no_stripped_ifc = bool(resolved["default_no_stripped_ifc"])
    keep_interior = bool(resolved["default_keep_interior"])
    report = bool(resolved["default_report"]) and not no_report_flag

    root = Path(directory)
    ifc_files = sorted(root.rglob("*.ifc"))
    if not ifc_files:
        click.echo(f"No .ifc files found under {root}", err=True)
        return 0

    click.echo(f"Found {len(ifc_files)} IFC file(s) under {root}", err=True)

    results: list[dict] = []
    rows: list[dict] = []
    had_error = False

    for ifc_path in ifc_files:
        if output_dir is not None:
            # Preserve relative directory structure from root.
            # Root-level files get their own subdirectory named after stem.
            rel_parent = ifc_path.parent.relative_to(root)
            rel_parts = [p for p in rel_parent.parts if p != "."]
            if rel_parts:
                per_file_out = Path(output_dir).joinpath(*rel_parts)
            else:
                per_file_out = Path(output_dir) / ifc_path.stem
            per_file_out_str = str(per_file_out)
        else:
            per_file_out_str = str(ifc_path.parent)

        click.echo("", err=True)
        click.echo(f"=== {ifc_path.name} ===", err=True)

        entry: dict[str, Any] = {"file": str(ifc_path), "status": "error"}
        try:
            (
                _result,
                stripped_result,
                _footprint_data,
                stripped_output,
                _footprint_output,
                elapsed,
                input_size,
            ) = _run_extract_pipeline(
                input_file=str(ifc_path),
                output_dir=per_file_out_str,
                ai=ai,
                api_key=api_key,
                ai_model=ai_model,
                no_filter=False,
                report=report,
                crs=crs,
                keep_interior=keep_interior,
                no_stripped_ifc=no_stripped_ifc,
                footprint=footprint,
                tiles3d=tiles3d,
                json_stats=False,
                verbose=verbose,
            )
            stripped_size = (
                stripped_output.stat().st_size
                if stripped_result and stripped_output.exists()
                else 0
            )
            entry.update({
                "status": "success",
                "elements": _result.input_element_count,
                "stripped_size": stripped_size,
                "elapsed": round(elapsed, 2),
            })
            rows.append({
                "file": ifc_path.name,
                "elements": _result.input_element_count,
                "stripped_size": stripped_size,
                "status": "success",
            })
        except SystemExit:
            raise
        except Exception as exc:
            had_error = True
            logger = logging.getLogger("exterior_shell.cli")
            logger.exception("Failed to process %s", ifc_path)
            click.echo(f"  ERROR: {exc}", err=True)
            rows.append({
                "file": ifc_path.name,
                "elements": 0,
                "stripped_size": 0,
                "status": "error",
            })
            entry["error"] = str(exc)

        results.append(entry)

    # ── Summary table ────────────────────────────────────────────────────
    click.echo("", err=True)
    click.echo("=" * 70, err=True)
    click.echo("Batch summary", err=True)
    click.echo("=" * 70, err=True)
    click.echo(
        f"{'File':<35} {'Elements':>10} {'Stripped':>12} {'Status':>10}",
        err=True,
    )
    click.echo("-" * 70, err=True)
    for row in rows:
        click.echo(
            f"{row['file']:<35} {row['elements']:>10} "
            f"{row['stripped_size'] / 1024:>10.1f}K "
            f"{row['status']:>10}",
            err=True,
        )
    click.echo("=" * 70, err=True)

    if json_stats:
        click.echo(json.dumps(results, indent=2))

    return 1 if had_error else 0


# ── info ─────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("input_file", type=click.Path(exists=True))
@click.option(
    "--validate",
    "validate_file",
    type=click.Path(exists=True),
    default=None,
    help="Validate spatial consistency against a stripped IFC output file.",
)
def info(input_file: str, validate_file: str | None):
    """Show information about an IFC file.

    Displays element counts, types, geometry statistics, bounding box,
    estimated volume, and a pre-classification preview.

    With --validate, compares spatial consistency against a stripped IFC
    output to detect geometry drift.
    """
    _setup_logging(False)

    input_path = Path(input_file)
    click.echo(f"IFC File: {input_path}")
    click.echo(f"Size: {input_path.stat().st_size / 1024:.1f} KB")
    click.echo()

    elements = parse_ifc(input_path)

    type_counts: dict[str, int] = {}
    for e in elements:
        type_counts[e.ifc_type] = type_counts.get(e.ifc_type, 0) + 1

    click.echo(f"Total elements: {len(elements)}")
    click.echo()
    click.echo("Element Types:")
    for ifc_type, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        click.echo(f"  {ifc_type:<35} {count:>5}")

    total_faces = sum(e.face_count for e in elements)
    click.echo()
    click.echo(f"Total faces: {total_faces}")

    # Storeys
    storeys = set()
    for e in elements:
        if e.storey:
            storeys.add(e.storey)
    click.echo()
    click.echo(f"Storeys ({len(storeys)}):")
    for s in sorted(storeys):
        count = sum(1 for e in elements if e.storey == s)
        click.echo(f"  {s:<35} {count:>5}")

    # Bounding box and volume
    bbox_min, bbox_max = _compute_global_bbox(elements)
    if bbox_min is not None and bbox_max is not None:
        dims = bbox_max - bbox_min
        click.echo()
        click.echo("Bounding Box:")
        click.echo(f"  X range: {bbox_min[0]:.2f} to {bbox_max[0]:.2f}  (dX {dims[0]:.2f})")
        click.echo(f"  Y range: {bbox_min[1]:.2f} to {bbox_max[1]:.2f}  (dY {dims[1]:.2f})")
        click.echo(f"  Z range: {bbox_min[2]:.2f} to {bbox_max[2]:.2f}  (dZ {dims[2]:.2f})")
        volume = float(dims[0] * dims[1] * dims[2])
        click.echo(f"  Estimated volume: {volume:.2f} cubic units")

    # Pre-classification preview
    click.echo()
    click.echo("Pre-classification preview:")
    preview_report = classify_all(elements)
    click.echo(f"  Would-be exterior:   {preview_report.exterior_count}")
    click.echo(f"  Would-be interior:   {preview_report.interior_count}")
    click.echo(f"  Would-be ambiguous:  {preview_report.ambiguous_count}")
    click.echo(f"  Ambiguity score:     {preview_report.ambiguity_score:.1f}%")
    if preview_report.ambiguity_score > 30.0:
        click.echo(
            "  Tip: ambiguity score > 30% - consider running extract with "
            "--ai for better results."
        )

    # Spatial consistency validation
    if validate_file:
        _validate_spatial_consistency(input_path, Path(validate_file), bbox_min, bbox_max)


def _validate_spatial_consistency(
    original_path: Path,
    stripped_path: Path,
    original_bbox_min,
    original_bbox_max,
) -> None:
    """Compare spatial extent of original IFC against stripped IFC output.

    Reports bounding box overlap ratio and element count reduction.
    """
    import numpy as np

    click.echo()
    click.echo("Spatial Consistency Validation")
    click.echo("-" * 40)

    stripped_elements = parse_ifc(stripped_path)
    stripped_bbox_min, stripped_bbox_max = _compute_global_bbox(stripped_elements)

    if original_bbox_min is None or stripped_bbox_min is None:
        click.echo("  Cannot compute: missing bounding box data")
        return

    # Compute overlap
    overlap_min = np.maximum(original_bbox_min, stripped_bbox_min)
    overlap_max = np.minimum(original_bbox_max, stripped_bbox_max)
    overlap_dims = np.maximum(overlap_max - overlap_min, 0.0)

    original_vol = float(np.prod(original_bbox_max - original_bbox_min))
    stripped_vol = float(np.prod(stripped_bbox_max - stripped_bbox_min))
    overlap_vol = float(np.prod(overlap_dims))

    if original_vol > 0:
        containment = overlap_vol / original_vol * 100
    else:
        containment = 0.0

    original_elements = len(parse_ifc(original_path))
    stripped_count = len(stripped_elements)
    reduction_pct = (1 - stripped_count / original_elements) * 100 if original_elements > 0 else 0

    click.echo(f"  Original:   {original_elements} elements, bbox vol {original_vol:.2f}")
    click.echo(f"  Stripped:   {stripped_count} elements, bbox vol {stripped_vol:.2f}")
    click.echo(f"  Reduction:  {reduction_pct:.1f}% elements removed")
    click.echo(f"  Containment: {containment:.1f}% bounding box overlap")

    if containment >= 99.0:
        click.echo("  Status: PASS - stripped shell fully contained in original")
    elif containment >= 95.0:
        click.echo("  Status: WARN - minor geometry drift detected")
    else:
        click.echo("  Status: FAIL - significant geometry drift, review extraction")


def _compute_global_bbox(elements) -> tuple[Optional[Any], Optional[Any]]:
    """Compute a global bounding box from element-level bboxes."""
    import numpy as np
    mins = []
    maxs = []
    for e in elements:
        if e.bbox_min is not None and e.bbox_max is not None:
            mins.append(e.bbox_min)
            maxs.append(e.bbox_max)
    if not mins:
        return None, None
    return np.min(np.vstack(mins), axis=0), np.max(np.vstack(maxs), axis=0)


# ── config ───────────────────────────────────────────────────────────────────

@main.group()
def config():
    """Manage exterior-shell configuration."""
    pass


@config.command("show")
def config_show():
    """Show current configuration and where each value came from."""
    from .config import CONFIG_FILE, load_config_file, show_config
    click.echo(f"Config file: {CONFIG_FILE}")
    click.echo(
        f"Status: {'present' if CONFIG_FILE.exists() else 'not found'}"
    )
    click.echo()
    click.echo(show_config())


@config.command("init")
@click.option("--force", is_flag=True, default=False,
              help="Overwrite existing config file.")
def config_init(force: bool):
    """Create a default config file at ~/.exterior-shell/config.json."""
    from . import config as cfg_mod

    config_path = cfg_mod.CONFIG_FILE
    if force and config_path.exists():
        config_path.unlink()

    if config_path.exists() and not force:
        click.echo(
            f"Config file already exists at {config_path} "
            "(use --force to overwrite)"
        )
        return

    cfg_mod.init_config()
    click.echo(f"Created config file at {config_path}")


if __name__ == "__main__":
    main()
