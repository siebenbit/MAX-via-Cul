const { cardStyles } = await import(new URL("./cul-max-card-styles.js" + new URL(import.meta.url).search, import.meta.url));
/* Queue UI uses HA service responses and the queue sensor's revision signal. */
const queueStatuses = {
  debouncing: "Wird gesammelt",
  queued: "Wartet", waiting_for_credits: "Wartet auf Funkbudget", sending: "Wird gesendet",
  awaiting_ack: "Wartet auf Bestätigung", retrying: "Wiederholungsversuch", completed: "Abgeschlossen",
  failed: "Fehlgeschlagen", cancelled: "Abgebrochen", superseded: "Ersetzt", cancelling: "Wird abgebrochen",
};
const escapeQueueText = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[c]));

class CulMaxQueueCard extends HTMLElement {
  static getConfigElement() { return document.createElement("cul-max-queue-card-editor"); }
  static getStubConfig() { return { title: "MAX! Sendewarteschlange" }; }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._selected = new Set();
    this._onReady = () => { this._epoch++; this._refresh(); };
    this._onDisconnected = () => { this._epoch++; this._error = "Verbindung getrennt – Anzeige möglicherweise veraltet"; this._render(); };
    this._epoch = 0;
    this._busy = false;
  }

  setConfig(config) {
    this._config = { title: "MAX! Sendewarteschlange", ...config };
    this._epoch++;
    this._selected.clear();
    this._render();
    this._refresh();
  }

  set hass(hass) {
    if (this._hass?.connection !== hass.connection) {
      this._detach();
      this._hass = hass;
      if (this.isConnected) this._attach();
    } else this._hass = hass;
    const revisions = Object.values(hass.states || {}).filter((state) => state.attributes?.cul_max_queue)
      .map((state) => `${state.attributes.config_entry_id}:${state.attributes.session_id}:${state.attributes.revision}:${state.attributes.budget_revision ?? 0}`).sort().join("|");
    if (revisions !== this._revisionSignal) {
      this._revisionSignal = revisions;
      this._refresh();
    }
    if (!this._data && !this._loading) this._refresh();
  }

  connectedCallback() { this._attach(); this._refresh(); }
  disconnectedCallback() { this._epoch++; this._detach(); }
  _attach() {
    if (!this._hass?.connection || this._attached === this._hass.connection) return;
    this._attached = this._hass.connection;
    this._attached.addEventListener("ready", this._onReady);
    this._attached.addEventListener("disconnected", this._onDisconnected);
    this._watchDeviceNames(this._attached);
  }
  async _watchDeviceNames(connection) {
    const epoch = this._registryEpoch = (this._registryEpoch || 0) + 1;
    if (typeof connection.subscribeEvents !== "function") return;
    try {
      const unsubscribe = await connection.subscribeEvents((event) => {
        if (epoch !== this._registryEpoch || !this.isConnected) return;
        const { action, changes = {} } = event.data || {};
        if (action !== "update" || "name" in changes || "name_by_user" in changes) this._refresh();
      }, "device_registry_updated");
      if (epoch !== this._registryEpoch || !this.isConnected) unsubscribe();
      else { this._registryUnsubscribe = unsubscribe; this._registryError = null; this._refresh(); }
    } catch (error) {
      if (epoch === this._registryEpoch) {
        this._registryError = `Namensänderungen können nicht automatisch geladen werden: ${error.message || error}`;
        this._render();
      }
    }
  }
  _detach() {
    this._registryEpoch = (this._registryEpoch || 0) + 1;
    this._registryUnsubscribe?.();
    this._registryUnsubscribe = null;
    this._attached?.removeEventListener("ready", this._onReady);
    this._attached?.removeEventListener("disconnected", this._onDisconnected);
    this._attached = null;
    this._stopCountdown();
  }
  _stopCountdown() {
    if (this._countdownTimer !== undefined) window.clearInterval(this._countdownTimer);
    this._countdownTimer = undefined;
  }
  _syncCountdown(items) {
    if (!this.isConnected || !items.some((item) => item.status === "debouncing") && !this._controller()?.budget?.next_attempt_at) {
      this._stopCountdown();
      return;
    }
    const update = () => this.shadowRoot.querySelectorAll("[data-debounce-until]").forEach((node) => {
      const remaining = Math.max(0, (Date.parse(node.dataset.debounceUntil) - Date.now()) / 1000);
      node.textContent = `${remaining.toFixed(1)} s`;
    });
    const updateBudget = () => this.shadowRoot.querySelectorAll("[data-budget-until]").forEach((node) => {
      const seconds = Math.ceil((Date.parse(node.dataset.budgetUntil) - Date.now()) / 1000);
      node.textContent = seconds > 0 ? `Nächste Budgetprüfung in ${seconds} s` : "Budgetprüfung ausstehend";
    });
    const tick = () => { update(); updateBudget(); };
    tick();
    if (this._countdownTimer === undefined) this._countdownTimer = window.setInterval(tick, 100);
  }
  getCardSize() { return 5; }

  async _call(service, data = {}) {
    const result = await this._hass.callWS({ type: "call_service", domain: "cul_max", service,
      service_data: data, return_response: true });
    return result.response;
  }

  async _refresh() {
    if (!this.isConnected || !this._hass || !this._config) return;
    if (this._loading) { this._refreshAgain = true; return; }
    this._loading = true;
    const epoch = this._epoch;
    try {
      const data = await this._call("get_queue");
      if (epoch !== this._epoch) return;
      this._data = data;
      this._error = null;
      const live = new Set((data.entries || []).filter((entry) => entry.cancellable).map((entry) => entry.id));
      this._selected = new Set([...this._selected].filter((id) => live.has(id)));
    } catch (err) {
      if (epoch === this._epoch) this._error = err.message || String(err);
    } finally {
      this._loading = false;
      this._render();
      if (this._refreshAgain) { this._refreshAgain = false; this._refresh(); }
    }
  }

  _controller() {
    const controllers = this._data?.controllers || [];
    const id = this._config?.config_entry_id || this._controllerId;
    return id ? controllers.find((item) => item.config_entry_id === id) || null
      : controllers.length === 1 ? controllers[0] : null;
  }

  _items() {
    const controller = this._controller();
    if (!controller) return [];
    const config = this._config || {};
    const entries = (controller.entries || []).filter((entry) => entry.scope === "general");
    const jobs = (controller.jobs || []).filter((job) => !["completed", "cancelled"].includes(job.status))
      .map((job) => ({ ...job, command_type: job.block === "temperature" ? "Temperaturparameter" : job.kind === "climate" ? "Wochenplan" : "Konfiguration",
        cancellable: false, attempts: job.attempts || 0 }));
    return [...entries, ...jobs].filter((entry) =>
      (!config.address || entry.device_address === config.address.toUpperCase()) &&
      (!config.status || entry.status === config.status) &&
      (!config.scope || entry.scope === config.scope));
  }

  async _action(service, data, message) {
    if (this._busy) return;
    this._busy = true;
    this._message = null;
    this._render();
    try {
      const response = await this._call(service, data);
      this._message = response?.protected?.length ? `${message} Geschützte Einträge bleiben erhalten.` : message;
      this._selected.clear();
    } catch (err) { this._message = `Nicht ausgeführt: ${err.message || err}`; }
    finally { this._busy = false; await this._refresh(); }
  }

  _time(value) {
    const date = new Date(value);
    if (!value || !Number.isFinite(date.getTime())) return "Zeit unbekannt";
    const locale = this._hass?.locale?.language || "de-DE";
    const zone = {timeZone: this._hass?.config?.time_zone};
    const day = new Intl.DateTimeFormat(locale, {...zone, day:"2-digit",month:"2-digit",year:"numeric"});
    const time = new Intl.DateTimeFormat(locale, {...zone, hour:"2-digit",minute:"2-digit",second:"2-digit"}).format(date);
    return day.format(date) === day.format(new Date()) ? time : day.format(date) + ", " + time;
  }
  _render() {
    if (!this.shadowRoot || !this._config) return;
    const opened = new Set([...this.shadowRoot.querySelectorAll("details[open][data-preserve]")].map((node) => node.dataset.preserve));
    const focused = this.shadowRoot.activeElement;
    const focusSelector = focused?.id ? "#" + focused.id : focused?.dataset.delete ? `[data-delete="${focused.dataset.delete}"]` : focused?.dataset.cancel ? `[data-cancel="${focused.dataset.cancel}"]` : focused?.dataset.select ? `[data-select="${focused.dataset.select}"]` : focused?.tagName === "SUMMARY" && focused.parentElement.dataset.preserve ? `details[data-preserve="${focused.parentElement.dataset.preserve}"] > summary` : null;
    const h = escapeQueueText;
    const controller = this._controller();
    const next = controller?.next_dispatch;
    const isNext = (item) => !!next && (item.id === next.entry_id || item.id === next.job_id);
    const rank = (item) => ["sending", "awaiting_ack", "retrying", "cancelling"].includes(item.status) ? 0 : isNext(item) ? 1 : 2;
    const items = this._items().sort((a, b) => rank(a) - rank(b) || (Date.parse(a.created_at) || 0) - (Date.parse(b.created_at) || 0) || a.id.localeCompare(b.id));
    const waiting = items.filter((item) => ["debouncing", "queued", "waiting_for_credits"].includes(item.status)).length;
    const active = items.filter((item) => ["sending", "awaiting_ack", "retrying", "cancelling"].includes(item.status)).length;
    const credits = controller?.budget;
    this.shadowRoot.innerHTML = `
      <style>${cardStyles}
        h2 { margin-bottom:12px; }
        .summary,.muted { color:var(--secondary-text-color); font-size:13px; } .summary { display:flex; gap:12px; flex-wrap:wrap; }
        .row { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:8px; padding:14px 0; border-top:1px solid var(--divider-color); }
        .row > button { align-self:start; max-width:150px; }
        .body { min-width:0; overflow-wrap:anywhere; } .device { display:flex;align-items:center;gap:8px;font-weight:600; margin-bottom:5px; } .description { margin-bottom:5px; }
        .rows { margin-top:14px; }
        button { cursor:pointer; } button:disabled { cursor:default; color:var(--disabled-text-color); } button:focus-visible,select:focus-visible { outline:2px solid var(--primary-color); }
        .actions { display:flex; gap:8px; flex-wrap:wrap; margin-top:12px; }  .error { color:var(--error-color); }
        pre { white-space:pre-wrap; overflow-wrap:anywhere; font-size:12px; } summary { cursor:pointer; margin-top:6px; } label { display:block; }
        @media(max-width:380px) { .row { grid-template-columns:minmax(0,1fr); } .row button { justify-self:start;max-width:none; } }
      </style>
      <ha-card><h2>${h(this._config.title)}</h2>
      ${(this._data?.controllers?.length || 0) > 1 && !this._config.config_entry_id ? `<label>Controller <select id="controller"><option value="">Bitte wählen</option>${this._data.controllers.map((c) => `<option value="${h(c.config_entry_id)}" ${controller === c ? "selected" : ""}>${h(c.name)}</option>`).join("")}</select></label>` : ""}
      <div class="summary"><span>Wartend: ${waiting}</span><span>Aktiv: ${active}</span></div>
      <div class="notice" role="status">${h(!credits?.budget_valid ? credits?.last_budget_error ? "Funkbudget nicht verfügbar" : "Funkbudget unbekannt" : credits.waiting_for_budget ? "Wartet auf Funkbudget" : active ? "Übertragung läuft" : items.length ? "Aufträge warten" : "Keine wartenden Aufträge")}${credits?.waiting_for_budget && credits?.next_attempt_at ? ` · <span data-budget-until="${h(credits.next_attempt_at)}"></span>` : ""}</div>
      ${next && !items.some(isNext) ? '<div class="muted">Der nächste Versand betrifft einen ausgeblendeten Auftrag.</div>' : ""}
      ${credits ? `<details data-preserve="budget"><summary>Funkdetails</summary><div class="muted">Zuletzt gemeldet: ${h(credits.reported_credits ?? "unbekannt")} Credits · Gemessen: ${h(this._time(credits.last_budget_query_at))}<br>Nächstes Paket einschließlich Reserve: ${h(credits.required_credits ?? "unbekannt")} Credits</div>${credits.last_budget_error ? `<div class="error">${h(credits.last_budget_error)}</div>` : ""}</details>` : ""}
      ${this._error ? `<div class="notice error" role="alert">${h(this._error)}</div><button id="reload">Erneut laden</button>` : ""}
      ${this._registryError ? `<div class="notice error" role="alert">${h(this._registryError)}</div>` : ""}
      ${this._message ? `<div class="notice" role="status">${h(this._message)}</div>` : ""}
      <div class="rows">${items.map((item) => {
        const isJob = item.scope === "configuration";
        const description = item.description.replace(/^SetTemperature /, "Solltemperatur → ");
        const created = this._time(item.created_at);
        return `<div class="row"><div class="body"><div class="device">${item.cancellable ? `<input type="checkbox" aria-label="${h(item.device_name)} auswählen" data-select="${h(item.id)}" ${this._selected.has(item.id) ? "checked" : ""}> ` : ""}${h(item.device_name || item.device_address)}</div>
          <div class="description">${h(isJob ? item.command_type : description)}</div>${isNext(item) ? '<span class="badge">Als Nächstes vorgesehen</span>' : ""}<div class="muted">Eingereiht: ${h(created)}</div><div>${h(queueStatuses[item.status] || item.status)}${item.status === "debouncing" ? ` · <span data-debounce-until="${h(item.debounce_until)}"></span>` : ""}</div>

          ${isJob ? `<div class="muted">${item.completed_steps?.length || 0} / ${item.steps?.length || 0} Schritte übertragen · ${item.confirmed_steps?.length || 0} bestätigt</div>` : ""}
          ${item.last_error ? `<div class="error">${h(item.last_error)}</div>` : ""}
          <details data-preserve="${h(item.id)}"><summary>Details</summary><div class="muted">Versuche: ${h(item.attempts)}</div><pre>${h(JSON.stringify(item, null, 2))}</pre></details></div>
          <button data-${isJob ? "cancel" : "delete"}="${h(item.id)}" ${this._busy || (!isJob && !item.cancellable) || item.status === "cancelling" ? "disabled" : ""} title="${h(item.blocked_reason || "")}">${isJob ? "Auftrag abbrechen" : item.cancellable ? "Löschen" : "Nicht löschbar"}</button></div>`;
      }).join("") || `<div class="${controller ? "empty-queue" : "notice"}">${controller ? "" : this._data ? "Controller auswählen" : "Warteschlange wird geladen …"}</div>`}</div>
      <div class="actions"><button id="clear" ${!controller || this._busy || !items.some((item) => item.cancellable) ? "disabled" : ""}>Wartende Befehle leeren</button>
      <button id="delete-selected" ${!this._selected.size || this._busy ? "disabled" : ""}>Auswahl löschen (${this._selected.size})</button></div></ha-card>`;
    for (const detail of this.shadowRoot.querySelectorAll("details[data-preserve]")) detail.open = opened.has(detail.dataset.preserve);
    if (focusSelector) this.shadowRoot.querySelector(focusSelector)?.focus();
    this._syncCountdown(items);
    this.shadowRoot.querySelector("#reload")?.addEventListener("click", () => this._refresh());
    this.shadowRoot.querySelector("#controller")?.addEventListener("change", (event) => { this._controllerId = event.target.value; this._selected.clear(); this._render(); });
    this.shadowRoot.querySelectorAll("[data-select]").forEach((box) => box.addEventListener("change", () => { box.checked ? this._selected.add(box.dataset.select) : this._selected.delete(box.dataset.select); this._render(); }));
    this.shadowRoot.querySelectorAll("[data-delete]").forEach((button) => button.addEventListener("click", () => this._action("delete_queue_entry", { entry_id: button.dataset.delete }, "Befehl gelöscht.")));
    this.shadowRoot.querySelectorAll("[data-cancel]").forEach((button) => button.addEventListener("click", () => {
      if (window.confirm("Gesamten Konfigurationsauftrag abbrechen? Das laufende Teilpaket wird noch abgeschlossen. Bereits übertragene Schritte werden nicht zurückgenommen."))
        this._action("cancel_config_job", { config_entry_id: controller.config_entry_id, job_id: button.dataset.cancel, confirm: true }, "Konfigurationsabbruch gespeichert.");
    }));
    this.shadowRoot.querySelector("#clear")?.addEventListener("click", () => {
      if (window.confirm("Alle abbrechbaren allgemeinen Befehle dieses Controllers und Gerätefilters löschen? Konfigurationsaufträge bleiben erhalten."))
        this._action("clear_queue", { config_entry_id: controller.config_entry_id, ...(this._config.address ? { address: this._config.address } : {}) }, "Wartende Befehle gelöscht.");
    });
    this.shadowRoot.querySelector("#delete-selected")?.addEventListener("click", () => this._action("delete_queue_entry", { entry_ids: [...this._selected] }, "Auswahl gelöscht."));
  }
}

class CulMaxQueueCardEditor extends HTMLElement {
  setConfig(config) { this._config = { ...config }; this._render(); }
  set hass(hass) { this._hass = hass; this._render(); }
  _render() {
    if (!this._config) return;
    const h = escapeQueueText;
    const controllers = Object.values(this._hass?.states || {}).filter((state) => state.attributes?.cul_max_queue);
    this.innerHTML = `<style>cul-max-queue-card-editor label{display:block;margin:12px 0}cul-max-queue-card-editor input,cul-max-queue-card-editor select{display:block;box-sizing:border-box;width:100%;padding:9px;color:var(--primary-text-color);background:var(--secondary-background-color);border:1px solid var(--divider-color);border-radius:6px}</style>
      <label>Titel<input data-key="title" value="${h(this._config.title || "MAX! Sendewarteschlange")}"></label>
      <label>Controller<select data-key="config_entry_id"><option value="">Automatisch / Auswahl in Karte</option>${controllers.map((state) => `<option value="${h(state.attributes.config_entry_id)}">${h(state.attributes.friendly_name || state.entity_id)}</option>`).join("")}</select></label>
      <label>Geräteadresse (optional)<input data-key="address" value="${h(this._config.address)}"></label>
      <label>Status<select data-key="status"><option value="">Alle</option>${Object.entries(queueStatuses).map(([key, label]) => `<option value="${key}">${label}</option>`).join("")}</select></label>
      <label>Bereich<select data-key="scope"><option value="">Alle</option><option value="general">Allgemeine Befehle</option><option value="configuration">Konfigurationsaufträge</option></select></label>`;
    this.querySelectorAll("[data-key]").forEach((field) => {
      if (field.tagName === "SELECT") field.value = this._config[field.dataset.key] || "";
      field.addEventListener("change", () => {
        this._config = { ...this._config, [field.dataset.key]: field.value };
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true }));
      });
    });
  }
}
if (!customElements.get("cul-max-queue-card")) customElements.define("cul-max-queue-card", CulMaxQueueCard);
if (!customElements.get("cul-max-queue-card-editor")) customElements.define("cul-max-queue-card-editor", CulMaxQueueCardEditor);
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "cul-max-queue-card")) window.customCards.push({ type: "cul-max-queue-card", name: "MAX! Sendewarteschlange", description: "Befehle ansehen, ersetzen und abbrechen" });
