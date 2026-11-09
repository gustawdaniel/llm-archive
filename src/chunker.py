from typing import List
from .models import NormalizedConversation, ChunkRecord


class SemanticChunker:
    def __init__(self, max_chunk_chars: int = 1200, overlap_chars: int = 150):
        self.max_chunk_chars = max_chunk_chars
        self.overlap_chars = overlap_chars

    def chunk_conversation(self, conv: NormalizedConversation) -> List[ChunkRecord]:
        chunks: List[ChunkRecord] = []
        chunk_idx = 0

        # Chunk 1: Title and overview
        overview_text = f"Title: {conv.title}\nPlatform: {conv.platform}\nModel: {conv.model or 'N/A'}\n"
        if conv.project_path:
            overview_text += f"Project: {conv.project_path}\n"
        tools = conv.tools_used
        if tools:
            overview_text += f"Tools Used: {', '.join(tools)}\n"

        chunks.append(ChunkRecord(
            chunk_index=chunk_idx,
            header_path=f"{conv.title} > Overview",
            text_content=overview_text.strip()
        ))
        chunk_idx += 1

        # Turn-based grouping: Group User message with immediate Assistant response
        i = 0
        n = len(conv.messages)

        while i < n:
            msg = conv.messages[i]
            role_label = msg.role.capitalize()
            header = f"{conv.title} > Step {msg.step_index} ({role_label})"

            turn_text_parts = [f"[{role_label} - {msg.created_at.strftime('%Y-%m-%d %H:%M')}]:\n{msg.content}"]

            # If there are tool calls, append their names and summary commands
            for tc in msg.tool_calls:
                turn_text_parts.append(f"[Tool Call: {tc.name} input={tc.input}]")
                if tc.output:
                    turn_text_parts.append(f"[Tool Output: {tc.output[:300]}]")

            # Check if next message is assistant response to this user query
            if msg.role == "user" and i + 1 < n and conv.messages[i + 1].role == "assistant":
                next_msg = conv.messages[i + 1]
                turn_text_parts.append(f"\n[Assistant Response]:\n{next_msg.content}")
                for tc in next_msg.tool_calls:
                    turn_text_parts.append(f"[Tool Call: {tc.name} input={tc.input}]")
                    if tc.output:
                        turn_text_parts.append(f"[Tool Output: {tc.output[:300]}]")
                i += 1  # consumed next message in this turn

            turn_text = "\n".join(turn_text_parts).strip()

            if len(turn_text) <= self.max_chunk_chars:
                chunks.append(ChunkRecord(
                    chunk_index=chunk_idx,
                    header_path=header,
                    text_content=turn_text
                ))
                chunk_idx += 1
            else:
                # Split with overlap
                start = 0
                while start < len(turn_text):
                    end = min(start + self.max_chunk_chars, len(turn_text))
                    sub_text = turn_text[start:end]
                    chunks.append(ChunkRecord(
                        chunk_index=chunk_idx,
                        header_path=f"{header} (part {start // (self.max_chunk_chars - self.overlap_chars) + 1})",
                        text_content=sub_text.strip()
                    ))
                    chunk_idx += 1
                    if end == len(turn_text):
                        break
                    start += self.max_chunk_chars - self.overlap_chars

            i += 1

        return chunks
