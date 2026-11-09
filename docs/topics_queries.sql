-- Ściąga SQL do przeglądania tematów (llm_topics) i tego, co w nich siedzi.
-- Połączenie: psql -h localhost -p 5432 -U postgres -d brain_knowledge

-- 1. Lista wszystkich tematów z rozmiarem i opisem (jeśli wygenerowany).
SELECT t.name, t.description, t.keywords, count(*) AS n
FROM llm_topics t
JOIN llm_conversation_topics ct ON ct.topic_id = t.id
GROUP BY t.id, t.name, t.description, t.keywords
ORDER BY n DESC;

-- 2. Konwersacje w JEDNYM konkretnym temacie (wpisz fragment nazwy w ILIKE).
SELECT c.title, c.platform, c.started_at, ct.score
FROM llm_conversation_topics ct
JOIN llm_conversations c ON c.id = ct.conversation_id
JOIN llm_topics t ON t.id = ct.topic_id
WHERE t.name ILIKE '%kalorie%'          -- <-- tu wpisujesz fragment nazwy tematu
ORDER BY ct.score DESC;

-- 3. Sam opis + keywords jednego tematu, bez listy konwersacji.
SELECT name, description, keywords
FROM llm_topics
WHERE name ILIKE '%kalorie%';           -- <-- fragment nazwy

-- 4. Odwrotnie: mam tytuł/frazę rozmowy, chcę wiedzieć do jakiego tematu (jeśli
--    do jakiegokolwiek) trafiła - to jest to zapytanie, którego brakowało wcześniej.
SELECT c.title, c.platform, t.name AS temat, t.description
FROM llm_conversations c
LEFT JOIN llm_conversation_topics ct ON ct.conversation_id = c.id
LEFT JOIN llm_topics t ON t.id = ct.topic_id
WHERE c.title ILIKE '%google api key%'  -- <-- fragment tytułu / słowo kluczowe
   OR c.title ILIKE '%apk%';

-- 5. Konwersacje, które NIE trafiły do żadnego tematu (outliers) - żeby zobaczyć
--    ile i co realnie zostaje poza automatyczną klasteryzacją.
SELECT c.title, c.platform, c.started_at
FROM llm_conversations c
LEFT JOIN llm_conversation_topics ct ON ct.conversation_id = c.id
WHERE ct.topic_id IS NULL
ORDER BY c.started_at DESC
LIMIT 50;
