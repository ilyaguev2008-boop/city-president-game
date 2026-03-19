const FALLBACK_STREAMS = [
  { title: "Матч 1", url: "" },
  { title: "Матч 2", url: "" },
  { title: "Матч 3", url: "" },
  { title: "Матч 4", url: "" },
];

async function loadStreams() {
  try {
    const response = await fetch("./streams.json", { cache: "no-store" });
    if (!response.ok) return FALLBACK_STREAMS;
    const data = await response.json();
    if (!Array.isArray(data)) return FALLBACK_STREAMS;
    return FALLBACK_STREAMS.map((fallback, index) => {
      const item = data[index];
      if (!item || typeof item !== "object") return fallback;
      return {
        title: typeof item.title === "string" ? item.title : fallback.title,
        url: typeof item.url === "string" ? item.url : "",
      };
    });
  } catch {
    return FALLBACK_STREAMS;
  }
}

function initTelegram() {
  if (!window.Telegram || !window.Telegram.WebApp) return;
  const tg = window.Telegram.WebApp;
  tg.ready();
  tg.expand();
}

function renderStreams(streams) {
  const grid = document.getElementById("streams-grid");
  if (!grid) return;

  grid.innerHTML = "";

  streams.forEach((stream, idx) => {
    const card = document.createElement("section");
    card.className = "stream-card";

    const head = document.createElement("div");
    head.className = "stream-head";
    head.textContent = stream.title || `Матч ${idx + 1}`;

    const wrap = document.createElement("div");
    wrap.className = "frame-wrap";

    const frame = document.createElement("iframe");
    const error = document.createElement("div");
    error.className = "error";
    if (!stream.url) {
      card.classList.add("blocked");
      error.textContent = "Ссылка для этого окна пока не задана.";
    } else {
      frame.src = stream.url;
      frame.allow =
        "autoplay; fullscreen; picture-in-picture; encrypted-media";
      frame.referrerPolicy = "origin";
      frame.loading = "lazy";
      // Показываем подсказку, если загрузка iframe явно не удалась.
      frame.addEventListener("error", () => {
        card.classList.add("blocked");
      });
    }

    wrap.appendChild(frame);
    wrap.appendChild(error);
    card.appendChild(head);
    card.appendChild(wrap);
    grid.appendChild(card);
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  initTelegram();
  const streams = await loadStreams();
  renderStreams(streams);
});
