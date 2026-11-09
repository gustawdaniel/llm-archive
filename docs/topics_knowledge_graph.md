# Topics & Knowledge Graph — decyzje projektowe

> Odpowiada Fazie 9 (Knowledge Graph). Ten dokument to zapis decyzji z research session — zadania z tymi samymi decyzjami rozbite na kroki, ten plik jest "dlaczego" w jednym miejscu.

## Problem

LLM Archive traktuje konwersacje jako płaską listę. Brakuje warstwy grupującej je po tematach (projektach, obszarach życia), pokazującej powiązania między nimi, i pozwalającej wrócić do kontekstu zamiast zaczynać od zera w nowym czacie.

## Fakty wyjściowe (2026-09-24)

- 3937 konwersacji, 132 532 chunków, embeddingi bge-m3 (1024-dim) **tylko na poziomie chunka** — nie ma dziś reprezentacji całej konwersacji jako jednego wektora.
- `llm_documents.summary` istnieje w schemacie od migracji 001, ale jest **całkowicie puste (0/3937)**.
- Platformy: chatgpt (2821), gemini (493), deepseek (318), antigravity (199), claude_web (40), grok (24), perplexity (22), claude_code (20).
- Skala jest mała. Żadna decyzja architektoniczna tutaj nie powinna być uzasadniana "co jeśli będzie milion konwersacji" — nie będzie, a jeśli będzie, to daleka przyszłość z innym budżetem inżynieryjnym.

## Decyzje

### 1. Tematy są emergentne, nie z góry zdefiniowaną taksonomią
User chce, żeby tematy "same wyskakiwały" z tego, o czym naturalnie rozmawia (projekt APK, NetPocket, projekty Michała, języki, relacje, dieta, brain/sauron, homelab, observability...), z możliwością ręcznego przypięcia nazwy/opisu do odkrytego klastra. To wyklucza sztywną taksonomię ustaloną z góry i wyklucza czyste tagowanie ręczne jako jedyny mechanizm.

### 2. Reprezentacja: title + summary, nie średnia z chunków
Uśrednianie embeddingów wszystkich chunków konwersacji rozmywa sygnał, gdy jedna rozmowa dotyka dwóch tematów (wypadkowa "pół o językach, pół o diecie" ląduje w bezsensownym środku przestrzeni). Zamiast tego: LLM (Qwen na `rog`, ten sam pipeline co planowane nowe tytuły) generuje krótkie podsumowanie do `llm_documents.summary`, i `title + summary` jest embedowane jako jeden wektor per konwersacja (`llm_conversations.embedding`). Gęstszy, mniej zaszumiony sygnał tematyczny.

### 3. Klastrowanie: HDBSCAN, batch, nie LLM-classification per konwersacja
Nie zgadujemy liczby tematów z góry (k-meansby wymagał). HDBSCAN znajduje gęste skupiska sam i explicitnie oznacza outliery jako "brak tematu" — realistyczne, jednorazowe pytania nie muszą mieć przypisania. Nocny batch, sekundy obliczeń przy tej skali. LLM nie jest używany do klasyfikacji per-konwersacja (drogie, niedeterministyczne) — tylko do generowania tekstu wejściowego (summary) dla embeddingu.

### 4. Ciągłość tematów między przebiegami re-klastrowania
Naiwne re-klastrowanie renumeruje klastry co przebieg i gubi etykiety. Każdy przebieg dopasowuje nowe centroidy do istniejących `llm_topics.centroid` (cosine similarity, próg ~0.85); dopasowany temat aktualizuje centroid i zachowuje nazwę/opis jeśli `is_manual=true`; niedopasowany tworzy nowy temat. Ręczne przypisania konwersacja→temat (`source='manual'`) nigdy nie są nadpisywane przez nocny job.

### 5. Intensywność w czasie jest pochodną, nie strukturą
User: "tagi jako funkcje intensywności w danym okresie" — projekt nie jest aktywny/nieaktywny, jest funkcją czasu (gorący, uciszony, wraca). To nie wymaga żadnej dodatkowej tabeli: `COUNT(*) GROUP BY topic_id, date_trunc('week', started_at)` na istniejących `llm_conversation_topics` + `llm_conversations.started_at`. Renderowane jako sparkline/timeline w widoku tematu.

### 6. Multi-topic per konwersacja: v1 = jeden dominujący temat, eskalacja tylko jeśli zabraknie
Klastrowanie na poziomie konwersacji (title+summary) daje jeden dominujący temat. Wersja z klastrowaniem na poziomie chunków (już zaembedowanych, 132k wierszy) i rzutowaniem w górę jako rozkład wag dałaby naturalny multi-label, ale jest cięższa obliczeniowo i nie budujemy jej z góry — tylko jeśli w praktyce jednotematowość przeszkadza.

### 7. Graf: dwutorowo, Obsidian przed customowym D3
- **Tor A (ship pierwszy):** top-k najbliższych sąsiadów (cosine) per konwersacja → `llm_similarity_edges` → wstrzyknięte jako `[[wikilinks]]`/`## Related` do eksportowanego markdownu. Obsidian renderuje graf **za darmo** ze swojego natywnego graph view. To jest graf *podobieństwa semantycznego*, nie graf cytowań jak standardowo w Obsidianie — inna semantyka krawędzi, trzeba to zakomunikować w UI/README, żeby nie zmylić.
- **Tor B (odroczony):** własna wizualizacja force-directed (D3.js/Cytoscape) w web UI, kolorowanie po temacie, slider czasowy animujący intensywność. Budowany tylko jeśli Tor A okaże się realnie używany i niewystarczający — inaczej ryzyko zbudowania drugiej wizualizacji czegoś, czego jeszcze nie wiadomo czy User potrzebuje.

### 8. Żadnej bazy grafowej
Krawędzie podobieństwa to jedna mała tabela (`conversation_id_a, conversation_id_b, score`), nie Neo4j/graf natywny. 3937 węzłów z ~5 krawędziami każdy to trywialne dla Postgresa; graf DB byłby czystym overkillem na tę skalę.

## Schemat (migracja `004_topics_knowledge_graph.sql`)

```sql
ALTER TABLE llm_conversations ADD COLUMN embedding vector(1024);
ALTER TABLE llm_conversations ADD COLUMN last_clustered_at TIMESTAMPTZ;

CREATE TABLE llm_topics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    description TEXT,
    centroid vector(1024) NOT NULL,
    is_manual BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE llm_conversation_topics (
    conversation_id UUID REFERENCES llm_conversations(id) ON DELETE CASCADE,
    topic_id UUID REFERENCES llm_topics(id) ON DELETE CASCADE,
    score FLOAT NOT NULL,
    source VARCHAR(20) NOT NULL DEFAULT 'auto',
    assigned_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (conversation_id, topic_id)
);

CREATE TABLE llm_similarity_edges (
    conversation_id_a UUID REFERENCES llm_conversations(id) ON DELETE CASCADE,
    conversation_id_b UUID REFERENCES llm_conversations(id) ON DELETE CASCADE,
    score FLOAT NOT NULL,
    computed_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (conversation_id_a, conversation_id_b)
);
```

## Kolejność wdrożenia (odpowiada podzadaniom ClickUp)

1. Schemat bazy (powyżej).
2. Auto-klasyfikator: generacja summary (Qwen) → embedding konwersacji → HDBSCAN → ciągłość klastrów.
3. **Tor A:** similarity edges → eksport wikilinków do Obsidiana.
4. Widok kontekstu tematu: agregacja, timeline intensywności, eksport do kontynuacji.
5. Topic-aware search: faceted filter po temacie w istniejącym hybrid search.
6. **Tor B (odroczony):** custom D3 knowledge graph — tylko po walidacji Toru A.
