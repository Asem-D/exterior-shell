# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.1] - 2026-09-12

### Fixed

- **3D Tiles exported in wrong positions**: ifcopenshell returns LOCAL coordinates by default; the parser now enables `USE_WORLD_COORDS` so every element lands at its real building position (previously all elements stacked near the origin)
- **GLB failed to load in viewers**: bufferView byteOffsets now match the actual binary layout, and indices are local to each primitive's own vertex buffer
- **Stripped IFC crashed the geometry engine**: relationships referencing removed products (voids, fills, connections) are now deleted, eliminating Blank-reference errors
- Entity identity now uses IFC entity `.id()` instead of Python `id()` (wrapper objects are recreated per access)

### Added

- IFC surface color extraction: GLB materials now carry per-element colors from IfcStyledItem styles
- `IfcFooting` classified exterior (foundation), `IfcOpeningElement` classified interior (boolean voids)
- `--tiles3d` rebuilds the tileset from the stripped IFC when present, so 3D Tiles exactly match the stripped output

## [2.0.0] - 2026-09-04

### Added

- 3D Tiles 1.1 export (`--tiles3d`): produces `tileset.json` + `model.glb` for CesiumJS and web visualization
- Pure Python GLB writer — zero new dependencies, handles coordinate transform (IFC Z-up to glTF Y-up), flat shading, PBR material
- Works with both `extract` and `batch` commands
- 25 new 3D Tiles tests (80 total)

## [1.5.0] - 2026-09-04

### Added

- Provenance metadata: `ExtractionParams` records tool version, CRS, AI settings, and classification mode in every extraction report and `--json-stats` output
- Contributing element traceability: footprint GeoJSON features and extraction reports now list the IFC GlobalIds of every exterior element that contributed to the output
- Spatial consistency validation: `exterior-shell info <original.ifc> --validate <stripped.ifc>` compares bounding boxes and reports containment ratio with PASS/WARN/FAIL status for geometry drift detection
- 10 new provenance tests (55 total)

## [1.4.0] - 2026-08-14

### Added

- Batch processing: `exterior-shell batch <directory>` processes all IFC files recursively, one output subdirectory per file, errors logged and skipped
- Config file support: `exterior-shell config init|show` manages defaults in `~/.exterior-shell/config.json`; precedence CLI flags > env vars > config file > hardcoded defaults
- Enriched `info` command: bounding box, estimated volume, storey breakdown, pre-classification preview with ambiguity score

### Fixed

- Test fixtures excluded from sdist (36 KB vs 19 MB)

## [1.3.0] - 2026-08-06

### Added

- AI-assisted classification for ambiguous elements (`--ai`): renders 8 viewpoints, vision model (GPT-4o-mini via OpenRouter, BYOK) reclassifies walls, columns, slabs; ~90-95% accuracy, conservative exterior fallback on API failure
- GitHub Actions CI (Python 3.10-3.12, Windows + Ubuntu)

### Changed

- Honest competitor positioning in README (factual capability table)

## [1.2.0] - 2026-07-18

### Added

- 2D footprint GeoJSON export with base elevation, height, and area attributes

### Changed

- Simplified output set: removed GeoPackage export and simplifier module in favor of stripped IFC + GeoJSON footprint focus

## [1.0.0] - 2026-07-13

### Added

- Initial MVP release: rule-based IFC exterior shell extraction
- Stripped IFC export (structurally valid, interior elements removed)
- GeoJSON and GeoPackage output
- 34 tests passing
