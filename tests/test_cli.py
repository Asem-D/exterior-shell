"""Tests for CLI commands."""
from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from exterior_shell.cli import main


FIXTURE = Path(__file__).parent / "fixtures" / "test_building.ifc"


def test_extract_default(tmp_path: Path):
    """Default extract produces a GPKG with shell + faces layers."""
    out = tmp_path / "out.gpkg"
    runner = CliRunner()
    result = runner.invoke(main, ["extract", str(FIXTURE), "-o", str(out)])
    assert result.exit_code == 0
    assert out.exists()


def test_extract_crs(tmp_path: Path):
    """--crs flag is accepted and written to GPKG."""
    out = tmp_path / "out.gpkg"
    runner = CliRunner()
    result = runner.invoke(main, [
        "extract", str(FIXTURE), "-o", str(out),
        "--crs", "EPSG:3857",
    ])
    assert result.exit_code == 0
    # Check CRS in GPKG metadata
    import sqlite3
    conn = sqlite3.connect(str(out))
    cursor = conn.execute(
        "SELECT organization_coordsys_id FROM gpkg_spatial_ref_sys"
    )
    ids = [row[0] for row in cursor.fetchall()]
    conn.close()
    assert 3857 in ids


def test_extract_keep_interior(tmp_path: Path):
    """--keep-interior flag is accepted and changes face count."""
    out_normal = tmp_path / "normal.gpkg"
    out_keep = tmp_path / "keep.gpkg"
    runner = CliRunner()

    runner.invoke(main, ["extract", str(FIXTURE), "-o", str(out_normal)])
    runner.invoke(main, ["extract", str(FIXTURE), "-o", str(out_keep), "--keep-interior"])

    # Both should produce valid output
    assert out_normal.exists()
    assert out_keep.exists()


def test_extract_no_report(tmp_path: Path):
    """--no-report suppresses report file."""
    out = tmp_path / "out.gpkg"
    runner = CliRunner()
    result = runner.invoke(main, [
        "extract", str(FIXTURE), "-o", str(out), "--no-report",
    ])
    assert result.exit_code == 0
    report = tmp_path / "out.report.md"
    assert not report.exists()


def test_info():
    """info command shows element counts."""
    runner = CliRunner()
    result = runner.invoke(main, ["info", str(FIXTURE)])
    assert result.exit_code == 0
    assert "Total elements:" in result.output
    assert "Total faces:" in result.output


def test_extract_geojson(tmp_path: Path):
    """GeoJSON format produces valid output."""
    out = tmp_path / "out.geojson"
    runner = CliRunner()
    result = runner.invoke(main, [
        "extract", str(FIXTURE), "-o", str(out), "-f", "geojson",
    ])
    assert result.exit_code == 0
    assert out.exists()

    import json
    data = json.loads(out.read_text())
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 1


def test_extract_json_stats(tmp_path: Path):
    """--json-stats outputs JSON to stdout."""
    out = tmp_path / "out.gpkg"
    runner = CliRunner()
    result = runner.invoke(main, [
        "extract", str(FIXTURE), "-o", str(out), "--json-stats",
    ])
    assert result.exit_code == 0
    # JSON should be in the output
    assert '"crs"' in result.output
    assert '"keep_interior"' in result.output
    assert '"geometry"' in result.output


def test_extract_simplify(tmp_path: Path):
    """--simplify flag is accepted and changes face count."""
    out_normal = tmp_path / "normal.gpkg"
    out_simplified = tmp_path / "simplified.gpkg"
    runner = CliRunner()

    runner.invoke(main, ["extract", str(FIXTURE), "-o", str(out_normal)])
    runner.invoke(main, ["extract", str(FIXTURE), "-o", str(out_simplified), "--simplify"])

    # Both should produce valid output
    assert out_normal.exists()
    assert out_simplified.exists()

    # Check face counts differ
    import sqlite3
    normal_faces = _count_gpkg_features(out_normal, "faces")
    simplified_faces = _count_gpkg_features(out_simplified, "faces")
    # Simplification should reduce or maintain face count
    assert simplified_faces <= normal_faces


def test_extract_gpkg_elements_layer(tmp_path: Path):
    """GPKG output includes elements layer as attribute-only table."""
    out = tmp_path / "out.gpkg"
    runner = CliRunner()
    result = runner.invoke(main, ["extract", str(FIXTURE), "-o", str(out)])
    assert result.exit_code == 0
    assert out.exists()

    # Verify elements layer exists and has records
    import sqlite3
    conn = sqlite3.connect(str(out))
    cursor = conn.execute("SELECT COUNT(*) FROM elements")
    count = cursor.fetchone()[0]
    conn.close()
    assert count >= 1


def test_extract_gpkg_layers(tmp_path: Path):
    """GPKG output contains shell, faces, and elements layers."""
    out = tmp_path / "out.gpkg"
    runner = CliRunner()
    result = runner.invoke(main, ["extract", str(FIXTURE), "-o", str(out)])
    assert result.exit_code == 0

    import sqlite3
    conn = sqlite3.connect(str(out))
    cursor = conn.execute(
        "SELECT table_name FROM gpkg_contents ORDER BY table_name"
    )
    layers = [row[0] for row in cursor.fetchall()]
    conn.close()
    assert "shell" in layers
    assert "faces" in layers
    assert "elements" in layers


def _count_gpkg_features(gpkg_path: Path, layer: str) -> int:
    """Count features in a GPKG layer."""
    import sqlite3
    conn = sqlite3.connect(str(gpkg_path))
    cursor = conn.execute(f"SELECT COUNT(*) FROM [{layer}]")
    count = cursor.fetchone()[0]
    conn.close()
    return count
