from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    bot_token: str
    openai_api_key: str
    openai_base_url: str
    openai_model: str
    poll_interval_sec: int
    rss_monitor_interval_sec: int
    # Если False — в канал ничего не уходит без кнопки «Опубликовать» в черновиках (даже если в БД стоит «авто»).
    allow_auto_posting: bool
    # Если ИИ недоступен — публиковать заголовок+текст из ленты без пересказа (иначе пост не уйдёт).
    openai_fallback_plain_text: bool
    # Сколько фото в одном посте (Telegram: разумно 1–2).
    post_max_images: int
    # Отбор релевантных картинок по смыслу поста (нужен OPENAI_API_KEY).
    post_image_llm_selection: bool
    # Если на сайте мало подходящих — добрать через DuckDuckGo (пакет duckduckgo-search).
    image_web_duckduckgo_fallback: bool


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

    mon_raw = os.getenv("RSS_MONITOR_INTERVAL_SEC", "90").strip()
    try:
        rss_monitor_interval_sec = max(30, int(mon_raw))
    except ValueError:
        rss_monitor_interval_sec = 90

    allow_auto = os.getenv("ALLOW_AUTO_POSTING", "0").strip().lower() in ("1", "true", "yes", "on")

    # По умолчанию вкл.: иначе любой сбой API останавливает публикацию.
    fb_raw = os.getenv("OPENAI_FALLBACK_PLAIN_TEXT", "1").strip().lower()
    openai_fallback_plain_text = fb_raw in ("1", "true", "yes", "on")

    pm_raw = os.getenv("POST_MAX_IMAGES", "2").strip()
    try:
        post_max_images = max(1, min(10, int(pm_raw)))
    except ValueError:
        post_max_images = 2

    pil_raw = os.getenv("POST_IMAGE_LLM_SELECTION", "1").strip().lower()
    post_image_llm_selection = pil_raw in ("1", "true", "yes", "on")

    img_web_raw = os.getenv("IMAGE_WEB_DUCKDUCKGO_FALLBACK", "0").strip().lower()
    image_web_duckduckgo_fallback = img_web_raw in ("1", "true", "yes", "on")

    if not token:
        raise RuntimeError(
            "BOT_TOKEN is not set. Создай .env рядом с bot.py/config.py "
                "и добавь строку BOT_TOKEN=123:ABC..."
        )

    if openai_api_key and "api.openai.com" in (openai_base_url or "").lower():
        if not openai_api_key.startswith("sk-"):
            logger.warning(
                "OPENAI_API_KEY для platform.openai.com обычно начинается с sk- . "
                "Проверь ключ: https://platform.openai.com/api-keys"
            )

    return Settings(
        bot_token=token,
        openai_api_key=openai_api_key,
        openai_base_url=openai_base_url or "https://api.openai.com",
        openai_model=openai_model or "gpt-4o-mini",
        poll_interval_sec=poll_interval_sec,
        rss_monitor_interval_sec=rss_monitor_interval_sec,
        allow_auto_posting=allow_auto,
        openai_fallback_plain_text=openai_fallback_plain_text,
        post_max_images=post_max_images,
        post_image_llm_selection=post_image_llm_selection,
        image_web_duckduckgo_fallback=image_web_duckduckgo_fallback,
    )
