"""Vision model integration for AI classification.

Uses OpenAI-compatible API (OpenRouter or direct OpenAI) to analyze
rendered building images and classify elements as exterior/interior.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ClassificationResult:
    """Result of AI classification for a single element."""
    global_id: str
    name: str
    classification: str  # "exterior" or "interior"
    confidence: float  # 0.0 to 1.0
    reasoning: str


@dataclass
class VisionConfig:
    """Configuration for vision model API."""
    api_key: str
    base_url: str = "https://openrouter.ai/api/v1"
    model: str = "openai/gpt-4o"
    max_tokens: int = 1000
    temperature: float = 0.1


def _encode_image(image_path: Path) -> str:
    """Encode image to base64.

    Args:
        image_path: Path to image file.

    Returns:
        Base64 encoded string.
    """
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _get_view_description(view_name: str) -> str:
    """Get human-readable description of camera viewpoint.

    Args:
        view_name: View name (e.g., 'front', 'top').

    Returns:
        Description string.
    """
    descriptions = {
        "front": "front elevation (south-facing)",
        "back": "back elevation (north-facing)",
        "left": "left elevation (west-facing)",
        "right": "right elevation (east-facing)",
        "top": "plan view from above (roof visible)",
        "bottom": "bottom view from below (foundation visible)",
        "iso_front": "isometric view from front-left",
        "iso_back": "isometric view from back-right",
    }
    return descriptions.get(view_name, view_name)


def classify_with_vision(
    view_images: dict[str, Path],
    ambiguous_elements: list[dict],
    config: VisionConfig,
    batch_size: int = 10,
) -> list[ClassificationResult]:
    """Classify ambiguous elements using vision model.

    Sends multiple views of the building to the vision model and asks it
    to classify each ambiguous element as exterior or interior.

    For large numbers of elements, batches requests to avoid token limits.

    Args:
        view_images: Dict mapping view names to image paths.
        ambiguous_elements: List of dicts with 'global_id', 'name', 'ifc_type',
                           'bbox_min', 'bbox_max'.
        config: Vision model configuration.
        batch_size: Max elements per API call.

    Returns:
        List of ClassificationResult for each element.
    """
    try:
        import openai
    except ImportError:
        logger.error("openai package not installed. Run: pip install openai")
        return []

    if not view_images:
        logger.error("No view images provided")
        return []

    # Batch elements to avoid token limits
    all_results = []
    for i in range(0, len(ambiguous_elements), batch_size):
        batch = ambiguous_elements[i:i + batch_size]
        logger.info(f"Processing batch {i // batch_size + 1} ({len(batch)} elements)")

        # Build the prompt
        prompt = _build_classification_prompt(batch)

        # Build message content with images
        content = []

        # Add text prompt
        content.append({
            "type": "text",
            "text": prompt
        })

        # Add images (limit to 4 views to stay within token limits)
        view_list = list(view_images.items())[:4]
        for view_name, image_path in view_list:
            image_data = _encode_image(image_path)
            view_desc = _get_view_description(view_name)

            content.append({
                "type": "text",
                "text": f"\n--- View: {view_desc} ---"
            })
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{image_data}",
                    "detail": "low"  # Save tokens
                }
            })

        # Call API
        client = openai.OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )

        try:
            response = client.chat.completions.create(
                model=config.model,
                messages=[{"role": "user", "content": content}],
                max_tokens=config.max_tokens,
                temperature=config.temperature,
            )

            # Parse response
            response_text = response.choices[0].message.content
            batch_results = _parse_classification_response(response_text, batch)
            all_results.extend(batch_results)

        except Exception as e:
            logger.error(f"Vision API call failed for batch {i // batch_size + 1}: {e}")
            # Continue with next batch

    return all_results


def _build_classification_prompt(elements: list[dict]) -> str:
    """Build the classification prompt.

    Args:
        elements: List of element dicts.

    Returns:
        Prompt string.
    """
    element_list = "\n".join([
        f"- {e['global_id']}: {e['name']} ({e['ifc_type']})"
        for e in elements
    ])

    return f"""You are analyzing a 3D building model to classify building elements.

TASK: Classify each of the following ambiguous elements as EXTERIOR or INTERIOR.

Elements to classify:
{element_list}

For each element, determine if it is:
- EXTERIOR: Part of the building envelope (visible from outside)
- INTERIOR: Inside the building (not visible from outside)

Respond in JSON format:
{{
  "classifications": [
    {{
      "global_id": "element_id",
      "classification": "exterior" or "interior",
      "confidence": 0.0 to 1.0,
      "reasoning": "brief explanation"
    }}
  ]
}}

Analyze the building views carefully. Consider:
1. Element position relative to building walls
2. Whether the element would be visible from outside
3. Element type (walls on building perimeter are exterior, interior partitions are interior)
4. Spatial relationships with other elements"""


def _parse_classification_response(
    response_text: str,
    elements: list[dict],
) -> list[ClassificationResult]:
    """Parse API response into ClassificationResults.

    Args:
        response_text: Raw API response text.
        elements: Original element list for fallback.

    Returns:
        List of ClassificationResult.
    """
    results = []

    try:
        # Try to extract JSON from response
        # Handle markdown code blocks
        if "```json" in response_text:
            json_str = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            json_str = response_text.split("```")[1].split("```")[0]
        else:
            json_str = response_text

        data = json.loads(json_str)

        for item in data.get("classifications", []):
            result = ClassificationResult(
                global_id=item.get("global_id", ""),
                name=item.get("name", ""),
                classification=item.get("classification", "interior"),
                confidence=float(item.get("confidence", 0.5)),
                reasoning=item.get("reasoning", ""),
            )
            results.append(result)

    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error(f"Failed to parse vision response: {e}")
        logger.debug(f"Response text: {response_text[:500]}")

    # Fill in any missing elements with default (exterior = conservative for shell extraction)
    classified_ids = {r.global_id for r in results}
    for elem in elements:
        if elem["global_id"] not in classified_ids:
            results.append(ClassificationResult(
                global_id=elem["global_id"],
                name=elem.get("name", ""),
                classification="exterior",  # Conservative: keep ambiguous elements
                confidence=0.3,
                reasoning="Not classified by vision model (default: exterior)",
            ))

    return results


def _load_config_file() -> dict:
    """Load config from ~/.exterior-shell/config.json.

    Backward-compatible wrapper around
    :func:`exterior_shell.config._load_config_file`.

    Returns:
        Config dict or empty dict if not found.
    """
    from ..config import _load_config_file as _load_user_config
    return _load_user_config()


def resolve_ai_config(
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Optional[VisionConfig]:
    """Resolve AI config with precedence: CLI flags > env vars > config file.

    Priority order:
        1. Explicit arguments (from CLI flags --api-key, --ai-model)
        2. Environment variables (EXTERIOR_SHELL_AI_KEY, OPENROUTER_API_KEY)
        3. Config file (~/.exterior-shell/config.json)

    Config file format:
        {
            "ai_api_key": "sk-...",
            "ai_model": "openai/gpt-4o-mini",
            "ai_base_url": "https://openrouter.ai/api/v1"
        }

    Args:
        api_key: Explicit API key (from CLI).
        model: Explicit model name (from CLI).
        base_url: Explicit base URL (from CLI).

    Returns:
        VisionConfig or None if no API key found.
    """
    # 1. CLI flags (explicit arguments)
    # 2. Environment variables
    env_key = os.environ.get("EXTERIOR_SHELL_AI_KEY") or os.environ.get("OPENROUTER_API_KEY")
    env_model = os.environ.get("EXTERIOR_SHELL_AI_MODEL")
    env_base = os.environ.get("EXTERIOR_SHELL_AI_BASE")

    # 3. Config file
    file_config = _load_config_file()

    # Resolve each field with precedence
    resolved_key = api_key or env_key or file_config.get("ai_api_key")
    if not resolved_key:
        return None

    resolved_model = (
        model
        or env_model
        or file_config.get("ai_model")
        or "openai/gpt-4o-mini"
    )
    resolved_base = (
        base_url
        or env_base
        or file_config.get("ai_base_url")
        or "https://openrouter.ai/api/v1"
    )

    return VisionConfig(
        api_key=resolved_key,
        base_url=resolved_base,
        model=resolved_model,
    )
