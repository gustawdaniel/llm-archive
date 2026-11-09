import pytest
from starlette.testclient import TestClient
from src.audio_feed.models import ContentSourceType, FeedItem
from src.audio_feed.aggregator import ContentCuratorAggregator
from src.audio_feed.scriptwriter import PodcastScriptwriter
from src.audio_feed.tts import PodcastTTSPipeline
from src.audio_feed.rss_server import app, PODCAST_SECRET_TOKEN

client = TestClient(app)


def test_aggregator_clickbait_and_scoring():
    aggregator = ContentCuratorAggregator()

    # Test clickbait rejection
    assert aggregator._is_clickbait("10 Shocking Reasons Why You Need This Tool") is True
    assert aggregator._is_clickbait("PostgreSQL HNSW Index Tuning for High Dimensional Vectors") is False

    # Test scoring
    item_relevant = FeedItem(
        source=ContentSourceType.HACKER_NEWS,
        title="Rust and PostgreSQL vector similarity benchmarks",
        url="https://example.com/rust-pg",
        summary="Optimizing zero-copy SIMD distance calculations for pgvector.",
        tags=["rust", "postgresql"]
    )
    score = aggregator._score_relevance(item_relevant)
    assert score > 0.5


def test_scriptwriter_generation():
    scriptwriter = PodcastScriptwriter()
    items = [
        FeedItem(
            source=ContentSourceType.HACKER_NEWS,
            title="Fast Vector Search in Rust",
            url="https://example.com/item1",
            summary="Benchmarking distance metrics."
        ),
        FeedItem(
            source=ContentSourceType.GITHUB_RELEASES,
            title="Wydanie nowego kompilatora języka",
            url="https://example.com/item2",
            summary="Wprowadzono optymalizacje czasu kompilacji."
        )
    ]

    segments = scriptwriter.generate_episode_script(items)
    assert len(segments) >= 3  # Intro, 2 items, Outro
    assert segments[0].title == "Wprowadzenie do audycji"
    assert "Dzień dobry" in segments[0].text
    assert segments[-1].title == "Zakończenie i podsumowanie"


@pytest.mark.asyncio
async def test_tts_rendering(tmp_path):
    tts = PodcastTTSPipeline(output_dir=tmp_path)
    scriptwriter = PodcastScriptwriter()
    items = [
        FeedItem(
            source=ContentSourceType.HACKER_NEWS,
            title="SQLite WAL Benchmark",
            url="https://example.com/wal",
            summary="Testing high throughput writes."
        )
    ]
    segments = scriptwriter.generate_episode_script(items)
    episode = await tts.render_episode(episode_number=1, title="Test Episode #1", segments=segments)

    assert episode.episode_number == 1
    assert episode.audio_filename.endswith(".mp3")
    assert episode.file_size_bytes > 0
    assert (tmp_path / episode.audio_filename).exists()


def test_rss_feed_endpoints():
    # 1. Health
    res_health = client.get("/health")
    assert res_health.status_code == 200
    assert res_health.json()["service"] == "brain-podcast-rss"

    # 2. Token protection
    res_forbidden = client.get("/feed?token=wrong_token")
    assert res_forbidden.status_code == 403

    # 3. Valid feed XML
    res_feed = client.get(f"/feed?token={PODCAST_SECRET_TOKEN}")
    assert res_feed.status_code == 200
    assert "application/rss+xml" in res_feed.headers["content-type"]
    assert "<rss version=\"2.0\"" in res_feed.text
    assert "xmlns:itunes=" in res_feed.text
    assert "Brain Personal Audio Feed" in res_feed.text
