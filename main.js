const STREAMS = [
  {
    title: "Матч 1",
    url: "https://okko.sport/sport/live_event/fc-midtjylland-nottingham-forest-uefaeuropaleague-round-of-16-2nd-leg-25-26?playing=live&id=7ed64093-35fb-3e89-82b5-381d4a818197&type=LIVE_EVENT",
  },
  {
    title: "Матч 2",
    url: "https://okko.sport/sport/live_event/fc-midtjylland-nottingham-forest-uefaeuropaleague-round-of-16-2nd-leg-25-26?playing=live&id=7ed64093-35fb-3e89-82b5-381d4a818197&type=LIVE_EVENT",
  },
  {
    title: "Матч 3",
    url: "https://okko.sport/sport/live_event/fc-midtjylland-nottingham-forest-uefaeuropaleague-round-of-16-2nd-leg-25-26?playing=live&id=7ed64093-35fb-3e89-82b5-381d4a818197&type=LIVE_EVENT",
  },
  {
    title: "Матч 4",
    url: "https://okko.sport/sport/live_event/fc-midtjylland-nottingham-forest-uefaeuropaleague-round-of-16-2nd-leg-25-26?playing=live&id=7ed64093-35fb-3e89-82b5-381d4a818197&type=LIVE_EVENT",
  },
];

function initTelegram() {
  if (!window.Telegram || !window.Telegram.WebApp) return;
  const tg = window.Telegram.WebApp;
  tg.ready();
  tg.expand();
}

function renderStreams() {
  const grid = document.getElementById("streams-grid");
  if (!grid) return;

  grid.innerHTML = "";

  STREAMS.forEach((stream, idx) => {
    const card = document.createElement("section");
    card.className = "stream-card";

    const head = document.createElement("div");
    head.className = "stream-head";
    head.textContent = stream.title || `Матч ${idx + 1}`;

    const wrap = document.createElement("div");
    wrap.className = "frame-wrap";

    const frame = document.createElement("iframe");
    frame.src = stream.url;
    frame.allow =
      "autoplay; fullscreen; picture-in-picture; encrypted-media";
    frame.referrerPolicy = "origin";
    frame.loading = "lazy";

    const error = document.createElement("div");
    error.className = "error";
    error.textContent =
      "Источник не дал показать видео в iframe. Нужен embed или прямой поток.";

    // Показываем подсказку, если загрузка iframe явно не удалась.
    frame.addEventListener("error", () => {
      card.classList.add("blocked");
    });

    wrap.appendChild(frame);
    wrap.appendChild(error);
    card.appendChild(head);
    card.appendChild(wrap);
    grid.appendChild(card);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initTelegram();
  renderStreams();
});
