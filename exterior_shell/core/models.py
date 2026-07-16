"""Data models for exterior shell extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np


class ElementType(Enum):
    """IFC element classification for exterior shell extraction."""
    WALL = "IfcWall"
    WALL_STANDARD = "IfcWallStandardCase"
    WINDOW = "IfcWindow"
    DOOR = "IfcDoor"
    ROOF = "IfcRoof"
    SLAB = "IfcSlab"
    COLUMN = "IfcColumn"
    BEAM = "IfcBeam"
    CURTAIN_WALL = "IfcCurtainWall"
    STAIR = "IfcStair"
    RAILING = "IfcRailing"
    PLATE = "IfcPlate"
    MEMBER = "IfcMember"
    COVERING = "IfcCovering"
    SPACE = "IfcSpace"
    BUILDING_STOREY = "IfcBuildingStorey"
    FURNISHING = "IfcFurnishingElement"
    CHIMNEY = "IfcChimney"
    PILE = "IfcPile"
    DOOR_CASE = "IfcDoorCase"
    WINDOW_CASE = "IfcWindowCase"
    OPENING_ELEMENT = "IfcOpeningElement"
    BUILDING_ELEMENT_PROXY = "IfcBuildingElementProxy"
    CONTROLLER = "IfcController"
    DISTRIBUTION_PORT = "IfcDistributionPort"
    FLOW_SEGMENT = "IfcFlowSegment"
    FLOW_TERMINAL = "IfcFlowTerminal"
    FLOW_FITTING = "IfcFlowFitting"
    FLOW_CONTROLLER = "IfcFlowController"
    BUILDING_SYSTEM = "IfcBuildingSystem"
    PROXY = "IfcProxy"
    # Catch-all for unrecognized types
    UNKNOWN = "Unknown"


class Classification(Enum):
    """Element classification result."""
    EXTERIOR = "exterior"
    INTERIOR = "interior"
    AMBIGUOUS = "ambiguous"


class ClassificationSource(Enum):
    """How the classification was determined."""
    RULE_BASED = "rule_based"
    AI = "ai"
    USER = "user"
    DEFAULT_EXTERIOR = "default_exterior"  # Conservative: ambiguous → exterior


@dataclass
class Face:
    """A single triangular face with vertices and normal."""
    vertices: np.ndarray  # (3, 3) array of triangle vertices
    normal: np.ndarray    # (3,) normal vector


@dataclass
class Element:
    """A parsed IFC element with geometry and metadata."""
    global_id: str
    name: str
    ifc_type: str
    element_type: ElementType
    faces: list[Face] = field(default_factory=list)
    bbox_min: Optional[np.ndarray] = None
    bbox_max: Optional[np.ndarray] = None
    storey: Optional[str] = None
    predefined_type: Optional[str] = None
    classification: Classification = Classification.AMBIGUOUS
    classification_source: ClassificationSource = ClassificationSource.RULE_BASED
    confidence: float = 0.0

    @property
    def face_count(self) -> int:
        return len(self.faces)

    @property
    def volume(self) -> float:
        """Approximate volume from bounding box."""
        if self.bbox_min is None or self.bbox_max is None:
            return 0.0
        dims = self.bbox_max - self.bbox_min
        return float(np.prod(dims))

    @property
    def center(self) -> Optional[np.ndarray]:
        """Center point of bounding box."""
        if self.bbox_min is None or self.bbox_max is None:
            return None
        return (self.bbox_min + self.bbox_max) / 2.0


@dataclass
class ClassificationReport:
    """Summary of classification results."""
    total_elements: int = 0
    exterior_count: int = 0
    interior_count: int = 0
    ambiguous_count: int = 0
    exterior_elements: list[Element] = field(default_factory=list)
    interior_elements: list[Element] = field(default_factory=list)
    ambiguous_elements: list[Element] = field(default_factory=list)

    @property
    def ambiguity_score(self) -> float:
        """Percentage of elements that are ambiguous."""
        if self.total_elements == 0:
            return 0.0
        return self.ambiguous_count / self.total_elements * 100.0

    def summary(self) -> str:
        lines = [
            f"Total elements:       {self.total_elements}",
            f"Exterior (confirmed): {self.exterior_count}",
            f"Interior (stripped):  {self.interior_count}",
            f"Ambiguous:            {self.ambiguous_count}",
            f"Ambiguity Score:      {self.ambiguity_score:.1f}%",
        ]
        return "\n".join(lines)


@dataclass
class ShellGeometry:
    """The assembled exterior shell geometry."""
    faces: list[Face] = field(default_factory=list)
    element_count: int = 0
    total_face_count: int = 0
    source_elements: list[Element] = field(default_factory=list)

    @property
    def bbox_min(self) -> Optional[np.ndarray]:
        if not self.faces:
            return None
        all_verts = np.vstack([f.vertices for f in self.faces])
        return all_verts.min(axis=0)

    @property
    def bbox_max(self) -> Optional[np.ndarray]:
        if not self.faces:
            return None
        all_verts = np.vstack([f.vertices for f in self.faces])
        return all_verts.max(axis=0)


@dataclass
class ExtractionResult:
    """Complete result of the extraction pipeline."""
    classification_report: ClassificationReport = field(default_factory=ClassificationReport)
    shell: ShellGeometry = field(default_factory=ShellGeometry)
    input_file: str = ""
    output_file: str = ""
    input_element_count: int = 0
    output_face_count: int = 0
    file_size_reduction: float = 0.0
    crs: str = "EPSG:4326"
    keep_interior: bool = False
    simplify: bool = False

    def summary(self) -> str:
        lines = [
            "=" * 50,
            "Exterior Shell Extraction Report",
            "=" * 50,
            f"Input:  {self.input_file}",
            f"Output: {self.output_file}",
            "",
            "Classification:",
            self.classification_report.summary(),
            "",
            "Output Geometry:",
            f"Elements in shell:  {self.shell.element_count}",
            f"Total faces:        {self.shell.total_face_count}",
            f"Size reduction:     {self.file_size_reduction:.1f}%",
            "=" * 50,
        ]
        return "\n".join(lines)
