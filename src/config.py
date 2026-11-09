import os
from pathlib import Path


# Detect workspace root
DEFAULT_WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_DOC_ARCHIVE = DEFAULT_WORKSPACE_ROOT / "doc" / "llm-archive"

class Settings:
    def __init__(self):
        # Check for config file: ~/.config/brain-llm/config.toml
        toml_conf = {}
        config_path = Path.home() / ".config" / "brain-llm" / "config.toml"
        if config_path.is_file():
            try:
                import tomllib
                with open(config_path, "rb") as f:
                    toml_conf = tomllib.load(f)
            except Exception:
                pass

        # Database
        self.DATABASE_URL: str = os.getenv(
            "DATABASE_URL",
            toml_conf.get("database_url", "postgresql://postgres:postgres@localhost:5432/brain_knowledge")
        )

        # Local paths
        self.WORKSPACE_ROOT: Path = Path(os.getenv("WORKSPACE_ROOT", toml_conf.get("workspace_root", str(DEFAULT_WORKSPACE_ROOT))))
        self.MARKDOWN_EXPORT_DIR: Path = Path(os.getenv("MARKDOWN_EXPORT_DIR", toml_conf.get("markdown_export_dir", str(DEFAULT_DOC_ARCHIVE))))
        self.OFFLINE_DB_PATH: Path = Path(os.getenv(
            "OFFLINE_DB_PATH", 
            toml_conf.get("offline_db_path", str(Path.home() / ".local" / "share" / "brain-llm" / "sync_buffer.db"))
        ))
        
        # Local agent directories
        self.CLAUDE_HOME: Path = Path(os.getenv("CLAUDE_HOME", toml_conf.get("claude_home", str(Path.home() / ".claude"))))
        self.ANTIGRAVITY_HOME: Path = Path(os.getenv(
            "ANTIGRAVITY_HOME",
            toml_conf.get("antigravity_home", str(Path.home() / ".gemini" / "antigravity-ide"))
        ))
        # Antigravity ships in several flavours (IDE, CLI, ...), each with its
        # own ~/.gemini/antigravity* home but the same brain/<id>/.system_generated
        # transcript layout. Watch every flavour that exists, not just the IDE
        # one, or CLI sessions never get ingested. ANTIGRAVITY_HOME stays first
        # so an explicit override still wins.
        _agy_candidates = [
            self.ANTIGRAVITY_HOME,
            Path.home() / ".gemini" / "antigravity-ide",
            Path.home() / ".gemini" / "antigravity-cli",
            Path.home() / ".gemini" / "antigravity",
        ]
        _agy_seen: set[Path] = set()
        self.ANTIGRAVITY_HOMES: list[Path] = []
        for _p in _agy_candidates:
            if _p not in _agy_seen and _p.is_dir():
                _agy_seen.add(_p)
                self.ANTIGRAVITY_HOMES.append(_p)
        if not self.ANTIGRAVITY_HOMES:
            self.ANTIGRAVITY_HOMES = [self.ANTIGRAVITY_HOME]
        cline_candidates = [
            Path.home() / ".cline" / "data" / "sessions",
            Path.home() / ".cline" / "data",
            Path.home() / ".config" / "Code - OSS" / "User" / "globalStorage" / "saoudrizwan.claude-dev",
            Path.home() / ".config" / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev",
            Path.home() / "Library" / "Application Support" / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev",
            Path.home() / ".config" / "Cursor" / "User" / "globalStorage" / "saoudrizwan.claude-dev",
            Path.home() / ".config" / "VSCodium" / "User" / "globalStorage" / "saoudrizwan.claude-dev",
        ]
        self.CLINE_HOMES: list[Path] = [p for p in cline_candidates if p.is_dir()]
        self.CLINE_HOME: Path = Path(os.getenv(
            "CLINE_HOME",
            toml_conf.get("cline_home", str(self.CLINE_HOMES[0] if self.CLINE_HOMES else cline_candidates[0]))
        ))

        # OpenCode, Aider, OMP, Zed, Hermes
        self.OPENCODE_DB: Path = Path(os.getenv("OPENCODE_DB", toml_conf.get("opencode_db", str(Path.home() / ".local" / "share" / "opencode" / "opencode.db"))))
        self.AIDER_HOME: Path = Path(os.getenv("AIDER_HOME", toml_conf.get("aider_home", str(Path.home() / ".aider"))))
        self.OMP_HOME: Path = Path(os.getenv("OMP_HOME", toml_conf.get("omp_home", str(Path.home() / ".omp"))))
        self.ZED_DB: Path = Path(os.getenv("ZED_DB", toml_conf.get("zed_db", str(Path.home() / ".local" / "share" / "zed" / "threads" / "threads.db"))))
        self.CODEX_HOME: Path = Path(os.getenv("CODEX_HOME", toml_conf.get("codex_home", str(Path.home() / ".codex"))))
        self.HERMES_DB: Path = Path(os.getenv("HERMES_DB", toml_conf.get("hermes_db", str(Path.home() / ".hermes" / "state.db"))))

        # Embedding & search
        self.EMBEDDING_PROVIDER: str = os.getenv("EMBEDDING_PROVIDER", toml_conf.get("embedding_provider", "ollama"))
        self.OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", toml_conf.get("ollama_base_url", "http://localhost:11434"))
        self.OLLAMA_FALLBACK_URLS: list[str] = [
            u.strip() for u in os.getenv(
                "OLLAMA_FALLBACK_URLS",
                toml_conf.get("ollama_fallback_urls", "")
            ).split(",") if u.strip()
        ]
        self.OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", toml_conf.get("ollama_model", "bge-m3"))
        self.OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", toml_conf.get("openai_api_key", ""))
        self.OPENAI_EMBEDDING_MODEL: str = os.getenv("OPENAI_EMBEDDING_MODEL", toml_conf.get("openai_embedding_model", "text-embedding-3-small"))
        self.EMBEDDING_DIM: int = int(os.getenv("EMBEDDING_DIM", str(toml_conf.get("embedding_dim", 1024))))

        # Tailscale / Service settings
        self.API_PORT: int = int(os.getenv("API_PORT", str(toml_conf.get("api_port", 8080))))
        self.DEVICE_NAME: str = os.getenv("DEVICE_NAME", toml_conf.get("device_name", os.uname().nodename))

        # Auto-Titler settings
        self.ENABLE_AUTO_TITLER: bool = os.getenv("ENABLE_AUTO_TITLER", "true").lower() in ("true", "1", "yes")
        self.TITLER_MODEL: str = os.getenv("TITLER_MODEL", toml_conf.get("titler_model", "qwen2.5:7b"))
        self.TITLER_INTERVAL: int = int(os.getenv("TITLER_INTERVAL", str(toml_conf.get("titler_interval", 600))))

    def get_default_ollama_urls(self) -> list[str]:
        """Returns prioritized candidate Ollama endpoints."""
        env_urls = os.getenv("OLLAMA_FALLBACK_URLS")
        if env_urls:
            return [u.strip() for u in env_urls.split(",") if u.strip()]
        return ["http://127.0.0.1:11434"]


settings = Settings()
