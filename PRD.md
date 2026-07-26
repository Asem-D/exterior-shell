# Product Requirements Document: BIM Exterior Shell Extractor

> **Version**: 1.2.0
> **Date**: 2026-07-18
> **Author**: Asem Daaboul
> **Status**: MVP Released (v1.2.0)

---

## 1. Product Overview

**Product Name**: exterior-shell

**One-liner**: Extract lightweight exterior shells from BIM models (IFC) for GIS and visualization workflows.

**What it does**: Takes an IFC file as input, classifies elements as exterior/interior using a rule-based engine, and produces a structurally valid stripped IFC (default) plus an optional 2D footprint GeoJSON with elevation attributes. Optionally uses AI vision models to improve classification accuracy on messy, early-stage models.

**What it is NOT**:
- Not a full BIM-to-GIS conversion tool (that's FME, ArcGIS Pro)
- Not a 3D reconstruction tool (not generating geometry from photos)
- Not a BIM authoring tool
- Not a CityJSON/STEP/OBJ generator (that's IfcEnvelopeExtractor)
- It does ONE thing: produce a clean, lightweight exterior shell from BIM data for GIS practitioners who receive IFC files they didn't ask for

---

## 2. Problem Statement

### The Pain

GIS teams in infrastructure consultancies don't ask for BIM models. They receive them. Architecture practices export IFC files and hand them off, and the GIS analyst is left with a 500MB model full of pipes, HVAC, and furniture when they need just the building envelope for a web map or spatial analysis.

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
4. **FME can solve it** but costs ~$4,200/year per seat, overkill for this one task

### Market Gap

There is no lightweight, affordable, purpose-built tool that converts BIM exterior shells to GIS-ready formats. The alternatives are:

- **Esri ExteriorShell**: Free but broken
- **IfcEnvelopeExtractor (TU Delft)**: Academic-grade, outputs CityJSON/STEP/OBJ with full LoD coverage. Different output ecosystem, not directly compatible with ArcGIS/web map workflows
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
> "When a GIS team receives a BIM model they didn't ask for, exterior-shell gives them a clean entry point. Not about merging BIM and GIS. About solving one specific problem well."

**Note on BIM-GIS convergence**: The industry narrative often oversells BIM-GIS integration. In practice, GIS workstreams and BIM workstreams are fundamentally different with different tools and display requirements. The more common need is bringing GIS context (terrain, utilities, roads, OSM) INTO BIM, not the reverse. exterior-shell exists for the narrower case where GIS practitioners receive BIM data and need a clean envelope for spatial analysis, web maps, or ArcGIS Pro visualization.

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
| Stripped IFC (.ifc) with exterior elements only | MVP (v1.2.0) | P0 — default output |
| 2D Footprint (.geojson) with base_elevation, height, area | MVP (v1.2.0) | P0 — opt-in via `--footprint` |
| 3D Tiles (.3dtiles) | Phase 3 | P2 |
| Per-floor footprints (`--floor-footprints`) | Future | P1 |

### 5.3 Core Features

#### Phase 1: Rule-Based Extraction (MVP)

| Feature | Description | Acceptance Criteria |
|---|---|---|
| **IFC Parsing** | Read IFC files, extract geometry and element metadata | Handles IFC2x3 and IFC4; extracts element types, geometry, spatial hierarchy |
| **Rule-Based Classification** | Classify elements as exterior/interior based on IFC type | IfcRoof → exterior; IfcWindow/IfcDoor → exterior; IfcSpace/IfcFurnishing → interior; IfcWall → ambiguous |
| **Exterior Geometry Assembly** | Combine confirmed-exterior elements into single multipatch | Single multipatch geometry per building; no interior faces visible; correct face normals |
| **Stripped IFC Export** (default) | Write a clean IFC file containing only exterior elements | Clone original IFC, remove interior elements, strip orphaned relationships (materials, containment); output is structurally valid IFC2x3/IFC4. Always produced unless `--no-stripped-ifc` |
| **2D Footprint Export** (opt-in) | Project exterior faces to XY plane, union into outline polygon | Output: GeoJSON FeatureCollection with `base_elevation`, `height`, `min_elevation`, `max_elevation`, `area` properties. Activated via `--footprint` flag. |
| **Ambiguity Report** | Count and list ambiguous elements, suggest AI mode | Report: total elements, confirmed exterior, confirmed interior, ambiguous; ambiguity score as % |
| **CLI Interface** | Command-line tool for extraction | `exterior-shell extract input.ifc [--footprint] [--no-stripped-ifc] [--ai] [--crs EPSG:3857] [--json-stats] [--report/--no-report]` |

#### Phase 2: AI-Enhanced Extraction

| Feature | Description | Acceptance Criteria |
|---|---|---|
| **Multi-View Rendering** | Render IFC model from 8+ viewpoints | Headless rendering, no browser dependency; consistent lighting; element highlighting |
| **AI Vision Classification** | Send rendered views to vision model, classify ambiguous elements | Works with GPT-4o and Claude; per-element classification with confidence; multi-view agreement |
| **Classification Aggregation** | Combine AI classifications across viewpoints | Element classified as exterior if 6/8+ views agree; flag low-confidence elements |
| **Re-Extraction with AI Labels** | Re-run geometry assembly using AI classifications | Produces improved shell; handles elements that rule-based missed or misclassified |
| **API Key Management** | Secure storage of OpenAI/Anthropic API keys | .env file; no hardcoded keys; clear error messages for missing/invalid keys |
| **Cost Estimation** | Report API cost before running AI pass | "$X.XX for Y ambiguous elements across N views" |

#### Phase 3: Provenance and Trust

| Feature | Description | Priority |
|---|---|---|
| **IFC GlobalId Linking** | Map output features back to source IFC element GlobalIds | P1 |
| **Extraction Parameters** | Record classification rules, AI model version, and settings used | P1 |
| **Spatial Validation** | Validate projected footprint is consistent with source shell geometry | P1 |
| **Provenance Metadata** | Embed extraction metadata in GeoJSON properties and IFC header | P2 |

#### Phase 4: Advanced Features

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
| Geometry Processing | Shapely + numpy | Face merging, exterior face detection, footprint union |
| Rendering (Phase 2) | pyvista or trimesh | Headless, Python-native, no browser |
| AI Vision (Phase 2) | OpenAI GPT-4o API | Best accuracy for structured vision tasks |
| CLI Framework | Click | Clean argument parsing, help text |
| Packaging | pyproject.toml + pip | Standard Python packaging |
| Testing | pytest | User's preferred framework |

> **Note**: GDAL and geopandas were removed in v1.2.0. The tool now has zero heavy GIS dependencies. Only ifcopenshell, Shapely, numpy, and click are required.

### 6.2 Module Structure

```
exterior-shell/
├── pyproject.toml
├── README.md
├── LICENSE
├── py.typed
├── exterior_shell/
│   ├── __init__.py
│   ├── cli.py                  # Click CLI entry point
│   ├── core/
│   │   ├── __init__.py
│   │   ├── parser.py           # IFC parsing with ifcopenshell
│   │   ├── classifier.py       # Rule-based classification engine
│   │   ├── assembler.py        # Geometry assembly + face deduplication
│   │   ├── shell_detection.py  # Exterior face detection via STRtree
│   │   └── models.py           # Data classes (Element, Classification, Shell)
│   ├── ai/
│   │   └── ...                 # Vision model classification (Phase 2)
│   ├── export/
│   │   ├── __init__.py
│   │   ├── stripped_ifc.py     # Stripped IFC export (remove interior elements)
│   │   ├── footprint.py        # 2D footprint GeoJSON with elevation attributes
│   │   └── report.py           # Extraction report generation
│   └── utils/
│       ├── __init__.py
│       ├── geometry.py         # Geometry helpers (normals, face ops)
│       └── io.py               # File I/O helpers
├── tests/
│   ├── test_core.py            # Core logic tests (9 tests)
│   ├── test_extraction.py      # Extraction pipeline tests (4 tests)
│   ├── test_shell_detection.py # Shell detection tests (13 tests)
│   ├── test_stripped_ifc.py    # Stripped IFC validity tests (7 tests)
│   ├── test_helpers.py         # Utility tests (5 tests)
│   └── fixtures/
│       ├── simple_house.ifc    # Clean test model
│       └── ...                 # Test fixtures
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
│ EXPORT                                    │
│                                           │
│ ├── Stripped IFC (default)                │
│ │   Clone original IFC                    │
│ │   Remove interior elements              │
│ │   Strip orphaned relationships          │
│ │   Output: <name>_stripped.ifc           │
│ │                                         │
│ ├── 2D Footprint (opt-in: --footprint)   │
│ │   Project exterior faces to XY plane    │
│ │   Union into single outline polygon     │
│ │   Compute base_elevation, height, area  │
│ │   Output: <name>_footprint.geojson      │
│ │                                         │
│ └── Report (default, skip with --no-report)
│     Element counts, ambiguity score       │
│     Output: <name>.report.md              │
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

**Exit criteria** (achieved in v1.2.0): CLI tool processes an IFC file and produces a structurally valid stripped IFC (default) plus optional 2D footprint GeoJSON with elevation attributes. 38 passing tests including Z-coordinate and IFC validity regressions.

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
| **Extraction accuracy** | >90% of exterior elements correctly identified | Manual inspection against test models |
| **False positive rate** | <5% interior elements included | Count interior faces in output |
| **File size reduction** | 33-78% reduction vs full model | Measured: test house 78%, office 33.2% |
| **Processing speed** | <30 seconds for typical model | Measured: test house <2s, office ~26s |
| **Test coverage** | 38 passing tests | Core, extraction, shell detection, stripped IFC, helpers |
| **Dependencies** | Zero heavy GIS deps | Removed GDAL, geopandas; only ifcopenshell, shapely, numpy, click |

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
| # | Question | Impact | Status |
|---|---|---|---|
| 1 | What is the final product name? | Branding, domain, packaging | **Decided**: exterior-shell |
| 2 | Open-source or proprietary? | Distribution model, community building | **Decided**: Open-source (MIT) |
| 3 | CLI-only for MVP, or include minimal web UI? | Development time, user accessibility | **Decided**: CLI-only for MVP |
| 4 | Should it handle multi-building IFC files? | Parsing complexity, edge cases | **Decided**: Yes, process first building |
| 5 | Target CRS handling: WGS84 only, or user-configurable? | Export complexity | **Decided**: User-configurable via `--crs` (default WGS84) |
| 6 | GeoPackage 3D export viable? | Output format complexity | **Decided**: Removed in v1.2.0 — GPKG binary header Z flag broken, ArcGIS Pro reads as 2D |
| 7 | Mesh simplifier needed? | Performance, code complexity | **Decided**: Removed in v1.2.0 — O(n^2) too slow for large models |
| 8 | Per-floor footprints for MVP? | Feature scope | **Deferred**: Planned for future release |
| 9 | --floor-footprints flag | Feature scope | **Deferred**: Planned for future release |

---

## 11. Dependencies

| Dependency | Version | Purpose | Risk |
|---|---|---|---|
| ifcopenshell | latest | IFC parsing | Low (mature, active) |
| shapely | 2.0+ | Geometry operations | Low (mature) |
| numpy | 1.24+ | Array operations | Low (mature) |
| ~~GDAL/ogr2ogr~~ | ~~3.x~~ | ~~GeoPackage export~~ | **Removed in v1.2.0** (broken Z-coordinates) |
| click | 8.0+ | CLI framework | Low (mature) |
| pyvista | latest | 3D rendering (Phase 2) | Medium (headless rendering) |
| openai | latest | Vision API (Phase 2) | Low (stable API) |

---

## Appendix A: Competitive Landscape

### Direct Competitors

| Product | Output Format | LoD Coverage | IFC Versions | Dependencies | Price |
|---|---|---|---|---|---|
| **exterior-shell** | Stripped IFC + GeoJSON | Exterior shell + footprint | IFC2x3, IFC4 | ifcopenshell, shapely, numpy | Free (MIT) |
| **IfcEnvelopeExtractor (TU Delft)** | CityJSON, STEP, OBJ | LOD0 through LOD5 (full spectrum) | IFC2x3, IFC4, IFC4x3 | C++ binaries | Free (academic) |
| **IfcConvert** | Mesh (OBJ, STL, etc.) | Exterior shell only | IFC2x3, IFC4 | IfcOpenShell | Free (LGPL) |
| **Esri ExteriorShell** | ArcGIS Pro building layer | Automatic sublayer | IFC, RVT | ArcGIS Pro | License required |
| **FME** | Multiple (via transformers) | Full BIM-to-GIS | Multiple | FME Desktop | ~$4,200/year |

### Key Differences

- **exterior-shell** targets GIS practitioners who need a clean stripped IFC plus GeoJSON footprint for ArcGIS/web map workflows. Rule-based by default, optional AI for messy models. Zero heavy GIS dependencies.
- **IfcEnvelopeExtractor** targets 3D city modeling with CityJSON output and full LoD framework coverage. Academic-grade, built on Biljecki et al. LoD taxonomy. Different output ecosystem.
- **IfcConvert** is a general-purpose IFC converter with an `--exterior-only` flag. Outputs mesh only, no structurally valid IFC, no GIS attributes.
- **Esri ExteriorShell** is built into ArcGIS Pro but unreliable: misses roofs, ground floors, includes interior geometry. No standalone output file.

### Our Differentiator

Purpose-built for ONE task: giving GIS practitioners a clean entry point when they receive BIM data they didn't ask for. First open-source CLI outputting both structurally valid stripped IFC and 2D footprint with elevation attributes. Not about merging BIM and GIS. About solving one specific problem well.

---

*This document is a living reference. Update as decisions are made and implementation progresses.*
