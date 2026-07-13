"""IFC file parser — extracts elements with geometry from IFC files."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import ifcopenshell
import ifcopenshell.geom
import numpy as np

from .models import Element, ElementType, Face

logger = logging.getLogger(__name__)

# Mapping from IFC type strings to our ElementType enum
IFC_TYPE_MAP: dict[str, ElementType] = {
    "IfcWall": ElementType.WALL,
    "IfcWallStandardCase": ElementType.WALL_STANDARD,
    "IfcWindow": ElementType.WINDOW,
    "IfcWindowCase": ElementType.WINDOW_CASE,
    "IfcDoor": ElementType.DOOR,
    "IfcDoorCase": ElementType.DOOR_CASE,
    "IfcRoof": ElementType.ROOF,
    "IfcSlab": ElementType.SLAB,
    "IfcColumn": ElementType.COLUMN,
    "IfcBeam": ElementType.BEAM,
    "IfcCurtainWall": ElementType.CURTAIN_WALL,
    "IfcStair": ElementType.STAIR,
    "IfcStairFlight": ElementType.STAIR,
    "IfcRailing": ElementType.RAILING,
    "IfcPlate": ElementType.PLATE,
    "IfcMember": ElementType.MEMBER,
    "IfcCovering": ElementType.COVERING,
    "IfcSpace": ElementType.SPACE,
    "IfcBuildingStorey": ElementType.BUILDING_STOREY,
    "IfcFurnishingElement": ElementType.FURNISHING,
    "IfcChimney": ElementType.CHIMNEY,
    "IfcPile": ElementType.PILE,
    "IfcOpeningElement": ElementType.OPENING_ELEMENT,
    "IfcBuildingElementProxy": ElementType.BUILDING_ELEMENT_PROXY,
    "IfcController": ElementType.CONTROLLER,
    "IfcDistributionPort": ElementType.DISTRIBUTION_PORT,
    "IfcFlowSegment": ElementType.FLOW_SEGMENT,
    "IfcFlowTerminal": ElementType.FLOW_TERMINAL,
    "IfcFlowFitting": ElementType.FLOW_FITTING,
    "IfcFlowController": ElementType.FLOW_CONTROLLER,
    "IfcBuildingSystem": ElementType.BUILDING_SYSTEM,
    "IfcProxy": ElementType.PROXY,
}


def _get_element_type(ifc_type_str: str) -> ElementType:
    """Map IFC type string to ElementType enum."""
    return IFC_TYPE_MAP.get(ifc_type_str, ElementType.UNKNOWN)


def _extract_faces_from_product(product, geom_settings) -> list[Face]:
    """Extract triangulated faces from an IFC product using the geometry engine."""
    faces = []

    try:
        shape = ifcopenshell.geom.create_shape(geom_settings, product)
        if shape is None:
            return faces

        verts = shape.geometry.verts  # flat list of vertex coordinates
        faces_idx = shape.geometry.faces  # flat list of face indices

        if verts is None or faces_idx is None or len(verts) == 0 or len(faces_idx) == 0:
            return faces

        # Reshape vertices into (N, 3) array
        verts_array = np.array(verts).reshape(-1, 3)
        # faces_idx is flat: [i0, i1, i2, i3, i4, i5, ...] → groups of 3
        faces_array = np.array(faces_idx).reshape(-1, 3)

        for tri_indices in faces_array:
            try:
                v0 = verts_array[tri_indices[0]]
                v1 = verts_array[tri_indices[1]]
                v2 = verts_array[tri_indices[2]]

                # Calculate face normal
                edge1 = v1 - v0
                edge2 = v2 - v0
                normal = np.cross(edge1, edge2)
                norm_len = np.linalg.norm(normal)
                if norm_len > 1e-10:
                    normal = normal / norm_len
                else:
                    normal = np.array([0.0, 0.0, 1.0])

                face = Face(
                    vertices=np.array([v0, v1, v2]),
                    normal=normal,
                )
                faces.append(face)
            except (IndexError, ValueError):
                continue

    except Exception as e:
        logger.debug(f"Could not extract geometry for product: {e}")

    return faces


def _compute_bbox(faces: list[Face]) -> tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """Compute bounding box from a list of faces."""
    if not faces:
        return None, None

    all_verts = np.vstack([f.vertices for f in faces])
    return all_verts.min(axis=0), all_verts.max(axis=0)


def _get_predefined_type(element) -> Optional[str]:
    """Get the predefined type of an IFC element, if available."""
    try:
        # IFC4 uses PredefinedType, IFC2x3 uses various attributes
        if hasattr(element, "PredefinedType") and element.PredefinedType:
            return str(element.PredefinedType)
        if hasattr(element, "ObjectType") and element.ObjectType:
            return str(element.ObjectType)
    except Exception:
        pass
    return None


def _get_storey(file: ifcopenshell.file, element) -> Optional[str]:
    """Find the building storey an element belongs to."""
    try:
        # Try spatial decomposition: element → contained in storey
        for rel in file.by_type("IfcRelContainedInSpatialStructure"):
            if element in rel.RelatedElements:
                storey = rel.RelatingStructure
                if storey.is_a("IfcBuildingStorey"):
                    return storey.Name
    except Exception:
        pass
    return None


def parse_ifc(file_path: str | Path) -> list[Element]:
    """Parse an IFC file and extract all elements with geometry.

    Args:
        file_path: Path to the IFC file.

    Returns:
        List of parsed Element objects.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"IFC file not found: {file_path}")

    logger.info(f"Parsing IFC file: {file_path}")
    file = ifcopenshell.open(str(file_path))

    # Set up geometry engine
    geom_settings = ifcopenshell.geom.settings()

    elements = []

    # Get all product elements (walls, doors, windows, etc.)
    products = file.by_type("IfcProduct")

    for product in products:
        ifc_type_str = product.is_a()
        element_type = _get_element_type(ifc_type_str)

        # Get name
        name = product.Name or "Unnamed"

        # Get GlobalId
        global_id = product.GlobalId or ""

        # Get geometry using the geometry engine
        faces = []
        if product.Representation is not None:
            faces = _extract_faces_from_product(product, geom_settings)

        # Compute bounding box
        bbox_min, bbox_max = _compute_bbox(faces) if faces else (None, None)

        # Get storey
        storey = _get_storey(file, product)

        # Get predefined type
        predefined_type = _get_predefined_type(product)

        element = Element(
            global_id=global_id,
            name=str(name),
            ifc_type=ifc_type_str,
            element_type=element_type,
            faces=faces,
            bbox_min=bbox_min,
            bbox_max=bbox_max,
            storey=storey,
            predefined_type=predefined_type,
        )

        elements.append(element)

    logger.info(
        f"Parsed {len(elements)} elements "
        f"({sum(e.face_count for e in elements)} total faces)"
    )
    return elements
