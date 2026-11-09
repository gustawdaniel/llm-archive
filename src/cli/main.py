import asyncio
import json
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.table import Table
import uvicorn

from ..config import settings
from ..daemon.watcher import LocalAgentWatcher
from ..normalizers import AntigravityNormalizer, ClaudeCodeNormalizer, CodexNormalizer, ChatGPTNormalizer, ClaudeWebNormalizer, MarkdownGenerator
from ..chunker import SemanticChunker
from ..embedder import Embedder
from ..database import Database
from ..models import SearchQuery

app = typer.Typer(name="brain-llm", help="Centralized LLM archive & semantic retrieval CLI.")
console = Console()


@app.command()
def scan():
    """Scan local machine for Antigravity and Claude Code sessions."""
    watcher = LocalAgentWatcher()
    files = watcher.scan_local_files()
    table = Table(title="Odnalezione Lokalne Sesje Agentów")
    table.add_column("Platforma", style="cyan")
    table.add_column("Ścieżka Pliku", style="dim")
    table.add_column("Rozmiar", justify="right")

    for f in files:
        plat = "antigravity" if "antigravity-ide" in str(f) else "claude_code"
        table.add_row(plat, str(f), f"{f.stat().st_size:,} B")

    console.print(table)
    console.print(f"[bold green]Łącznie znaleziono:[/bold green] {len(files)} sesji.")


@app.command()
def ingest(
    limit: Optional[int] = typer.Option(None, "--limit", "-n", help="Limit liczby przetwarzanych sesji"),
    offline_only: bool = typer.Option(False, "--offline-only", help="Zapisz tylko Markdown bez wysyłki do bazy")
):
    """Przetwórz lokalne sesje (Antigravity + Claude Code + Codex), zapisz Markdown i zindeksuj w PostgreSQL."""
    async def _do_ingest():
        watcher = LocalAgentWatcher()
        files = watcher.scan_local_files()
        if limit:
            files = files[:limit]

        db = None
        embedder = None
        chunker = SemanticChunker()

        if not offline_only:
            try:
                db = Database()
                await db.connect()
                embedder = Embedder()
                console.print(f"[green]Połączono z bazą PostgreSQL na {settings.DATABASE_URL}[/green]")
            except Exception as e:
                console.print(f"[yellow]Brak połączenia z PostgreSQL ({e}). Tryb tylko-markdown.[/yellow]")
                db = None

        console.print(f"[yellow]Rozpoczynam przetwarzanie {len(files)} sesji...[/yellow]")
        success_count = 0

        for f in files:
            is_antigravity = "antigravity-ide" in str(f)
            if is_antigravity:
                norm = AntigravityNormalizer()
            elif f.name.startswith("rollout-"):
                norm = CodexNormalizer()
            else:
                norm = ClaudeCodeNormalizer()
            try:
                conv = norm.parse(f)
                md_content, rel_path = MarkdownGenerator.generate(conv)
                target_file = settings.MARKDOWN_EXPORT_DIR / rel_path
                target_file.parent.mkdir(parents=True, exist_ok=True)
                target_file.write_text(md_content, encoding="utf-8")

                db_status = ""
                if db and embedder:
                    chunks = chunker.chunk_conversation(conv)
                    texts = [c.text_content for c in chunks]
                    embs = await embedder.embed_texts(texts)
                    for c, emb in zip(chunks, embs):
                        c.embedding = emb
                    await db.upsert_conversation(conv, md_content, rel_path, chunks)
                    db_status = f" [cyan]({len(chunks)} chunks zindeksowano w Postgres)[/cyan]"

                success_count += 1
                console.print(f"  [green]✓[/green] [{conv.platform}] {conv.title[:60]} -> [dim]{rel_path}[/dim]{db_status}")
            except Exception as e:
                console.print(f"  [red]✗ Błąd dla {f.name}: {e}[/red]")

        if db:
            await db.close()

        console.print(f"[bold green]Zakończono![/bold green] Pomyślnie przetworzono {success_count} dokumentów.")

    asyncio.run(_do_ingest())



@app.command()
def search(
    query: str = typer.Argument(..., help="Zapytanie tekstowe lub pojęciowe"),
    platform: Optional[str] = typer.Option(None, "--platform", "-p", help="Filtruj po platformie"),
    after: Optional[str] = typer.Option(None, "--after", help="Filtruj po dacie od (YYYY-MM-DD lub ISO)"),
    limit: int = typer.Option(5, "--limit", "-l", help="Maksymalna liczba wyników"),
    format: str = typer.Option("text", "--format", "-f", help="Format wyjściowy: 'text', 'json', 'markdown'"),
    hybrid: bool = typer.Option(True, "--hybrid/--vector-only", help="Wyszukiwanie hybrydowe (wektorowe + FTS)")
):
    """Wyszukaj w zindeksowanej historii LLM (Vector + FullText Search)."""
    async def _do_search():
        db = Database()
        embedder = Embedder()
        try:
            await db.connect()
        except Exception as e:
            console.print(f"[red]Brak połączenia z PostgreSQL ({e}). Upewnij się, że baza danych działa.[/red]")
            return

        from ..models import SearchFilters
        filters = SearchFilters(platform=platform, after=after)
        q = SearchQuery(
            query=query,
            platform=platform,
            filters=filters,
            limit=limit,
            alpha=0.5 if hybrid else 1.0
        )
        emb = await embedder.embed_texts([query])
        query_vec = emb[0] if emb else None

        results = await db.hybrid_search(q, query_vec)
        await db.close()

        if not results:
            if format.lower() == "json":
                console.print("[]")
            else:
                console.print("[yellow]Brak wyników dla podanego zapytania.[/yellow]")
            return

        fmt = format.lower()
        if fmt == "json":
            out_data = [r.model_dump(mode="json") for r in results]
            console.print(json.dumps(out_data, indent=2, ensure_ascii=False))
        elif fmt in ("markdown", "md"):
            md_lines = [f"# Wyniki wyszukiwania dla: `{query}`\n"]
            for idx, r in enumerate(results, 1):
                md_lines.append(f"## {idx}. {r.title} (Score: {r.score:.4f})")
                md_lines.append(f"> Platforma: **{r.platform}** | Data: `{r.started_at}` | Projekt: `{r.project_path or '-'}`\n")
                if r.relative_path:
                    md_lines.append(f"> 📄 [doc/llm-archive/{r.relative_path}](doc/llm-archive/{r.relative_path})\n")
                md_lines.append(f"### {r.header_path}")
                md_lines.append(f"```text\n{r.chunk_text}\n```\n")
                md_lines.append("---\n")
            console.print("\n".join(md_lines))
        else:
            for idx, r in enumerate(results, 1):
                console.rule(f"[bold cyan]Wynik #{idx}: {r.title}[/bold cyan] (Score: {r.score:.4f})")
                console.print(f"[dim]Platforma: {r.platform} | Data: {r.started_at.strftime('%Y-%m-%d %H:%M')}[/dim]")
                if r.project_path:
                    console.print(f"[dim]Projekt: {r.project_path}[/dim]")
                if r.relative_path:
                    console.print(f"[blue]Plik: doc/llm-archive/{r.relative_path}[/blue]")
                console.print(f"\n[bold]{r.header_path}[/bold]")
                console.print(r.chunk_text[:500] + ("..." if len(r.chunk_text) > 500 else ""))
                console.print()

    asyncio.run(_do_search())


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host", "-h"),
    port: int = typer.Option(settings.API_PORT, "--port", "-p")
):
    """Uruchom serwer API (FastAPI) na potrzeby odbierania danych z wtyczki i demonów."""
    uvicorn.run("src.service.api:app", host=host, port=port, reload=True)


from ..importers import (
    OpenAIArchiveImporter,
    ClaudeArchiveImporter,
    GoogleTakeoutImporter,
    GenericJSONLImporter,
    ArchiveReconciler,
    TakeoutMasterImporter,
)


@app.command("extract-takeout")
def extract_takeout(
    path: Path = typer.Argument(
        Path("./takeout-extracted"),
        help="Katalog lub archiwum do rozpakowania"
    ),
    subfolder: bool = typer.Option(False, "--subfolder", help="Rozpakuj każde archiwum do dedykowanego podfolderu"),
    keep: bool = typer.Option(True, "--keep", help="Zachowaj archiwa po rozpakowaniu"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Tryb symulacji bez zapisu na dysku")
):
    """Bezpieczne, rekursywne rozpakowanie archiwów ZIP/TAR ze zrzutów Takeout."""
    from ..importers import ArchiveExtractor, extract_archive

    p = path.resolve()
    if not p.exists():
        console.print(f"[red]Ścieżka nie istnieje: {p}[/red]")
        raise typer.Exit(1)

    if p.is_file():
        dest = (p.parent / p.stem) if subfolder else p.parent
        console.print(f"[yellow]Rozpakowywanie pojedynczego archiwum: {p.name} -> {dest}...[/yellow]")
        f_cnt, b_cnt = extract_archive(p, dest, dry_run=dry_run)
        console.print(f"[bold green]Pomyślnie rozpakowano {f_cnt} plików ({b_cnt:,} B).[/bold green]")
        return

    console.print(f"[yellow]Skanowanie archiwów w: {p}...[/yellow]")
    res = ArchiveExtractor.extract_directory_archives(p, subfolder=subfolder, keep=keep, dry_run=dry_run)
    console.print(f"[bold green]Zakończono rozpakowywanie![/bold green]")
    console.print(f"  • Przetworzone archiwa: {res['archives_processed']}")
    console.print(f"  • Wypakowane pliki:     {res['files_extracted']}")
    console.print(f"  • Rozmiar:             {res['total_bytes']:,} B")


@app.command("import-takeout")
def import_takeout(
    path: Path = typer.Argument(
        Path("./takeout-extracted"),
        help="Ścieżka do katalogu lub archiwum ze zrzutami Takeout"
    ),
    platform: Optional[str] = typer.Option(None, "--platform", "-p", help="Filtruj do wybranej platformy (np. chatgpt, gemini, deepseek, claude, grok, perplexity)"),
    limit: Optional[int] = typer.Option(None, "--limit", "-n", help="Maksymalna liczba konwersacji na platformę"),
    concurrency: int = typer.Option(5, "--concurrency", "-c", help="Liczba równolegle przetwarzanych konwersacji"),
    force: bool = typer.Option(False, "--force", "-f", help="Wymuś reindeksację bez sprawdzania hash SHA256"),
    no_extract: bool = typer.Option(False, "--no-extract", help="Pomiń automatyczne rozpakowywanie archiwów .zip/.tar"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Tylko sparsuj i wyświetl podsumowanie bez zapisu"),
    sync_s3: bool = typer.Option(False, "--sync-s3", help="Po zaimportowaniu zsynchronizuj zrzuty i artefakty na S3 via s3cmd")
):
    """Zunifikowany, powtarzalny i idempotentny import wszystkich zrzutów z katalogu Takeout."""
    async def _do_takeout_import():
        if not path.exists():
            console.print(f"[red]Ścieżka nie istnieje: {path}[/red]")
            raise typer.Exit(1)

        importer = TakeoutMasterImporter(path, auto_extract=not no_extract)
        target_platforms = [platform] if platform else None

        console.print(f"[bold yellow]Rozpoczynam skanowanie i parsowanie katalogu:[/bold yellow] {path}")
        parsed_results = importer.parse_all(platforms=target_platforms, limit_per_platform=limit)

        if not parsed_results:
            console.print("[yellow]Nie znaleziono żadnych konwersacji w podanym katalogu.[/yellow]")
            return

        table = Table(title="Wykryte i Znormalizowane Konwersacje Takeout")
        table.add_column("Platforma", style="cyan bold")
        table.add_column("Liczba Konwersacji", justify="right", style="green")
        table.add_column("Liczba Wiadomości", justify="right", style="white")

        total_all_convs = 0
        total_all_msgs = 0
        for plat, convs in parsed_results.items():
            c_cnt = len(convs)
            m_cnt = sum(len(c.messages) for c in convs)
            total_all_convs += c_cnt
            total_all_msgs += m_cnt
            table.add_row(plat, f"{c_cnt:,}", f"{m_cnt:,}")

        table.add_section()
        table.add_row("RAZEM", f"{total_all_convs:,}", f"{total_all_msgs:,}")
        console.print(table)

        if dry_run:
            console.print("[bold yellow]Tryb dry-run: pomijam zapis do PostgreSQL i generowanie plików.[/bold yellow]")
            return

        db = Database()
        try:
            await db.connect()
            console.print(f"[green]Połączono z bazą PostgreSQL na {settings.DATABASE_URL}[/green]")
        except Exception as e:
            console.print(f"[yellow]Brak połączenia z PostgreSQL ({e}). Zapisuję tylko pliki Markdown.[/yellow]")
            db = None

        embedder = Embedder() if db else None
        reconciler = ArchiveReconciler(db=db, embedder=embedder)

        summary_table = Table(title="Podsumowanie Idempotentnego Importu")
        summary_table.add_column("Platforma", style="cyan bold")
        summary_table.add_column("Wszystkich", justify="right")
        summary_table.add_column("Zaimportowano", justify="right", style="green")
        summary_table.add_column("Zaktualizowano", justify="right", style="cyan")
        summary_table.add_column("Pominięto (identyczne)", justify="right", style="dim")
        summary_table.add_column("Błędy", justify="right", style="red")

        for plat, convs in parsed_results.items():
            status_text = f"[bold green]Reconciliation dla platformy: {plat}...[/bold green]"
            with console.status(status_text) as status:
                def _prog(curr, tot):
                    status.update(f"[bold green]Reconciliation {plat}: {curr}/{tot} ({(curr/tot*100):.1f}%)...[/bold green]")
                stats = await reconciler.import_conversations(
                    convs,
                    force_reindex=force,
                    concurrency=concurrency,
                    on_progress=_prog
                )
            summary_table.add_row(
                plat,
                f"{stats['total']:,}",
                f"{stats['imported']:,}",
                f"{stats['updated']:,}",
                f"{stats['skipped']:,}",
                f"{stats['failed']:,}"
            )

        if db:
            await db.close()

        console.print(summary_table)
        console.print("[bold green]Import i synchronizacja takeout zakończona sukcesem![/bold green]")

        if sync_s3:
            console.print("[cyan]Uruchamiam synchronizację Takeout z S3 (s3cmd sync)...[/cyan]")
            import subprocess
            s3_res = subprocess.run(["s3cmd", "sync", "--skip-existing", str(path) + "/", "s3://preciselab/takeout/"])
            if s3_res.returncode == 0:
                console.print("[bold green]Synchronizacja z S3 (s3://preciselab/takeout/) zakończona pomyślnie![/bold green]")
            else:
                console.print(f"[bold red]Błąd synchronizacji s3cmd: {s3_res.returncode}[/bold red]")

    asyncio.run(_do_takeout_import())


@app.command("sync-s3")
def sync_s3_command(
    takeout_dir: Path = typer.Option(
        Path("./takeout-extracted"),
        "--dir", "-d",
        help="Katalog ze zrzutami Takeout"
    ),
    s3_uri: str = typer.Option("s3://preciselab/takeout/", "--s3-uri", help="Docelowy URI w S3"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Tylko symuluj synchronizację bez przesyłania plików")
):
    """Zsynchronizuj zrzuty i artefakty Takeout na S3 (s3cmd sync)."""
    import subprocess
    if not takeout_dir.exists():
        console.print(f"[red]Katalog nie istnieje: {takeout_dir}[/red]")
        raise typer.Exit(1)

    cmd = ["s3cmd", "sync", "--skip-existing"]
    if dry_run:
        cmd.append("--dry-run")
    cmd.extend([str(takeout_dir) + "/", s3_uri])

    console.print(f"[bold cyan]Uruchamiam s3cmd sync:[/bold cyan] {' '.join(cmd)}")
    res = subprocess.run(cmd)
    if res.returncode == 0:
        console.print("[bold green]Synchronizacja z S3 zakończona sukcesem![/bold green]")
    else:
        console.print(f"[bold red]Błąd podczas synchronizacji s3cmd: kod {res.returncode}[/bold red]")
        raise typer.Exit(res.returncode)



@app.command("import-archive")
def import_archive(
    source_type: str = typer.Argument(..., help="Typ źródła: 'openai', 'claude', 'takeout', 'jsonl'"),
    archive_path: Path = typer.Argument(..., help="Ścieżka do pliku ZIP lub JSON/JSONL"),
    platform: Optional[str] = typer.Option(None, "--platform", "-p", help="Nazwa platformy (dla formatu generic jsonl)"),
    force: bool = typer.Option(False, "--force", "-f", help="Wymuś reindeksację bez względu na hash SHA256")
):
    """Importuj zrzuty GDPR (OpenAI, Claude, Google Takeout) z deduplikacją i reconciliacją."""
    async def _do_import():
        if not archive_path.exists():
            console.print(f"[red]Plik nie istnieje: {archive_path}[/red]")
            raise typer.Exit(1)

        source_norm = source_type.lower()
        if source_norm in ("openai", "chatgpt"):
            importer = OpenAIArchiveImporter()
        elif source_norm == "claude":
            importer = ClaudeArchiveImporter()
        elif source_norm in ("takeout", "gemini", "bard"):
            importer = GoogleTakeoutImporter()
        elif source_norm == "jsonl":
            importer = GenericJSONLImporter(platform=platform or "deepseek")
        else:
            console.print(f"[red]Nieznany typ źródła: {source_type}. Wybierz openai, claude, takeout lub jsonl.[/red]")
            raise typer.Exit(1)

        console.print(f"[yellow]Odczytuję i parsuję archiwum: {archive_path}...[/yellow]")
        try:
            conversations = importer.parse_archive(archive_path)
        except Exception as e:
            console.print(f"[red]Błąd parsowania archiwum: {e}[/red]")
            raise typer.Exit(1)

        console.print(f"[green]Odnaleziono {len(conversations)} konwersacji w archiwum.[/green]")
        if not conversations:
            return

        db = Database()
        try:
            await db.connect()
        except Exception as e:
            console.print(f"[yellow]Brak połączenia z PostgreSQL ({e}). Zapisuję tylko pliki Markdown.[/yellow]")
            db = None

        embedder = Embedder() if db else None
        reconciler = ArchiveReconciler(db=db, embedder=embedder)

        with console.status("[bold green]Trwa import i deduplikacja konwersacji...[/bold green]"):
            stats = await reconciler.import_conversations(conversations, force_reindex=force)

        if db:
            await db.close()

        console.print(f"[bold green]Zakończono import![/bold green]")
        console.print(f"  • Wszystkich: [bold]{stats['total']}[/bold]")
        console.print(f"  • Zaimportowano nowych: [green]{stats['imported']}[/green]")
        console.print(f"  • Zaktualizowano (zmiana treści): [cyan]{stats['updated']}[/cyan]")
        console.print(f"  • Pominięto (identyczny hash SHA256): [dim]{stats['skipped']}[/dim]")
        if stats.get("failed"):
            console.print(f"  • Błędy: [red]{stats['failed']}[/red]")

    asyncio.run(_do_import())



@app.command()
def stats():
    """Pokaż statystyki zindeksowanych konwersacji w bazie PostgreSQL."""
    async def _do_stats():
        db = Database()
        try:
            await db.connect()
        except Exception as e:
            console.print(f"[red]Brak połączenia z PostgreSQL ({e}).[/red]")
            return

        rows = await db.get_stats()
        await db.close()

        if not rows:
            console.print("[yellow]Brak danych w bazie wiedzy.[/yellow]")
            return

        table = Table(title="Statystyki Brain LLM Archive")
        table.add_column("Platforma", style="cyan bold")
        table.add_column("Konwersacje", justify="right", style="green")
        table.add_column("Wiadomości", justify="right", style="white")
        table.add_column("Chunki Wektorowe", justify="right", style="magenta")
        table.add_column("Ostatnia Synchronizacja", style="dim")

        total_convs = 0
        total_msgs = 0
        total_chunks = 0

        for r in rows:
            c = r["conversations"]
            m = r["messages"]
            ch = r["chunks"]
            total_convs += c
            total_msgs += m
            total_chunks += ch
            sync_str = r["last_sync"].strftime("%Y-%m-%d %H:%M") if r["last_sync"] else "brak"
            table.add_row(r["platform"], f"{c:,}", f"{m:,}", f"{ch:,}", sync_str)

        table.add_section()
        table.add_row("RAZEM", f"{total_convs:,}", f"{total_msgs:,}", f"{total_chunks:,}", "-")
        console.print(table)

    asyncio.run(_do_stats())


@app.command()
def export(
    format: str = typer.Option("json", "--format", "-f", help="Format wyjściowy: 'json', 'jsonl', 'md', 'markdown'"),
    query: Optional[str] = typer.Option(None, "--query", "-q", help="Opcjonalny filtr pojęciowy lub fraza w tytule"),
    platform: Optional[str] = typer.Option(None, "--platform", "-p", help="Filtruj po platformie"),
    after: Optional[str] = typer.Option(None, "--after", help="Filtruj po dacie od (YYYY-MM-DD lub ISO)"),
    limit: int = typer.Option(10, "--limit", "-l", help="Maksymalna liczba konwersacji do wyeksportowania"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Ścieżka do pliku lub katalogu wyjściowego")
):
    """Eksportuj konwersacje w formacie JSON, JSONL lub Markdown."""
    async def _do_export():
        from datetime import datetime, timezone
        db = Database()
        try:
            await db.connect()
        except Exception as e:
            console.print(f"[red]Brak połączenia z PostgreSQL ({e}).[/red]")
            return

        after_dt = None
        if after:
            try:
                after_dt = datetime.fromisoformat(after.replace("Z", "+00:00"))
                if after_dt.tzinfo is None:
                    after_dt = after_dt.replace(tzinfo=timezone.utc)
            except Exception:
                pass

        conversations = await db.list_conversations(
            platform=platform,
            after=after_dt,
            query=query,
            limit=limit
        )
        if not conversations:
            console.print("[yellow]Brak konwersacji do wyeksportowania.[/yellow]")
            await db.close()
            return

        export_data = []
        for c in conversations:
            full = await db.get_conversation_full(c["id"])
            if full:
                export_data.append(full)

        await db.close()

        fmt = format.lower()
        if fmt == "jsonl":
            out_str = "\n".join(json.dumps(item, ensure_ascii=False) for item in export_data)
        elif fmt == "json":
            out_str = json.dumps(export_data, indent=2, ensure_ascii=False)
        else:
            # Markdown export
            # If output is a directory (or has no file extension), save individual files
            if output and (output.is_dir() or not output.suffix):
                output.mkdir(parents=True, exist_ok=True)
                for item in export_data:
                    rel = item.get("relative_path") or f"{item['platform']}/{item['id']}.md"
                    target_file = output / rel
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    target_file.write_text(item.get("content_markdown") or f"# {item['title']}", encoding="utf-8")
                console.print(f"[bold green]Zapisano {len(export_data)} plików Markdown do katalogu:[/bold green] {output}")
                return
            else:
                out_parts = []
                for item in export_data:
                    out_parts.append(item.get("content_markdown") or f"# {item['title']}")
                    out_parts.append("\n\n---\n\n")
                out_str = "".join(out_parts)

        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(out_str, encoding="utf-8")
            console.print(f"[bold green]Zapisano eksport {len(export_data)} konwersacji do:[/bold green] {output}")
        else:
            print(out_str)

    asyncio.run(_do_export())


@app.command()
def reindex(
    platform: Optional[str] = typer.Option(None, "--platform", "-p", help="Filtruj reindeksację po platformie")
):
    """Przebuduj embeddingi wektorowe dla chunków konwersacji."""
    async def _do_reindex():
        db = Database()
        try:
            await db.connect()
        except Exception as e:
            console.print(f"[red]Brak połączenia z PostgreSQL ({e}).[/red]")
            return

        embedder = Embedder()
        async with db.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT c.id, c.text_content
                FROM llm_chunks c
                JOIN llm_conversations cv ON c.conversation_id = cv.id
                WHERE ($1::text IS NULL OR cv.platform = $1)
                ORDER BY c.id;
                """,
                platform
            )
            console.print(f"[yellow]Rozpoczynam reindeksację {len(rows)} chunków...[/yellow]")
            if rows:
                texts = [r["text_content"] for r in rows]
                embs = await embedder.embed_texts(texts)
                update_data = [(emb, r["id"]) for emb, r in zip(embs, rows)]
                await conn.executemany("UPDATE llm_chunks SET embedding = $1 WHERE id = $2;", update_data)

        await db.close()
        console.print(f"[bold green]Pomyślnie zreindeksowano {len(rows)} chunków.[/bold green]")

    asyncio.run(_do_reindex())


@app.command()
def mcp():
    """Uruchom serwer MCP (Model Context Protocol) na stdio."""
    from ..service.mcp_server import BrainArchiveMCPServer
    server = BrainArchiveMCPServer()
    asyncio.run(server.run_stdio())


@app.command()
def retitle(
    limit: int = typer.Option(10, "--limit", "-n", help="Liczba konwersacji do przetworzenia"),
    force: bool = typer.Option(False, "--force", "-f", help="Wymuś przeliczenie tytułów nawet dla świeżych sesji")
):
    """Przelicz i ulepsz tytuły starszych sesji (Claude Code, Antigravity) przez model LLM na ROG."""
    from ..service.auto_titler import AutoTitler

    async def _do_retitle():
        db = Database()
        await db.connect()
        if not db.pool:
            console.print("[bold red]Błąd: Nie można połączyć się z bazą PostgreSQL.[/bold red]")
            return

        titler = AutoTitler(db=db)
        console.print(f"[cyan]Uruchamianie auto-titlera (model: {titler.model})...[/cyan]")
        count = await titler.retitle_batch(batch_size=limit, force=force)
        await db.close()
        console.print(f"[bold green]Zakończono. Pomyślnie zaktualizowano tytuły dla {count} konwersacji.[/bold green]")

    asyncio.run(_do_retitle())


topics_app = typer.Typer(help="Emergent topics + graf podobieństwa (patrz docs/topics_knowledge_graph.md).")
app.add_typer(topics_app, name="topics")


@topics_app.command("recluster")
def topics_recluster(
    force_embeddings: bool = typer.Option(
        False, "--force-embeddings", help="Przelicz embeddingi dla WSZYSTKICH konwersacji, nie tylko brakujących (np. po backfillu summary)."
    ),
    min_cluster_size: int = typer.Option(5, "--min-cluster-size", help="Minimalna wielkość klastra dla HDBSCAN."),
    max_cluster_size: int = typer.Option(40, "--max-cluster-size", help="Klastry większe niż to są rekurencyjnie podklastrowane, żeby znaleźć podtematy zamiast jednego dużego worka."),
    match_threshold: float = typer.Option(0.85, "--match-threshold", help="Próg cosine similarity dopasowania nowego klastra do istniejącego tematu."),
):
    """Przelicz embeddingi konwersacji (title+summary) i przeklastruj tematy (HDBSCAN)."""
    async def _do_recluster():
        from ..topics import TopicClusterer

        db = Database()
        try:
            await db.connect()
        except Exception as e:
            console.print(f"[red]Brak połączenia z PostgreSQL ({e}).[/red]")
            return

        embedder = Embedder()
        clusterer = TopicClusterer(
            db, embedder,
            min_cluster_size=min_cluster_size,
            max_cluster_size=max_cluster_size,
            match_threshold=match_threshold,
        )

        with console.status("[bold green]Liczę brakujące embeddingi konwersacji...[/bold green]"):
            n_embedded = await clusterer.ensure_embeddings(force=force_embeddings)
        console.print(f"[green]Zaembedowano {n_embedded} konwersacji.[/green]")

        with console.status("[bold green]Klastruję (HDBSCAN)...[/bold green]"):
            stats = await clusterer.recluster()

        await db.close()

        table = Table(title="Wynik re-klastrowania")
        table.add_column("Metryka", style="cyan")
        table.add_column("Wartość", justify="right")
        for k, v in stats.items():
            table.add_row(k, str(v))
        console.print(table)

    asyncio.run(_do_recluster())


async def _resolve_one_topic(db: Database, name_or_id: str):
    import uuid as uuid_mod
    try:
        uuid_mod.UUID(name_or_id)
        return {"id": name_or_id, "name": name_or_id}
    except ValueError:
        pass
    matches = await db.find_topics_by_name(name_or_id)
    if not matches:
        console.print(f"[red]Brak tematu pasującego do '{name_or_id}'.[/red]")
        return None
    exact = [m for m in matches if m["name"] == name_or_id]
    if len(exact) == 1:
        return exact[0]
    if len(matches) > 1:
        console.print(f"[yellow]Wiele tematów pasuje do '{name_or_id}' - podaj UUID:[/yellow]")
        for m in matches:
            console.print(f"  {m['id']}  {m['name']}")
        return None
    return matches[0]


async def _resolve_one_conversation(db: Database, uuid_or_title_fragment: str):
    import uuid as uuid_mod
    try:
        uuid_mod.UUID(uuid_or_title_fragment)
        return {"id": uuid_or_title_fragment, "title": uuid_or_title_fragment}
    except ValueError:
        pass
    matches = await db.find_conversations_by_title(uuid_or_title_fragment)
    if not matches:
        console.print(f"[red]Brak konwersacji pasującej do '{uuid_or_title_fragment}'.[/red]")
        return None
    if len(matches) > 1:
        console.print(f"[yellow]Wiele konwersacji pasuje do '{uuid_or_title_fragment}' - podaj UUID:[/yellow]")
        for m in matches:
            console.print(f"  {m['id']}  [{m['platform']}] {m['title'][:70]}")
        return None
    return matches[0]


@topics_app.command("create")
def topics_create(
    name: str = typer.Argument(..., help="Nazwa nowego, ręcznego tematu."),
    description: Optional[str] = typer.Option(None, "--description", "-d"),
):
    """Stwórz nowy, ręczny temat - pusty, do samodzielnego przypinania konwersacji."""
    async def _do_create():
        from ..topics import TopicClusterer

        db = Database()
        try:
            await db.connect()
        except Exception as e:
            console.print(f"[red]Brak połączenia z PostgreSQL ({e}).[/red]")
            return
        clusterer = TopicClusterer(db, Embedder())
        topic_id = await clusterer.create_manual_topic(name, description=description)
        await db.close()
        console.print(f"[bold green]Utworzono temat '{name}'[/bold green] ({topic_id})")

    asyncio.run(_do_create())


@topics_app.command("assign")
def topics_assign(
    topic: str = typer.Argument(..., help="Nazwa tematu (albo UUID)."),
    conversation: str = typer.Argument(..., help="UUID konwersacji albo fragment tytułu."),
):
    """Przypnij konwersację do tematu ręcznie (source='manual', nigdy nie nadpisywane przez recluster)."""
    async def _do_assign():
        from ..topics import TopicClusterer

        db = Database()
        try:
            await db.connect()
        except Exception as e:
            console.print(f"[red]Brak połączenia z PostgreSQL ({e}).[/red]")
            return

        t = await _resolve_one_topic(db, topic)
        c = await _resolve_one_conversation(db, conversation)
        if not t or not c:
            await db.close()
            return

        clusterer = TopicClusterer(db, Embedder())
        await clusterer.assign(t["id"], c["id"])
        await db.close()
        console.print(f"[bold green]Przypięto[/bold green] '{c.get('title', c['id'])[:70]}' -> [bold]{t['name']}[/bold]")

    asyncio.run(_do_assign())


@topics_app.command("unassign")
def topics_unassign(
    topic: str = typer.Argument(..., help="Nazwa tematu (albo UUID)."),
    conversation: str = typer.Argument(..., help="UUID konwersacji albo fragment tytułu."),
):
    """Odczep konwersację od tematu."""
    async def _do_unassign():
        from ..topics import TopicClusterer

        db = Database()
        try:
            await db.connect()
        except Exception as e:
            console.print(f"[red]Brak połączenia z PostgreSQL ({e}).[/red]")
            return

        t = await _resolve_one_topic(db, topic)
        c = await _resolve_one_conversation(db, conversation)
        if not t or not c:
            await db.close()
            return

        clusterer = TopicClusterer(db, Embedder())
        removed = await clusterer.unassign(t["id"], c["id"])
        await db.close()
        if removed:
            console.print(f"[bold green]Odczepiono[/bold green] '{c.get('title', c['id'])[:70]}' od [bold]{t['name']}[/bold]")
        else:
            console.print("[yellow]Ta konwersacja nie była przypięta do tego tematu.[/yellow]")

    asyncio.run(_do_unassign())


@topics_app.command("suggest")
def topics_suggest(
    topic: str = typer.Argument(..., help="Nazwa tematu (albo UUID)."),
    limit: int = typer.Option(10, "--limit", "-l"),
):
    """Zasugeruj konwersacje podobne do tych już ręcznie przypiętych - nic nie przypisuje samo, tylko pokazuje."""
    async def _do_suggest():
        from ..topics import TopicClusterer

        db = Database()
        try:
            await db.connect()
        except Exception as e:
            console.print(f"[red]Brak połączenia z PostgreSQL ({e}).[/red]")
            return

        t = await _resolve_one_topic(db, topic)
        if not t:
            await db.close()
            return

        clusterer = TopicClusterer(db, Embedder())
        suggestions = await clusterer.suggest(t["id"], limit=limit)
        await db.close()

        if not suggestions:
            console.print("[yellow]Brak sugestii - temat jest pusty (przypnij coś najpierw) albo nic więcej nie jest podobne.[/yellow]")
            return

        table = Table(title=f"Sugestie dla: {t['name']}")
        table.add_column("Score", justify="right")
        table.add_column("Data", style="dim")
        table.add_column("Platforma", style="cyan")
        table.add_column("Tytuł")
        table.add_column("UUID", style="dim")
        for s in suggestions:
            table.add_row(f"{s['score']:.2f}", (s["started_at"] or "")[:10], s["platform"], s["title"][:60], s["id"])
        console.print(table)
        console.print(f"[dim]Zatwierdź: brain-llm topics assign \"{t['name']}\" <UUID>[/dim]")

    asyncio.run(_do_suggest())


@topics_app.command("show")
def topics_show(
    name: str = typer.Argument(..., help="Nazwa tematu (albo jej fragment) lub UUID tematu."),
    limit: int = typer.Option(200, "--limit", "-l", help="Maksymalna liczba konwersacji na temat."),
):
    """Pokaż konwersacje przypisane do tematu - odpowiedź na 'co tam właściwie jest w środku'."""
    async def _do_show():
        import uuid as uuid_mod

        db = Database()
        try:
            await db.connect()
        except Exception as e:
            console.print(f"[red]Brak połączenia z PostgreSQL ({e}).[/red]")
            return

        try:
            uuid_mod.UUID(name)
            topics = [{"id": name, "name": name, "description": None}]
        except ValueError:
            topics = await db.find_topics_by_name(name)

        if not topics:
            console.print(f"[yellow]Brak tematów pasujących do '{name}'.[/yellow]")
            await db.close()
            return

        for t in topics:
            convs = await db.get_topic_conversations(t["id"], limit=limit)
            title = f"{t['name']} ({len(convs)} konwersacji)"
            if len(topics) > 1:
                title += f" — {t['id']}"
            table = Table(title=title)
            table.add_column("Data", style="dim")
            table.add_column("Platforma", style="cyan")
            table.add_column("Tytuł")
            table.add_column("Score", justify="right")
            for c in convs:
                table.add_row(
                    (c["started_at"] or "")[:10] or "-",
                    c["platform"],
                    c["title"][:80],
                    f"{c['score']:.2f}",
                )
            console.print(table)
            if t.get("description"):
                console.print(f"[dim]{t['description']}[/dim]\n")

        await db.close()

    asyncio.run(_do_show())


@topics_app.command("describe")
def topics_describe(
    all_topics: bool = typer.Option(False, "--all", help="Przelicz opisy dla WSZYSTKICH tematów, nie tylko tych bez opisu."),
    sample_size: int = typer.Option(6, "--sample-size", help="Liczba konwersacji-przykładów na temat do zbudowania opisu."),
):
    """Wygeneruj opis + słowa kluczowe per temat z realnych wypowiedzi usera (głębszy sygnał niż same tytuły)."""
    async def _do_describe():
        from ..topics import TopicClusterer

        db = Database()
        try:
            await db.connect()
        except Exception as e:
            console.print(f"[red]Brak połączenia z PostgreSQL ({e}).[/red]")
            return

        clusterer = TopicClusterer(db, Embedder())
        with console.status("[bold green]Generuję opisy tematów...[/bold green]"):
            n = await clusterer.generate_descriptions(only_missing=not all_topics, sample_size=sample_size)
        await db.close()
        console.print(f"[bold green]Zaktualizowano opis+keywords dla {n} tematów.[/bold green]")

    asyncio.run(_do_describe())


@topics_app.command("merge-similar")
def topics_merge_similar(
    low_threshold: float = typer.Option(0.6, "--low-threshold", help="Dolna granica cosine similarity centroidów, od której warto zapytać LLM."),
    high_threshold: Optional[float] = typer.Option(None, "--high-threshold", help="Górna granica (domyślnie: --match-threshold z recluster, powyżej tego już scalone przy tworzeniu)."),
):
    """Dla par tematów w 'szarej zonie' podobieństwa, zapytaj LLM (na opisie+keywords) czy to ten sam temat, i scal jeśli tak."""
    async def _do_merge():
        from ..topics import TopicClusterer

        db = Database()
        try:
            await db.connect()
        except Exception as e:
            console.print(f"[red]Brak połączenia z PostgreSQL ({e}).[/red]")
            return

        clusterer = TopicClusterer(db, Embedder())
        with console.status("[bold green]Szukam i oceniam kandydatów do scalenia...[/bold green]"):
            n = await clusterer.merge_similar_topics(low_threshold=low_threshold, high_threshold=high_threshold)
        await db.close()
        console.print(f"[bold green]Scalono {n} par tematów.[/bold green]")

    asyncio.run(_do_merge())


@topics_app.command("export-links")
def topics_export_links(
    top_k: int = typer.Option(5, "--top-k", help="Liczba najbliższych sąsiadów per konwersacja."),
    min_score: float = typer.Option(0.75, "--min-score", help="Minimalny cosine similarity, żeby uznać krawędź."),
    markdown_root: Optional[Path] = typer.Option(None, "--markdown-root", help="Katalog z eksportowanym markdownem (domyślnie MARKDOWN_EXPORT_DIR)."),
):
    """Policz krawędzie podobieństwa i wstrzyknij [[wikilinki]] do markdownu (graf w Obsidianie za darmo)."""
    async def _do_export_links():
        from ..topics import TopicClusterer

        db = Database()
        try:
            await db.connect()
        except Exception as e:
            console.print(f"[red]Brak połączenia z PostgreSQL ({e}).[/red]")
            return

        embedder = Embedder()
        clusterer = TopicClusterer(db, embedder, top_k_neighbors=top_k, similarity_threshold=min_score)

        with console.status("[bold green]Liczę krawędzie podobieństwa (kNN)...[/bold green]"):
            n_edges = await clusterer.export_similarity_edges()
        console.print(f"[green]Zapisano {n_edges} krawędzi podobieństwa.[/green]")

        root = markdown_root or settings.MARKDOWN_EXPORT_DIR
        with console.status(f"[bold green]Wstrzykuję linki do markdownu w {root}...[/bold green]"):
            n_updated = await clusterer.export_similarity_links_to_markdown(root)
        await db.close()

        console.print(f"[bold green]Zaktualizowano {n_updated} plików Markdown z sekcją Related.[/bold green]")

    asyncio.run(_do_export_links())


@topics_app.command("export-hub-docs")
def topics_export_hub_docs(
    markdown_root: Optional[Path] = typer.Option(None, "--markdown-root", help="Katalog z eksportowanym markdownem (domyślnie MARKDOWN_EXPORT_DIR)."),
):
    """Wygeneruj/odśwież dokumenty-huby tematów w _topics/ - nazwa, keywords jako #tagi, cross-linki po wspólnych keywords, linki do konwersacji."""
    async def _do_export_hub_docs():
        from ..topics import TopicClusterer

        db = Database()
        try:
            await db.connect()
        except Exception as e:
            console.print(f"[red]Brak połączenia z PostgreSQL ({e}).[/red]")
            return

        clusterer = TopicClusterer(db, Embedder())
        root = markdown_root or settings.MARKDOWN_EXPORT_DIR
        with console.status(f"[bold green]Generuję dokumenty-huby tematów w {root}/_topics...[/bold green]"):
            n = await clusterer.export_hub_docs(root)
        await db.close()
        console.print(f"[bold green]Zaktualizowano {n} dokumentów-hubów tematów.[/bold green]")

    asyncio.run(_do_export_hub_docs())


if __name__ == "__main__":
    app()
