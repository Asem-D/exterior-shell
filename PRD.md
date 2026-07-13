# Product Requirements Document: BIM Exterior Shell Extractor

> **Version**: 0.1 (Draft)
> **Date**: 2026-07-10
> **Author**: Asem Daaboul
> **Status**: Concept Approved, Pre-Implementation

---

## 1. Product Overview

**Working Name**: ExteriorAI (working title, TBD)

**One-liner**: Extract lightweight 3D exterior shells from BIM models for GIS visualization.

**What it does**: Takes an IFC or Revit model as input, identifies and extracts only the exterior building envelope (walls, windows, doors, roofs, canopies), and outputs a lightweight GIS-ready multipatch geometry. Optionally uses AI vision models to improve classification accuracy on messy, early-stage models.

**What it is NOT**:
- Not a full BIM-to-GIS conversion tool (that's FME, ArcGIS Pro)
- Not a 3D reconstruction tool (not generating geometry from photos)
- Not a BIM authoring tool
- It does ONE thing: produce a clean, lightweight exterior shell from BIM data

---

## 2. Problem Statement

### The Pain

Infrastructure consultancies producing 3D GIS deliverables for clients face a recurring problem:

| Scenario | What happens today | Cost |
|---|---|---|
| Client wants 3D building model on web map | Export full Revit model → 500MB multipatch, unusable | Hours of manual cleanup |
| Urban planning needs massing model | Manually trace building footprints and extrude | Imprecise, no facade detail |
| 3D visualization for public consultation | Revit model too heavy, manually delete interior elements | Days of tedious work per model |
| GIS team needs building shell from BIM | Interior geometry (pipes, HVAC, furniture) bloats the model | Data volume 5-10x what's needed |

### Root Cause

1. **No standard tool exists** to extract just the exterior shell from BIM for GIS use cases
2. **Esri's ExteriorShell** (ArcGIS Pro) is unreliable: misses roofs, ground floors, includes interior junk, many Revit files fall back to degraded "Fallback Shell"
3. **BIM models are messy**, especially at early project stages when GIS visualization is most needed (planning, design review, public consultation)
4. **FME can solve it** but costs $10K+/year per seat, overkill for this one task

### Market Gap

There is no lightweight, affordable, purpose-built tool that converts BIM exterior shells to GIS-ready formats. The alternatives are:

- **Esri ExteriorShell**: Free but broken
- **FME**: Works but expensive and generalist
- **Manual cleanup**: Slow, error-prone, doesn't scale
- **Custom scripts per project**: No reusability, no UI

---

## 3. Target Users

### Primary: GIS Analysts in Infrastructure Consultancies

- Work at firms like Dar, AECOM, WSP, Arcadis
- Receive BIM models from design teams
- Need to publish 3D building data to GIS portals and web maps
- Currently spend hours cleaning up models manually
- Comfortable with CLI tools, prefer Python ecosystem
- Budget authority for project-specific tools ($5-20 per model)

### Secondary: Urban Planners and Municipal GIS Teams

- Need massing models or simplified 3D for city-scale visualization
- Receive BIM submissions from developers
- Need to extract exterior shells for 3D city models
- Less technical, prefer drag-and-drop or web upload

### Tertiary: BIM Coordinators Needing GIS Output

- Understand BIM deeply but need GIS-compatible output
- Currently struggle with format conversion tools
- Want clean geometry without learning GIS software

---

## 4. Value Proposition

### For GIS Analysts
> "Stop spending hours manually deleting interior elements from Revit models. Get a clean exterior shell in 30 seconds."

### For Planners
> "See the real building exterior on your map, not a crude box extrusion."

### For the Industry
> "Bridge the BIM-GIS gap for exterior visualization. No other tool does this reliably."

---

## 5. Product Requirements

### 5.1 Input Formats

| Format | Phase | Priority |
|---|---|---|
| IFC (Industry Foundation Classes) | MVP (Phase 1) | P0 |
| Revit (.rvt) via Revit API | Phase 2 | P1 |
| Revit (.rvt) via IFC export (workaround) | MVP | P0 (workaround) |

### 5.2 Output Formats

| Format | Phase | Priority |
|---|---|---|
| GeoPackage (.gpkg) with multipatch geometry | MVP | P0 |
| Stripped IFC (.ifc) with exterior elements only | MVP | P0 |
| GeoJSON (.geojson) with extruded polygons | MVP | P1 |
| 3D Tiles (.3dtiles) | Phase 3 | P2 |
| Shapefile (.shp) with extruded polygons | Phase 2 | P2 |

### 5.3 Core Features

#### Phase 1: Rule-Based Extraction (MVP)

| Feature | Description | Acceptance Criteria |
|---|---|---|
| **IFC Parsing** | Read IFC files, extract geometry and element metadata | Handles IFC2x3 and IFC4; extracts element types, geometry, spatial hierarchy |
| **Rule-Based Classification** | Classify elements as exterior/interior based on IFC type | IfcRoof → exterior; IfcWindow/IfcDoor → exterior; IfcSpace/IfcFurnishing → interior; IfcWall → ambiguous |
| **Exterior Geometry Assembly** | Combine confirmed-exterior elements into single multipatch | Single multipatch geometry per building; no interior faces visible; correct face normals |
| **GeoPackage Export** | Write multipatch to GeoPackage with attributes | Includes element_type, element_id, phase; spatial reference WGS84 + project CRS |
| **Stripped IFC Export** | Write a clean IFC file containing only exterior elements | Clone original IFC, remove interior elements, strip orphaned relationships (materials, containment); output is structurally valid IFC2x3/IFC4 |
| **Ambiguity Report** | Count and list ambiguous elements, suggest AI mode | Report: total elements, confirmed exterior, confirmed interior, ambiguous; ambiguity score as % |
| **CLI Interface** | Command-line tool for batch processing | `exterior-shell extract input.ifc -o output.gpkg [--stripped-ifc] [--ai]` |

#### Phase 2: AI-Enhanced Extraction

| Feature | Description | Acceptance Criteria |
|---|---|---|
| **Multi-View Rendering** | Render IFC model from 8+ viewpoints | Headless rendering, no browser dependency; consistent lighting; element highlighting |
| **AI Vision Classification** | Send rendered views to vision model, classify ambiguous elements | Works with GPT-4o and Claude; per-element classification with confidence; multi-view agreement |
| **Classification Aggregation** | Combine AI classifications across viewpoints | Element classified as exterior if 6/8+ views agree; flag low-confidence elements |
| **Re-Extraction with AI Labels** | Re-run geometry assembly using AI classifications | Produces improved shell; handles elements that rule-based missed or misclassified |
| **API Key Management** | Secure storage of OpenAI/Anthropic API keys | .env file; no hardcoded keys; clear error messages for missing/invalid keys |
| **Cost Estimation** | Report API cost before running AI pass | "$X.XX for Y ambiguous elements across N views" |

#### Phase 3: Advanced Features

| Feature | Description | Priority |
|---|---|---|
| **LOD Generation** | Auto-generate LOD0 (footprint), LOD1 (box), LOD2 (full shell) | P2 |
| **Revit Direct Integration** | Read .rvt files via Revit API (headless via pyRevit or Dynamo) | P1 |
| **3D Tiles Export** | Export as Cesium 3D Tiles for web visualization | P2 |
| **Web UI** | Browser-based upload and download interface | P3 |
| **Batch Processing** | Process directory of IFC files with config | P2 |
| **Quality Metrics** | Report geometric accuracy, face count reduction, file size comparison | P2 |

### 5.4 Classification Rules (MVP)

```
RULES ENGINE (ifcopenshell)

ALWAYS EXTERIOR:
  - IfcRoof
  - IfcWindow
  - IfcDoor
  - IfcCurtainWall
  - IfcSlab (predefinedtype = ROOF)
  - IfcChimney
  - IfcPile (exterior structural)

ALWAYS INTERIOR (STRIP):
  - IfcSpace
  - IfcBuildingStorey
  - IfcFurnishingElement
  - IfcCovering (interior finishes)
  - IfcStair (interior stairs)
  - IfcRailing (interior railings)
  - IfcPlate (interior partitions)
  - IfcMember (interior framing)

AMBIGUOUS (NEEDS AI OR USER DECISION):
  - IfcWall (could be exterior or interior)
  - IfcWallStandardCase (same)
  - IfcColumn (could be exterior structural or interior)
  - IfcBeam (same)
  - IfcSlab (predefinedtype = FLOOR — could be ground floor exterior)
  - IfcStair (could be exterior entrance stair)
  - IfcRailing (could be exterior balcony railing)
  - IfcPlate (could be exterior cladding)
```

### 5.5 AI Classification Specification (Phase 2)

**Input to AI**:
- 8 rendered views of the model (front, back, left, right, 4 angled)
- Each view annotated: confirmed-exterior elements in green, ambiguous elements in yellow
- Prompt template (fixed, versioned)

**Prompt template**:
```
You are analyzing a 3D building model to identify which elements are part of the
exterior building envelope. The model shows:
- GREEN elements: confirmed exterior (roof, windows, doors, curtain walls)
- YELLOW elements: candidates that could be exterior or interior walls/structures

For each YELLOW element visible in this view, classify it as:
- EXTERIOR: The element is part of the building's outer shell
- INTERIOR: The element is inside the building, not visible from outside
- UNCERTAIN: Cannot determine from this viewpoint

Element IDs are labeled in the image. Return results as JSON:
[{"element_id": "xxx", "classification": "EXTERIOR|INTERIOR|UNCERTAIN", "confidence": 0.0-1.0}]
```

**Aggregation logic**:
- EXTERIOR in 6/8 views → classified as exterior (high confidence)
- EXTERIOR in 4-5/8 views → classified as exterior (medium confidence, flag for review)
- UNCERTAIN in 6+ views → classified as exterior (benefit of doubt, conservative)
- INTERIOR in 6/8 views → classified as interior
- Otherwise → classified as exterior with warning

**Conservative bias**: When uncertain, classify as EXTERIOR. Better to include a few interior elements than miss an exterior wall.

---

## 6. Technical Architecture

### 6.1 Stack

| Component | Technology | Rationale |
|---|---|---|
| Language | Python 3.10+ | User's primary language, rich BIM/GIS ecosystem |
| IFC Parsing | ifcopenshell | De facto standard, open-source, mature |
| Geometry Processing | Shapely + numpy | Face merging, coplanar detection, triangulation |
| Multipatch Output | GeoPackage via GDAL/ogr2ogr | User's existing GIS toolchain |
| Rendering (Phase 2) | pyvista or trimesh | Headless, Python-native, no browser |
| AI Vision (Phase 2) | OpenAI GPT-4o API | Best accuracy for structured vision tasks |
| CLI Framework | Click | Clean argument parsing, help text |
| Packaging | pyproject.toml + pip | Standard Python packaging |
| Testing | pytest | User's preferred framework |

### 6.2 Module Structure

```
exterior-shell/
├── pyproject.toml
├── README.md
├── LICENSE
├── exterior_shell/
│   ├── __init__.py
│   ├── cli.py                  # Click CLI entry point
│   ├── core/
│   │   ├── __init__.py
│   │   ├── parser.py           # IFC parsing with ifcopenshell
│   │   ├── classifier.py       # Rule-based classification engine
│   │   ├── assembler.py        # Geometry assembly + multipatch creation
│   │   ├── simplifier.py       # Mesh decimation + face merging
│   │   └── models.py           # Data classes (Element, Classification, Shell)
│   ├── ai/
│   │   ├── __init__.py
│   │   ├── renderer.py         # Multi-view rendering of IFC model
│   │   ├── classifier.py       # Vision model API calls
│   │   ├── aggregator.py       # Multi-view classification aggregation
│   │   └── prompts.py          # Versioned prompt templates
│   ├── export/
│   │   ├── __init__.py
│   │   ├── geopackage.py       # GeoPackage/multipatch export
│   │   ├── stripped_ifc.py     # Stripped IFC export (exterior only)
│   │   ├── geojson.py          # GeoJSON with extruded polygons
│   │   └── report.py           # Extraction report generation
│   └── utils/
│       ├── __init__.py
│       ├── geometry.py         # Geometry helpers (normals, merging, etc.)
│       └── io.py               # File I/O helpers
├── tests/
│   ├── conftest.py
│   ├── test_parser.py
│   ├── test_classifier.py
│   ├── test_assembler.py
│   ├── test_export.py
│   ├── test_cli.py
│   └── fixtures/
│       ├── simple_house.ifc        # Clean test model
│       ├── messy_model.ifc          # Early-stage model with bad metadata
│       └── complex_building.ifc     # Multi-story with varied elements
└── docs/
    ├── architecture.md
    └── classification_rules.md
```

### 6.3 Data Flow

```
Input IFC File
    │
    ▼
┌─────────────────────────────────────────┐
│ PARSER (parser.py)                      │
│ - Load IFC with ifcopenshell            │
│ - Extract IfcBuilding → spatial tree    │
│ - For each element: type, geometry,     │
│   bounding box, spatial containment     │
│ - Output: List[Element]                 │
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│ CLASSIFIER (classifier.py)             │
│ - Apply rule table to each Element      │
│ - Result: EXTERIOR / INTERIOR /         │
│           AMBIGUOUS                     │
│ - Count elements per category           │
│ - Output: ClassificationReport          │
└─────────────────────────────────────────┘
    │
    ├── [if --ai] ──► AI CLASSIFICATION PIPELINE
    │                  (renderer → classifier → aggregator)
    │                  Re-classifies AMBIGUOUS elements
    │
    ▼
┌─────────────────────────────────────────┐
│ ASSEMBLER (assembler.py)               │
│ - Collect all EXTERIOR elements         │
│ - Merge into single multipatch          │
│ - Remove hidden faces (interior-facing) │
│ - Fix normals (all face outward)        │
│ - Output: ShellGeometry                 │
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│ SIMPLIFIER (simplifier.py) [Optional]   │
│ - Merge coplanar adjacent faces         │
│ - Decimate non-essential detail         │
│ - Preserve visual feature edges         │
│ - Output: SimplifiedShellGeometry       │
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│ EXPORTER (geopackage.py / geojson.py)  │
│ - Write geometry to chosen format       │
│ - Add attributes: element_type, id,     │
│   classification_source, confidence     │
│ - Generate extraction report            │
│ - Output: .gpkg / .geojson + report.md  │
└─────────────────────────────────────────┘
    │
    ├── [if --stripped-ifc] ──► STRIPPED IFC EXPORTER
    │                           (stripped_ifc.py)
    │                           - Clone original IFC file
    │                           - Remove interior elements
    │                           - Strip orphaned relationships
    │                           - Write clean .ifc output
    │
    ▼
┌─────────────────────────────────────────┐
│ STRIPPED IFC EXPORT (stripped_ifc.py)  │
│ - Clone original IFC via ifcopenshell   │
│ - Remove all INTERIOR-classified elements│
│ - Strip orphaned:                       │
│   material associations, containment,   │
│   property sets, spatial hierarchy      │
│ - Validate output IFC structure         │
│ - Output: stripped_<name>.ifc           │
└─────────────────────────────────────────┘
```

---

## 7. Development Phases

### Phase 1: MVP (Rule-Based Extraction)

**Goal**: Working CLI tool that extracts exterior shells from IFC files without AI.

| Week | Deliverable | Details |
|---|---|---|
| 1 | Project scaffolding + IFC parser | pyproject.toml, module structure, ifcopenshell parsing, Element data model |
| 2 | Rule-based classifier + geometry assembly | Classification engine, multipatch assembly, face merging |
| 3 | GeoPackage export + CLI | Export pipeline, Click CLI, extraction report |
| 4 | Testing + polish | Unit tests, test fixtures, edge cases, README |

**Exit criteria**: CLI tool processes a messy early-stage IFC file and produces a usable GeoPackage with exterior shell geometry. Ambiguity report is accurate.

### Phase 2: AI-Enhanced Extraction

**Goal**: Optional AI classification improves accuracy on messy models.

| Week | Deliverable | Details |
|---|---|---|
| 5 | Multi-view renderer | Headless IFC rendering from 8 viewpoints, element highlighting |
| 6 | AI classifier + aggregator | Vision model integration, prompt engineering, multi-view aggregation |
| 7 | Integration + cost estimation | Wire AI into main pipeline, cost reporting, API key management |
| 8 | End-to-end testing + documentation | Test with real Dar project IFC files, refine prompts |

**Exit criteria**: AI mode classifies ambiguous walls with >85% accuracy on test models. Cost per model is under $2.

### Phase 3: Expansion

**Goal**: Revit direct integration, 3D Tiles, web UI.

| Week | Deliverable | Details |
|---|---|---|
| 9-10 | Revit API integration | Direct .rvt reading, headless Revit via pyRevit or similar |
| 11-12 | 3D Tiles export + LOD generation | Cesium 3D Tiles output, auto-LOD generation |
| 13-14 | Web UI prototype | Browser-based upload/download, optional AI toggle |

---

## 8. Testing Strategy

### 8.1 Test Fixtures

Three IFC test models needed:

| Model | Purpose | Characteristics |
|---|---|---|
| `simple_house.ifc` | Baseline test | Clean IFC, single-story, well-classified elements |
| `messy_model.ifc` | Real-world test | Early-stage, walls without classification, missing metadata |
| `complex_building.ifc` | Scale test | Multi-story, mixed elements, 1000+ elements |

### 8.2 Test Categories

| Category | What | Method |
|---|---|---|
| **Unit** | Parser extracts correct element types | pytest, fixture-based |
| **Unit** | Classifier assigns correct labels | pytest, known input/output pairs |
| **Integration** | Full pipeline: IFC → GeoPackage | End-to-end with test fixtures |
| **Regression** | Results don't break between versions | Golden file comparison |
| **Accuracy** (Phase 2) | AI classification correctness | Compare against manually labeled ground truth |
| **Performance** | Large model processing time | Benchmark: <60s for 5000-element IFC |

### 8.3 Manual QA Checklist

For each test model:
- [ ] Open output GeoPackage in ArcGIS Pro
- [ ] Visual inspection: no interior elements visible
- [ ] Visual inspection: all exterior features present (roof, windows, walls)
- [ ] Geometry is valid (no self-intersections, correct normals)
- [ ] File size is reasonable (rule of thumb: <10% of input IFC geometry)
- [ ] Element attributes are correct in attribute table

---

## 9. Success Metrics

### MVP (Phase 1)

| Metric | Target | Measurement |
|---|---|---|
| **Extraction accuracy** | >90% of exterior elements correctly identified (on well-structured IFC) | Manual inspection against 3 test models |
| **False positive rate** | <5% interior elements included | Count interior faces in output |
| **File size reduction** | >80% reduction vs full model geometry | Compare input/output geometry weights |
| **Processing speed** | <30 seconds for typical model (5000 elements) | Benchmark on Dell laptop |
| **User satisfaction** | "This is better than manual cleanup" | Feedback from 3 Dar colleagues |

### Phase 2 (AI)

| Metric | Target | Measurement |
|---|---|---|
| **AI classification accuracy** | >85% on ambiguous walls | Ground truth comparison |
| **Cost per model** | <$2.00 for GPT-4o | API usage tracking |
| **Ambiguity resolution** | >70% of ambiguous elements correctly reclassified | Manual verification |

---

## 10. Open Questions

| # | Question | Impact | Decision Needed By |
|---|---|---|---|
| 1 | What is the final product name? | Branding, domain, packaging | Before Phase 3 |
| 2 | Open-source or proprietary? | Distribution model, community building | Before MVP launch |
| 3 | CLI-only for MVP, or include minimal web UI? | Development time, user accessibility | Before Phase 1 |
| 4 | Should it handle multi-building IFC files? | Parsing complexity, edge cases | Week 1 |
| 5 | Target CRS handling: WGS84 only, or user-configurable? | Export complexity | Week 2 |
| 6 | License: MIT (like arcgis-portal-mcp) or more restrictive? | Community adoption, commercialization | Before MVP launch |

---

## 11. Dependencies

| Dependency | Version | Purpose | Risk |
|---|---|---|---|
| ifcopenshell | latest | IFC parsing | Low (mature, active) |
| shapely | 2.0+ | Geometry operations | Low (mature) |
| numpy | 1.24+ | Array operations | Low (mature) |
| GDAL/ogr2ogr | 3.x | GeoPackage export | Low (already installed) |
| click | 8.0+ | CLI framework | Low (mature) |
| pyvista | latest | 3D rendering (Phase 2) | Medium (headless rendering) |
| openai | latest | Vision API (Phase 2) | Low (stable API) |

---

## Appendix A: Similar Products in the Market

| Product | What it does | Price | Limitation |
|---|---|---|---|
| Esri ExteriorShell | Auto-extract exterior from Revit/IFC in ArcGIS Pro | Free (with ArcGIS Pro license) | Broken: misses elements, includes junk, poor reliability |
| FME | General BIM-to-GIS conversion | ~$4,200/year | Overkill for this task, expensive |
| GISBox | Full BIM-to-3D-Tiles conversion | Free tier available | Converts everything, not exterior-only |
| Cesium ion | 3D Tiles hosting + conversion | $varies | Requires source 3D Tiles, doesn't do BIM classification |
| Polygon Cruncher | Generic mesh decimation | One-time license | Not BIM-aware, no classification |

**Our differentiator**: Purpose-built for ONE task (exterior shell extraction), affordable, optional AI for messy models, GIS-native output.

---

*This document is a living reference. Update as decisions are made and implementation progresses.*
