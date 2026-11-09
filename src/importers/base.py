import io
import json
import zipfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, List, Optional
from ..models import NormalizedConversation


class BaseArchiveImporter(ABC):
    def parse(self, archive_path: Path) -> List[NormalizedConversation]:
        """Common interface method for parsing an archive file or directory."""
        return self.parse_archive(archive_path)

    @abstractmethod
    def parse_archive(self, file_path: Path) -> List[NormalizedConversation]:
        pass

    @abstractmethod
    def to_common_model(self, raw: dict) -> NormalizedConversation:
        """Convert a single raw conversation dict into the normalized common model."""
        pass

    @staticmethod
    def read_file_or_zip(file_path: Path, inner_filename: str) -> Optional[Any]:
        """Read a file directly or extract inner_filename from a ZIP archive."""
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if file_path.suffix.lower() == ".zip":
            with zipfile.ZipFile(file_path, "r") as z:
                # Check direct match or case-insensitive match
                target_name = None
                for name in z.namelist():
                    if name == inner_filename or name.endswith("/" + inner_filename):
                        target_name = name
                        break

                if not target_name:
                    # Look for any .json file if inner_filename not found
                    for name in z.namelist():
                        if name.endswith(".json") and not name.startswith("__MACOSX"):
                            target_name = name
                            break

                if not target_name:
                    return None

                with z.open(target_name) as f:
                    return json.load(io.TextIOWrapper(f, encoding="utf-8", errors="replace"))
        else:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                return json.load(f)


Importer = BaseArchiveImporter

