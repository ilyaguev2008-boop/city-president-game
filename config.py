from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    bot_token: str
    openai_api_key: str
    openai_base_url: str
    openai_model: str
    poll_interval_sec: int


def _load_dotenv_if_exists(path: Path) -> None:
    if not path.exists() or not path.is_file():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


def load_settings() -> Settings:
    _load_dotenv_if_exists(Path(__file__).with_name(".env"))

    token = os.getenv("BOT_TOKEN", "").strip()
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    openai_base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com").strip()
    openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
    poll_raw = os.getenv("POLL_INTERVAL_SEC", "300").strip()
    try:
        poll_interval_sec = max(60, int(poll_raw))
    except ValueError:
        poll_interval_sec = 300

    if not token:
        raise RuntimeError(
            "BOT_TOKEN is not set. Создай .env рядом с bot.py/config.py "
            "и добавь строку BOT_TOKEN=123:ABC..."
        )

    return Settings(
        bot_token=token,
        openai_api_key=openai_api_key,
        openai_base_url=openai_base_url or "https://api.openai.com",
        openai_model=openai_model or "gpt-4o-mini",
        poll_interval_sec=poll_interval_sec,
    )
