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


# ── batch command ────────────────────────────────────────────────────────────

def test_batch_processes_directory(tmp_path: Path):
    """batch command processes all IFC files found recursively."""
    import shutil
    work = tmp_path / "batch_in"
    work.mkdir()
    out = tmp_path / "batch_out"
    shutil.copy(FIXTURE, work / "a.ifc")
    shutil.copy(FIXTURE, work / "b.ifc")
    nested = work / "nested"
    nested.mkdir()
    shutil.copy(FIXTURE, nested / "c.ifc")

    runner = CliRunner()
    result = runner.invoke(main, ["batch", str(work), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert (out / "a" / "a_stripped.ifc").exists()
    assert (out / "b" / "b_stripped.ifc").exists()
    assert (out / "nested" / "c_stripped.ifc").exists()
    assert "Batch summary" in result.output


def test_batch_empty_directory(tmp_path: Path):
    """batch command on a directory with no IFC files reports 0 files."""
    work = tmp_path / "empty"
    work.mkdir()

    runner = CliRunner()
    result = runner.invoke(main, ["batch", str(work)])
    assert result.exit_code == 0
    assert "No .ifc files found" in result.output


def test_batch_skips_non_ifc(tmp_path: Path):
    """batch command ignores files that are not .ifc."""
    work = tmp_path / "mixed"
    work.mkdir()
    (work / "readme.txt").write_text("hello")
    (work / "data.json").write_text("{}")

    runner = CliRunner()
    result = runner.invoke(main, ["batch", str(work)])
    assert result.exit_code == 0
    assert "No .ifc files found" in result.output


# ── config command ───────────────────────────────────────────────────────────

def test_config_show(tmp_path: Path, monkeypatch):
    """config show displays resolved values with source attribution."""
    runner = CliRunner()
    result = runner.invoke(main, ["config", "show"])
    assert result.exit_code == 0, result.output
    assert "Config file:" in result.output
    assert "default_crs" in result.output
    assert "ai_model" in result.output


def test_config_init(tmp_path: Path, monkeypatch):
    """config --init creates ~/.exterior-shell/config.json with defaults."""
    import json
    from exterior_shell import config as cfg_mod

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", fake_home / ".exterior-shell")
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", fake_home / ".exterior-shell" / "config.json")

    runner = CliRunner()
    result = runner.invoke(main, ["config", "init"])
    assert result.exit_code == 0, result.output

    created = fake_home / ".exterior-shell" / "config.json"
    assert created.exists()
    data = json.loads(created.read_text(encoding="utf-8"))
    assert data["default_crs"] == "EPSG:4326"
    assert data["ai_model"] == "openai/gpt-4o-mini"


def test_config_defaults_applied(tmp_path: Path, monkeypatch):
    """A config file value is picked up as the resolved default for extract."""
    import json
    from exterior_shell import config as cfg_mod

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    cfg_path = fake_home / ".exterior-shell" / "config.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        json.dumps({"default_crs": "EPSG:3857", "default_footprint": True}),
        encoding="utf-8",
    )

    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", fake_home / ".exterior-shell")
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", cfg_path)

    runner = CliRunner()
    result = runner.invoke(main, ["extract", str(FIXTURE), "-o", str(tmp_path / "out")])
    assert result.exit_code == 0, result.output
    # If the default footprint flag was applied, the footprint file must exist.
    assert (tmp_path / "out" / "test_building_footprint.geojson").exists()
    footprint = tmp_path / "out" / "test_building_footprint.geojson"
    data = json.loads(footprint.read_text(encoding="utf-8"))
    assert "3857" in data["crs"]["properties"]["name"]


# ── enriched info ────────────────────────────────────────────────────────────

def test_info_enriched():
    """info command shows bounding box, volume, and classification preview."""
    runner = CliRunner()
    result = runner.invoke(main, ["info", str(FIXTURE)])
    assert result.exit_code == 0
    assert "Total elements:" in result.output
    assert "Total faces:" in result.output
    assert "Bounding Box" in result.output
    assert "Estimated volume" in result.output
    assert "Pre-classification preview" in result.output
    assert "Ambiguity score" in result.output


# ── provenance ───────────────────────────────────────────────────────────────

def test_extract_json_stats_includes_params(tmp_path: Path):
    """--json-stats output includes extraction parameters."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["extract", str(FIXTURE), "-o", str(tmp_path), "--json-stats"],
    )
    assert result.exit_code == 0
    import json
    # The JSON stats block starts with {"input_file" and ends before the summary
    marker = '"input_file"'
    idx = result.output.find(marker)
    assert idx >= 0, "No JSON stats found in output"
    # Walk backwards to find the opening brace
    start = result.output.rfind("{", 0, idx)
    # Walk forward to find matching closing brace (count nesting)
    depth = 0
    end = start
    for i in range(start, len(result.output)):
        if result.output[i] == "{":
            depth += 1
        elif result.output[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    data = json.loads(result.output[start:end])
    assert "params" in data
    assert data["params"]["version"] == "2.0.0"
    assert data["params"]["crs"] == "EPSG:4326"
    assert data["params"]["ai_enabled"] is False


def test_footprint_includes_contributing_ids(tmp_path: Path):
    """Footprint GeoJSON includes contributing_global_ids."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["extract", str(FIXTURE), "-o", str(tmp_path), "--footprint"],
    )
    assert result.exit_code == 0
    import json
    footprint = tmp_path / "test_building_footprint.geojson"
    data = json.loads(footprint.read_text(encoding="utf-8"))
    props = data["features"][0]["properties"]
    assert "contributing_global_ids" in props
    assert isinstance(props["contributing_global_ids"], list)
    assert len(props["contributing_global_ids"]) > 0


def test_report_includes_parameters(tmp_path: Path):
    """Extraction report includes provenance parameters."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["extract", str(FIXTURE), "-o", str(tmp_path)],
    )
    assert result.exit_code == 0
    report = tmp_path / "test_building.report.md"
    content = report.read_text(encoding="utf-8")
    assert "Parameters:" in content
    assert "Version:" in content
    assert "2.0.0" in content


def test_report_includes_contributing_ids(tmp_path: Path):
    """Extraction report includes contributing element IDs."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["extract", str(FIXTURE), "-o", str(tmp_path)],
    )
    assert result.exit_code == 0
    report = tmp_path / "test_building.report.md"
    content = report.read_text(encoding="utf-8")
    assert "Contributing Element IDs" in content


def test_info_validate_flag():
    """info --validate accepts a stripped IFC path."""
    runner = CliRunner()
    # First extract a stripped IFC
    result = runner.invoke(main, ["extract", str(FIXTURE)])
    assert result.exit_code == 0
    stripped = FIXTURE.parent.parent / "test_building_stripped.ifc"
    if stripped.exists():
        result2 = runner.invoke(
            main, ["info", str(FIXTURE), "--validate", str(stripped)]
        )
        assert result2.exit_code == 0
        assert "Spatial Consistency" in result2.output
        assert "containment" in result2.output.lower() or "Containment" in result2.output
        stripped.unlink()  # cleanup
