const ECON_START_MONEY = 100000;
const MAX_HOURS_ACCUMULATE = 168;

const ENTERPRISES = [
  { id: "ent_1", name: "Ларёк", icon: "🏪", cost: 2000, population: 0, economy: 1, incomePerHour: 80 },
  { id: "ent_2", name: "Магазин", icon: "🛒", cost: 5000, population: 0, economy: 2, incomePerHour: 220 },
  { id: "ent_3", name: "Кафе", icon: "☕", cost: 10000, population: 2, economy: 3, incomePerHour: 450 },
  { id: "ent_4", name: "АЗС", icon: "⛽", cost: 18000, population: 0, economy: 4, incomePerHour: 750 },
  { id: "ent_5", name: "Склад", icon: "📦", cost: 28000, population: 0, economy: 5, incomePerHour: 1100 },
  { id: "ent_6", name: "Прачечная", icon: "🧺", cost: 40000, population: 3, economy: 6, incomePerHour: 1600 },
  { id: "ent_7", name: "Пекарня", icon: "🥖", cost: 55000, population: 5, economy: 7, incomePerHour: 2200 },
  { id: "ent_8", name: "Автосервис", icon: "🔧", cost: 75000, population: 8, economy: 9, incomePerHour: 3000 },
  { id: "ent_9", name: "Супермаркет", icon: "🏬", cost: 100000, population: 10, economy: 11, incomePerHour: 4000 },
  { id: "ent_10", name: "Завод", icon: "🏭", cost: 130000, population: 0, economy: 14, incomePerHour: 5200 },
  { id: "ent_11", name: "ТЦ", icon: "🛍️", cost: 170000, population: 15, economy: 17, incomePerHour: 6800 },
  { id: "ent_12", name: "Логистический центр", icon: "🚚", cost: 220000, population: 0, economy: 20, incomePerHour: 8800 },
  { id: "ent_13", name: "Отель", icon: "🏨", cost: 280000, population: 20, economy: 24, incomePerHour: 11200 },
  { id: "ent_14", name: "Фабрика", icon: "🏗️", cost: 350000, population: 0, economy: 28, incomePerHour: 14000 },
  { id: "ent_15", name: "Бизнес-центр", icon: "🏢", cost: 430000, population: 25, economy: 33, incomePerHour: 17200 },
  { id: "ent_16", name: "IT-компания", icon: "💻", cost: 520000, population: 30, economy: 38, incomePerHour: 20800 },
  { id: "ent_17", name: "Недра", icon: "⛏️", cost: 620000, population: 0, economy: 44, incomePerHour: 24800 },
  { id: "ent_18", name: "Медиа-холдинг", icon: "📡", cost: 750000, population: 40, economy: 50, incomePerHour: 30000 },
  { id: "ent_19", name: "IT-парк", icon: "🌐", cost: 900000, population: 50, economy: 58, incomePerHour: 36000 },
  { id: "ent_20", name: "Корпорация", icon: "🏛️", cost: 1100000, population: 60, economy: 70, incomePerHour: 44000 },
];

const RESIDENCES = [
  { id: "res_1", name: "Сарай", icon: "🛖", cost: 1500, population: 3, economy: 0, incomePerHour: 30 },
  { id: "res_2", name: "Домик", icon: "🏠", cost: 4000, population: 8, economy: 0, incomePerHour: 100 },
  { id: "res_3", name: "Малый дом", icon: "🏡", cost: 8000, population: 15, economy: 1, incomePerHour: 200 },
  { id: "res_4", name: "Квартирный дом", icon: "🏘️", cost: 15000, population: 28, economy: 2, incomePerHour: 380 },
  { id: "res_5", name: "Жилой блок", icon: "🏢", cost: 25000, population: 45, economy: 3, incomePerHour: 600 },
  { id: "res_6", name: "Микрорайон", icon: "🏙️", cost: 40000, population: 70, economy: 5, incomePerHour: 950 },
  { id: "res_7", name: "Жилой комплекс", icon: "🏗️", cost: 60000, population: 100, economy: 7, incomePerHour: 1400 },
  { id: "res_8", name: "Таунхаусы", icon: "🏘️", cost: 90000, population: 140, economy: 9, incomePerHour: 2000 },
  { id: "res_9", name: "ЖК «Комфорт»", icon: "✨", cost: 130000, population: 190, economy: 12, incomePerHour: 2700 },
  { id: "res_10", name: "Высотка", icon: "🌆", cost: 180000, population: 250, economy: 15, incomePerHour: 3600 },
  { id: "res_11", name: "ЖК «Бизнес»", icon: "💼", cost: 240000, population: 320, economy: 19, incomePerHour: 4700 },
  { id: "res_12", name: "Элитный квартал", icon: "👑", cost: 320000, population: 400, economy: 24, incomePerHour: 6200 },
  { id: "res_13", name: "Жилой район", icon: "🏘️", cost: 420000, population: 500, economy: 30, incomePerHour: 8000 },
  { id: "res_14", name: "Мега-ЖК", icon: "🌃", cost: 540000, population: 620, economy: 36, incomePerHour: 10200 },
  { id: "res_15", name: "Городок", icon: "🏛️", cost: 700000, population: 760, economy: 44, incomePerHour: 12800 },
  { id: "res_16", name: "Агломерация", icon: "🌉", cost: 900000, population: 920, economy: 52, incomePerHour: 16000 },
  { id: "res_17", name: "Спутник города", icon: "🛸", cost: 1150000, population: 1100, economy: 62, incomePerHour: 19800 },
  { id: "res_18", name: "Новый город", icon: "🏗️", cost: 1450000, population: 1320, economy: 73, incomePerHour: 24500 },
  { id: "res_19", name: "Мегаполис", icon: "🌇", cost: 1800000, population: 1580, economy: 86, incomePerHour: 30200 },
  { id: "res_20", name: "Столица", icon: "🏰", cost: 2200000, population: 1900, economy: 100, incomePerHour: 38000 },
];

const ALL_BUILDINGS = [...ENTERPRISES, ...RESIDENCES];

/** URL картинки для объекта: локальные сгенерированные или плейсхолдер по id */
function getBuildingImageUrl(b) {
  const base = "./images/buildings";
  return `${base}/${b.id}.png`;
}

const BONUS_UPGRADES = {
  click: {
    name: "Доход за клик",
    desc: "Сколько ₽ даёт один клик по кружку в Городе",
    baseCost: 500,
    costScale: 1.55,
    baseValue: 100,
    perLevel: 25,
    getValue(level) {
      return this.baseValue + level * this.perLevel;
    },
  },
  maxEnergy: {
    name: "Макс. энергия",
    desc: "Максимальный запас энергии",
    baseCost: 400,
    costScale: 1.5,
    baseValue: 10,
    perLevel: 5,
    getValue(level) {
      return this.baseValue + level * this.perLevel;
    },
  },
  energyPerHour: {
    name: "Энергия в час",
    desc: "Сколько энергии восстанавливается каждый час",
    baseCost: 600,
    costScale: 1.6,
    baseValue: 2,
    perLevel: 1,
    getValue(level) {
      return this.baseValue + level * this.perLevel;
    },
  },
};

const initialState = {
  money: ECON_START_MONEY,
  population: 0,
  economy: 0,
  buildings: {},
  lastIncomeTime: 0,
  energy: 10,
  maxEnergy: 10,
  energyPerHour: 2,
  lastEnergyTime: 0,
  clickIncome: 100,
  upgradeLevels: { click: 0, maxEnergy: 0, energyPerHour: 0 },
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
  resEnergy: document.getElementById("res-energy"),
  screenEconomy: document.getElementById("screen-economy"),
  screenPlaceholder: document.getElementById("screen-placeholder"),
};

let state = { ...initialState };
let currentTab = "city";
let currentEconomySection = "enterprises";

const TAB_TITLES = {
  rating: { title: "Рейтинг", subtitle: "Топ президентов" },
  economy: { title: "Экономика", subtitle: "Застройка и доход" },
  city: { title: "Город", subtitle: "Клик — заработать" },
  citizens: { title: "Жители", subtitle: "Население" },
  donat: { title: "Донат", subtitle: "Поддержать игру" },
};

function setActiveTab(tab) {
  currentTab = tab;
  document.body.classList.toggle("dark-theme", tab !== "city");
  document.body.classList.toggle("city-tab", tab === "city");
  el.title.textContent = "City President";
  el.subtitle.textContent = TAB_TITLES[tab] ? TAB_TITLES[tab].subtitle : tab;
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  });
  if (tab === "economy") {
    el.screenEconomy.style.display = "";
    el.screenPlaceholder.style.display = "none";
    applyHourlyIncome();
    updateResourcesUI();
    renderEconomy();
  } else if (tab === "city") {
    el.screenEconomy.style.display = "none";
    el.screenPlaceholder.style.display = "block";
    applyHourlyEnergy();
    updateResourcesUI();
    renderCity();
  } else {
    el.screenEconomy.style.display = "none";
    el.screenPlaceholder.style.display = "block";
    renderPlaceholder(tab);
  }
}

function renderPlaceholder(tab) {
  const texts = {
    rating:
      "<h3>🏆 Рейтинг</h3>Скоро здесь появится таблица лидеров.",
    citizens:
      "<h3>👥 Жители</h3>Информация о населении: рост, занятость и настроение жителей.",
    donat:
      "<h3>❤️ Донат</h3>Поддержать разработчика и получить бонусы в игре можно будет здесь.",
  };
  el.screenPlaceholder.innerHTML = texts[tab] || "<p>Раздел в разработке.</p>";
}

function renderCity() {
  applyHourlyEnergy();
  const energyPct = state.maxEnergy > 0 ? (state.energy / state.maxEnergy) * 100 : 0;
  el.screenPlaceholder.innerHTML = `
    <div class="city-circle-wrap">
      <div class="city-bg" aria-hidden="true"></div>
      <div class="city-bg-overlay" aria-hidden="true"></div>
      <div class="city-content">
        <div class="city-circle ${state.energy <= 0 ? "disabled" : ""}" id="city-circle" role="button" tabindex="0">
          <span class="city-circle-emoji">💰</span>
          <span class="city-circle-label">Клик</span>
        </div>
        <div class="energy-bar-wrap">
          <div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:4px;">
            <span>Энергия</span>
            <span id="city-energy-text">${state.energy} / ${state.maxEnergy}</span>
          </div>
          <div class="energy-bar">
            <div class="energy-fill" id="city-energy-fill" style="width:${energyPct}%"></div>
          </div>
        </div>
        <p class="city-hint" style="margin:0;font-size:12px;opacity:0.9;">+${fmtMoney(state.clickIncome)} ₽ за клик · восст. ${state.energyPerHour}/час</p>
      </div>
    </div>
  `;
  const circle = document.getElementById("city-circle");
  const energyText = document.getElementById("city-energy-text");
  const energyFill = document.getElementById("city-energy-fill");
  if (circle) {
    circle.addEventListener("click", () => {
      if (state.energy <= 0) return;
      state.energy -= 1;
      state.money += state.clickIncome;
      saveState();
      updateResourcesUI();
      energyText.textContent = `${state.energy} / ${state.maxEnergy}`;
      energyFill.style.width = `${(state.energy / state.maxEnergy) * 100}%`;
      circle.classList.toggle("disabled", state.energy <= 0);
    });
  }
}

function applyHourlyEnergy() {
  const now = Date.now();
  if (!state.lastEnergyTime) {
    state.lastEnergyTime = now;
    state.energy = Math.min(state.energy, state.maxEnergy);
    saveState();
    return;
  }
  const hoursPassed = (now - state.lastEnergyTime) / (1000 * 60 * 60);
  const hoursToAdd = Math.min(hoursPassed, MAX_HOURS_ACCUMULATE);
  const toAdd = Math.floor(state.energyPerHour * hoursToAdd);
  if (toAdd > 0) {
    state.energy = Math.min(state.maxEnergy, state.energy + toAdd);
    state.lastEnergyTime = now;
    saveState();
  } else {
    state.lastEnergyTime = now;
    saveState();
  }
}

function fmtMoney(v) {
  return v.toLocaleString("ru-RU", { maximumFractionDigits: 0 });
}

function updateResourcesUI() {
  el.resMoney.textContent = fmtMoney(state.money);
  el.resPopulation.textContent = fmtMoney(state.population);
  const perHour = calcTotalIncomePerHour();
  el.resEconomy.textContent = perHour > 0 ? `${fmtMoney(perHour)} ₽` : "0 ₽";
  if (el.resEnergy) {
    el.resEnergy.textContent = `${state.energy}/${state.maxEnergy}`;
  }
  el.metaNode.textContent = perHour > 0 ? `Доход: ${fmtMoney(perHour)} ₽/час` : "Доход: 0 ₽/час";
}

function calcTotalIncomePerHour() {
  let income = 0;
  for (const b of ALL_BUILDINGS) {
    const count = state.buildings[b.id] || 0;
    income += count * (b.incomePerHour || 0);
  }
  return income;
}

function applyHourlyIncome() {
  const now = Date.now();
  if (!state.lastIncomeTime) {
    state.lastIncomeTime = now;
    saveState();
    return;
  }
  const incomePerHour = calcTotalIncomePerHour();
  if (incomePerHour <= 0) {
    state.lastIncomeTime = now;
    saveState();
    return;
  }
  const hoursPassed = (now - state.lastIncomeTime) / (1000 * 60 * 60);
  const hoursToPay = Math.min(hoursPassed, MAX_HOURS_ACCUMULATE);
  const toAdd = Math.floor(incomePerHour * hoursToPay);
  if (toAdd > 0) {
    state.money += toAdd;
  }
  state.lastIncomeTime = now;
  saveState();
}

function getUpgradeCost(id, level) {
  const u = BONUS_UPGRADES[id];
  return Math.floor(u.baseCost * Math.pow(u.costScale, level));
}

function buyUpgrade(id) {
  const u = BONUS_UPGRADES[id];
  const level = state.upgradeLevels[id] || 0;
  const cost = getUpgradeCost(id, level);
  if (state.money < cost) {
    el.metaEnding.textContent = "Недостаточно денег 😕";
    el.metaEnding.classList.add("danger");
    return;
  }
  el.metaEnding.textContent = "";
  el.metaEnding.classList.remove("danger");
  state.money -= cost;
  state.upgradeLevels[id] = level + 1;
  if (id === "click") {
    state.clickIncome = u.getValue(level + 1);
  } else if (id === "maxEnergy") {
    state.maxEnergy = u.getValue(level + 1);
    state.energy = Math.min(state.energy, state.maxEnergy);
  } else if (id === "energyPerHour") {
    state.energyPerHour = u.getValue(level + 1);
  }
  saveState();
  updateResourcesUI();
  renderEconomy();
}

function renderEconomy() {
  el.title.textContent = "City President";
  el.subtitle.textContent = "Экономика";

  const incomePerHour = calcTotalIncomePerHour();
  el.storyText.textContent =
    "Доход от построек начисляется каждый час при открытии игры. Выбери раздел ниже.";

  const progress = Math.min(1, state.economy / 100);
  el.progressFill.style.width = `${(progress * 100).toFixed(0)}%`;

  el.choices.innerHTML = "";

  const subNav = document.createElement("div");
  subNav.className = "economy-sub-nav";
  ["enterprises", "residences", "bonuses"].forEach((section) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "economy-sub-btn" + (currentEconomySection === section ? " active" : "");
    btn.textContent =
      section === "enterprises"
        ? "ПРЕДПРИЯТИЯ"
        : section === "residences"
          ? "ЖИЛЫЕ ЗДАНИЯ"
          : "БОНУСЫ";
    btn.addEventListener("click", () => {
      currentEconomySection = section;
      renderEconomy();
    });
    subNav.appendChild(btn);
  });
  el.choices.appendChild(subNav);

  if (currentEconomySection === "enterprises") {
    ENTERPRISES.forEach((b) => {
      const count = state.buildings[b.id] || 0;
      const affordable = state.money >= b.cost;
      const card = document.createElement("div");
      card.className = "purchase-card" + (affordable ? "" : " disabled");
      const imgWrap = document.createElement("div");
      imgWrap.className = "purchase-card-image-wrap";
      const img = document.createElement("img");
      img.className = "purchase-card-image";
      img.src = getBuildingImageUrl(b);
      img.alt = b.name;
      img.loading = "lazy";
      img.onerror = () => imgWrap.classList.add("failed");
      const imgFallback = document.createElement("span");
      imgFallback.className = "img-fallback";
      imgFallback.textContent = b.icon || "🏪";
      imgWrap.appendChild(img);
      imgWrap.appendChild(imgFallback);
      const body = document.createElement("div");
      body.className = "purchase-card-body";
      body.innerHTML = `
        <span class="purchase-card-name">${b.name}</span>
        <span class="purchase-card-stats">x${count} · 📈 +${b.economy} · 💰 ${fmtMoney(b.incomePerHour)}/час</span>
        <span class="purchase-card-price">${fmtMoney(b.cost)} ₽</span>
      `;
      const action = document.createElement("div");
      action.className = "purchase-card-action";
      const buyBtn = document.createElement("button");
      buyBtn.type = "button";
      buyBtn.className = "buy-btn";
      buyBtn.textContent = "Купить";
      buyBtn.addEventListener("click", (e) => { e.stopPropagation(); if (affordable) buyBuilding(b); });
      action.appendChild(buyBtn);
      card.appendChild(imgWrap);
      card.appendChild(body);
      card.appendChild(action);
      card.addEventListener("click", (e) => { if (!e.target.closest(".buy-btn") && affordable) buyBuilding(b); });
      el.choices.appendChild(card);
    });
  } else if (currentEconomySection === "residences") {
    RESIDENCES.forEach((b) => {
      const count = state.buildings[b.id] || 0;
      const affordable = state.money >= b.cost;
      const card = document.createElement("div");
      card.className = "purchase-card" + (affordable ? "" : " disabled");
      const imgWrap = document.createElement("div");
      imgWrap.className = "purchase-card-image-wrap";
      const img = document.createElement("img");
      img.className = "purchase-card-image";
      img.src = getBuildingImageUrl(b);
      img.alt = b.name;
      img.loading = "lazy";
      img.onerror = () => imgWrap.classList.add("failed");
      const imgFallback = document.createElement("span");
      imgFallback.className = "img-fallback";
      imgFallback.textContent = b.icon || "🏠";
      imgWrap.appendChild(img);
      imgWrap.appendChild(imgFallback);
      const body = document.createElement("div");
      body.className = "purchase-card-body";
      body.innerHTML = `
        <span class="purchase-card-name">${b.name}</span>
        <span class="purchase-card-stats">x${count} · 👥 +${b.population} · 💰 ${fmtMoney(b.incomePerHour)}/час</span>
        <span class="purchase-card-price">${fmtMoney(b.cost)} ₽</span>
      `;
      const action = document.createElement("div");
      action.className = "purchase-card-action";
      const buyBtn = document.createElement("button");
      buyBtn.type = "button";
      buyBtn.className = "buy-btn";
      buyBtn.textContent = "Купить";
      buyBtn.addEventListener("click", (e) => { e.stopPropagation(); if (affordable) buyBuilding(b); });
      action.appendChild(buyBtn);
      card.appendChild(imgWrap);
      card.appendChild(body);
      card.appendChild(action);
      card.addEventListener("click", (e) => { if (!e.target.closest(".buy-btn") && affordable) buyBuilding(b); });
      el.choices.appendChild(card);
    });
  } else {
    Object.entries(BONUS_UPGRADES).forEach(([id, u]) => {
      const level = state.upgradeLevels[id] || 0;
      const value = u.getValue(level);
      const nextCost = getUpgradeCost(id, level);
      const card = document.createElement("div");
      card.className = "bonus-card";
      let valueText = "";
      if (id === "click") valueText = `${fmtMoney(value)} ₽ за клик`;
      else if (id === "maxEnergy") valueText = `${value} ед.`;
      else if (id === "energyPerHour") valueText = `${value} ед/час`;
      card.innerHTML = `
        <h4>${u.name}</h4>
        <p>${u.desc}</p>
        <p style="margin-top:6px;"><b>Сейчас:</b> ${valueText}</p>
        <p><b>След. уровень:</b> ${fmtMoney(nextCost)} ₽</p>
      `;
      const buyBtn = document.createElement("button");
      buyBtn.className = "choice-btn";
      buyBtn.style.marginTop = "8px";
      buyBtn.textContent = `Улучшить (${fmtMoney(nextCost)} ₽)`;
      buyBtn.addEventListener("click", () => buyUpgrade(id));
      card.appendChild(buyBtn);
      el.choices.appendChild(card);
    });
  }
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
  state.population += building.population || 0;
  state.economy += building.economy || 0;
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
      if (!state.upgradeLevels) state.upgradeLevels = { click: 0, maxEnergy: 0, energyPerHour: 0 };
      state.clickIncome = BONUS_UPGRADES.click.getValue(state.upgradeLevels.click || 0);
      state.maxEnergy = BONUS_UPGRADES.maxEnergy.getValue(state.upgradeLevels.maxEnergy || 0);
      state.energyPerHour = BONUS_UPGRADES.energyPerHour.getValue(state.upgradeLevels.energyPerHour || 0);
      state.energy = Math.min(state.energy, state.maxEnergy);
    }
  } catch {
    state = { ...initialState };
  }
  applyHourlyIncome();
  applyHourlyEnergy();
  updateResourcesUI();
  renderEconomy();
}

function saveState() {
  try {
    window.localStorage.setItem("tg_city_president_state", JSON.stringify(state));
  } catch {}
}

function initTelegram() {
  if (!window.Telegram || !window.Telegram.WebApp) return;
  const tg = window.Telegram.WebApp;
  tg.ready();
  tg.expand();
}

document.addEventListener("DOMContentLoaded", () => {
  initTelegram();
  restoreProgress();
  setActiveTab("city");

  document.getElementById("bottom-nav").addEventListener("click", (e) => {
    const btn = e.target.closest(".nav-btn");
    if (btn && btn.dataset.tab) setActiveTab(btn.dataset.tab);
  });
});
