"""Configuration loading. All secrets come from environment / .env, never hardcoded."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env loader (no external dependency).

    Existing environment variables win, so `--dry-run` style overrides from the
    shell are never clobbered by a file on disk.
    """
    env_path = path or PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export ") :].strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ[key] = value


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "y", "on")


def _int(value: str | None, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _mids(value: str | None) -> list[int]:
    result: list[int] = []
    for part in (value or "").replace(" ", "").split(","):
        if not part:
            continue
        try:
            result.append(int(part))
        except ValueError:
            continue
    return result


@dataclass
class Settings:
    root: Path = PROJECT_ROOT
    data_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data")
    out_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "out")
    work_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "work")
    logs_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "logs")

    sessdata: str = ""
    bili_jct: str = ""
    dedeuserid: str = ""
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    # OpenAI-compatible multimodal endpoint (DeepSeek V4.1 Flash by default).
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-flash"

    # ego = drive the logged-in browser; api = legacy cookie + wbi path.
    delivery: str = "ego"
    ego_bin: str = ""
    bot_uname: str = ""

    allow_mids: list[int] = field(default_factory=list)
    daily_limit: int = 3
    poll_interval: int = 600
    max_duration_min: int = 30
    max_retries: int = 2
    frame_count: int = 12
    max_height: int = 480

    @property
    def db_path(self) -> Path:
        return self.data_dir / "bili_note.db"

    @property
    def card_path(self) -> Path:
        return self.out_dir / "card.png"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.out_dir, self.work_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)

    def has_cookie(self) -> bool:
        return bool(self.sessdata)

    def has_sender(self) -> bool:
        return bool(self.sessdata and self.bili_jct and self.dedeuserid)

    @property
    def use_ego(self) -> bool:
        return self.delivery != "api"

    def require_llm(self) -> bool:
        return bool(self.llm_api_key)


def load_settings() -> Settings:
    load_dotenv()
    s = Settings()
    s.sessdata = os.environ.get("SESSDATA", "").strip()
    s.bili_jct = os.environ.get("BILI_JCT", "").strip()
    s.dedeuserid = os.environ.get("DEDEUSERID", "").strip()
    s.user_agent = os.environ.get("BILI_USER_AGENT", s.user_agent).strip()

    s.llm_base_url = (os.environ.get("LLM_BASE_URL", "").strip()
                      or "https://api.deepseek.com/v1").rstrip("/")
    s.llm_api_key = os.environ.get("LLM_API_KEY", "").strip()
    s.llm_model = os.environ.get("LLM_MODEL", "").strip() or "deepseek-flash"
    s.delivery = (os.environ.get("DELIVERY", "").strip() or "ego").lower()
    s.ego_bin = os.environ.get("EGO_BIN", "").strip()
    s.bot_uname = os.environ.get("BOT_UNAME", "").strip()

    s.allow_mids = _mids(os.environ.get("ALLOW_MIDS"))
    s.daily_limit = _int(os.environ.get("DAILY_LIMIT"), 3)
    s.poll_interval = _int(os.environ.get("POLL_INTERVAL"), 600)
    s.max_duration_min = _int(os.environ.get("MAX_DURATION_MIN"), 30)
    s.max_retries = max(0, min(_int(os.environ.get("MAX_RETRIES"), 2), 2))
    s.frame_count = max(10, min(_int(os.environ.get("FRAME_COUNT"), 12), 12))

    if os.environ.get("BILI_NOTE_DATA_DIR"):
        s.data_dir = Path(os.environ["BILI_NOTE_DATA_DIR"]).expanduser()
        s.out_dir = s.data_dir / "out"
        s.work_dir = s.data_dir / "work"
        s.logs_dir = s.data_dir / "logs"
    return s
