import json
import re
import yaml
from pathlib import Path
from typing import Tuple
from ..models import NormalizedConversation, NormalizedMessage, ToolCallRecord
from ..naming import conversation_rel_path


class MarkdownGenerator:
    @staticmethod
    def generate(conversation: NormalizedConversation) -> Tuple[str, str]:
        """
        Generates:
        1. Full markdown text with YAML frontmatter.
        2. Suggested relative file path (e.g. 'doc/llm-archive/antigravity/2026-09-21_title.md').
        """
        # 1. Frontmatter metadata
        date_str = conversation.started_at.strftime("%Y-%m-%d")
        frontmatter_data = {
            "id": f"{conversation.platform}_{conversation.external_id}",
            "platform": conversation.platform,
            "title": conversation.title,
            "started_at": conversation.started_at.isoformat(),
            "updated_at": conversation.updated_at.isoformat(),
        }

        if conversation.model:
            frontmatter_data["model"] = conversation.model
        if conversation.project_path:
            frontmatter_data["project_path"] = conversation.project_path
        if conversation.device:
            frontmatter_data["device"] = conversation.device
        
        tools = conversation.tools_used
        if tools:
            frontmatter_data["tools_used"] = tools

        # Auto-tags
        tags = [conversation.platform, "llm-archive"]
        if conversation.project_path:
            project_name = Path(conversation.project_path).name
            if project_name:
                tags.append(project_name)
        frontmatter_data["tags"] = tags

        token_sum = (conversation.raw_metadata or {}).get("token_summary") or (conversation.raw_metadata or {}).get("usage")
        if token_sum:
            frontmatter_data["tokens"] = token_sum

        # YAML dump
        yaml_str = yaml.dump(frontmatter_data, sort_keys=False, allow_unicode=True).strip()
        md_lines = ["---", yaml_str, "---", ""]

        # Title
        md_lines.append(f"# {conversation.title}\n")

        # Messages
        for msg in conversation.messages:
            role_icon = {
                "user": "👤 User",
                "assistant": "🤖 Assistant",
                "system": "⚙️ System",
                "tool": "🛠️ Tool"
            }.get(msg.role, msg.role.capitalize())

            time_str = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
            md_lines.append(f"## {role_icon} ({time_str})\n")

            if msg.token_usage and not msg.token_usage.get("is_estimated"):
                tok_parts = []
                if "input_tokens" in msg.token_usage:
                    tok_parts.append(f"in: {msg.token_usage['input_tokens']:,}")
                if "output_tokens" in msg.token_usage:
                    tok_parts.append(f"out: {msg.token_usage['output_tokens']:,}")
                if msg.token_usage.get("cache_read_tokens", 0) > 0:
                    tok_parts.append(f"cache_read: {msg.token_usage['cache_read_tokens']:,}")
                if tok_parts:
                    md_lines.append(f"> ⚡ *Tokens:* `{' | '.join(tok_parts)}`\n")

            # Format reasoning / thinking
            if msg.reasoning_content:
                md_lines.extend([
                    "<details>",
                    "<summary>💭 <b>Thought Process</b> (kliknij, aby rozwinąć)</summary>\n",
                    msg.reasoning_content.strip(),
                    "\n</details>\n"
                ])

            # Format attachments
            if msg.attachments:
                att_lines = ["> 📎 **Załączniki:**"]
                for att in msg.attachments:
                    fname = att.get("filename") or att.get("name") or "plik"
                    mtype = att.get("type", "plik")
                    att_lines.append(f"> * `[{mtype}]` {fname}")
                md_lines.append("\n".join(att_lines) + "\n")

            # Format sources
            if msg.sources:
                src_lines = ["> 🌐 **Źródła wyszukiwania:**"]
                for src in msg.sources:
                    title = src.get("title") or src.get("url") or "źródło"
                    url = src.get("url")
                    if url:
                        src_lines.append(f"> * [{title}]({url})")
                    else:
                        src_lines.append(f"> * {title}")
                md_lines.append("\n".join(src_lines) + "\n")

            # Format tool calls
            for tc in msg.tool_calls:
                md_lines.append(MarkdownGenerator._format_tool_call(tc))
                md_lines.append("")

            # Main content text
            if msg.content:
                md_lines.append(msg.content.strip() + "\n")

        full_md = "\n".join(md_lines).strip() + "\n"

        # Safe slug for filename
        clean_title = re.sub(r"[^\w\s-]", "", conversation.title.lower())
        slug = re.sub(r"[-\s]+", "-", clean_title).strip("-")[:60] or "conversation"
        short_id = conversation.external_id[:8]
        rel_path = conversation_rel_path(conversation.platform, date_str, slug, short_id)

        return full_md, rel_path

    @staticmethod
    def _format_tool_call(tc: ToolCallRecord) -> str:
        summary_args = ""
        # Highlight command or path if available
        if "command" in tc.input:
            summary_args = f" (<code>{tc.input['command'][:60]}</code>)"
        elif "CommandLine" in tc.input:
            summary_args = f" (<code>{tc.input['CommandLine'][:60]}</code>)"
        elif "AbsolutePath" in tc.input:
            summary_args = f" (<code>{Path(str(tc.input['AbsolutePath'])).name}</code>)"
        elif "TargetFile" in tc.input:
            summary_args = f" (<code>{Path(str(tc.input['TargetFile'])).name}</code>)"

        lines = [
            "<details>",
            f"<summary>🛠️ <b>Tool Call</b>: <code>{tc.name}</code>{summary_args}</summary>\n",
            "**Input:**",
            "```json",
            json.dumps(tc.input, indent=2, ensure_ascii=False),
            "```"
        ]

        if tc.output is not None:
            clean_out = tc.output.strip()
            # If output is too huge, truncate for readability
            if len(clean_out) > 3000:
                clean_out = clean_out[:3000] + "\n... [truncated for archive readability]"
            lines.extend([
                "\n**Output:**",
                "```",
                clean_out,
                "```"
            ])

        lines.append("</details>")
        return "\n".join(lines)
