"""Tests for stripped IFC export."""

import tempfile
from pathlib import Path

import pytest

from exterior_shell.core.models import Classification, Element, ElementType
from exterior_shell.export.stripped_ifc import export_stripped_ifc


FIXTURES = Path(__file__).parent / "fixtures"
TEST_IFC = FIXTURES / "test_building.ifc"


@pytest.fixture
def sample_elements():
    """Build a mix of classified elements matching test_building.ifc."""
    import ifcopenshell

    model = ifcopenshell.open(str(TEST_IFC))

    elements = []
    for product in model.by_type("IfcProduct"):
        gid = product.GlobalId or f"auto_{product.id()}"
        ifc_type = product.is_a()
        name = product.Name or gid

        # Map IFC type to ElementType
        etype_map = {
            "IfcWall": ElementType.WALL,
            "IfcWallStandardCase": ElementType.WALL_STANDARD,
            "IfcWindow": ElementType.WINDOW,
            "IfcDoor": ElementType.DOOR,
            "IfcRoof": ElementType.ROOF,
            "IfcSlab": ElementType.SLAB,
            "IfcColumn": ElementType.COLUMN,
            "IfcBeam": ElementType.BEAM,
            "IfcStair": ElementType.STAIR,
            "IfcRailing": ElementType.RAILING,
            "IfcCurtainWall": ElementType.CURTAIN_WALL,
            "IfcPlate": ElementType.PLATE,
            "IfcMember": ElementType.MEMBER,
            "IfcCovering": ElementType.COVERING,
            "IfcFurnishingElement": ElementType.FURNISHING,
            "IfcFlowSegment": ElementType.FLOW_SEGMENT,
            "IfcFlowTerminal": ElementType.FLOW_TERMINAL,
            "IfcBuildingElementProxy": ElementType.BUILDING_ELEMENT_PROXY,
            "IfcOpeningElement": ElementType.OPENING_ELEMENT,
            "IfcSpace": ElementType.SPACE,
            "IfcBuildingStorey": ElementType.BUILDING_STOREY,
        }
        etype = etype_map.get(ifc_type, ElementType.UNKNOWN)

        # Interior elements for testing
        interior_types = {
            "IfcFurnishingElement", "IfcFlowSegment", "IfcFlowTerminal",
            "IfcFlowFitting", "IfcFlowController", "IfcSpace",
            "IfcCovering", "IfcBuildingStorey",
        }

        if ifc_type in interior_types:
            cls = Classification.INTERIOR
        else:
            cls = Classification.EXTERIOR

        elements.append(Element(
            global_id=gid,
            name=name,
            ifc_type=ifc_type,
            element_type=etype,
            classification=cls,
        ))

    return elements


class TestStrippedIfcExport:
    """Tests for the stripped IFC export functionality."""

    def test_export_creates_file(self, sample_elements, tmp_path):
        """Export produces an output IFC file."""
        output = tmp_path / "stripped.ifc"
        result = export_stripped_ifc(TEST_IFC, output, sample_elements)
        assert output.exists()
        assert output.stat().st_size > 0

    def test_export_removes_interior(self, sample_elements, tmp_path):
        """Interior elements are removed from the output."""
        import ifcopenshell

        output = tmp_path / "stripped.ifc"
        result = export_stripped_ifc(TEST_IFC, output, sample_elements)

        assert result["removed_count"] > 0
        assert result["kept_count"] > 0

        # Verify interior elements are gone
        model = ifcopenshell.open(str(output))
        interior_gids = {
            e.global_id for e in sample_elements
            if e.classification == Classification.INTERIOR
        }
        remaining_gids = {p.GlobalId for p in model.by_type("IfcProduct") if p.GlobalId}
        assert len(interior_gids & remaining_gids) == 0

    def test_export_keeps_exterior(self, sample_elements, tmp_path):
        """Exterior elements remain in the output."""
        import ifcopenshell

        output = tmp_path / "stripped.ifc"
        export_stripped_ifc(TEST_IFC, output, sample_elements)

        model = ifcopenshell.open(str(output))
        exterior_gids = {
            e.global_id for e in sample_elements
            if e.classification == Classification.EXTERIOR
        }
        remaining_gids = {p.GlobalId for p in model.by_type("IfcProduct") if p.GlobalId}
        # At least some exterior elements should remain
        assert len(exterior_gids & remaining_gids) > 0

    def test_export_valid_ifc(self, sample_elements, tmp_path):
        """Output IFC can be opened without errors."""
        import ifcopenshell

        output = tmp_path / "stripped.ifc"
        export_stripped_ifc(TEST_IFC, output, sample_elements)

        # Should not raise
        model = ifcopenshell.open(str(output))
        assert model.schema

    def test_export_returns_stats(self, sample_elements, tmp_path):
        """Export returns expected statistics dictionary."""
        output = tmp_path / "stripped.ifc"
        result = export_stripped_ifc(TEST_IFC, output, sample_elements)

        assert "removed_count" in result
        assert "kept_count" in result
        assert "orphaned_reps_removed" in result
        assert "orphaned_contexts_removed" in result
        assert "orphaned_history_removed" in result
        assert "input_size" in result
        assert "output_size" in result
        assert "size_reduction_pct" in result

    def test_export_size_reduction(self, sample_elements, tmp_path):
        """Stripped IFC is smaller than the original."""
        output = tmp_path / "stripped.ifc"
        result = export_stripped_ifc(TEST_IFC, output, sample_elements)

        assert result["output_size"] < result["input_size"]
        assert result["size_reduction_pct"] > 0

    def test_export_no_interior_no_removal(self, tmp_path):
        """When all elements are exterior, nothing is removed."""
        import ifcopenshell

        model = ifcopenshell.open(str(TEST_IFC))
        all_exterior = []
        for product in model.by_type("IfcProduct"):
            gid = product.GlobalId or f"auto_{product.id()}"
            all_exterior.append(Element(
                global_id=gid,
                name=product.Name or gid,
                ifc_type=product.is_a(),
                element_type=ElementType.UNKNOWN,
                classification=Classification.EXTERIOR,
            ))

        output = tmp_path / "stripped.ifc"
        result = export_stripped_ifc(TEST_IFC, output, all_exterior)
        assert result["removed_count"] == 0

    def test_export_missing_input_raises(self, sample_elements, tmp_path):
        """Missing input file raises FileNotFoundError."""
        output = tmp_path / "stripped.ifc"
        with pytest.raises(FileNotFoundError):
            export_stripped_ifc(tmp_path / "nonexistent.ifc", output, sample_elements)

    def test_export_all_interior_minimal_output(self, tmp_path):
        """When all elements are interior, minimal output remains."""
        import ifcopenshell

        model = ifcopenshell.open(str(TEST_IFC))
        all_interior = []
        for product in model.by_type("IfcProduct"):
            gid = product.GlobalId or f"auto_{product.id()}"
            all_interior.append(Element(
                global_id=gid,
                name=product.Name or gid,
                ifc_type=product.is_a(),
                element_type=ElementType.UNKNOWN,
                classification=Classification.INTERIOR,
            ))

        output = tmp_path / "stripped_all_interior.ifc"
        result = export_stripped_ifc(TEST_IFC, output, all_interior)
        assert result["removed_count"] > 0
        assert result["kept_count"] == 0
        # File still exists and is valid
        assert output.exists()

    def test_export_keep_ambiguous_false(self, tmp_path):
        """Setting keep_ambiguous=False removes ambiguous elements too."""
        import ifcopenshell

        model = ifcopenshell.open(str(TEST_IFC))
        elements = []
        for product in model.by_type("IfcProduct"):
            gid = product.GlobalId or f"auto_{product.id()}"
            elements.append(Element(
                global_id=gid,
                name=product.Name or gid,
                ifc_type=product.is_a(),
                element_type=ElementType.UNKNOWN,
                classification=Classification.AMBIGUOUS,
            ))

        output = tmp_path / "stripped_no_ambig.ifc"
        result = export_stripped_ifc(
            TEST_IFC, output, elements, keep_ambiguous=False,
        )
        assert result["removed_count"] > 0
        assert result["kept_count"] == 0
