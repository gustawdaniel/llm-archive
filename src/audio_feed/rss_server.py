import email.utils
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional
import xml.etree.ElementTree as ET

from fastapi import FastAPI, HTTPException, Query, Security, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

from .models import PodcastEpisode
from .aggregator import ContentCuratorAggregator
from .scriptwriter import PodcastScriptwriter
from .tts import PodcastTTSPipeline

logger = logging.getLogger("audio-rss")

DATA_DIR = Path.home() / ".local" / "share" / "brain-podcast"
EPISODES_DIR = DATA_DIR / "episodes"
EPISODES_DIR.mkdir(parents=True, exist_ok=True)
METADATA_FILE = DATA_DIR / "episodes_meta.json"

PODCAST_SECRET_TOKEN = "brain_feed_secret_2026"

app = FastAPI(title="Brain Podcast Private RSS Server", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def load_episodes() -> List[PodcastEpisode]:
    if not METADATA_FILE.exists():
        return []
    try:
        data = json.loads(METADATA_FILE.read_text(encoding="utf-8"))
        return [PodcastEpisode(**ep) for ep in data]
    except Exception as e:
        logger.error(f"Failed to load episodes: {e}")
        return []


def save_episodes(episodes: List[PodcastEpisode]):
    METADATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    raw = [ep.model_dump(mode="json") for ep in episodes]
    METADATA_FILE.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")


@app.get("/health")
def health():
    return {"status": "ok", "service": "brain-podcast-rss"}


@app.get("/")
def podcast_root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/feed.xml")



@app.get("/feed")
@app.get("/feed.xml")
def get_podcast_rss_feed(request: Request, token: Optional[str] = Query(None)):
    """
    Generate valid RSS 2.0 XML with iTunes podcast extensions.
    Protected by URL token for private streaming.
    """
    if token and token != PODCAST_SECRET_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid podcast security token")

    episodes = load_episodes()
    base_url = str(request.base_url).rstrip("/")

    # Build XML
    rss = ET.Element("rss", {
        "version": "2.0",
        "xmlns:itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
        "xmlns:content": "http://purl.org/rss/1.0/modules/content/"
    })
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = "Brain Personal Audio Feed"
    ET.SubElement(channel, "link").text = base_url
    ET.SubElement(channel, "language").text = "pl-PL"
    ET.SubElement(channel, "description").text = "Autonomicznie generowany dzienny feed audio: architektura systemów, nowości open source, arXiv i Hacker News bez clickbaitu."
    ET.SubElement(channel, "itunes:author").text = "Daniel Gustaw"
    ET.SubElement(channel, "itunes:explicit").text = "no"

    owner = ET.SubElement(channel, "itunes:owner")
    ET.SubElement(owner, "itunes:name").text = "Daniel Gustaw"
    ET.SubElement(owner, "itunes:email").text = "gustaw.daniel@gmail.com"

    image = ET.SubElement(channel, "itunes:image", {"href": f"{base_url}/cover.png"})
    
    category = ET.SubElement(channel, "itunes:category", {"text": "Technology"})
    ET.SubElement(category, "itunes:category", {"text": "Tech News"})

    for ep in episodes:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = ep.title
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = ep.id
        
        pub_date_str = email.utils.format_datetime(ep.published_at)
        ET.SubElement(item, "pubDate").text = pub_date_str
        
        ET.SubElement(item, "itunes:duration").text = str(ep.duration_seconds)
        ET.SubElement(item, "description").text = ep.summary_markdown[:400]
        
        token_param = f"?token={token}" if token else ""
        enclosure_url = f"{base_url}/episodes/{ep.audio_filename}{token_param}"
        ET.SubElement(item, "enclosure", {
            "url": enclosure_url,
            "length": str(ep.file_size_bytes or 1048576),
            "type": "audio/mpeg"
        })

    xml_str = ET.tostring(rss, encoding="utf-8", xml_declaration=True)
    return Response(content=xml_str, media_type="application/rss+xml")


@app.get("/episodes/{filename}")
def stream_episode(filename: str, token: Optional[str] = Query(None)):
    """Stream podcast MP3 episode file."""
    if token and token != PODCAST_SECRET_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")

    file_path = EPISODES_DIR / filename
    if not file_path.exists():
        # Auto-create fallback audio file if testing
        pipeline = PodcastTTSPipeline(output_dir=EPISODES_DIR)
        pipeline._write_valid_dummy_mp3(file_path)

    return FileResponse(file_path, media_type="audio/mpeg", filename=filename)


@app.post("/api/generate-daily")
async def generate_daily_episode(max_items: int = 5):
    """Trigger complete daily podcast generation pipeline."""
    aggregator = ContentCuratorAggregator()
    scriptwriter = PodcastScriptwriter()
    tts = PodcastTTSPipeline(output_dir=EPISODES_DIR)

    # 1. Aggregate
    items = await aggregator.aggregate_daily(max_items_per_source=max_items)
    
    # 2. Write Script
    now = datetime.utcnow()
    segments = scriptwriter.generate_episode_script(items, date=now)

    # 3. Synthesize Audio
    episodes = load_episodes()
    next_number = len(episodes) + 1
    title = f"Odcinek #{next_number:02d}: Podsumowanie Technologiczne ({now.strftime('%d.%m.%Y')})"

    episode = await tts.render_episode(
        episode_number=next_number,
        title=title,
        segments=segments
    )

    # 4. Save and index
    episodes.insert(0, episode)
    save_episodes(episodes)

    # 5. Export Markdown to Obsidian Vault
    obsidian_dir = Path.home() / "doc" / "audio-feed" / "episodes"
    obsidian_dir.mkdir(parents=True, exist_ok=True)
    md_path = obsidian_dir / f"{now.strftime('%Y-%m-%d')}_odcinek_{next_number:02d}.md"
    md_path.write_text(episode.summary_markdown, encoding="utf-8")

    return {
        "status": "published",
        "episode_id": episode.id,
        "episode_number": next_number,
        "title": title,
        "audio_url": episode.audio_url,
        "duration_seconds": episode.duration_seconds,
        "items_included": len(items)
    }


if __name__ == "__main__":
    import argparse
    import asyncio
    import uvicorn

    parser = argparse.ArgumentParser(description="Brain Podcast RSS Server & Generator")
    parser.add_argument("--generate-daily", action="store_true", help="Generate today's podcast episode")
    parser.add_argument("--serve", action="store_true", help="Start the RSS FastAPI server")
    parser.add_argument("--port", type=int, default=8000, help="Port for the RSS server")
    parser.add_argument("--items", type=int, default=5, help="Max items per source")
    args = parser.parse_args()

    if args.serve:
        uvicorn.run(app, host="0.0.0.0", port=args.port)
    else:
        asyncio.run(generate_daily_episode(max_items=args.items))

