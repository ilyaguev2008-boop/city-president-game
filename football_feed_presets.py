"""Готовые RSS-ленты по футболу и смежному спорту для быстрого старта.

Сайты попадают в «Источники новостей» в Telegram у пользователя при:
- первом /start, если у него ещё нет ни одного источника;
- нажатии «⚽ Футбольные ленты (набор)» / кнопки «Футбольные ленты» в разделе источников.

Уже существующие URL не дублируются.
"""

# Кортежи: (URL ленты, подпись в списке источников в боте).
FOOTBALL_PRESET_FEEDS: list[tuple[str, str]] = [
    # Международные (англ.)
    ("https://feeds.bbci.co.uk/sport/football/rss.xml", "BBC Sport — футбол"),
    ("https://www.theguardian.com/football/rss", "The Guardian — football"),
    ("https://www.espn.com/espn/rss/soccer/news", "ESPN — soccer"),
    ("https://www.fourfourtwo.com/feeds.xml", "FourFourTwo"),
    ("https://www.90min.com/posts.rss", "90min — football"),
    (
        "https://news.google.com/rss/search?q=football+soccer&hl=en-US&gl=US&ceid=US:en",
        "Google News — football (EN)",
    ),
    (
        "https://news.google.com/rss/search?q=%D1%84%D1%83%D1%82%D0%B1%D0%BE%D0%BB&hl=ru&gl=RU&ceid=RU:ru",
        "Google News — футбол (RU)",
    ),
    # РФ и СНГ: СМИ и спорт (в лентах много футбола)
    ("https://matchtv.ru/news/rss", "Матч ТВ — новости спорта"),
    ("https://ria.ru/export/sport/rss2/index.xml", "РИА Новости — спорт"),
    ("https://lenta.ru/rss/news/sport", "Lenta.ru — спорт"),
    (
        "https://www.transfermarkt.ru/rss/news",
        "Transfermarkt — новости трансферов",
    ),
    # Фан-сообщество и обсуждения (не только «сухие» новости)
    ("https://www.soccer.ru/rss.xml", "Soccer.ru — футбол, блоги и новости"),
    # Украина (часть текстов на укр.; подходит для сбора материалов)
    ("https://isport.ua/rss", "iSport.ua — спорт (RU)"),
    ("https://football.ua/rss2.ashx?cat=10", "football.ua — новости"),
    # Беларусь: много футбола (чемпионат, сборная) + другие виды
    ("https://www.pressball.by/rss.xml", "Pressball.by — спорт (футбол, РБ)"),
]
