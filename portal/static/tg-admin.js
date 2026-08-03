(() => {
  "use strict";
  const apiBase = "/portal/api/tg-admin";
  const tg = window.Telegram && window.Telegram.WebApp;
  const app = document.getElementById("app");
  const outside = document.getElementById("outside");
  const notice = document.getElementById("notice");
  const usersList = document.getElementById("users-list");
  const requestsList = document.getElementById("requests-list");
  const search = document.getElementById("user-search");
  const state = { users: [], requests: [], initData: "", ready: false };

  function applyTelegramTheme() {
    if (!tg || !tg.themeParams) return;
    const variables = {
      bg_color: "--tg-theme-bg-color",
      secondary_bg_color: "--tg-theme-secondary-bg-color",
      text_color: "--tg-theme-text-color",
      hint_color: "--tg-theme-hint-color",
      button_color: "--tg-theme-button-color",
      button_text_color: "--tg-theme-button-text-color"
    };
    Object.entries(variables).forEach(([key, variable]) => {
      if (tg.themeParams[key]) document.documentElement.style.setProperty(variable, tg.themeParams[key]);
    });
  }

  const addText = (node, value) => node.append(document.createTextNode(value == null || value === "" ? "—" : String(value)));
  const make = (tag, className, value) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined) addText(node, value);
    return node;
  };
  const setNotice = (message = "", isError = false) => {
    notice.textContent = message;
    notice.classList.toggle("is-error", isError);
  };
  const messageFor = (payload) => payload && payload.error && payload.error.message
    ? payload.error.message : "Не удалось выполнить действие. Попробуйте ещё раз.";
  const newKey = () => window.crypto && crypto.randomUUID
    ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}-tg-admin`;

  async function api(path, options = {}) {
    const headers = { "X-Telegram-Init-Data": state.initData, ...(options.headers || {}) };
    const response = await fetch(`${apiBase}${path}`, { ...options, headers });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      const error = new Error(messageFor(payload));
      error.retryable = Boolean(payload && payload.error && payload.error.retryable);
      throw error;
    }
    return payload;
  }

  async function runAction(path, button, successText) {
    const key = newKey(); // Один ключ привязан к одному нажатию, включая повтор запроса.
    button.disabled = true;
    setNotice("");
    const send = () => api(path, { method: "POST", headers: { "Idempotency-Key": key } });
    try {
      let result;
      try { result = await send(); }
      catch (error) {
        if (!error.retryable && !(error instanceof TypeError)) throw error;
        result = await send();
      }
      button.dataset.actionCompleted = "true";
      setNotice(result.replayed ? "Действие уже было выполнено ранее." : successText);
      try {
        await loadData();
      } catch (error) {
        setNotice("Действие выполнено, но обновить данные не удалось. Обновите данные позже.", true);
      }
    } catch (error) {
      setNotice(error.message, true);
      button.disabled = false;
    }
  }

  function action(label, path, confirmation, className = "") {
    const button = make("button", `action ${className}`, label);
    button.type = "button";
    button.disabled = !state.ready;
    button.addEventListener("click", () => {
      if (!state.ready || button.dataset.actionCompleted === "true" || !window.confirm(confirmation)) return;
      runAction(path, button, "Изменения сохранены.");
    });
    return button;
  }

  function renderUsers() {
    const needle = search.value.trim().toLocaleLowerCase("ru");
    usersList.replaceChildren();
    const users = state.users.filter((user) => [user.display_name, user.username, user.client_email]
      .join(" ").toLocaleLowerCase("ru").includes(needle));
    if (!users.length) { usersList.append(make("p", "empty", "Пользователи не найдены.")); return; }
    users.forEach((user) => {
      const card = make("article", "card");
      const header = make("div", "card-header");
      const title = make("div");
      title.append(make("h2", "", user.display_name));
      title.append(make("p", "muted", `${user.username} · ${user.client_email}`));
      header.append(title, make("span", `badge ${user.vpn_state}`, user.vpn_state));
      card.append(header);
      card.append(make("p", "details", `Срок: ${user.expiry_display || "неизвестно"}`));
      card.append(make("p", "details", `Трафик: ${user.traffic_used_display || "неизвестно"} · Telegram: ${user.telegram_linked ? "привязан" : "не привязан"}`));
      const encoded = encodeURIComponent(user.username);
      const actions = make("div", "actions");
      actions.append(
        action("Продлить на 30 дней", `/users/${encoded}/extend`, `Продлить доступ для «${user.display_name}» на настроенный срок?`, "primary"),
        action("Требовать оплату", `/users/${encoded}/require-payment`, `Приостановить VPN-доступ для «${user.display_name}» и включить требование оплаты?`, "danger"),
        action("Бесплатный доступ", `/users/${encoded}/set-free`, `Включить для «${user.display_name}» бессрочный бесплатный доступ?`)
      );
      card.append(actions);
      usersList.append(card);
    });
  }

  function renderRequests() {
    requestsList.replaceChildren();
    if (!state.requests.length) { requestsList.append(make("p", "empty", "Ожидающих заявок нет.")); return; }
    state.requests.forEach((request) => {
      const card = make("article", "card");
      card.append(make("h2", "", request.display_name));
      card.append(make("p", "muted", `${request.username} · ${request.client_email}`));
      card.append(make("p", "details", `Заявка #${request.id} от ${request.created_at}`));
      const actions = make("div", "actions");
      actions.append(
        action("Подтвердить +30 дней", `/payment-requests/${request.id}/approve`, `Подтвердить оплату пользователя «${request.display_name}» и продлить доступ на настроенный срок?`, "primary"),
        action("Отклонить", `/payment-requests/${request.id}/reject`, `Отклонить заявку пользователя «${request.display_name}»?`, "danger")
      );
      card.append(actions);
      requestsList.append(card);
    });
  }

  function renderSummary(summary) {
    document.getElementById("summary-active").textContent = summary.active;
    document.getElementById("summary-payment").textContent = summary.requires_payment;
    document.getElementById("summary-pending").textContent = summary.pending_payment_requests;
    document.getElementById("request-count").textContent = summary.pending_payment_requests ? `(${summary.pending_payment_requests})` : "";
  }

  async function loadData() {
    const [summary, users, requests] = await Promise.all([
      api("/summary"), api("/users"), api("/payment-requests?status=pending")
    ]);
    state.users = users.items || [];
    state.requests = requests.items || [];
    renderSummary(summary);
    renderUsers();
    renderRequests();
  }

  document.querySelectorAll(".tab").forEach((button) => button.addEventListener("click", () => {
    const usersTab = button.dataset.tab === "users";
    document.getElementById("users-panel").hidden = !usersTab;
    document.getElementById("requests-panel").hidden = usersTab;
    document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("is-active", tab === button));
  }));
  search.addEventListener("input", renderUsers);

  async function boot() {
    state.initData = tg && typeof tg.initData === "string" ? tg.initData : "";
    if (!state.initData) { outside.hidden = false; return; }
    applyTelegramTheme();
    tg.ready();
    tg.expand();
    app.hidden = false;
    try {
      const me = await api("/me"); // Сначала проверяем серверную Telegram-авторизацию.
      document.getElementById("principal").textContent = me.display_name || me.telegram_username || "Администратор";
      state.ready = true;
      await loadData();
    } catch (error) {
      setNotice(error.message, true);
    }
  }
  boot();
})();
