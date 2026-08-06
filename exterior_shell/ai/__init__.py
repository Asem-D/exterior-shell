"""AI-assisted classification for exterior shell extraction.

This module provides vision-based classification for IFC elements
that cannot be resolved by rule-based heuristics alone.

Usage:
    from exterior_shell.ai import classify_ambiguous_with_ai, resolve_ai_config

    # Configure vision model (precedence: CLI > env vars > config file)
    config = resolve_ai_config(api_key="your-api-key")

    # Classify ambiguous elements
    report = classify_ambiguous_with_ai(
        report=classification_report,
        ifc_path="building.ifc",
        config=config
    )

Environment variables:
    EXTERIOR_SHELL_AI_KEY   - API key (or OPENROUTER_API_KEY)
    EXTERIOR_SHELL_AI_MODEL - Model name (default: openai/gpt-4o-mini)
    EXTERIOR_SHELL_AI_BASE  - API base URL (default: OpenRouter)

Config file (~/.exterior-shell/config.json):
    {
        "ai_api_key": "sk-...",
        "ai_model": "openai/gpt-4o-mini",
        "ai_base_url": "https://openrouter.ai/api/v1"
    }
"""

from .classifier import classify_ambiguous_with_ai
from .vision import VisionConfig, resolve_ai_config

__all__ = [
    "classify_ambiguous_with_ai",
    "VisionConfig",
    "resolve_ai_config",
]
