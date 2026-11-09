from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import List, Optional
import uuid
from pydantic import BaseModel, Field


class ContentSourceType(str, Enum):
    HACKER_NEWS = "hacker_news"
    ARXIV = "arxiv"
    GITHUB_RELEASES = "github_releases"
    RSS_FEED = "rss_feed"
    LLM_ARCHIVE = "llm_archive"


class FeedItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source: ContentSourceType
    title: str
    url: str
    summary: str
    author: Optional[str] = None
    score: float = 0.5  # Relevance score (0.0 to 1.0)
    published_at: datetime = Field(default_factory=datetime.utcnow)
    tags: List[str] = Field(default_factory=list)


class PodcastSegment(BaseModel):
    title: str
    language: str = "pl"   # "pl" (darkman) or "en" (lessac)
    voice: str = "darkman"
    text: str


class PodcastEpisode(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    episode_number: int = 1
    title: str
    published_at: datetime = Field(default_factory=datetime.utcnow)
    duration_seconds: int = 600
    audio_filename: str
    audio_url: str
    file_size_bytes: int = 0
    summary_markdown: str
    segments: List[PodcastSegment] = Field(default_factory=list)
