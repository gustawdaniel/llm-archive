from typing import Any, Dict, Optional, Tuple

from ..models import NormalizedConversation
from ..normalizers import (
    AntigravityNormalizer,
    ChatGPTNormalizer,
    ClaudeCodeNormalizer,
    ClaudeWebNormalizer,
    DeepSeekNormalizer,
    GeminiNormalizer,
    GrokNormalizer,
    MarkdownGenerator,
    PerplexityNormalizer,
)


class UnifiedNormalizer:
    """Central entrypoint for normalizing conversations from any supported LLM platform to Markdown."""

    NORMALIZERS = {
        "antigravity": AntigravityNormalizer,
        "chatgpt": ChatGPTNormalizer,
        "claude_code": ClaudeCodeNormalizer,
        "claude_web": ClaudeWebNormalizer,
        "deepseek": DeepSeekNormalizer,
        "gemini": GeminiNormalizer,
        "grok": GrokNormalizer,
        "perplexity": PerplexityNormalizer,
    }

    @classmethod
    def normalize_to_conversation(
        cls,
        raw_data: Any,
        platform: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> NormalizedConversation:
        plat_key = platform.lower().replace("-", "_")
        normalizer_cls = cls.NORMALIZERS.get(plat_key)
        if not normalizer_cls:
            raise ValueError(f"Unsupported platform: {platform}")

        normalizer = normalizer_cls()
        return normalizer.parse(raw_data, metadata=metadata or {})

    @classmethod
    def normalize_to_markdown(
        cls,
        raw_data: Any,
        platform: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Tuple[NormalizedConversation, str, str]:
        """
        Normalizes raw platform data and generates Markdown with YAML frontmatter.
        Returns: (conversation, markdown_content, relative_path)
        """
        conv = cls.normalize_to_conversation(raw_data, platform, metadata)
        md_content, rel_path = MarkdownGenerator.generate(conv)
        return conv, md_content, rel_path


# Re-export MarkdownGenerator for convenience
__all__ = ["UnifiedNormalizer", "MarkdownGenerator"]
