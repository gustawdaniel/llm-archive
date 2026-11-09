from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from ..models import NormalizedConversation


class BaseNormalizer(ABC):
    @abstractmethod
    def parse(self, raw_data: Any, metadata: Optional[Dict[str, Any]] = None) -> NormalizedConversation:
        """Parse raw payload/file content into a NormalizedConversation object."""
        pass
