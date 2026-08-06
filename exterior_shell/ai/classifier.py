"""AI classifier for resolving ambiguous IFC elements.

Orchestrates rendering and vision model analysis to classify
elements that couldn't be resolved by rule-based classification.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from ..core.models import (
    Classification,
    ClassificationReport,
    ClassificationSource,
    Element,
    ElementType,
)
from .renderer import render_views
from .vision import (
    ClassificationResult,
    VisionConfig,
    classify_with_vision,
)

logger = logging.getLogger(__name__)


def _element_to_dict(element: Element) -> dict:
    """Convert Element to dict for vision API.

    Args:
        element: Element to convert.

    Returns:
        Dict with element properties.
    """
    return {
        "global_id": element.global_id,
        "name": element.name,
        "ifc_type": element.ifc_type,
        "bbox_min": element.bbox_min.tolist() if element.bbox_min is not None else None,
        "bbox_max": element.bbox_max.tolist() if element.bbox_max is not None else None,
        "storey": element.storey,
        "predefined_type": element.predefined_type,
    }


def _apply_ai_results(
    elements: list[Element],
    results: list[ClassificationResult],
) -> int:
    """Apply AI classification results to elements.

    Args:
        elements: List of elements to update.
        results: AI classification results.

    Returns:
        Number of elements updated.
    """
    # Build lookup by global_id
    result_map = {r.global_id: r for r in results}

    updated_count = 0
    for element in elements:
        if element.global_id in result_map:
            result = result_map[element.global_id]

            # Update classification
            if result.classification == "exterior":
                element.classification = Classification.EXTERIOR
            else:
                element.classification = Classification.INTERIOR

            element.classification_source = ClassificationSource.AI
            element.confidence = result.confidence
            updated_count += 1

            logger.debug(
                f"AI classified {element.name} as {result.classification} "
                f"(confidence: {result.confidence:.2f}): {result.reasoning}"
            )

    return updated_count


def classify_ambiguous_with_ai(
    report: ClassificationReport,
    ifc_path: str | Path,
    config: Optional[VisionConfig] = None,
    temp_dir: Optional[str | Path] = None,
) -> ClassificationReport:
    """Resolve ambiguous elements using AI vision classification.

    This is the main entry point for AI classification. It:
    1. Renders the IFC model from multiple viewpoints
    2. Sends images + element list to vision model
    3. Updates element classifications based on AI response

    Args:
        report: Classification report with ambiguous elements.
        ifc_path: Path to IFC file for rendering.
        config: Vision model config (uses env vars if None).
        temp_dir: Temporary directory for rendered images.

    Returns:
        Updated ClassificationReport.
    """
    if not report.ambiguous_elements:
        logger.info("No ambiguous elements to classify")
        return report

    # Get config from env if not provided
    if config is None:
        from .vision import resolve_ai_config
        config = resolve_ai_config()
        if config is None:
            logger.warning(
                "AI classification requested but no API key found. "
                "Set EXTERIOR_SHELL_AI_KEY or OPENROUTER_API_KEY env var, "
                "or pass config via resolve_ai_config(). "
                "Falling back to conservative default (exterior)."
            )
            return _fallback_to_exterior(report)

    logger.info(
        f"Starting AI classification for {len(report.ambiguous_elements)} "
        f"ambiguous elements"
    )

    # Set up temp directory for renders
    if temp_dir is None:
        temp_dir = Path(ifc_path).parent / ".exterior_shell_ai_renders"
    else:
        temp_dir = Path(temp_dir)

    # Step 1: Render views
    logger.info("Rendering building model from multiple viewpoints...")
    view_images = render_views(
        ifc_path=ifc_path,
        output_dir=temp_dir,
        views=["iso_front", "front", "right", "top"],
    )

    if not view_images:
        logger.error("Failed to render any views. Falling back to conservative default.")
        return _fallback_to_exterior(report)

    logger.info(f"Rendered {len(view_images)} views")

    # Step 2: Convert elements to dicts
    element_dicts = [_element_to_dict(e) for e in report.ambiguous_elements]

    # Step 3: Call vision model
    logger.info("Sending to vision model for classification...")
    ai_results = classify_with_vision(
        view_images=view_images,
        ambiguous_elements=element_dicts,
        config=config,
    )

    if not ai_results:
        logger.error("Vision model returned no results. Falling back to conservative default.")
        return _fallback_to_exterior(report)

    # Step 4: Apply results
    updated = _apply_ai_results(report.ambiguous_elements, ai_results)
    logger.info(f"AI classified {updated}/{len(report.ambiguous_elements)} elements")

    # Move resolved elements to appropriate lists
    still_ambiguous = []
    for element in report.ambiguous_elements:
        if element.classification == Classification.EXTERIOR:
            report.exterior_count += 1
            report.exterior_elements.append(element)
        elif element.classification == Classification.INTERIOR:
            report.interior_count += 1
            report.interior_elements.append(element)
        else:
            still_ambiguous.append(element)

    # Update report
    report.ambiguous_count = len(still_ambiguous)
    report.ambiguous_elements = still_ambiguous

    logger.info(
        f"AI resolution complete: {report.exterior_count} exterior, "
        f"{report.interior_count} interior, {report.ambiguous_count} still ambiguous"
    )

    return report


def _fallback_to_exterior(report: ClassificationReport) -> ClassificationReport:
    """Fallback: classify all ambiguous as exterior (conservative).

    Args:
        report: Classification report.

    Returns:
        Updated report.
    """
    for element in report.ambiguous_elements:
        element.classification = Classification.EXTERIOR
        element.classification_source = ClassificationSource.DEFAULT_EXTERIOR
        element.confidence = 0.5

        report.exterior_count += 1
        report.exterior_elements.append(element)

    report.ambiguous_count = 0
    report.ambiguous_elements.clear()

    return report
