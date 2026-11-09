import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import zstandard

from ..models import NormalizedConversation, NormalizedMessage, ToolCallRecord
from .base import BaseNormalizer


class ZedNormalizer(BaseNormalizer):
    def parse(self, raw_data: Any, metadata: Optional[Dict[str, Any]] = None) -> NormalizedConversation:
        """
        raw_data can be:
        - a dict containing serialized {"thread": {...}, "data": {...}}
        - a Path to threads.db (extracts thread specified in metadata, or latest thread)
        - a string path or thread_id
        """
        meta = metadata or {}
        if isinstance(raw_data, list) and raw_data and isinstance(raw_data[0], dict) and "role" in raw_data[0]:
            msgs = [NormalizedMessage.model_validate(item) for item in raw_data]
            sess_id = meta.get("thread_id") or meta.get("session_id") or meta.get("conversation_id") or "unknown-zed"
            return NormalizedConversation(
                platform="zed",
                external_id=sess_id,
                title=meta.get("title") or f"Zed Assistant {sess_id[:8]}",
                project_path=meta.get("project_path"),
                git_branch=meta.get("git_branch"),
                device=meta.get("device"),
                model=meta.get("model") or "gpt-5.6-luna",
                started_at=msgs[0].created_at if msgs and msgs[0].created_at else datetime.now(timezone.utc),
                updated_at=msgs[-1].created_at if msgs and msgs[-1].created_at else datetime.now(timezone.utc),
                raw_metadata=meta,
                messages=msgs
            )

        thread_dict: Optional[Dict[str, Any]] = None
        data_json: Optional[Dict[str, Any]] = None

        if isinstance(raw_data, dict) and "data" in raw_data:
            thread_dict = raw_data.get("thread", {})
            data_json = raw_data["data"]
        else:
            db_path: Path
            thread_id: Optional[str] = meta.get("thread_id") or meta.get("session_id") or meta.get("conversation_id")

            if isinstance(raw_data, (str, Path)) and str(raw_data).endswith("threads.db"):
                db_path = Path(raw_data)
            elif isinstance(raw_data, dict) and "db_path" in raw_data:
                db_path = Path(raw_data["db_path"])
                thread_id = thread_id or raw_data.get("thread_id")
            elif isinstance(raw_data, str) and len(raw_data) >= 32 and "-" in raw_data:
                thread_id = raw_data
                db_path = Path.home() / ".local" / "share" / "zed" / "threads" / "threads.db"
            else:
                db_path = Path.home() / ".local" / "share" / "zed" / "threads" / "threads.db"

            if not db_path.is_file():
                raise FileNotFoundError(f"Zed database not found at {db_path}")

            thread_dict, data_json = self._load_from_sqlite(db_path, thread_id)

        if not data_json:
            raise ValueError("No thread data found in Zed")

        thread_id = (thread_dict or {}).get("id") or meta.get("thread_id") or "unknown-zed"
        title = data_json.get("title") or (thread_dict or {}).get("summary") or f"Zed Assistant {thread_id[:8]}"

        # Model parsing
        raw_model = data_json.get("model", {})
        if isinstance(raw_model, dict):
            model_name = raw_model.get("model") or raw_model.get("id") or "gpt-5.6-luna"
        elif isinstance(raw_model, str):
            model_name = raw_model
        else:
            model_name = "gpt-5.6-luna"

        # Timestamps
        updated_at_str = data_json.get("updated_at") or (thread_dict or {}).get("updated_at")
        created_at_str = (thread_dict or {}).get("created_at") or updated_at_str

        def parse_iso(ts_str: Optional[str]) -> datetime:
            if not ts_str:
                return datetime.now(timezone.utc)
            try:
                # Handle nanoseconds if present (e.g. 2026-09-21T00:01:50.616420426Z)
                clean_ts = ts_str.replace("Z", "+00:00")
                if "." in clean_ts:
                    parts = clean_ts.split(".")
                    subparts = parts[1].split("+")
                    fraction = subparts[0][:6]  # truncate to microseconds
                    tz_part = ("+" + subparts[1]) if len(subparts) > 1 else ""
                    clean_ts = f"{parts[0]}.{fraction}{tz_part}"
                return datetime.fromisoformat(clean_ts)
            except Exception:
                return datetime.now(timezone.utc)

        started_at = parse_iso(created_at_str)
        updated_at = parse_iso(updated_at_str)

        # Cumulative tokens
        cum_tokens = data_json.get("cumulative_token_usage", {})
        tokens_in = cum_tokens.get("input_tokens", 0)
        tokens_out = cum_tokens.get("output_tokens", 0)
        cache_read = cum_tokens.get("cache_read_input_tokens", 0)

        # Parse messages
        norm_messages: List[NormalizedMessage] = []
        raw_messages = data_json.get("messages", [])
        total_msgs = len(raw_messages)

        # Interpolate timestamps linearly between started_at and updated_at
        time_span = max((updated_at - started_at).total_seconds(), 0.0)

        for idx, m in enumerate(raw_messages):
            step_idx = idx + 1
            if total_msgs > 1:
                fraction = idx / (total_msgs - 1)
                msg_time = datetime.fromtimestamp(started_at.timestamp() + (time_span * fraction), timezone.utc)
            else:
                msg_time = started_at

            if "User" in m:
                u = m["User"]
                content_parts = []
                for item in u.get("content", []):
                    if isinstance(item, dict) and "Text" in item:
                        content_parts.append(str(item["Text"]))
                    elif isinstance(item, str):
                        content_parts.append(item)
                text = "\n".join(content_parts).strip()

                norm_messages.append(
                    NormalizedMessage(
                        step_index=step_idx,
                        external_id=u.get("id"),
                        role="user",
                        content=text,
                        token_usage={},
                        created_at=msg_time,
                    )
                )

            elif "Agent" in m:
                a = m["Agent"]
                content_parts = []
                thinking_parts = []
                tool_calls: List[ToolCallRecord] = []
                tool_results = a.get("tool_results", {})

                for item in a.get("content", []):
                    if not isinstance(item, dict):
                        continue
                    if "Text" in item:
                        content_parts.append(str(item["Text"]))
                    elif "Thinking" in item:
                        thinking_parts.append(str(item["Thinking"]))
                    elif "ToolUse" in item:
                        tu = item["ToolUse"]
                        call_id = tu.get("id") or f"call_{step_idx}_{len(tool_calls)}"
                        tool_name = tu.get("name") or "unknown_tool"

                        # Parse tool input
                        inp = tu.get("input", {})
                        if isinstance(inp, dict) and "value" in inp:
                            tool_input = inp.get("value") or {}
                        else:
                            tool_input = inp or {}
                        if not tool_input and "raw_input" in tu:
                            try:
                                tool_input = json.loads(tu["raw_input"])
                            except Exception:
                                tool_input = {"raw": tu["raw_input"]}

                        # Match tool output
                        tool_out_str = None
                        is_err = False
                        if call_id and call_id in tool_results:
                            tr = tool_results[call_id]
                            is_err = bool(tr.get("is_error", False))
                            if tr.get("output") is not None:
                                tool_out_str = str(tr["output"])
                            elif "content" in tr:
                                tr_texts = [
                                    str(c["Text"]) for c in tr.get("content", [])
                                    if isinstance(c, dict) and "Text" in c
                                ]
                                tool_out_str = "\n".join(tr_texts)

                        tool_calls.append(
                            ToolCallRecord(
                                name=tool_name,
                                input=tool_input if isinstance(tool_input, dict) else {"arg": tool_input},
                                output=tool_out_str,
                                is_error=is_err
                            )
                        )

                text = "\n".join(content_parts).strip()
                reasoning = "\n".join(thinking_parts).strip() if thinking_parts else None

                # For the last message or distributed token usage
                tok_dict = {}
                if idx == total_msgs - 1 and (tokens_in or tokens_out):
                    tok_dict = {
                        "input_tokens": int(tokens_in),
                        "output_tokens": int(tokens_out),
                        "cache_read_tokens": int(cache_read),
                        "total_tokens": int(tokens_in + tokens_out + cache_read)
                    }

                norm_messages.append(
                    NormalizedMessage(
                        step_index=step_idx,
                        role="assistant",
                        content=text,
                        reasoning_content=reasoning,
                        tool_calls=tool_calls,
                        token_usage=tok_dict,
                        created_at=msg_time,
                    )
                )

            elif "Compaction" in m:
                c = m["Compaction"]
                summary_text = c.get("Summary") or ""
                norm_messages.append(
                    NormalizedMessage(
                        step_index=step_idx,
                        role="system",
                        content=f"### [Context Compaction Summary]\n\n{summary_text}",
                        token_usage={},
                        created_at=msg_time,
                    )
                )

        # Fallback if no messages
        if not norm_messages:
            norm_messages.append(
                NormalizedMessage(
                    step_index=1,
                    role="assistant",
                    content="Pusta sesja Zed Assistant.",
                    token_usage={},
                    created_at=started_at
                )
            )

        token_summary = None
        if tokens_in or tokens_out or cache_read:
            token_summary = {
                "input_tokens": int(tokens_in),
                "output_tokens": int(tokens_out),
                "cache_read_tokens": int(cache_read),
                "total_tokens": int(tokens_in + tokens_out + cache_read)
            }

        if (not title or title.startswith("Zed Assistant")) and norm_messages:
            for m in norm_messages:
                if m.role == "user" and m.content:
                    first_line = m.content.strip().split("\n")[0].strip()
                    if first_line:
                        title = first_line[:100]
                        break

        folder_paths = (thread_dict or {}).get("folder_paths")
        project_path = meta.get("project_path") or (folder_paths.split(",")[0] if folder_paths else None)

        raw_meta = {
            "thread_id": thread_id,
            "cumulative_token_usage": cum_tokens,
            "folder_paths": folder_paths,
            **(meta or {})
        }
        if token_summary:
            raw_meta["token_summary"] = token_summary

        return NormalizedConversation(
            platform="zed",
            external_id=str(thread_id),
            title=title,
            project_path=project_path,
            git_branch=meta.get("git_branch"),
            device=meta.get("device"),
            model=model_name,
            started_at=started_at,
            updated_at=updated_at,
            raw_metadata=raw_meta,
            messages=norm_messages
        )

    def _load_from_sqlite(self, db_path: Path, thread_id: Optional[str]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        try:
            if thread_id:
                cur.execute(
                    "SELECT id, summary, updated_at, data_type, data, parent_id, folder_paths, created_at FROM threads WHERE id = ?",
                    (thread_id,)
                )
            else:
                cur.execute(
                    "SELECT id, summary, updated_at, data_type, data, parent_id, folder_paths, created_at FROM threads ORDER BY updated_at DESC LIMIT 1"
                )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"No thread matching id '{thread_id}' found in {db_path}")

            thread_dict = {
                "id": row["id"],
                "summary": row["summary"],
                "updated_at": row["updated_at"],
                "data_type": row["data_type"],
                "parent_id": row["parent_id"],
                "folder_paths": row["folder_paths"],
                "created_at": row["created_at"]
            }

            blob = row["data"]
            data_type = row["data_type"]

            if data_type == "zstd":
                dctx = zstandard.ZstdDecompressor()
                decompressed = dctx.decompress(blob, max_output_size=100 * 1024 * 1024)
                data_json = json.loads(decompressed)
            else:
                data_json = json.loads(blob.decode("utf-8", errors="replace"))

            return thread_dict, data_json
        finally:
            conn.close()
