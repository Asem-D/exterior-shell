# exterior-shell

Extract lightweight exterior shells from BIM models (IFC) for GIS and visualization workflows.

`exterior-shell` reads an IFC file, classifies elements as exterior/interior, and produces:

- **Stripped IFC** (.ifc) with interior elements removed, preserving a structurally valid IFC file
- **2D Footprint** (.geojson) with base elevation, height, and area attributes for GIS extrusion

**AI-assisted classification** resolves ambiguous elements (walls, columns, slabs without PredefinedType) that rule-based logic alone can't handle. Multi-view rendering + vision model = smarter shell extraction.

## Why

GIS teams don't ask for BIM models. They receive them. Architecture practices export IFC files and hand them off, and the GIS analyst is left with 500MB of pipes, HVAC, and furniture when they need just the building envelope for a web map or spatial analysis.

| Approach | Stripped IFC | GIS Footprint | AI Classification | Cost |
|----------|:---:|:---:|:---:|:---:|
| **exterior-shell** | ✅ | ✅ With elevation | ✅ Vision model (BYOK) | Free |
| IfcEnvelopeExtractor (TU Delft) | ❌ (CityJSON) | ❌ (CityJSON) | ❌ | Free |
| ArcGIS Pro Building Layer | ❌ No standalone output | ❌ | ❌ | ArcGIS Pro license |
| FME (IFC Connector) | ❌ | Via translation | ❌ | $4K+/yr |
| IfcConvert `--exterior-only` | ❌ Mesh only | ❌ | ❌ | Free |
| Manual Revit/ArchiCAD cleanup | ❌ | ❌ | ❌ | Hours per model |

`exterior-shell` does one thing: clean exterior shell, lightweight output, under 30 seconds. The output is a structurally valid IFC file that any BIM or GIS tool can read, plus an optional GeoJSON footprint ready for ArcGIS Pro, QGIS, or web maps.

## Install

```bash
pip install exterior-shell          # rule-based only
pip install exterior-shell[ai]     # with AI classification support
```

Or from source:

```bash
git clone https://github.com/Asem-D/exterior-shell.git
cd exterior-shell
pip install -e .                   # rule-based only
pip install -e ".[ai]"            # with AI support
```

### Requirements

- Python 3.10+
- ifcopenshell, shapely, numpy, click
- openai (only needed for `--ai` flag, installed via `exterior-shell[ai]`)

## Usage

### Extract exterior shell

```bash
exterior-shell extract building.ifc
# Output: building_stripped.ifc + building.report.md
```

### Extract with 2D footprint

```bash
exterior-shell extract building.ifc --footprint
# Output: building_stripped.ifc + building_footprint.geojson + building.report.md
```

The footprint GeoJSON includes `base_elevation`, `height`, `min_elevation`, `max_elevation`, and `area` properties. Load it in ArcGIS Pro or QGIS and extrude by the `height` attribute, or use it directly in web maps (MapLibre, CesiumJS).

### Stripped IFC only (no GIS output)

```bash
exterior-shell extract building.ifc --no-stripped-ifc --footprint
# Output: building_footprint.geojson only
```

### AI Classification

Without AI, ambiguous elements (walls, columns, slabs) default to exterior (conservative). With `--ai`, a vision model reclassifies them by analyzing rendered views of the building.

```
exterior-shell extract building.ifc            # rule-based: 18 exterior, 20 interior, 28 ambiguous
exterior-shell extract building.ifc --ai       # AI resolves: 33 exterior, 33 interior, 0 ambiguous
```

The AI eliminates interior partition walls, interior columns, and interior beams from the shell, while keeping all truly exterior elements. Typical accuracy: 90-95% on real IFC models.

```bash
# Pass API key directly
exterior-shell extract building.ifc --ai --api-key sk-or-v1-xxx

# Or set environment variable
export EXTERIOR_SHELL_AI_KEY=sk-or-v1-xxx
exterior-shell extract building.ifc --ai

# Or use a config file
echo '{"ai_api_key": "sk-or-v1-xxx", "ai_model": "openai/gpt-4o-mini"}' > ~/.exterior-shell/config.json
exterior-shell extract building.ifc --ai
```

**BYOK (Bring Your Own Key)**: no telemetry, no data leaves your machine unless you explicitly enable `--ai` and provide your own key. Works with any OpenAI-compatible API (OpenRouter, OpenAI, Azure, etc.).

**Config precedence**: CLI flag (`--api-key`) > env var (`EXTERIOR_SHELL_AI_KEY`) > config file (`~/.exterior-shell/config.json`)

### Other options

```bash
exterior-shell extract building.ifc --crs EPSG:3857     # Footprint in Web Mercator
exterior-shell extract building.ifc --keep-interior      # Include interior-facing faces
exterior-shell extract building.ifc --no-report          # Skip report generation
exterior-shell extract building.ifc --json-stats         # Machine-readable output
exterior-shell info building.ifc                         # Inspect IFC file
```

## How It Works

```
IFC File
  │
  ├─ Parse ─── ifcopenshell extracts elements, geometry, spatial hierarchy
  │
  ├─ Classify ─ Rule-based engine assigns EXTERIOR / INTERIOR / AMBIGUOUS
  │   │
  │   └─ [--ai] Render 8 views → vision model classifies ambiguous elements
  │
  ├─ Assemble ─ Merge exterior faces, remove hidden interior-facing geometry
  │
  └─ Export
      ├─ Stripped IFC (.ifc) ─ structurally valid IFC with interiors removed
      ├─ Footprint (.geojson) ─ 2D outline with base_elevation and height
      └─ Report (.md) ─ extraction summary with element counts
```

### Classification Rules

| Category | Elements | Action |
|----------|----------|--------|
| Always exterior | IfcRoof, IfcWindow, IfcDoor, IfcCurtainWall, IfcChimney | Keep |
| Always interior | IfcSpace, IfcFurnishingElement, IfcCovering, IfcBuildingStorey | Remove |
| Ambiguous | IfcWall, IfcColumn, IfcBeam, IfcSlab (floor), IfcStair, IfcRailing | Default to exterior; use `--ai` to resolve |

### AI Pipeline

```
Ambiguous elements
  │
  ├─ Render ─── 8 viewpoints (front, back, left, right, top, iso, ...)
  │              Full 3D via ifcopenshell+trimesh, or bounding-box fallback
  │
  ├─ Classify ─ Vision model (GPT-4o-mini or user-specified) analyzes views
  │              Batched: 10 elements per API call, ~90-95% accuracy
  │
  └─ Apply ──── EXTERIOR or INTERIOR with confidence score
                 Fallback: exterior (conservative) if API fails
```

## Performance

Tested on real-world IFC models:

| Model | Elements | Extraction Time | Stripped IFC Size | Size Reduction |
|-------|----------|----------------|-------------------|---------------|
| Test house | 14 | <2s | ~200 KB | ~78% |
| Office building | 1,190 | ~26s | 7,036 KB | 33.2% |

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## Project Structure

```
exterior_shell/
├── cli.py              # Click CLI entry point
├── core/
│   ├── parser.py       # IFC parsing with ifcopenshell
│   ├── classifier.py   # Rule-based classification engine
│   ├── assembler.py    # Geometry assembly + face deduplication
│   └── models.py       # Data classes (Element, Classification, Shell)
├── ai/
│   ├── classifier.py   # AI orchestration (render → classify → apply)
│   ├── renderer.py     # Multi-view rendering (trimesh + matplotlib fallback)
│   └── vision.py       # Vision model API integration (OpenAI-compatible)
├── export/
│   ├── stripped_ifc.py # Stripped IFC export (remove interior elements)
│   └── footprint.py    # 2D footprint GeoJSON with elevation attributes
└── utils/
    └── ...             # Geometry helpers, I/O utilities
```

## Prior Art

This problem has been approached from different angles:

- **IfcEnvelopeExtractor** (TU Delft): Academic-grade tool outputting CityJSON, STEP, and OBJ with full LoD coverage (LOD0 through LOD5). Built on the Biljecki et al. LoD framework. Different output ecosystem from exterior-shell. If you're building 3D city models with CityJSON, that's the tool. [GitHub](https://github.com/tudelft3d/IFC_BuildingEnvExtractor)
- **IfcConvert** (`--exterior-only`): Open-source, extracts exterior shell as mesh. No structurally valid IFC output, no GIS attributes.
- **Esri ExteriorShell**: Built into ArcGIS Pro. Automatic sublayer extraction when loading IFC/RVT. Often misses roofs, ground floors, and includes interior geometry.

exterior-shell targets a narrower niche: GIS practitioners who need a clean stripped IFC plus a GeoJSON footprint with elevation attributes, with zero heavy GIS dependencies.

## Roadmap

- **v1.2** - Stripped IFC + 2D footprint output, rule-based extraction
- **v1.3** (current) - AI-assisted classification for ambiguous elements (multi-view rendering + vision API, BYOK)
- **v1.4** - Provenance metadata: link output features to IFC GlobalIds, record extraction parameters, validate spatial consistency with source shell
- **v2.0** - Revit direct integration (.rvt), 3D Tiles export, LOD generation

## License

MIT

## Acknowledgments

Built with [ifcopenshell](https://github.com/IfcOpenShell/IfcOpenShell) and [Shapely](https://shapely.readthedocs.io/).

Inspired by the daily pain of GIS teams who receive BIM models they didn't ask for and need just the envelope.

## Trademarks

ArcGIS is a registered trademark of Esri. This project is not affiliated with or endorsed by Esri.
