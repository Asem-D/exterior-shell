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
from .export.geopackage import export_geopackage, write_extraction_report
from .export.stripped_ifc import export_stripped_ifc


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
    """Extract lightweight exterior shells from BIM models for GIS visualization.

    Converts IFC files to GeoPackage layers suitable for ArcGIS and other
    GIS platforms.
    """
    pass


@main.command()
@click.argument("input_file", type=click.Path(exists=True))
@click.option(
    "-o", "--output", "output_file",
    type=click.Path(),
    default=None,
    help="Output file path (.gpkg or .geojson). Defaults to input name + _shell.gpkg",
)
@click.option(
    "-f", "--format", "output_format",
    type=click.Choice(["gpkg", "geojson"]),
    default="gpkg",
    help="Output format (default: gpkg)",
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
    help="Output coordinate reference system (default: EPSG:4326)",
    show_default=True,
)
@click.option(
    "--keep-interior",
    is_flag=True,
    default=False,
    help="Keep interior-facing faces in the shell",
)
@click.option(
    "--stripped-ifc",
    is_flag=True,
    default=False,
    help="Also export a stripped IFC file with interior elements removed",
)
@click.option(
    "--json-stats",
    is_flag=True,
    default=False,
    help="Output stats as JSON to stdout",
)
def extract(
    input_file: str,
    output_file: str | None,
    output_format: str,
    ai: bool,
    no_filter: bool,
    report: bool,
    verbose: bool,
    json_stats: bool,
    crs: str,
    keep_interior: bool,
    stripped_ifc: bool,
):
    """Extract exterior shell from an IFC file.

    \b
    Examples:
        exterior-shell extract building.ifc
        exterior-shell extract building.ifc -o shell.gpkg
        exterior-shell extract building.ifc -f geojson --ai
        exterior-shell extract building.ifc --stripped-ifc
    """
    _setup_logging(verbose)
    logger = logging.getLogger("exterior_shell.cli")

    input_path = Path(input_file)

    # Determine output path
    if output_file is None:
        output_file = str(input_path.with_suffix("")) + f"_shell.{output_format}"
    output_path = Path(output_file)

    # Track timing
    start_time = time.time()

    # ── Step 1: Parse ──────────────────────────────────────────────────
    click.echo(f"Parsing {input_path}...", err=True)
    elements = parse_ifc(input_path)
    click.echo(f"  Found {len(elements)} elements", err=True)

    # ── Step 2: Filter / Classify ──────────────────────────────────────
    if no_filter:
        click.echo("Skipping classification (--no-filter)", err=True)
        # All elements treated as exterior
        from .core.models import Classification
        for e in elements:
            e.classification = Classification.EXTERIOR
        exterior_elements = elements
        report_data = None
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
        exterior_elements = report_data.exterior_elements

    # ── Step 3: Assemble ──────────────────────────────────────────────
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

    # ── Step 4: Export ─────────────────────────────────────────────────
    click.echo(f"Exporting to {output_path}...", err=True)

    if output_format == "geojson":
        from .export.geopackage import export_geojson
        result = export_geojson(
            shell=shell,
            report=report_data or type('obj', (object,), {'total_elements': len(elements), 'exterior_count': len(elements), 'interior_count': 0, 'ambiguous_count': 0, 'ambiguous_elements': [], 'exterior_elements': [], 'interior_elements': [], 'ambiguity_score': 0.0, 'summary': lambda self: "No classification"})(),
            output_path=output_path,
            input_file=str(input_path),
            crs=crs,
        )
    else:
        result = export_geopackage(
            shell=shell,
            report=report_data,
            output_path=output_path,
            input_file=str(input_path),
            crs=crs,
        )

    # Store CRS and keep_interior in result for JSON output
    result.crs = crs
    result.keep_interior = keep_interior

    # ── Step 5: Report ─────────────────────────────────────────────────
    elapsed = time.time() - start_time

    if report and report_data:
        report_path = output_path.with_suffix(".report.md")
        write_extraction_report(result, report_path)
        click.echo(f"Report written to {report_path}", err=True)

    # ── Step 5b: Stripped IFC Export ───────────────────────────────────
    stripped_result = None
    if stripped_ifc and report_data:
        stripped_output = output_path.with_name(
            output_path.stem.replace("_shell", "") + "_stripped.ifc"
        )
        click.echo(f"Exporting stripped IFC to {stripped_output}...", err=True)
        try:
            all_elements = report_data.exterior_elements + report_data.interior_elements + report_data.ambiguous_elements
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

    # File sizes
    input_size = input_path.stat().st_size
    output_size = output_path.stat().st_size if output_path.exists() else 0
    if input_size > 0:
        result.file_size_reduction = (1 - output_size / input_size) * 100

    # Summary
    click.echo("", err=True)
    click.echo(f"Done in {elapsed:.1f}s", err=True)
    click.echo(f"Input:  {input_size / 1024:.1f} KB ({input_file})", err=True)
    click.echo(f"Output: {output_size / 1024:.1f} KB ({output_path.name})", err=True)
    click.echo(f"Reduction: {result.file_size_reduction:.1f}%", err=True)

    # Print summary
    click.echo("", err=True)
    click.echo(result.summary())

    # JSON stats if requested
    if json_stats:
        stats_output = {
            "input_file": str(input_path),
            "output_file": str(output_path),
            "input_size_kb": input_size / 1024,
            "output_size_kb": output_size / 1024,
            "crs": crs,
            "keep_interior": keep_interior,
            "elements": {
                "total": result.input_element_count,
                "exterior": result.classification_report.exterior_count if report_data else len(elements),
                "interior": result.classification_report.interior_count if report_data else 0,
                "ambiguous": result.classification_report.ambiguous_count if report_data else 0,
            },
            "geometry": stats,
            "stripped_ifc": stripped_result,
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
