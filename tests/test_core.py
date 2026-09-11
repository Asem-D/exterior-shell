"""Tests for exterior-shell core modules."""

import tempfile
from pathlib import Path

import pytest

from exterior_shell.core.models import (
    Classification,
    ClassificationReport,
    ClassificationSource,
    Element,
    ElementType,
    Face,
    ExtractionResult,
    ShellGeometry,
)
from exterior_shell.core.classifier import classify_element, classify_all, resolve_ambiguities
from exterior_shell.core.assembler import assemble_shell, get_shell_stats


# ── Model tests ──────────────────────────────────────────────────────────────


def test_element_face_count():
    """Element.face_count returns the number of faces."""
    e = Element(
        global_id="test",
        name="Test Wall",
        ifc_type="IfcWallStandardCase",
        element_type=ElementType.WALL_STANDARD,
        faces=[],
    )
    assert e.face_count == 0


def test_element_volume():
    """Element.volume computes approximate volume from bbox."""
    import numpy as np
    e = Element(
        global_id="test",
        name="Test Wall",
        ifc_type="IfcWallStandardCase",
        element_type=ElementType.WALL_STANDARD,
        bbox_min=np.array([0, 0, 0]),
        bbox_max=np.array([10, 1, 3]),
    )
    assert abs(e.volume - 30.0) < 0.01


def test_classification_report_ambiguity_score():
    """Ambiguity score is computed correctly."""
    report = ClassificationReport(
        total_elements=100,
        exterior_count=50,
        interior_count=30,
        ambiguous_count=20,
    )
    assert abs(report.ambiguity_score - 20.0) < 0.01


def test_classification_report_summary():
    """Summary returns a readable string."""
    report = ClassificationReport(
        total_elements=10,
        exterior_count=5,
        interior_count=3,
        ambiguous_count=2,
    )
    s = report.summary()
    assert "Total elements" in s
    assert "10" in s


# ── Classifier tests ─────────────────────────────────────────────────────────


def test_wall_is_ambiguous():
    """Standard walls are ambiguous (could be exterior or interior)."""
    e = Element(
        global_id="test",
        name="Wall",
        ifc_type="IfcWallStandardCase",
        element_type=ElementType.WALL_STANDARD,
    )
    assert classify_element(e) == Classification.AMBIGUOUS


def test_window_is_exterior():
    """Windows are always exterior."""
    e = Element(
        global_id="test",
        name="Window",
        ifc_type="IfcWindow",
        element_type=ElementType.WINDOW,
    )
    assert classify_element(e) == Classification.EXTERIOR


def test_door_is_exterior():
    """Doors are always exterior."""
    e = Element(
        global_id="test",
        name="Door",
        ifc_type="IfcDoor",
        element_type=ElementType.DOOR,
    )
    assert classify_element(e) == Classification.EXTERIOR


def test_roof_is_exterior():
    """Roofs are always exterior."""
    e = Element(
        global_id="test",
        name="Roof",
        ifc_type="IfcRoof",
        element_type=ElementType.ROOF,
    )
    assert classify_element(e) == Classification.EXTERIOR


def test_furniture_is_interior():
    """Furnishing elements are always interior."""
    e = Element(
        global_id="test",
        name="Chair",
        ifc_type="IfcFurnishingElement",
        element_type=ElementType.FURNISHING,
    )
    assert classify_element(e) == Classification.INTERIOR


def test_hvac_is_interior():
    """Flow segments (HVAC ducts) are interior."""
    e = Element(
        global_id="test",
        name="Duct",
        ifc_type="IfcFlowSegment",
        element_type=ElementType.FLOW_SEGMENT,
    )
    assert classify_element(e) == Classification.INTERIOR


def test_roof_slab_is_exterior():
    """Slabs with predefined type ROOF are exterior."""
    e = Element(
        global_id="test",
        name="Roof Slab",
        ifc_type="IfcSlab",
        element_type=ElementType.SLAB,
        predefined_type="ROOF",
    )
    assert classify_element(e) == Classification.EXTERIOR


def test_floor_slab_is_ambiguous():
    """FLOOR slabs are ambiguous."""
    e = Element(
        global_id="test",
        name="Floor Slab",
        ifc_type="IfcSlab",
        element_type=ElementType.SLAB,
        predefined_type="FLOOR",
    )
    assert classify_element(e) == Classification.AMBIGUOUS


def test_classify_all_produces_report():
    """classify_all returns a complete report."""
    elements = [
        Element("1", "Wall", "IfcWallStandardCase", ElementType.WALL_STANDARD),
        Element("2", "Window", "IfcWindow", ElementType.WINDOW),
        Element("3", "Door", "IfcDoor", ElementType.DOOR),
        Element("4", "Chair", "IfcFurnishingElement", ElementType.FURNISHING),
        Element("5", "Roof", "IfcRoof", ElementType.ROOF),
    ]
    report = classify_all(elements)
    assert report.total_elements == 5
    assert report.exterior_count == 3  # window, door, roof
    assert report.interior_count == 1  # chair
    assert report.ambiguous_count == 1  # wall


def test_resolve_ambiguities_moves_to_exterior():
    """Resolving ambiguities moves ambiguous elements to exterior."""
    report = ClassificationReport(
        total_elements=3,
        exterior_count=1,
        interior_count=1,
        ambiguous_count=1,
        ambiguous_elements=[
            Element("amb", "Wall", "IfcWallStandardCase", ElementType.WALL_STANDARD),
        ],
    )
    resolve_ambiguities(report)
    assert report.ambiguous_count == 0
    assert report.exterior_count == 2
    assert len(report.ambiguous_elements) == 0


# ── Assembler tests ──────────────────────────────────────────────────────────


def test_assemble_empty_shell():
    """Assembling empty list produces empty shell."""
    shell = assemble_shell([])
    assert shell.total_face_count == 0
    assert shell.element_count == 0


def test_assemble_with_faces():
    """Assembling elements with faces produces a shell."""
    import numpy as np
    face1 = Face(
        vertices=np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0]], dtype=float),
        normal=np.array([0, 0, 1], dtype=float),
    )
    face2 = Face(
        vertices=np.array([[1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype=float),
        normal=np.array([0, 0, 1], dtype=float),
    )
    elem = Element(
        global_id="test",
        name="Roof",
        ifc_type="IfcRoof",
        element_type=ElementType.ROOF,
        faces=[face1, face2],
    )
    shell = assemble_shell([elem])
    assert shell.total_face_count == 2
    assert shell.element_count == 1


def test_shell_stats():
    """get_shell_stats returns expected keys."""
    import numpy as np
    face = Face(
        vertices=np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0]], dtype=float),
        normal=np.array([0, 0, 1], dtype=float),
    )
    shell = ShellGeometry(faces=[face], element_count=1, total_face_count=1)
    stats = get_shell_stats(shell)
    assert "face_count" in stats
    assert "bbox" in stats
    assert "total_area" in stats


# ── Provenance ──────────────────────────────────────────────────────────────


def test_extraction_params_defaults():
    """ExtractionParams has correct defaults."""
    from exterior_shell.core.models import ExtractionParams
    p = ExtractionParams()
    assert p.version == "2.0.0"
    assert p.crs == "EPSG:4326"
    assert p.ai_enabled is False
    assert p.classification_mode == "rule_based"


def test_extraction_params_to_dict():
    """ExtractionParams.to_dict serializes correctly."""
    from exterior_shell.core.models import ExtractionParams
    p = ExtractionParams(ai_enabled=True, ai_model="openai/gpt-4o-mini")
    d = p.to_dict()
    assert d["ai_enabled"] is True
    assert d["ai_model"] == "openai/gpt-4o-mini"
    assert d["classification_mode"] == "rule_based"  # not auto-set by to_dict
    assert "version" in d


def test_extraction_params_summary():
    """ExtractionParams.summary includes key fields."""
    from exterior_shell.core.models import ExtractionParams
    p = ExtractionParams(ai_enabled=True, ai_model="gpt-4o")
    s = p.summary()
    assert "2.0.0" in s
    assert "EPSG:4326" in s
    assert "gpt-4o" in s


def test_contributing_global_ids_populated():
    """ShellGeometry.contributing_global_ids is populated from elements."""
    import numpy as np
    from exterior_shell.core.models import Element, ElementType, Classification
    e1 = Element(global_id="id-001", name="Wall", ifc_type="IfcWall", element_type=ElementType.WALL)
    e2 = Element(global_id="id-002", name="Roof", ifc_type="IfcRoof", element_type=ElementType.ROOF)
    for e in (e1, e2):
        e.faces = [Face(
            vertices=np.array([[0,0,0],[1,0,0],[1,1,0]], dtype=float),
            normal=np.array([0,0,1], dtype=float),
        )]
        e.classification = Classification.EXTERIOR
    shell = assemble_shell([e1, e2])
    assert "id-001" in shell.contributing_global_ids
    assert "id-002" in shell.contributing_global_ids


def test_extraction_result_has_params():
    """ExtractionResult includes ExtractionParams by default."""
    from exterior_shell.core.models import ExtractionResult, ExtractionParams
    result = ExtractionResult()
    assert isinstance(result.params, ExtractionParams)
    assert result.params.version == "2.0.0"
