"""
Отбор 1–2 иллюстраций к посту: качество URL, смысловое соответствие через ИИ,
опционально — поиск изображений в интернете (DuckDuckGo).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from article_images import extract_image_urls_from_html_fragment, fetch_article_image_urls
from rss_entries import FeedItem

logger = logging.getLogger(__name__)


def _read_min_short_side_px() -> int:
    try:
        v = int(os.getenv("POST_MIN_IMAGE_SHORT_SIDE", "720").strip())
        return max(320, min(4096, v))
    except ValueError:
        return 720


# Минимум «как 720p»: меньшая сторона кадра не ниже N px (по умолчанию 720 — как у 1280×720).
MIN_SHORT_SIDE_PX = _read_min_short_side_px()

# Похоже на мелкий превью / иконку / сжатие
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
    "80x80",
    "100x100",
    "150x150",
    "200x200",
    "32x32",
    "24x24",
    "gravatar",
    "doubleclick",
    "adsystem",
    "-xs.",
    "-xs-",
    "_xs.",
    "size=small",
    "scale=small",
    "compress",
    "quality=60",
    "quality=50",
    "q=60",
    "q=50",
    "w=200",
    "w=150",
    "h=200",
    "h=150",
    "crop",
    "resize",
    "mini",
    "-min.",
)
# Высокое разрешение / главное фото
_GOOD_SUBSTR = (
    "1200",
    "1280",
    "1600",
    "1920",
    "2048",
    "2400",
    "2560",
    "3840",
    "4096",
    "large",
    "xlarge",
    "full",
    "original",
    "hero",
    "featured",
    "og-image",
    "wp-content/uploads",
    "high",
    "quality=95",
    "quality=90",
    "q=95",
    "q=90",
    "q=100",
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
        area = w * h
        if w >= 1200 and h >= 675:
            s += 28.0
        elif w >= 1000 and h >= 600:
            s += 22.0
        elif w >= 800 and h >= 500:
            s += 18.0
        elif w >= 600 and h >= 400:
            s += 15.0
        elif w >= 400:
            s += 8.0
        elif area < 120_000:
            s -= 18.0
        elif w < 200 or h < 200:
            s -= 14.0
    m2 = re.search(r"[?&]w=(\d{3,4})", low)
    if m2:
        w = int(m2.group(1))
        if w >= 1200:
            s += 14.0
        elif w >= 800:
            s += 10.0
        elif w >= 500:
            s += 5.0
        elif w < 400:
            s -= 8.0
    if low.endswith((".svg", ".gif")):
        s -= 8.0
    if ".jpg" in low or ".jpeg" in low:
        s += 4.0
    elif ".webp" in low:
        s += 2.0
    elif ".png" in low:
        s += 1.0
    return s


def _dims_wxh_from_url(url: str) -> tuple[int, int] | None:
    m = re.search(r"(\d{2,4})x(\d{2,4})", (url or "").lower())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _query_width_height(url: str) -> tuple[int | None, int | None]:
    try:
        q = parse_qs(urlparse(url).query)
    except Exception:
        return None, None

    def _int(keys: tuple[str, ...]) -> int | None:
        for k in keys:
            vals = q.get(k) or q.get(k.lower())
            if not vals:
                continue
            try:
                v = int(str(vals[0]).strip())
                return v if v > 0 else None
            except ValueError:
                continue
        return None

    return _int(("w", "width")), _int(("h", "height"))


def is_resolution_below_720p(
    url: str,
    *,
    width: int | None = None,
    height: int | None = None,
) -> bool:
    """
    True, если **известно**, что короткая сторона < MIN_SHORT_SIDE_PX.
    Размер неизвестен — не считаем нарушением (кроме явных миниатюр в строке URL).
    """
    raw = url or ""
    if width is not None and height is not None and width > 0 and height > 0:
        return min(width, height) < MIN_SHORT_SIDE_PX

    d = _dims_wxh_from_url(raw)
    if d:
        w, h = d
        return min(w, h) < MIN_SHORT_SIDE_PX

    qw, qh = _query_width_height(raw)
    if qw is not None and qh is not None:
        return min(qw, qh) < MIN_SHORT_SIDE_PX
    if qw is not None:
        return qw < MIN_SHORT_SIDE_PX
    if qh is not None:
        return qh < MIN_SHORT_SIDE_PX

    low = raw.lower()
    if any(
        x in low
        for x in (
            "50x50",
            "64x64",
            "80x80",
            "100x100",
            "150x150",
            "200x200",
            "320x240",
            "480x270",
            "640x360",
        )
    ):
        return True
    return False


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


def prefer_high_resolution_candidates(urls: list[str]) -> list[str]:
    """Оставляет только URL, по которым известно или вероятно ≥720p по короткой стороне."""
    return [u for u in urls if not is_resolution_below_720p(u)]


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
        "Тебе дан только список URL — выбирай номера строго по смыслу заголовка и текста поста: "
        "чтобы фото поясняло сюжет (герой новости, место события, ключевой объект, документ, эпизод). "
        "Не выбирай картинку «просто потому что она есть» — только если она реально относится к тексту.\n"
        "Не выбирай логотипы, абстрактные баннеры, рекламу, сток без темы, мелкие иконки, если есть осмысленное фото.\n"
        "При равной смысловой уместности предпочитай URL с признаками большого разрешения "
        "(короткая сторона не ниже 720 px; в пути 1280, 1920, large, original, full), избегай thumb/preview.\n"
        "Если ни один вариант не подходит по смыслу — верни пустой массив indices.\n"
        "Ответ строго одним JSON-объектом без markdown: "
        '{"indices":[числа], "brief":"одно короткое предложение на русском — почему эти кадры к теме"}'
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
        scored: list[tuple[float, str]] = []
        fetch_n = max(max_results * 4, 12)
        try:
            with DDGS() as ddgs:
                for r in ddgs.images(query, max_results=fetch_n):
                    u = (r.get("image") or "").strip()
                    if not u.startswith(("http://", "https://")):
                        continue
                    w = r.get("width")
                    h = r.get("height")
                    try:
                        wi = int(w) if w is not None else 0
                        hi = int(h) if h is not None else 0
                    except (TypeError, ValueError):
                        wi = hi = 0
                    if wi > 0 and hi > 0:
                        if is_resolution_below_720p(u, width=wi, height=hi):
                            continue
                    elif is_resolution_below_720p(u):
                        continue
                    area = max(0, wi) * max(0, hi)
                    score = area / 10_000.0 + score_image_url_quality(u)
                    scored.append((score, u))
        except Exception:
            logger.debug("DDG images failed for %s", query[:80], exc_info=True)
        scored.sort(key=lambda x: -x[0])
        out = [u for _, u in scored]
        if not out:
            return []
        seen: set[str] = set()
        uniq: list[str] = []
        for u in out:
            if u not in seen:
                seen.add(u)
                uniq.append(u)
        return uniq[:max_results]

    return await asyncio.to_thread(_run)


def heuristic_top_image_urls(raw_candidates: list[str], max_images: int) -> list[str]:
    """Подбор без ИИ: лучшие по эвристике качества URL."""
    ranked = dedupe_sort_candidates(raw_candidates)
    ranked = prefer_high_resolution_candidates(ranked)
    return ranked[:max_images] if ranked else []


async def pick_image_urls_by_semantics(
    *,
    candidates: list[str],
    post_title: str,
    post_body: str,
    api_key: str,
    base_url: str,
    model: str,
    max_images: int,
) -> list[str]:
    """Смысловой отбор через ИИ; пустой список — нет уместных кадров."""
    if not candidates:
        return []
    ranked = dedupe_sort_candidates(candidates)
    ranked = prefer_high_resolution_candidates(ranked)
    if not ranked:
        return []
    top = ranked[:20]
    numbered = list(enumerate(top, start=1))
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
    return chosen[:max_images]


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
    semantic_only: bool = True,
) -> list[str]:
    """
    Итог: 0..max_images URL для отправки в Telegram.
    При включённом смысловом режиме и semantic_only не подставляются случайные URL без одобрения ИИ.
    """
    raw = collect_candidate_image_urls(item)
    key = (api_key or "").strip()

    if use_llm_selection and key:
        try:
            chosen = await pick_image_urls_by_semantics(
                candidates=raw,
                post_title=post_title,
                post_body=post_body,
                api_key=key,
                base_url=base_url,
                model=model,
                max_images=max_images,
            )
            if chosen:
                return chosen
            # ИИ не нашёл уместных среди сайта — пробуем веб с тем же смысловым отбором
            if web_fallback:
                q = await suggest_web_image_search_query(
                    api_key=key,
                    base_url=base_url,
                    model=model,
                    title=post_title,
                    post_text=post_body,
                )
                if q:
                    web = await duckduckgo_image_urls(
                        q, max_results=max(max_images * 3, 12)
                    )
                    web_chosen = await pick_image_urls_by_semantics(
                        candidates=web,
                        post_title=post_title,
                        post_body=post_body,
                        api_key=key,
                        base_url=base_url,
                        model=model,
                        max_images=max_images,
                    )
                    if web_chosen:
                        return web_chosen
            if semantic_only:
                return []
            return heuristic_top_image_urls(raw, max_images)
        except Exception:
            logger.warning(
                "ИИ-отбор картинок по смыслу не удался",
                exc_info=True,
            )
            if semantic_only:
                return []
            return heuristic_top_image_urls(raw, max_images)

    # Без ключа или отключён смысловой отбор — эвристика
    return heuristic_top_image_urls(raw, max_images)
