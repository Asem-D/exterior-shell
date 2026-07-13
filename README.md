# exterior-shell

Extract lightweight 3D exterior shells from BIM models (IFC) for GIS visualization.

`exterior-shell` reads an IFC file, classifies elements as exterior/interior using a rule-based engine, and outputs:

- **GeoPackage** (.gpkg) with GIS-native multipatch geometry, ready for ArcGIS, QGIS, or any spatial platform
- **Stripped IFC** (.ifc) with interior elements removed, preserving a structurally valid IFC file

Optional AI-assisted classification handles ambiguous elements (walls, columns, slabs) that rule-based logic alone can't resolve.

## Why

BIM models contain everything: walls, windows, roofs, HVAC, furniture, pipes. When you need just the building envelope for a GIS deliverable, you're left with bad options:

| Approach | Problem |
|----------|---------|
| Full BIM-to-GIS conversion | 5-10x heavier than needed, interior geometry bloats the model |
| Manual cleanup in Revit/ArchiCAD | Hours per model, doesn't scale |
| Esri ExteriorShell (ArcGIS Pro) | Unreliable: misses roofs, includes interior junk, frequent fallbacks |
| FME | Works but $4K+/year, overkill for this one task |
| IfcConvert `--exterior-only` | Outputs mesh formats (OBJ, glTF), not GIS-native |

`exterior-shell` does one thing and gets it right: clean exterior shell, GIS-ready output, under 30 seconds.

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
- ifcopenshell, shapely, numpy, GDAL, click

## Usage

### Extract exterior shell to GeoPackage

```bash
exterior-shell extract building.ifc
# Output: building_shell.gpkg + building_shell.report.md
```

### Extract with stripped IFC output

```bash
exterior-shell extract building.ifc --stripped-ifc
# Output: building_shell.gpkg + building_stripped.ifc
```

### GeoJSON output with AI classification

```bash
exterior-shell extract building.ifc -f geojson --ai
```

### Other options

```bash
exterior-shell extract building.ifc --crs EPSG:3857      # Output in Web Mercator
exterior-shell extract building.ifc --keep-interior       # Include interior-facing faces
exterior-shell extract building.ifc --json-stats          # Machine-readable output
exterior-shell info building.ifc                          # Inspect IFC file
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
      ├─ GeoPackage (.gpkg) ─ GIS-native multipatch with element attributes
      ├─ GeoJSON (.geojson) ─ extruded polygons for lightweight visualization
      └─ Stripped IFC (.ifc) ─ structurally valid IFC with interiors removed
```

### Classification Rules

| Category | Elements | Action |
|----------|----------|--------|
| Always exterior | IfcRoof, IfcWindow, IfcDoor, IfcCurtainWall, IfcChimney | Keep |
| Always interior | IfcSpace, IfcFurnishingElement, IfcCovering, IfcBuildingStorey | Remove |
| Ambiguous | IfcWall, IfcColumn, IfcBeam, IfcSlab (floor), IfcStair, IfcRailing | Default to exterior (conservative); use `--ai` to resolve |

## Performance

Tested on real-world IFC models:

| Model | Elements | Extraction Time | GeoPackage Size | Size Reduction |
|-------|----------|----------------|----------------|---------------|
| Test house | 14 | <2s | 3.5 KB | 78.7% |
| Office building | 1,190 | <8s | 789 KB | 21.3% (geometry), 33.2% (stripped IFC) |

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
│   ├── assembler.py    # Geometry assembly + multipatch creation
│   └── models.py       # Data classes (Element, Classification, Shell)
├── ai/
│   └── ...             # Vision model classification (Phase 2)
├── export/
│   ├── geopackage.py   # GeoPackage + GeoJSON export
│   └── stripped_ifc.py # Stripped IFC export
└── utils/
    └── ...             # Geometry helpers, I/O utilities
```

## Roadmap

- **v1.0** (current) - Rule-based extraction, GeoPackage/GeoJSON/Stripped IFC export
- **v1.1** - AI-assisted classification for ambiguous elements (multi-view rendering + vision API)
- **v2.0** - Revit direct integration (.rvt), 3D Tiles export, LOD generation

## License

MIT

## Acknowledgments

Built with [ifcopenshell](https://github.com/IfcOpenShell/IfcOpenShell), [Shapely](https://shapely.readthedocs.io/), and [GDAL](https://gdal.org/).

Inspired by the daily pain of infrastructure GIS teams who spend hours cleaning BIM models they shouldn't have to clean.
