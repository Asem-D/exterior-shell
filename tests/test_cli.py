"""Tests for CLI commands."""
from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from exterior_shell.cli import main


FIXTURE = Path(__file__).parent / "fixtures" / "test_building.ifc"


def test_extract_default(tmp_path: Path):
    """Default extract produces a stripped IFC file."""
    runner = CliRunner()
    result = runner.invoke(main, ["extract", str(FIXTURE), "-o", str(tmp_path)])
    assert result.exit_code == 0
    stripped = tmp_path / "test_building_stripped.ifc"
    assert stripped.exists()
    assert stripped.stat().st_size > 0


def test_extract_footprint(tmp_path: Path):
    """--footprint flag produces a GeoJSON footprint file."""
    runner = CliRunner()
    result = runner.invoke(
        main, ["extract", str(FIXTURE), "-o", str(tmp_path), "--footprint"]
    )
    assert result.exit_code == 0
    footprint = tmp_path / "test_building_footprint.geojson"
    assert footprint.exists()

    import json
    data = json.loads(footprint.read_text(encoding="utf-8"))
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 1

    props = data["features"][0]["properties"]
    assert "base_elevation" in props
    assert "height" in props
    assert "area" in props


def test_extract_footprint_crs(tmp_path: Path):
    """--crs flag is accepted for footprint export."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["extract", str(FIXTURE), "-o", str(tmp_path),
         "--footprint", "--crs", "EPSG:3857"],
    )
    assert result.exit_code == 0
    footprint = tmp_path / "test_building_footprint.geojson"
    assert footprint.exists()

    import json
    data = json.loads(footprint.read_text(encoding="utf-8"))
    assert "3857" in data["crs"]["properties"]["name"]


def test_extract_keep_interior(tmp_path: Path):
    """--keep-interior flag is accepted and runs without error."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["extract", str(FIXTURE), "-o", str(tmp_path), "--keep-interior"],
    )
    assert result.exit_code == 0
    stripped = tmp_path / "test_building_stripped.ifc"
    assert stripped.exists()


def test_extract_no_report(tmp_path: Path):
    """--no-report suppresses report file."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["extract", str(FIXTURE), "-o", str(tmp_path), "--no-report"],
    )
    assert result.exit_code == 0
    report = tmp_path / "test_building.report.md"
    assert not report.exists()


def test_extract_no_stripped_ifc(tmp_path: Path):
    """--no-stripped-ifc skips IFC output."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["extract", str(FIXTURE), "-o", str(tmp_path), "--no-stripped-ifc"],
    )
    assert result.exit_code == 0
    stripped = tmp_path / "test_building_stripped.ifc"
    assert not stripped.exists()


def test_extract_no_stripped_ifc_with_footprint(tmp_path: Path):
    """--no-stripped-ifc --footprint produces only the footprint."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["extract", str(FIXTURE), "-o", str(tmp_path),
         "--no-stripped-ifc", "--footprint"],
    )
    assert result.exit_code == 0
    assert not (tmp_path / "test_building_stripped.ifc").exists()
    assert (tmp_path / "test_building_footprint.geojson").exists()


def test_extract_json_stats(tmp_path: Path):
    """--json-stats outputs JSON to stdout."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["extract", str(FIXTURE), "-o", str(tmp_path), "--json-stats"],
    )
    assert result.exit_code == 0
    assert '"elements"' in result.output
    assert '"shell"' in result.output
    assert '"stripped_ifc"' in result.output


def test_extract_json_stats_with_footprint(tmp_path: Path):
    """--json-stats with --footprint includes footprint in JSON."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["extract", str(FIXTURE), "-o", str(tmp_path),
         "--footprint", "--json-stats"],
    )
    assert result.exit_code == 0
    assert '"footprint"' in result.output
    assert '"base_elevation"' in result.output


def test_info():
    """info command shows element counts."""
    runner = CliRunner()
    result = runner.invoke(main, ["info", str(FIXTURE)])
    assert result.exit_code == 0
    assert "Total elements:" in result.output
    assert "Total faces:" in result.output


def test_extract_both_outputs(tmp_path: Path):
    """Default extract with --footprint produces both stripped IFC and footprint."""
    runner = CliRunner()
    result = runner.invoke(
        main, ["extract", str(FIXTURE), "-o", str(tmp_path), "--footprint"]
    )
    assert result.exit_code == 0
    stripped = tmp_path / "test_building_stripped.ifc"
    footprint = tmp_path / "test_building_footprint.geojson"
    assert stripped.exists()
    assert footprint.exists()
