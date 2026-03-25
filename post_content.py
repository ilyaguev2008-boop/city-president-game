"""
Сборка текста и URL картинок для поста (канал и черновик) — одна логика с post_worker.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ai_service import rewrite_news_ru
from config import Settings
from post_image_selection import resolve_final_image_urls
from rss_entries import FeedItem
from text_utils import normalize_cyrillic_news_prose, sanitize_post_text, strip_llm_artifacts, strip_urls

logger = logging.getLogger(__name__)


@dataclass
class BuiltPost:
    """Готовые данные для отправки в канал или предпросмотра в черновике."""

    rewritten: str
    ai_note: str
    text: str
    body_for_images: str
    image_urls: list[str]


async def build_feed_post_content(
    item: FeedItem,
    settings: Settings,
    *,
    send_images: bool,
    polish_english: bool,
) -> BuiltPost:
    """
    Пересказ + картинки. Без проверки дубликатов и прав канала.
    """
    if not (settings.openai_api_key or "").strip():
        if settings.openai_fallback_plain_text:
            rewritten = f"{item.title}\n\n{item.body_text}"
            ai_note = "⚠️ Нет OPENAI_API_KEY — публикуется текст из ленты без пересказа.\n\n"
        else:
            raise RuntimeError("Нет OPENAI_API_KEY и OPENAI_FALLBACK_PLAIN_TEXT=0")
    else:
        ai_note = ""
        try:
            rewritten = await rewrite_news_ru(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                model=settings.openai_model,
                title=item.title,
                body=item.body_text,
                polish_english_translation=polish_english,
            )
        except Exception as exc:
            if settings.openai_fallback_plain_text:
                logger.warning("ИИ пересказа недоступен: %s", exc)
                rewritten = f"{item.title}\n\n{item.body_text}"
                ai_note = (
                    "⚠️ Пересказ ИИ недоступен — текст из ленты.\n"
                    f"Причина: {str(exc)[:300]}\n\n"
                )
            else:
                raise

    text = sanitize_post_text(strip_urls(ai_note + rewritten))
    if not text.strip():
        text = sanitize_post_text(strip_urls(f"{item.title}\n\n{item.body_text}"))
    text = normalize_cyrillic_news_prose(text)
    text = strip_llm_artifacts(text)

    body_for_images = strip_llm_artifacts(
        normalize_cyrillic_news_prose(sanitize_post_text(strip_urls(rewritten)))
    )[:8000]

    image_urls: list[str] = []
    if send_images:
        api_key = (settings.openai_api_key or "").strip() or None
        image_urls = await resolve_final_image_urls(
            item,
            post_title=(item.title or "").strip(),
            post_body=body_for_images,
            api_key=api_key,
            base_url=settings.openai_base_url,
            model=settings.openai_model,
            max_images=settings.post_max_images,
            use_llm_selection=settings.post_image_llm_selection and bool(api_key),
            web_fallback=settings.image_web_duckduckgo_fallback,
            web_if_no_site_images=settings.image_web_if_no_site_images,
            semantic_only=settings.post_image_semantic_only,
            site_only=settings.post_image_site_only,
            web_after_ai_rejects_site=settings.post_image_web_after_ai_rejects_site,
        )

    return BuiltPost(
        rewritten=rewritten,
        ai_note=ai_note,
        text=text,
        body_for_images=body_for_images,
        image_urls=image_urls,
    )
