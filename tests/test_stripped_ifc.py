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
            "IfcCovering",
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
        """When all elements are interior, only spatial anchors remain."""
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
        # Spatial anchors (Site, Building, Storey) are never stripped
        assert result["kept_count"] == 3
        # File still exists and is valid
        assert output.exists()

    def test_spatial_hierarchy_survives_interior_classification(self, tmp_path):
        """Site/Building/Storey are never removed, even if classified interior."""
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
                classification=Classification.INTERIOR,
            ))

        output = tmp_path / "stripped_anchors.ifc"
        export_stripped_ifc(TEST_IFC, output, elements)

        stripped = ifcopenshell.open(str(output))
        assert len(stripped.by_type("IfcSite")) == 1
        assert len(stripped.by_type("IfcBuilding")) == 1
        assert len(stripped.by_type("IfcBuildingStorey")) == 1

    def test_no_dangling_relations(self, sample_elements, tmp_path):
        """No empty aggregations or orphaned containment in the output."""
        import ifcopenshell

        output = tmp_path / "stripped.ifc"
        export_stripped_ifc(TEST_IFC, output, sample_elements)

        stripped = ifcopenshell.open(str(output))
        for rel in stripped.by_type("IfcRelAggregates"):
            assert rel.RelatedObjects, "empty IfcRelAggregates left behind"
        for rel in stripped.by_type("IfcRelContainedInSpatialStructure"):
            assert rel.RelatingStructure is not None, "dangling containment"
            assert rel.RelatedElements, "empty containment left behind"

    def test_elements_in_removed_space_reassigned(self, tmp_path):
        """Elements contained in a removed IfcSpace are reassigned to its storey."""
        import ifcopenshell
        import ifcopenshell.api

        f = ifcopenshell.api.run("project.create_file", version="IFC4")
        project = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcProject")
        ifcopenshell.api.run("unit.assign_unit", f)
        site = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcSite")
        building = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcBuilding")
        storey = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcBuildingStorey")
        space = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcSpace")
        ifcopenshell.api.run("aggregate.assign_object", f, products=[site], relating_object=project)
        ifcopenshell.api.run("aggregate.assign_object", f, products=[building], relating_object=site)
        ifcopenshell.api.run("aggregate.assign_object", f, products=[storey], relating_object=building)
        ifcopenshell.api.run("aggregate.assign_object", f, products=[space], relating_object=storey)
        wall = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcWall")
        trim = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcBuildingElementProxy")
        ifcopenshell.api.run("spatial.assign_container", f, products=[wall], relating_structure=storey)
        ifcopenshell.api.run("spatial.assign_container", f, products=[trim], relating_structure=space)

        src = tmp_path / "space_fixture.ifc"
        f.write(str(src))

        def el(product, cls):
            return Element(
                global_id=product.GlobalId,
                name=product.Name or product.GlobalId,
                ifc_type=product.is_a(),
                element_type=ElementType.UNKNOWN,
                classification=cls,
            )

        elements = [
            el(space, Classification.INTERIOR),
            el(wall, Classification.EXTERIOR),
            el(trim, Classification.EXTERIOR),
        ]

        output = tmp_path / "stripped_space.ifc"
        export_stripped_ifc(src, output, elements)

        stripped = ifcopenshell.open(str(output))
        assert len(stripped.by_type("IfcSpace")) == 0
        # trim was contained in the removed space; it must now hang off the storey
        trim_out = stripped.by_type("IfcBuildingElementProxy")[0]
        cont = [
            r for r in stripped.by_type("IfcRelContainedInSpatialStructure")
            if trim_out in (r.RelatedElements or [])
        ]
        assert len(cont) == 1
        assert cont[0].RelatingStructure.is_a("IfcBuildingStorey")

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
        # Only the spatial anchors (Site, Building, Storey) survive
        assert result["kept_count"] == 3
