from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

TAG_RE = re.compile(r"<[^>]+>")
URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)


def strip_html(html: str) -> str:
    if not html:
        return ""
    return TAG_RE.sub(" ", html)


def clean_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def strip_urls(text: str) -> str:
    if not text:
        return ""
    return clean_whitespace(URL_RE.sub("", text))


# Строки целиком — типичный мусор СМИ и сайтов (не тема новости)
_JUNK_LINE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"^подписаться\b",
        r"^subscribe\b",
        r"^следите\s+за\s+новостями",
        r"^читайте\s+также",
        r"^читать\s+полностью",
        r"^читать\s+дальше",
        r"^read\s+more\b",
        r"^перейти\s+к\s+содержанию",
        r"^cookie\b",
        r"файлы?\s+cookie",
        r"^мы\s+используем\s+cookie",
        r"^реклама\.?\s*$",
        r"^\[?\s*реклама\s*\]?\s*$",
        r"^материалы?\s+по\s+теме",
        r"^ещё\s+по\s+теме",
        r"^похожие\s+материалы",
        r"^источник:\s*$",
        r"^фото\s*:\s*$",
        r"^видео\s*:\s*$",
        r"^иллюстративное\s+фото",
        r"^архивное\s+фото",
        r"^коллаж\s+",
        r"^подписка\s+на\s+",
        r"^не\s+пропустите",
        r"^следите\s+за\s+нами",
        r"^поделиться\s*:?\s*$",
        r"^share\s+on\b",
        r"^комментарии\s*\(\s*\d+\s*\)",
        r"^обсудить\s+в\s+",
        r"^tags?:\s*",
        r"^теги:\s*",
        r"^рубрика:\s*$",
        r"^раздел:\s*$",
        r"^главная\s*/\s*",  # хлебные крошки одной строкой
    )
)

# Фрагменты внутри строки (убираем целиком короткие вставки)
_JUNK_INLINE_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\(?\s*реклама\s*\)?", re.IGNORECASE),
    re.compile(r"\[реклама\]", re.IGNORECASE),
    re.compile(r"\(источник\s*:[^)]+\)", re.IGNORECASE),
    re.compile(r"\[подпись\s+фото[^\]]*\]", re.IGNORECASE),
)


def _strip_invisible_and_controls(s: str) -> str:
    out: list[str] = []
    for ch in s:
        o = ord(ch)
        if ch in ("\u200b", "\u200c", "\u200d", "\ufeff"):
            continue
        if o == 0x00A0:
            out.append(" ")
            continue
        # Символы форматирования / невидимые в диапазоне Unicode
        if 0x2000 <= o <= 0x200F or 0x2028 <= o <= 0x202F or 0x2060 <= o <= 0x206F:
            continue
        if o < 32 and ch not in "\n\t":
            continue
        out.append(ch)
    return "".join(out)


def _is_junk_line(line: str) -> bool:
    ln = line.strip()
    if not ln:
        return False
    if len(ln) <= 120:
        for rx in _JUNK_LINE_PATTERNS:
            if rx.search(ln):
                return True
    # Только разделители
    if re.match(r"^[\s\-_=•·‣\*─═]{3,}$", ln):
        return True
    return False


def sanitize_post_text(text: str) -> str:
    """
    Чистит текст поста: невидимые символы, типичный редакционный мусор,
    лишние пустые строки. Не удаляет смысловые абзацы новости.
    """
    if not text:
        return ""
    t = _strip_invisible_and_controls(text)
    t = t.replace("\r\n", "\n").replace("\r", "\n")

    for rx in _JUNK_INLINE_RES:
        t = rx.sub("", t)

    lines = t.split("\n")
    kept: list[str] = []
    for line in lines:
        if _is_junk_line(line):
            continue
        ln = line.strip()
        # Очень короткая строка — только типичный мусор
        if len(ln) < 4 and ln.lower() in {"реклама", "ad", "ads"}:
            continue
        kept.append(line.strip())

    t = "\n".join(kept)
    t = re.sub(r"\n{3,}", "\n\n", t)
    # Схлопываем множественные пробелы внутри строк
    t = "\n".join(clean_whitespace(p) if p.strip() else "" for p in t.split("\n"))
    # Убираем пустые строки подряд > 2
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


# Типичные английские служебные слова в «русском» тексте (модель иногда вставляет их) —
# удаляем только полностью строчные латинские токены, чтобы не трогать имена (Title Case) и бренды.
_EN_STOPWORDS_LOWER = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "if",
        "as",
        "of",
        "at",
        "by",
        "for",
        "with",
        "from",
        "into",
        "onto",
        "upon",
        "to",
        "in",
        "on",
        "over",
        "under",
        "after",
        "before",
        "between",
        "through",
        "during",
        "about",
        "against",
        "among",
        "is",
        "are",
        "was",
        "were",
        "been",
        "be",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "must",
        "shall",
        "can",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "they",
        "them",
        "their",
        "he",
        "she",
        "his",
        "her",
        "we",
        "you",
        "who",
        "whom",
        "which",
        "what",
        "when",
        "where",
        "why",
        "how",
        "all",
        "each",
        "every",
        "both",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "nor",
        "not",
        "only",
        "own",
        "same",
        "so",
        "than",
        "too",
        "very",
        "just",
        "also",
        "even",
        "here",
        "there",
        "then",
        "once",
        "again",
        "further",
        "news",
        "report",
        "reports",
        "said",
        "says",
        "according",
        "sources",
        "source",
        "media",
        "press",
        "official",
        "government",
        "state",
        "country",
        "million",
        "billion",
        "percent",
        "per",
        "new",
        "first",
        "last",
        "next",
        "year",
        "years",
        "day",
        "days",
        "week",
        "weeks",
        "month",
        "months",
        "time",
        "people",
        "two",
        "one",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "read",
        "more",
        "full",
        "story",
        "video",
        "photo",
        "image",
        "file",
        "via",
        "ok",
        "okay",
        "yes",
        "vs",
        "etc",
        "ie",
        "eg",
        "approx",
    }
)


def _strip_token_punctuation_for_check(token: str) -> str:
    return token.strip(".,!?;:«»\"'()[]…—–‐-")


def _is_ascii_lowercase_stopword_token(core: str) -> bool:
    if len(core) < 2:
        return False
    if not core.isascii():
        return False
    if not core.isalpha():
        return False
    if not core.islower():
        return False
    return core in _EN_STOPWORDS_LOWER


def normalize_cyrillic_news_prose(text: str) -> str:
    """
    Убирает случайные английские служебные слова (полностью строчные латинские токены из списка).
    Имена собственные вроде Trump, NASA, iPhone не трогает (не совпадают с условием «всё строчное»).
    """
    if not text:
        return ""
    lines_out: list[str] = []
    for line in text.split("\n"):
        toks = line.split()
        kept: list[str] = []
        for t in toks:
            core = _strip_token_punctuation_for_check(t)
            if core and _is_ascii_lowercase_stopword_token(core):
                continue
            kept.append(t)
        lines_out.append(" ".join(kept))
    t = "\n".join(lines_out)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def clean_title_for_post(title: str) -> str:
    """Заголовок: без HTML и лишних пробелов."""
    if not title:
        return ""
    t = title.strip()
    if "<" in t:
        t = strip_html(t)
    t = _strip_invisible_and_controls(t)
    t = clean_whitespace(t)
    return t[:500]


_TRACKING_QUERY_KEYS = frozenset(
    k.lower()
    for k in (
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_content",
        "utm_term",
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
    )
)


def normalize_article_link(url: str) -> str:
    """Одинаковые новости с разных источников часто отличаются только метками в URL."""
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        p = urlparse(raw)
        if p.scheme not in ("http", "https") or not p.netloc:
            return ""
        netloc = p.netloc.lower()
        path = p.path or "/"
        if len(path) > 1 and path.endswith("/"):
            path = path.rstrip("/")
        q = parse_qs(p.query, keep_blank_values=False)
        q = {k: v for k, v in q.items() if k.lower() not in _TRACKING_QUERY_KEYS}
        query = urlencode(sorted(q.items()), doseq=True)
        return urlunparse((p.scheme.lower(), netloc, path, p.params, query, ""))
    except Exception:
        return ""
