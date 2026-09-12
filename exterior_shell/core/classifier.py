"""Rule-based classifier — classifies IFC elements as exterior/interior/ambiguous."""

from __future__ import annotations

import logging
from typing import Optional

from .models import (
    Classification,
    ClassificationReport,
    ClassificationSource,
    Element,
    ElementType,
)

logger = logging.getLogger(__name__)


# ── Classification rules ─────────────────────────────────────────────────────

# Elements that are ALWAYS part of the exterior shell
EXTERIOR_TYPES: set[ElementType] = {
    ElementType.ROOF,
    ElementType.WINDOW,
    ElementType.WINDOW_CASE,
    ElementType.DOOR,
    ElementType.DOOR_CASE,
    ElementType.CURTAIN_WALL,
    ElementType.CHIMNEY,
    ElementType.FOOTING,       # foundation is exterior
}

# Elements that are ALWAYS interior (stripped from output)
INTERIOR_TYPES: set[ElementType] = {
    ElementType.SPACE,
    ElementType.BUILDING_STOREY,
    ElementType.FURNISHING,
    ElementType.COVERING,
    ElementType.MEMBER,      # interior framing
    ElementType.CONTROLLER,
    ElementType.DISTRIBUTION_PORT,
    ElementType.FLOW_SEGMENT,
    ElementType.FLOW_TERMINAL,
    ElementType.FLOW_FITTING,
    ElementType.FLOW_CONTROLLER,
    ElementType.BUILDING_SYSTEM,
    ElementType.PROXY,
    ElementType.OPENING_ELEMENT,  # voids for doors/windows, not solid geometry
    ElementType.UNKNOWN,
}

# Elements that are AMBIGUOUS (could be exterior or interior)
AMBIGUOUS_TYPES: set[ElementType] = {
    ElementType.WALL,
    ElementType.WALL_STANDARD,
    ElementType.COLUMN,
    ElementType.BEAM,
    ElementType.SLAB,
    ElementType.STAIR,
    ElementType.RAILING,
    ElementType.PLATE,
    ElementType.OPENING_ELEMENT,
    ElementType.BUILDING_ELEMENT_PROXY,
    ElementType.PILE,
}


# ── Special rules for subtypes ───────────────────────────────────────────────

def _classify_slab(element: Element) -> Classification:
    """Slabs need special handling based on predefined type."""
    if element.predefined_type:
        pt = element.predefined_type.upper()
        if pt in ("ROOF",):
            return Classification.EXTERIOR
        if pt in ("FLOOR", "BASESLAB", "LANDING"):
            # Ground floor slabs are often exterior (visible from below)
            # but upper floor slabs are interior → ambiguous
            return Classification.AMBIGUOUS
    return Classification.AMBIGUOUS


def _classify_stair(element: Element) -> Classification:
    """Stairs can be exterior (entrance) or interior."""
    return Classification.AMBIGUOUS


def _classify_railing(element: Element) -> Classification:
    """Railings can be exterior (balcony) or interior."""
    return Classification.AMBIGUOUS


# ── Main classifier ──────────────────────────────────────────────────────────

def classify_element(element: Element) -> Classification:
    """Classify a single element as exterior, interior, or ambiguous.

    Uses IFC type and predefined type for classification.
    Does NOT use geometric analysis (that's the AI phase).

    Args:
        element: The element to classify.

    Returns:
        Classification result.
    """
    etype = element.element_type

    # Check exterior types
    if etype in EXTERIOR_TYPES:
        return Classification.EXTERIOR

    # Check interior types
    if etype in INTERIOR_TYPES:
        return Classification.INTERIOR

    # Special handling for slabs
    if etype == ElementType.SLAB:
        return _classify_slab(element)

    # Special handling for stairs
    if etype == ElementType.STAIR:
        return _classify_stair(element)

    # Special handling for railings
    if etype == ElementType.RAILING:
        return _classify_railing(element)

    # Check ambiguous types
    if etype in AMBIGUOUS_TYPES:
        return Classification.AMBIGUOUS

    # Unknown types default to interior (safer to strip)
    logger.debug(f"Unknown element type '{element.ifc_type}', defaulting to interior")
    return Classification.INTERIOR


def classify_all(elements: list[Element]) -> ClassificationReport:
    """Classify all elements and generate a report.

    Args:
        elements: List of parsed elements.

    Returns:
        ClassificationReport with categorized elements.
    """
    report = ClassificationReport(total_elements=len(elements))

    for element in elements:
        classification = classify_element(element)
        element.classification = classification
        element.classification_source = ClassificationSource.RULE_BASED

        if classification == Classification.EXTERIOR:
            report.exterior_count += 1
            report.exterior_elements.append(element)
        elif classification == Classification.INTERIOR:
            report.interior_count += 1
            report.interior_elements.append(element)
        else:
            report.ambiguous_count += 1
            report.ambiguous_elements.append(element)

    logger.info(
        f"Classification complete: "
        f"{report.exterior_count} exterior, "
        f"{report.interior_count} interior, "
        f"{report.ambiguous_count} ambiguous "
        f"(ambiguity score: {report.ambiguity_score:.1f}%)"
    )

    return report


def resolve_ambiguities(
    report: ClassificationReport,
    use_ai: bool = False,
) -> ClassificationReport:
    """Resolve ambiguous element classifications.

    In rule-based mode (no AI): all ambiguous elements default to EXTERIOR
    (conservative — better to include extra than miss exterior walls).

    In AI mode: this is where the AI classifier would re-evaluate each
    ambiguous element. For now, it applies the same conservative default.

    Args:
        report: Classification report with ambiguous elements.
        use_ai: Whether AI classification is enabled (future use).

    Returns:
        Updated classification report.
    """
    for element in report.ambiguous_elements:
        # Conservative: assume exterior
        element.classification = Classification.EXTERIOR
        element.classification_source = ClassificationSource.DEFAULT_EXTERIOR
        element.confidence = 0.5  # Low confidence — it's a guess

        # Move from ambiguous to exterior
        report.exterior_count += 1
        report.exterior_elements.append(element)

    # Clear ambiguous list (all resolved)
    report.ambiguous_count = 0
    report.ambiguous_elements.clear()

    logger.info(
        f"Ambiguity resolution: {report.exterior_count} exterior (after resolving)"
    )

    return report
