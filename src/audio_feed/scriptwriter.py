import logging
from datetime import datetime
from typing import List

from .models import FeedItem, PodcastSegment

logger = logging.getLogger("audio-scriptwriter")


class PodcastScriptwriter:
    """
    Synthesizes curated technical articles, releases, and discussions into
    a coherent, natural audio show script with smooth topic transitions.
    """

    def generate_episode_script(
        self,
        curated_items: List[FeedItem],
        date: datetime = None
    ) -> List[PodcastSegment]:
        d = date or datetime.utcnow()
        date_str = d.strftime("%d %B %Y")
        
        segments: List[PodcastSegment] = []

        # 1. INTRO
        intro_text = (
            f"Dzień dobry! Witaj w Twoim porannym wydaniu Brain Audio Feed na dzień {date_str}. "
            f"Zamiast algorytmów YouTube i rozpraszających wideo, przygotowałem dla Ciebie "
            f"skondensowane podsumowanie najważniejszych architektur, premier open source i dyskusji inżynieryjnych ze świata technologii. "
            f"Dzisiaj w programie omówimy {len(curated_items)} wyselekcjonowanych tematów."
        )
        segments.append(PodcastSegment(
            title="Wprowadzenie do audycji",
            language="pl",
            voice="darkman",
            text=intro_text
        ))

        # 2. BODY TOPICS
        for idx, item in enumerate(curated_items, 1):
            is_english = self._detect_english(item.title)
            
            transition = "Przechodząc do kolejnego tematu. " if idx > 1 else "Zaczynamy od pierwszego zagadnienia. "
            
            if is_english:
                seg_text = (
                    f"{transition} Ze źródła {item.source.value.replace('_', ' ').title()}: "
                    f"{item.title}. "
                    f"Kluczowe podsumowanie zagadnienia: {item.summary}. "
                    f"Więcej szczegółów znajdziesz w odnośniku w Twoim Obsidian Vault."
                )
                voice = "lessac" if len(item.title.split()) > 4 and not any(ord(c) > 127 for c in item.title) else "darkman"
            else:
                seg_text = (
                    f"{transition} Temat: {item.title}. "
                    f"Najważniejsze wnioski architektoniczne: {item.summary}."
                )
                voice = "darkman"

            segments.append(PodcastSegment(
                title=item.title[:60],
                language="en" if voice == "lessac" else "pl",
                voice=voice,
                text=seg_text
            ))

        # 3. OUTRO
        outro_text = (
            "To wszystko w dzisiejszym wydaniu Twojej audycji technologicznej Brain Audio. "
            "Wszystkie źródła, transkrypcje oraz notatki zostały automatycznie zindeksowane "
            "w Twojej bazie pgvector i zsynchronizowane z Obsidianem. "
            "Miłego, produktywnego dnia i do usłyszenia jutro rano o szóstej!"
        )
        segments.append(PodcastSegment(
            title="Zakończenie i podsumowanie",
            language="pl",
            voice="darkman",
            text=outro_text
        ))

        return segments

    def _detect_english(self, text: str) -> bool:
        # Check for Polish diacritics
        polish_chars = set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")
        if any(c in polish_chars for c in text):
            return False
        english_words = {"the", "and", "for", "with", "system", "database", "fast", "release", "discussion", "python", "rust"}
        words = set(text.lower().split())
        return len(words.intersection(english_words)) >= 1
