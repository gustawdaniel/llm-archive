import glob
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from ..models import NormalizedConversation, NormalizedMessage
from ..normalizers import (
    ChatGPTNormalizer,
    ClaudeWebNormalizer,
    DeepSeekNormalizer,
    GeminiNormalizer,
    GrokNormalizer,
    PerplexityNormalizer,
)
from .extractor import ArchiveExtractor, extract_archive, find_archive_files

logger = logging.getLogger("importer.takeout_master")


class TakeoutMasterImporter:
    """
    Central orchestrator for bulk importing and normalizing data from takeout directories.
    Supports:
    - Auto-extraction of .zip / .tar archives if present in directory
    - OpenAI / ChatGPT (multi-file conversations-*.json + conversation_asset_file_names.json)
    - DeepSeek (directory of *.json session files)
    - Gemini (Takeout My Activity log aggregated by URL)
    - Claude AI (conversations.json) & Claude Platform (workbench prompts)
    - Grok (prod-grok-backend.json)
    - Perplexity (conversations-*.json)
    """

    def __init__(self, base_dir: Path, auto_extract: bool = True):
        self.base_dir = base_dir.resolve()
        self.auto_extract = auto_extract

        # If base_dir is an archive itself, unpack it into a sibling directory
        if self.base_dir.is_file():
            dest = self.base_dir.parent / self.base_dir.stem
            logger.info(f"Target is an archive file. Extracting {self.base_dir.name} to {dest}...")
            extract_archive(self.base_dir, dest)
            self.base_dir = dest

        # If directory contains zip/tar archives and auto_extract is enabled, unpack them
        if self.auto_extract and self.base_dir.is_dir():
            archives = find_archive_files(self.base_dir)
            if archives:
                logger.info(f"Found {len(archives)} archive(s) in {self.base_dir}. Auto-extracting...")
                ArchiveExtractor.extract_directory_archives(self.base_dir, subfolder=False, keep=True)

    def parse_all(
        self,
        platforms: Optional[List[str]] = None,
        limit_per_platform: Optional[int] = None
    ) -> Dict[str, List[NormalizedConversation]]:
        results: Dict[str, List[NormalizedConversation]] = {}
        target_platforms = [p.lower() for p in platforms] if platforms else None

        # 1. OpenAI / ChatGPT
        if not target_platforms or any(p in ("openai", "chatgpt") for p in target_platforms):
            openai_dirs = self._find_candidate_dirs(["open-ai", "openai", "chatgpt"])
            for d in openai_dirs:
                logger.info(f"Parsing OpenAI directory: {d}")
                convs = self.parse_openai(d, limit=limit_per_platform)
                results.setdefault("chatgpt", []).extend(convs)

        # 2. DeepSeek
        if not target_platforms or "deepseek" in target_platforms:
            deepseek_dirs = self._find_candidate_dirs(["deepseek"])
            for d in deepseek_dirs:
                logger.info(f"Parsing DeepSeek directory: {d}")
                convs = self.parse_deepseek(d, limit=limit_per_platform)
                results.setdefault("deepseek", []).extend(convs)

        # 3. Gemini
        if not target_platforms or any(p in ("gemini", "bard") for p in target_platforms):
            gemini_dirs = self._find_candidate_dirs(["gemini"])
            for d in gemini_dirs:
                logger.info(f"Parsing Gemini directory: {d}")
                convs = self.parse_gemini(d, limit=limit_per_platform)
                results.setdefault("gemini", []).extend(convs)

        # 4. Claude AI & Claude Platform
        if not target_platforms or any(p in ("claude", "claude-ai", "claude_web", "claude-platform") for p in target_platforms):
            claude_dirs = self._find_candidate_dirs(["claude-ai", "claude"])
            for d in claude_dirs:
                logger.info(f"Parsing Claude directory: {d}")
                convs = self.parse_claude(d, limit=limit_per_platform)
                results.setdefault("claude_web", []).extend(convs)

            claude_plat_dirs = self._find_candidate_dirs(["claude-platform"])
            for d in claude_plat_dirs:
                logger.info(f"Parsing Claude Platform directory: {d}")
                convs = self.parse_claude_platform(d, limit=limit_per_platform)
                if convs:
                    results.setdefault("claude_platform", []).extend(convs)

        # 5. Grok
        if not target_platforms or "grok" in target_platforms:
            grok_dirs = self._find_candidate_dirs(["grok"])
            for d in grok_dirs:
                logger.info(f"Parsing Grok directory: {d}")
                convs = self.parse_grok(d, limit=limit_per_platform)
                results.setdefault("grok", []).extend(convs)

        # 6. Perplexity
        if not target_platforms or "perplexity" in target_platforms:
            perplexity_dirs = self._find_candidate_dirs(["perplexity"])
            for d in perplexity_dirs:
                logger.info(f"Parsing Perplexity directory: {d}")
                convs = self.parse_perplexity(d, limit=limit_per_platform)
                results.setdefault("perplexity", []).extend(convs)

        return results

    def parse_openai(self, dir_path: Path, limit: Optional[int] = None) -> List[NormalizedConversation]:
        # Load asset map if available
        asset_map: Dict[str, str] = {}
        map_file = dir_path / "conversation_asset_file_names.json"
        if map_file.is_file():
            try:
                with open(map_file, "r", encoding="utf-8") as f:
                    asset_map = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load asset map {map_file}: {e}")

        # Find conversation files
        json_files = sorted(dir_path.glob("conversations*.json"))
        normalizer = ChatGPTNormalizer()
        conversations: List[NormalizedConversation] = []

        for jf in json_files:
            try:
                with open(jf, "r", encoding="utf-8", errors="replace") as f:
                    data = json.load(f)
                items = data if isinstance(data, list) else [data]
                for raw_conv in items:
                    conv = normalizer.parse(raw_conv, metadata={"asset_map": asset_map})
                    if conv and conv.messages:
                        conversations.append(conv)
                        if limit and len(conversations) >= limit:
                            return conversations
            except Exception as e:
                logger.error(f"Error parsing OpenAI file {jf}: {e}", exc_info=True)

        return conversations

    def parse_deepseek(self, dir_path: Path, limit: Optional[int] = None) -> List[NormalizedConversation]:
        json_files = sorted(dir_path.glob("*.json"))
        normalizer = DeepSeekNormalizer()
        conversations: List[NormalizedConversation] = []

        for jf in json_files:
            try:
                with open(jf, "r", encoding="utf-8", errors="replace") as f:
                    data = json.load(f)
                conv = normalizer.parse(data)
                if conv and conv.messages:
                    conversations.append(conv)
                    if limit and len(conversations) >= limit:
                        return conversations
            except Exception as e:
                logger.error(f"Error parsing DeepSeek file {jf}: {e}", exc_info=True)

        return conversations

    def parse_gemini(self, dir_path: Path, limit: Optional[int] = None) -> List[NormalizedConversation]:
        candidates = list(dir_path.rglob("*aktywność*.json")) + list(dir_path.rglob("*activity*.json"))
        if not candidates:
            # check any json file under dir_path
            candidates = list(dir_path.rglob("*.json"))

        for cfile in candidates:
            try:
                with open(cfile, "r", encoding="utf-8", errors="replace") as f:
                    data = json.load(f)
                if isinstance(data, list) and data and ("header" in data[0] or "safeHtmlItem" in data[0] or "details" in data[0]):
                    convs = GeminiNormalizer.aggregate_takeout_events(data)
                    return convs[:limit] if limit else convs
            except Exception as e:
                logger.error(f"Error parsing Gemini file {cfile}: {e}", exc_info=True)

        return []

    def parse_claude(self, dir_path: Path, limit: Optional[int] = None) -> List[NormalizedConversation]:
        conv_file = dir_path / "conversations.json"
        if not conv_file.is_file():
            candidates = list(dir_path.glob("conversations*.json"))
            if candidates:
                conv_file = candidates[0]
            else:
                return []

        normalizer = ClaudeWebNormalizer()
        conversations: List[NormalizedConversation] = []

        try:
            with open(conv_file, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
            items = data if isinstance(data, list) else [data]
            for raw_conv in items:
                conv = normalizer.parse(raw_conv)
                if conv and conv.messages:
                    conversations.append(conv)
                    if limit and len(conversations) >= limit:
                        return conversations
        except Exception as e:
            logger.error(f"Error parsing Claude file {conv_file}: {e}", exc_info=True)

        return conversations

    def parse_claude_platform(self, dir_path: Path, limit: Optional[int] = None) -> List[NormalizedConversation]:
        prompts_file = dir_path / "workbench" / "prompts.json"
        if not prompts_file.is_file():
            candidates = list(dir_path.rglob("prompts.json"))
            if candidates:
                prompts_file = candidates[0]
            else:
                return []

        conversations: List[NormalizedConversation] = []
        try:
            with open(prompts_file, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
            items = data if isinstance(data, list) else [data]
            for item in items:
                conv_id = item.get("uuid") or "unknown"
                title = item.get("name") or "Claude Workbench Prompt"
                created_str = item.get("created_at")
                updated_str = item.get("updated_at")
                created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00")) if created_str else datetime.now(timezone.utc)
                updated_dt = datetime.fromisoformat(updated_str.replace("Z", "+00:00")) if updated_str else created_dt

                rev = item.get("latest_revision") or {}
                model = rev.get("model") or "claude-platform"
                raw_msgs = rev.get("messages") or []

                messages: List[NormalizedMessage] = []
                for s_idx, m in enumerate(raw_msgs):
                    role = "user" if m.get("role") in ("human", "user") else "assistant"
                    text_parts = []
                    for c in m.get("content", []):
                        if isinstance(c, dict) and c.get("text"):
                            text_parts.append(c["text"])
                        elif isinstance(c, str):
                            text_parts.append(c)
                    content = "\n".join(text_parts).strip()
                    if content:
                        messages.append(NormalizedMessage(
                            step_index=s_idx,
                            external_id=m.get("uuid") or f"{conv_id}_{s_idx}",
                            role=role,
                            content=content,
                            created_at=created_dt
                        ))

                if messages:
                    conversations.append(NormalizedConversation(
                        platform="claude_platform",
                        external_id=conv_id,
                        title=title if title.strip() else (messages[0].content[:60] if messages else "Prompt"),
                        model=model,
                        started_at=created_dt,
                        updated_at=updated_dt,
                        messages=messages,
                        raw_metadata={"workbench": True}
                    ))
                    if limit and len(conversations) >= limit:
                        return conversations
        except Exception as e:
            logger.error(f"Error parsing Claude platform file {prompts_file}: {e}", exc_info=True)

        return conversations

    def parse_grok(self, dir_path: Path, limit: Optional[int] = None) -> List[NormalizedConversation]:
        candidates = list(dir_path.rglob("prod-grok-backend.json")) + list(dir_path.rglob("*grok*.json"))
        if not candidates:
            candidates = list(dir_path.rglob("*.json"))

        normalizer = GrokNormalizer()
        conversations: List[NormalizedConversation] = []

        for cfile in candidates:
            try:
                with open(cfile, "r", encoding="utf-8", errors="replace") as f:
                    data = json.load(f)
                if isinstance(data, dict) and "conversations" in data:
                    for raw_c in data["conversations"]:
                        conv = normalizer.parse(raw_c)
                        if conv and conv.messages:
                            conversations.append(conv)
                            if limit and len(conversations) >= limit:
                                return conversations
            except Exception as e:
                logger.error(f"Error parsing Grok file {cfile}: {e}", exc_info=True)

        return conversations

    def parse_perplexity(self, dir_path: Path, limit: Optional[int] = None) -> List[NormalizedConversation]:
        candidates = sorted(dir_path.glob("conversations*.json"))
        normalizer = PerplexityNormalizer()
        conversations: List[NormalizedConversation] = []

        for cfile in candidates:
            try:
                with open(cfile, "r", encoding="utf-8", errors="replace") as f:
                    data = json.load(f)
                raw_convs = data.get("conversations", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                for raw_c in raw_convs:
                    conv = normalizer.parse(raw_c)
                    if conv and conv.messages:
                        conversations.append(conv)
                        if limit and len(conversations) >= limit:
                            return conversations
            except Exception as e:
                logger.error(f"Error parsing Perplexity file {cfile}: {e}", exc_info=True)

        return conversations

    def _find_candidate_dirs(self, names: List[str]) -> List[Path]:
        found: List[Path] = []
        # Check if the base directory itself matches
        if self.base_dir.name.lower() in [n.lower() for n in names]:
            return [self.base_dir]

        for name in names:
            d = self.base_dir / name
            if d.is_dir():
                found.append(d)
        return found
