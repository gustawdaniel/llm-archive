import pytest
from pathlib import Path
from src.config import settings


@pytest.fixture(autouse=True)
def isolate_markdown_export(tmp_path: Path):
    """Ensure tests never write mock/test markdown files to the real doc/llm-archive vault."""
    orig_export_dir = settings.MARKDOWN_EXPORT_DIR
    settings.MARKDOWN_EXPORT_DIR = tmp_path
    yield tmp_path
    settings.MARKDOWN_EXPORT_DIR = orig_export_dir
