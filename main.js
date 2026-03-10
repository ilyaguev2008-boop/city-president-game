    const ECON_START_MONEY = 100000;

const BUILDINGS = [
  {
    id: "house_small",
    type: "home",
    name: "Малый жилой дом",
    desc: "+12 жителей, небольшой налог",
    cost: 8000,
    population: 12,
    economy: 1,
    incomePerTurn: 400,
  },
  {
    id: "house_block",
    type: "home",
    name: "Жилой квартал",
    desc: "+55 жителей, стабильный налог",
    cost: 35000,
    population: 55,
    economy: 4,
    incomePerTurn: 2200,
  },
  {
    id: "factory",
    type: "biz",
    name: "Завод",
    desc: "+30 рабочих мест, высокий доход",
    cost: 60000,
    population: 0,
    economy: 10,
    incomePerTurn: 6000,
  },
  {
    id: "it_park",
    type: "biz",
    name: "IT-парк",
    desc: "Повышает экономику и статус города",
    cost: 90000,
    population: 10,
    economy: 18,
    incomePerTurn: 9500,
  },
];

const initialState = {
  money: ECON_START_MONEY,
  population: 0,
  economy: 0,
  turn: 1,
  buildings: {},
};

const el = {
  title: document.getElementById("game-title"),
  subtitle: document.getElementById("game-subtitle"),
  storyText: document.getElementById("story-text"),
  choices: document.getElementById("choices"),
  progressFill: document.getElementById("progress-fill"),
  metaNode: document.getElementById("meta-node"),
  metaEnding: document.getElementById("meta-ending"),
  resMoney: document.getElementById("res-money"),
  resPopulation: document.getElementById("res-population"),
  resEconomy: document.getElementById("res-economy"),
  screenEconomy: document.getElementById("screen-economy"),
  screenPlaceholder: document.getElementById("screen-placeholder"),
};

let state = { ...initialState };
let currentTab = "economy";

const TAB_TITLES = {
  rating: { title: "Рейтинг", subtitle: "Топ президентов" },
  economy: { title: "Экономика", subtitle: "Застройка и доход" },
  city: { title: "Город", subtitle: "Обзор города" },
  citizens: { title: "Жители", subtitle: "Население" },
  donat: { title: "Донат", subtitle: "Поддержать игру" },
};

function setActiveTab(tab) {
  currentTab = tab;
  el.title.textContent = "City President";
  el.subtitle.textContent = TAB_TITLES[tab] ? TAB_TITLES[tab].subtitle : tab;
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  });
  if (tab === "economy") {
    el.screenEconomy.style.display = "";
    el.screenPlaceholder.style.display = "none";
    renderEconomy();
  } else {
    el.screenEconomy.style.display = "none";
    el.screenPlaceholder.style.display = "block";
    renderPlaceholder(tab);
  }
}

function renderPlaceholder(tab) {
  const texts = {
    rating:
      "<h3>🏆 Рейтинг</h3>Скоро здесь появится таблица лидеров. Копи деньги, население и экономику — и попади в топ!",
    city:
      "<h3>🏙️ Город</h3>Здесь будет обзор твоего города: карта, построенные здания и статистика по районам.",
    citizens:
      "<h3>👥 Жители</h3>Информация о населении: рост, занятость и настроение жителей. Развивай город — привлечёшь больше людей.",
    donat:
      "<h3>❤️ Донат</h3>Поддержать разработчика и получить бонусы в игре можно будет здесь. Функция скоро появится!",
  };
  el.screenPlaceholder.innerHTML = texts[tab] || "<p>Раздел в разработке.</p>";
}

function fmtMoney(v) {
  return v.toLocaleString("ru-RU", { maximumFractionDigits: 0 });
}

function updateResourcesUI() {
  el.resMoney.textContent = fmtMoney(state.money);
  el.resPopulation.textContent = fmtMoney(state.population);
  el.resEconomy.textContent = fmtMoney(state.economy);
  el.metaNode.textContent = `Ход ${state.turn}`;
}

function calcTotalIncomePerTurn() {
  let income = 0;
  for (const b of BUILDINGS) {
    const count = state.buildings[b.id] || 0;
    income += count * b.incomePerTurn;
  }
  return income;
}

function renderEconomy() {
  el.title.textContent = "City President";
  el.subtitle.textContent = "Экономика и застройка";

  const income = calcTotalIncomePerTurn();
  const textLines = [
    "Ты президент города. Развивай экономику и не обанкротись.",
    `Доход за ход: ${fmtMoney(income)} 💰`,
    "Построй жилые дома и предприятия, чтобы увеличить население и доход.",
  ];
  el.storyText.textContent = textLines.join(" ");

  const progress = Math.min(1, state.economy / 100);
  el.progressFill.style.width = `${(progress * 100).toFixed(0)}%`;

  el.choices.innerHTML = "";

  BUILDINGS.forEach((b, index) => {
    const btn = document.createElement("button");
    const count = state.buildings[b.id] || 0;
    const affordable = state.money >= b.cost;
    btn.className = "choice-btn" + (index === 0 ? " primary" : "");
    if (!affordable) {
      btn.className += " disabled";
    }

    const labelSpan = document.createElement("span");
    labelSpan.textContent = `${b.name} — ${fmtMoney(b.cost)} 💰 (x${count})`;
    btn.appendChild(labelSpan);

    const hk = document.createElement("span");
    hk.className = "choice-hotkey";
    hk.textContent = `${b.population ? `👥 +${b.population} ` : ""}${
      b.economy ? `📈 +${b.economy} ` : ""
    }💰 +${fmtMoney(b.incomePerTurn)}/ход`;
    btn.appendChild(hk);

    btn.addEventListener("click", () => {
      buyBuilding(b);
    });

    el.choices.appendChild(btn);
  });

  const nextTurnBtn = document.createElement("button");
  nextTurnBtn.className = "choice-btn";
  const lbl = document.createElement("span");
  lbl.textContent = "Следующий ход (получить доход)";
  nextTurnBtn.appendChild(lbl);
  const hk2 = document.createElement("span");
  hk2.className = "choice-hotkey";
  hk2.textContent = "💰";
  nextTurnBtn.appendChild(hk2);
  nextTurnBtn.addEventListener("click", () => {
    applyTurnIncome();
  });
  el.choices.appendChild(nextTurnBtn);
}

function buyBuilding(building) {
  if (state.money < building.cost) {
    el.metaEnding.textContent = "Недостаточно денег 😕";
    el.metaEnding.classList.add("danger");
    return;
  }
  el.metaEnding.textContent = "";
  el.metaEnding.classList.remove("danger");

  state.money -= building.cost;
  state.population += building.population;
  state.economy += building.economy;
  state.buildings[building.id] = (state.buildings[building.id] || 0) + 1;
  saveState();
  updateResourcesUI();
  renderEconomy();
}

function restoreProgress() {
  try {
    const raw = window.localStorage.getItem("tg_city_president_state");
    if (raw) {
      const parsed = JSON.parse(raw);
      state = { ...initialState, ...parsed };
    }
  } catch {
    state = { ...initialState };
  }
  updateResourcesUI();
  renderEconomy();
}

function saveState() {
  try {
    window.localStorage.setItem("tg_city_president_state", JSON.stringify(state));
  } catch {
    // ignore
  }
}

function applyTurnIncome() {
  const income = calcTotalIncomePerTurn();
  if (income <= 0) {
    el.metaEnding.textContent = "Построй хотя бы одно здание, чтобы получать доход.";
    el.metaEnding.classList.add("danger");
    return;
  }
  el.metaEnding.textContent = "";
  el.metaEnding.classList.remove("danger");

  state.money += income;
  state.turn += 1;
  saveState();
  updateResourcesUI();
  renderEconomy();
}

function initTelegram() {
  if (!window.Telegram || !window.Telegram.WebApp) {
    return;
  }
  const tg = window.Telegram.WebApp;
  tg.ready();
  tg.expand();
}

document.addEventListener("DOMContentLoaded", () => {
  initTelegram();
  restoreProgress();
  setActiveTab("economy");

  document.getElementById("bottom-nav").addEventListener("click", (e) => {
    const btn = e.target.closest(".nav-btn");
    if (btn && btn.dataset.tab) {
      setActiveTab(btn.dataset.tab);
    }
  });
});

