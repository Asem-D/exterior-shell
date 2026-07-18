"""CLI entry point for exterior-shell."""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

import click

from . import __version__
from .core.parser import parse_ifc
from .core.classifier import classify_all, resolve_ambiguities
from .core.assembler import assemble_shell, get_shell_stats
from .export.stripped_ifc import export_stripped_ifc
from .export.footprint import export_footprint_geojson, write_extraction_report


def _setup_logging(verbose: bool) -> None:
    """Configure logging based on verbosity."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)-8s %(name)s: %(message)s",
        stream=sys.stderr,
    )


@click.group()
@click.version_option(__version__, prog_name="exterior-shell")
def main():
    """Extract lightweight exterior shells from BIM models (IFC).

    Produces a stripped IFC (interior elements removed) and optionally a
    2D building footprint with elevation attributes for GIS use.
    """
    pass


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
    "--no-filter",
    is_flag=True,
    default=False,
    help="Include all elements (skip rule-based filtering)",
)
@click.option(
    "--report/--no-report",
    default=True,
    help="Generate extraction report",
)
@click.option(
    "-v", "--verbose",
    is_flag=True,
    default=False,
    help="Enable debug logging",
)
@click.option(
    "--crs",
    default="EPSG:4326",
    help="Output coordinate reference system for footprint (default: EPSG:4326)",
    show_default=True,
)
@click.option(
    "--keep-interior",
    is_flag=True,
    default=False,
    help="Keep interior-facing faces in the shell",
)
@click.option(
    "--no-stripped-ifc",
    is_flag=True,
    default=False,
    help="Skip stripped IFC export (only useful with --footprint)",
)
@click.option(
    "--footprint",
    is_flag=True,
    default=False,
    help="Also export a 2D building footprint GeoJSON with elevation attributes",
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
    no_filter: bool,
    report: bool,
    verbose: bool,
    json_stats: bool,
    crs: str,
    keep_interior: bool,
    no_stripped_ifc: bool,
    footprint: bool,
):
    """Extract exterior shell from an IFC file.

    \b
    Examples:
        exterior-shell extract building.ifc
        exterior-shell extract building.ifc -o /output/
        exterior-shell extract building.ifc --footprint
        exterior-shell extract building.ifc --footprint --no-stripped-ifc
        exterior-shell extract building.ifc --footprint --crs EPSG:3857
    """
    _setup_logging(verbose)
    logger = logging.getLogger("exterior_shell.cli")

    input_path = Path(input_file)
    stem = input_path.stem

    # Determine output directory
    if output_dir is not None:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
    else:
        out_dir = input_path.parent

    # Track timing
    start_time = time.time()

    # ── Step 1: Parse ──────────────────────────────────────────────────
    click.echo(f"Parsing {input_path}...", err=True)
    elements = parse_ifc(input_path)
    click.echo(f"  Found {len(elements)} elements", err=True)

    # ── Step 2: Filter / Classify ──────────────────────────────────────
    report_data = None
    if no_filter:
        click.echo("Skipping classification (--no-filter)", err=True)
        from .core.models import Classification
        for e in elements:
            e.classification = Classification.EXTERIOR
    else:
        click.echo("Classifying elements...", err=True)
        report_data = classify_all(elements)

        if report_data.ambiguous_count > 0:
            click.echo(
                f"  {report_data.ambiguous_count} ambiguous elements "
                f"(defaulting to exterior)",
                err=True,
            )
            report_data = resolve_ambiguities(report_data, use_ai=ai)

        click.echo(
            f"  {report_data.exterior_count} exterior, "
            f"{report_data.interior_count} interior",
            err=True,
        )

    # ── Step 3: Assemble ──────────────────────────────────────────────
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

    # ── Step 4: Stripped IFC Export ───────────────────────────────────
    stripped_result = None
    if not no_stripped_ifc:
        stripped_output = out_dir / f"{stem}_stripped.ifc"
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

    # ── Step 5: Footprint Export ──────────────────────────────────────
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

    # ── Step 6: Report ───────────────────────────────────────────────
    elapsed = time.time() - start_time
    input_size = input_path.stat().st_size

    # Build result for summary and report
    from .core.models import ExtractionResult
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
    )

    if report and report_data:
        report_path = out_dir / f"{stem}.report.md"
        write_extraction_report(result, report_path)
        click.echo(f"Report written to {report_path}", err=True)

    # ── Summary ──────────────────────────────────────────────────────
    # File sizes
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

    click.echo("", err=True)
    click.echo(result.summary())

    # JSON stats if requested
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
            "elapsed_seconds": round(elapsed, 2),
        }
        click.echo(json.dumps(stats_output, indent=2))

    return 0


@main.command()
@click.argument("input_file", type=click.Path(exists=True))
def info(input_file: str):
    """Show information about an IFC file.

    Displays element counts, types, and geometry statistics.
    """
    _setup_logging(False)

    input_path = Path(input_file)
    click.echo(f"IFC File: {input_path}")
    click.echo(f"Size: {input_path.stat().st_size / 1024:.1f} KB")
    click.echo()

    elements = parse_ifc(input_path)

    # Count by type
    type_counts: dict[str, int] = {}
    for e in elements:
        type_counts[e.ifc_type] = type_counts.get(e.ifc_type, 0) + 1

    click.echo(f"Total elements: {len(elements)}")
    click.echo()
    click.echo("Element Types:")
    for ifc_type, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        click.echo(f"  {ifc_type:<35} {count:>5}")

    # Face counts
    total_faces = sum(e.face_count for e in elements)
    click.echo()
    click.echo(f"Total faces: {total_faces}")

    # Storeys
    storeys = set()
    for e in elements:
        if e.storey:
            storeys.add(e.storey)
    if storeys:
        click.echo()
        click.echo("Storeys:")
        for s in sorted(storeys):
            count = sum(1 for e in elements if e.storey == s)
            click.echo(f"  {s:<35} {count:>5}")


if __name__ == "__main__":
    main()
