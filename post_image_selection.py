"""
Отбор 1–2 иллюстраций к посту: качество URL, смысловое соответствие через ИИ,
опционально — поиск изображений в интернете (DuckDuckGo).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from article_images import extract_image_urls_from_html_fragment, fetch_article_image_urls
from rss_entries import FeedItem

logger = logging.getLogger(__name__)

# Похоже на мелкий превью / иконку
_BAD_SUBSTR = (
    "thumb",
    "thumbnail",
    "thumbs/",
    "/icons/",
    "favicon",
    "1x1",
    "spacer",
    "pixel.gif",
    "emoji",
    "sprite",
    "avatar-48",
    "-50x",
    "50x50",
    "32x32",
    "24x24",
    "gravatar",
    "doubleclick",
    "adsystem",
)
# Высокое разрешение / главное фото
_GOOD_SUBSTR = (
    "1200",
    "1280",
    "1600",
    "1920",
    "2048",
    "large",
    "xlarge",
    "full",
    "original",
    "hero",
    "featured",
    "og-image",
    "wp-content/uploads",
    "high",
)


def score_image_url_quality(url: str) -> float:
    """Эвристика «качества» по строке URL (без скачивания файла)."""
    if not url or not url.startswith(("http://", "https://")):
        return -100.0
    low = url.lower()
    s = 0.0
    for b in _BAD_SUBSTR:
        if b in low:
            s -= 12.0
    for g in _GOOD_SUBSTR:
        if g in low:
            s += 6.0
    # Размеры в пути: ...-800x600... или w=800
    m = re.search(r"(\d{3,4})x(\d{3,4})", low)
    if m:
        w, h = int(m.group(1)), int(m.group(2))
        if w >= 600 and h >= 400:
            s += 15.0
        elif w >= 400:
            s += 8.0
        elif w < 200:
            s -= 10.0
    m2 = re.search(r"[?&]w=(\d{3,4})", low)
    if m2:
        w = int(m2.group(1))
        if w >= 800:
            s += 10.0
        elif w >= 500:
            s += 5.0
    if low.endswith((".svg", ".gif")):
        s -= 5.0
    if ".jpg" in low or ".jpeg" in low or ".webp" in low:
        s += 2.0
    return s


def dedupe_sort_candidates(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for u in urls:
        u = (u or "").strip()
        if not u or u in seen:
            continue
        seen.add(u)
        unique.append(u)
    unique.sort(key=score_image_url_quality, reverse=True)
    return unique


def collect_candidate_image_urls(item: FeedItem, *, max_collect: int = 28) -> list[str]:
    """Собирает кандидатов из HTML ленты, enclosure и страницы статьи."""
    seen: set[str] = set()
    out: list[str] = []
    base = (item.link or "").strip() or "https://example.com/"

    if item.body_text and (
        "<img" in item.body_text or "srcset=" in item.body_text.lower()
    ):
        try:
            for u in extract_image_urls_from_html_fragment(
                item.body_text, base, max_images=14
            ):
                if u not in seen:
                    seen.add(u)
                    out.append(u)
                    if len(out) >= max_collect:
                        return out
        except Exception:
            logger.debug("extract RSS html images failed", exc_info=True)

    if item.image_url:
        u = item.image_url.strip()
        if u.startswith(("http://", "https://")) and u not in seen:
            seen.add(u)
            out.append(u)

    if item.link:
        try:
            for u in fetch_article_image_urls(item.link, max_images=20):
                if u not in seen:
                    seen.add(u)
                    out.append(u)
                    if len(out) >= max_collect:
                        break
        except Exception:
            logger.debug("fetch_article_image_urls failed", exc_info=True)

    return out[:max_collect]


async def select_image_indices_with_llm(
    *,
    api_key: str,
    base_url: str,
    model: str,
    title: str,
    post_text: str,
    numbered_urls: list[tuple[int, str]],
    max_pick: int,
) -> list[int]:
    """
    ИИ выбирает индексы из переданного списка (только они допустимы).
    """
    from ai_service import complete_chat

    lines = [f"{i}. {url}" for i, url in numbered_urls[:22]]
    block = "\n".join(lines)
    system = (
        "Ты редактор иллюстраций к новости для Telegram-канала.\n"
        "По заголовку и тексту поста выбери номера изображений из списка, которые лучше всего "
        "иллюстрируют суть: главный герой, ключевое событие, важная деталь сюжета.\n"
        "Не выбирай логотипы, пустые декоративные фото, баннеры рекламы, мелкие иконки, если есть смысловое фото.\n"
        "Если все варианты мусорные — верни пустой массив.\n"
        "Ответ строго одним JSON-объектом без markdown: "
        '{"indices":[числа], "brief":"одно короткое предложение на русском"}'
    )
    user = (
        f"Заголовок: {title}\n\nТекст поста:\n{post_text[:6000]}\n\n"
        f"Список URL изображений (номер — позиция, выбирай не больше {max_pick}):\n{block}"
    )
    raw = await complete_chat(
        api_key=api_key,
        base_url=base_url,
        model=model,
        user_text=user,
        timeout_sec=60,
        system_prompt=system,
    )
    idx_list = _parse_indices_json(raw, max_pick=max_pick)
    valid = {i for i, _ in numbered_urls}
    return [i for i in idx_list if i in valid][:max_pick]


def _parse_indices_json(raw: str, *, max_pick: int) -> list[int]:
    raw = (raw or "").strip()
    if not raw:
        return []
    # Вырезать JSON из ответа
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("ИИ: не JSON в ответе выбора картинок: %s", raw[:200])
        return []
    indices = data.get("indices") if isinstance(data, dict) else None
    if not isinstance(indices, list):
        return []
    out: list[int] = []
    for x in indices:
        if isinstance(x, int):
            out.append(x)
        elif isinstance(x, float) and x == int(x):
            out.append(int(x))
        if len(out) >= max_pick:
            break
    return out


async def suggest_web_image_search_query(
    *,
    api_key: str,
    base_url: str,
    model: str,
    title: str,
    post_text: str,
) -> str | None:
    """Короткий запрос для поиска фото в интернете (имя, событие)."""
    from ai_service import complete_chat

    system = (
        "Сформируй одну короткую строку поиска картинок в интернете по сути новости "
        "(имя человека + роль/контекст, или название события + место). "
        "Латиница или кириллица — как уместнее для поиска. "
        "Без кавычек. Не больше 100 символов. "
        "Если для иллюстрации нет конкретного объекта — верни пустую строку в JSON: "
        '{"q":""}'
    )
    user = f"Заголовок:\n{title}\n\nТекст:\n{post_text[:4000]}"
    raw = await complete_chat(
        api_key=api_key,
        base_url=base_url,
        model=model,
        user_text=user,
        timeout_sec=40,
        system_prompt=system,
    )
    raw = (raw or "").strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    try:
        data = json.loads(raw)
        q = data.get("q") if isinstance(data, dict) else None
        if isinstance(q, str):
            q = q.strip()
            return q[:120] if q else None
    except json.JSONDecodeError:
        pass
    return None


async def duckduckgo_image_urls(query: str, *, max_results: int = 4) -> list[str]:
    """Поиск изображений через duckduckgo-search (опциональная зависимость)."""
    if not query or len(query) < 2:
        return []

    def _run() -> list[str]:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            logger.debug("duckduckgo-search не установлен — веб-поиск картинок отключён")
            return []
        out: list[str] = []
        try:
            with DDGS() as ddgs:
                for r in ddgs.images(query, max_results=max_results):
                    u = (r.get("image") or "").strip()
                    if u.startswith(("http://", "https://")):
                        out.append(u)
        except Exception:
            logger.debug("DDG images failed for %s", query[:80], exc_info=True)
        return out

    return await asyncio.to_thread(_run)


async def resolve_final_image_urls(
    item: FeedItem,
    *,
    post_title: str,
    post_body: str,
    api_key: str | None,
    base_url: str,
    model: str,
    max_images: int,
    use_llm_selection: bool,
    web_fallback: bool,
) -> list[str]:
    """
    Итог: 0..max_images URL для отправки в Telegram.
    """
    raw = collect_candidate_image_urls(item)
    ranked = dedupe_sort_candidates(raw)
    if not ranked:
        if web_fallback and api_key:
            q = await suggest_web_image_search_query(
                api_key=api_key,
                base_url=base_url,
                model=model,
                title=post_title,
                post_text=post_body,
            )
            if q:
                web = await duckduckgo_image_urls(q, max_results=max_images)
                return dedupe_sort_candidates(web)[:max_images]
        return []

    top = ranked[:20]
    if use_llm_selection and api_key:
        numbered = list(enumerate(top, start=1))
        try:
            picked = await select_image_indices_with_llm(
                api_key=api_key,
                base_url=base_url,
                model=model,
                title=post_title,
                post_text=post_body,
                numbered_urls=numbered,
                max_pick=max_images,
            )
            chosen = [top[i - 1] for i in picked if 1 <= i <= len(top)]
            if chosen:
                return chosen[:max_images]
        except Exception:
            logger.warning("ИИ-отбор картинок не удался, берём эвристику", exc_info=True)

    # Без ИИ или сбой — лучшие по эвристике
    fallback = top[:max_images]
    if len(fallback) < max_images and web_fallback and api_key:
        q = await suggest_web_image_search_query(
            api_key=api_key,
            base_url=base_url,
            model=model,
            title=post_title,
            post_text=post_body,
        )
        if q:
            web = await duckduckgo_image_urls(q, max_results=max_images)
            merged = dedupe_sort_candidates(fallback + web)
            return merged[:max_images]
    return fallback
