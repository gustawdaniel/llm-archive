from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field
import uuid


class ToolCallRecord(BaseModel):
    name: str
    input: Dict[str, Any] = Field(default_factory=dict)
    output: Optional[str] = None
    duration_ms: Optional[float] = None
    is_error: bool = False


class NormalizedMessage(BaseModel):
    step_index: int
    external_id: Optional[str] = None
    parent_id: Optional[str] = None
    role: str  # 'user', 'assistant', 'system', 'tool'
    content: str
    reasoning_content: Optional[str] = None
    tool_calls: List[ToolCallRecord] = Field(default_factory=list)
    attachments: List[Dict[str, Any]] = Field(default_factory=list)
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    token_usage: Dict[str, int] = Field(default_factory=dict)
    created_at: datetime


class NormalizedConversation(BaseModel):
    id: Optional[uuid.UUID] = None
    platform: str  # 'chatgpt', 'claude_web', 'claude_code', 'antigravity', 'deepseek', 'gemini', 'grok'
    external_id: str
    title: str
    project_path: Optional[str] = None
    git_branch: Optional[str] = None
    device: Optional[str] = None
    model: Optional[str] = None
    started_at: datetime
    updated_at: datetime
    raw_metadata: Dict[str, Any] = Field(default_factory=dict)
    messages: List[NormalizedMessage] = Field(default_factory=list)

    @property
    def tools_used(self) -> List[str]:
        tools = set()
        for msg in self.messages:
            for tc in msg.tool_calls:
                tools.add(tc.name)
        return sorted(list(tools))


class ChunkRecord(BaseModel):
    chunk_index: int
    header_path: str
    text_content: str
    embedding: Optional[List[float]] = None


class SearchFilters(BaseModel):
    platform: Optional[Union[str, List[str]]] = None
    after: Optional[Union[datetime, str]] = None
    project_path: Optional[str] = None
    topic_ids: Optional[Union[str, List[str]]] = None


class SearchQuery(BaseModel):
    query: str
    platform: Optional[Union[str, List[str]]] = None
    project_path: Optional[str] = None
    filters: Optional[SearchFilters] = None
    limit: int = 10
    alpha: float = 0.5  # Weight between dense vector (1.0) and full-text search (0.0)

    @property
    def platforms_list(self) -> Optional[List[str]]:
        raw = None
        if self.filters and self.filters.platform:
            raw = self.filters.platform
        elif self.platform:
            raw = self.platform
        if raw is None:
            return None
        return [raw] if isinstance(raw, str) else list(raw)

    @property
    def filter_after(self) -> Optional[datetime]:
        if self.filters and self.filters.after:
            if isinstance(self.filters.after, str):
                try:
                    return datetime.fromisoformat(self.filters.after.replace("Z", "+00:00"))
                except Exception:
                    return None
            return self.filters.after
        return None

    @property
    def effective_project_path(self) -> Optional[str]:
        if self.filters and self.filters.project_path:
            return self.filters.project_path
        return self.project_path

    @property
    def topic_ids_list(self) -> Optional[List[uuid.UUID]]:
        raw = None
        if self.filters and self.filters.topic_ids:
            raw = self.filters.topic_ids
        if raw is None:
            return None
        items = [raw] if isinstance(raw, str) else list(raw)
        valid = []
        for it in items:
            try:
                valid.append(uuid.UUID(str(it)))
            except Exception:
                pass
        return valid if valid else None


class SearchResult(BaseModel):
    conversation_id: str
    platform: str
    title: str
    project_path: Optional[str] = None
    header_path: str
    chunk_text: str
    score: float
    started_at: datetime
    relative_path: Optional[str] = None
    topic_id: Optional[str] = None
    topic_name: Optional[str] = None

