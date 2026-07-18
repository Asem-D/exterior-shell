# exterior-shell

Extract lightweight exterior shells from BIM models (IFC) for GIS and visualization workflows.

`exterior-shell` reads an IFC file, classifies elements as exterior/interior using a rule-based engine, and produces:

- **Stripped IFC** (.ifc) with interior elements removed, preserving a structurally valid IFC file
- **2D Footprint** (.geojson) with base elevation, height, and area attributes for GIS extrusion

Optional AI-assisted classification handles ambiguous elements (walls, columns, slabs) that rule-based logic alone can't resolve.

## Why

BIM models contain everything: walls, windows, roofs, HVAC, furniture, pipes. When you need just the building envelope, you're left with bad options:

| Approach | Stripped IFC | GIS Footprint | Cost |
|----------|:---:|:---:|:---:|
| **exterior-shell** | ✅ | ✅ With elevation | Free |
| ArcGIS Pro Building Layer | ❌ No standalone output | ❌ | ArcGIS Pro license |
| FME (IFC Connector) | ❌ | Via translation | $4K+/yr |
| IfcConvert `--exterior-only` | ❌ Mesh only | ❌ | Free |
| Manual Revit/ArchiCAD cleanup | ❌ | ❌ | Hours per model |

`exterior-shell` does one thing and gets it right: clean exterior shell, lightweight output, under 30 seconds.

## Install

```bash
pip install exterior-shell
```

Or from source:

```bash
git clone https://github.com/Asem-D/exterior-shell.git
cd exterior-shell
pip install -e .
```

### Requirements

- Python 3.10+
- ifcopenshell, shapely, numpy, click

## Usage

### Extract exterior shell (default)

Produces a stripped IFC file with interior elements removed:

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

### Other options

```bash
exterior-shell extract building.ifc --ai                # AI-assisted classification
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
  │   └─ [--ai] Vision model reclassifies ambiguous elements from rendered views
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
| Ambiguous | IfcWall, IfcColumn, IfcBeam, IfcSlab (floor), IfcStair, IfcRailing | Default to exterior (conservative); use `--ai` to resolve |

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
│   └── ...             # Vision model classification (Phase 2)
├── export/
│   ├── stripped_ifc.py # Stripped IFC export (remove interior elements)
│   └── footprint.py    # 2D footprint GeoJSON with elevation attributes
└── utils/
    └── ...             # Geometry helpers, I/O utilities
```

## Roadmap

- **v1.2** (current) - Stripped IFC + 2D footprint output, rule-based extraction
- **v1.3** - AI-assisted classification for ambiguous elements (multi-view rendering + vision API)
- **v2.0** - Revit direct integration (.rvt), 3D Tiles export, LOD generation

## License

MIT

## Acknowledgments

Built with [ifcopenshell](https://github.com/IfcOpenShell/IfcOpenShell) and [Shapely](https://shapely.readthedocs.io/).

Inspired by the daily pain of infrastructure GIS teams who spend hours cleaning BIM models they shouldn't have to clean.

## Trademarks

ArcGIS is a registered trademark of Esri. This project is not affiliated with or endorsed by Esri.
