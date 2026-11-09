import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from ..models import NormalizedConversation, NormalizedMessage, ToolCallRecord
from .base import BaseNormalizer


class ChatGPTNormalizer(BaseNormalizer):
    def parse(self, raw_data: Any, metadata: Optional[Dict[str, Any]] = None) -> NormalizedConversation:
        """
        raw_data can be:
        - a single conversation dict (from /backend-api/conversation/{id} or an element of conversations-*.json)
        - a JSON string of a single conversation
        """
        if isinstance(raw_data, str):
            raw_data = json.loads(raw_data)

        conv_id = raw_data.get("id") or (metadata or {}).get("conversation_id", "unknown-chatgpt")
        title = raw_data.get("title") or "Rozmowa ChatGPT"
        create_time = raw_data.get("create_time")
        update_time = raw_data.get("update_time")
        asset_map: Dict[str, str] = (metadata or {}).get("asset_map", {})

        def ts_to_dt(ts: Optional[float]) -> datetime:
            if ts:
                try:
                    return datetime.fromtimestamp(ts, timezone.utc)
                except Exception:
                    pass
            return datetime.now(timezone.utc)

        started_at = ts_to_dt(create_time)
        updated_at = ts_to_dt(update_time) if update_time else started_at

        mapping = raw_data.get("mapping") or {}
        current_node = raw_data.get("current_node")

        # 1. Active path traversal from current_node backwards to root (eliminates branching graphs)
        active_nodes = []
        if current_node and current_node in mapping:
            curr = current_node
            visited = set()
            while curr and curr in mapping and curr not in visited:
                visited.add(curr)
                node = mapping[curr]
                if node.get("message"):
                    active_nodes.append(node)
                curr = node.get("parent")
            active_nodes.reverse()
        else:
            # Fallback: sort nodes chronologically
            sorted_nodes = []
            for node_id, node in mapping.items():
                msg = node.get("message")
                if not msg:
                    continue
                node_created_at = msg.get("create_time")
                dt = ts_to_dt(node_created_at)
                sorted_nodes.append((dt, node))
            sorted_nodes.sort(key=lambda x: x[0])
            active_nodes = [n for _, n in sorted_nodes]

        messages: List[NormalizedMessage] = []
        detected_model: Optional[str] = None
        step_counter = 0

        for node in active_nodes:
            msg = node["message"]
            author = msg.get("author") or {}
            role = author.get("role", "unknown")
            if role not in ("user", "assistant", "system", "tool"):
                continue

            node_created_at = msg.get("create_time")
            dt = ts_to_dt(node_created_at)

            msg_meta = msg.get("metadata") or {}
            if not detected_model and msg_meta.get("model_slug"):
                detected_model = msg_meta.get("model_slug")
            elif not detected_model and raw_data.get("default_model_slug"):
                detected_model = raw_data.get("default_model_slug")

            content_obj = msg.get("content") or {}
            content_type = content_obj.get("content_type", "text")
            parts = content_obj.get("parts") or []

            # Skip pure system prompts if they have no user interaction
            if role == "system" and not parts:
                continue

            # Process reasoning / thinking
            reasoning_str: Optional[str] = None
            if content_type == "thoughts":
                thoughts_list = content_obj.get("thoughts") or []
                thought_texts = [t.get("summary") or t.get("content") for t in thoughts_list if isinstance(t, dict)]
                reasoning_str = "\n".join(t for t in thought_texts if t).strip() or None
            elif content_type == "reasoning_recap":
                reasoning_str = content_obj.get("content")

            # Content assembly and asset collection
            text_parts: List[str] = []
            attachments: List[Dict[str, Any]] = []

            for p in parts:
                if isinstance(p, str):
                    text_parts.append(p)
                elif isinstance(p, dict):
                    # Voice transcription in multimodal messages
                    if p.get("content_type") == "audio_transcription" and p.get("text"):
                        text_parts.append(p["text"])
                    elif p.get("text"):
                        text_parts.append(p["text"])

                    # Collect asset pointers (audio, images, files)
                    asset_ptr = p.get("asset_pointer")
                    if not asset_ptr and isinstance(p.get("audio_asset_pointer"), dict):
                        asset_ptr = p["audio_asset_pointer"].get("asset_pointer")

                    if asset_ptr:
                        clean_ptr = asset_ptr.replace("sediment://", "").strip()
                        resolved_filename = asset_map.get(clean_ptr) or asset_map.get(f"{clean_ptr}.dat") or clean_ptr
                        ext = Path(resolved_filename).suffix.lower()
                        media_type = "audio" if ext in (".wav", ".mp3", ".ogg") else ("image" if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif") else "file")
                        attachments.append({
                            "pointer": asset_ptr,
                            "filename": resolved_filename,
                            "type": media_type
                        })

            content_str = "\n".join(text_parts).strip()

            # Tool calls (code interpreter, DALL-E, browsing)
            tool_calls: List[ToolCallRecord] = []
            recipient = msg.get("recipient") or msg_meta.get("recipient")
            if role == "tool" or recipient == "python" or content_type in ("code", "execution_output"):
                tool_calls.append(ToolCallRecord(
                    name=recipient or "code_interpreter",
                    input={"code": content_str} if role != "tool" else {},
                    output=content_str if role == "tool" else None
                ))

            # Only append if message has meaningful content, reasoning, tools, or attachments
            if content_str or reasoning_str or tool_calls or attachments or role in ("user", "assistant"):
                messages.append(NormalizedMessage(
                    step_index=step_counter,
                    external_id=msg.get("id"),
                    parent_id=node.get("parent"),
                    role=role if role in ("user", "assistant") else "assistant",
                    content=content_str,
                    reasoning_content=reasoning_str,
                    tool_calls=tool_calls,
                    attachments=attachments,
                    created_at=dt
                ))
                step_counter += 1

        return NormalizedConversation(
            platform="chatgpt",
            external_id=conv_id,
            title=title,
            model=detected_model or "gpt-4o",
            device=(metadata or {}).get("device"),
            started_at=started_at,
            updated_at=updated_at,
            raw_metadata={"moderation": raw_data.get("moderation_results")},
            messages=messages
        )

