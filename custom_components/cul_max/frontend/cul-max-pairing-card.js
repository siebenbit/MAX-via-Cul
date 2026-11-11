const { cardStyles } = await import(new URL("./cul-max-card-styles.js" + new URL(import.meta.url).search, import.meta.url));
const { openDeviceDialog } = await import(new URL("./cul-max-device-dialog.js" + new URL(import.meta.url).search, import.meta.url));
const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
class CulMaxPairingCard extends HTMLElement {
  static getStubConfig() { return { title: "MAX! Geräte anlernen", duration: 60 }; }
  static getConfigElement() { return document.createElement("cul-max-pairing-card-editor"); }
  constructor() { super(); this.attachShadow({ mode: "open" }); this._epoch = 0; this._data = { controllers: [] }; }
  setConfig(config) {
    const duration = config.duration ?? 60;
    if (!Number.isInteger(duration) || duration < 1 || duration > 3600) throw Error("Dauer: 1 bis 3600 Sekunden");
    this._config = { title: "MAX! Geräte anlernen", ...config, duration };
    this._render();
  }
  set hass(hass) {
    const changed = this._hass?.connection !== hass.connection || this._hass?.user?.is_admin !== hass.user?.is_admin;
    this._hass = hass;
    if (changed && this.isConnected) this._connect();
  }
  connectedCallback() { if (this._hass) this._connect(); }
  disconnectedCallback() { this._disconnect(); }
  getCardSize() { return 4; }
  _disconnect() {
    this._epoch++;
    this._online = false;
    this._unsubscribe?.(); this._unsubscribe = null;
    this._connection?.removeEventListener("ready", this._ready);
    this._connection?.removeEventListener("disconnected", this._lost);
    clearInterval(this._timer); this._timer = null;
  }
  async _connect() {
    this._disconnect();
    if (!this._hass.user?.is_admin) { this._data = { controllers: [] }; this._error = "Nur für Administratoren verfügbar."; this._render(); return; }
    const epoch = this._epoch;
    this._connection = this._hass.connection;
    this._ready = () => this._connect();
    this._lost = () => { this._epoch++; this._unsubscribe?.(); this._unsubscribe = null; this._online = false; this._error = "Verbindung getrennt – Anzeige möglicherweise veraltet"; clearInterval(this._timer); this._render(); };
    this._connection.addEventListener("ready", this._ready);
    this._connection.addEventListener("disconnected", this._lost);
    try {
      const unsub = await this._connection.subscribeMessage((data) => {
        if (epoch !== this._epoch || !this.isConnected) return;
        this._data = data; this._online = true; this._error = ""; this._render();
      }, { type: "cul_max/pairing/subscribe" });
      if (epoch !== this._epoch || !this.isConnected) unsub(); else this._unsubscribe = unsub;
    } catch (error) { if (epoch === this._epoch) { this._error = error.message || String(error); this._render(); } }
  }
  _controller() {
    const controllers = this._data.controllers;
    const id = this._config?.config_entry_id || this._selected;
    return id ? controllers.find((c) => c.config_entry_id === id) : controllers.length === 1 ? controllers[0] : null;
  }
  async _start() {
    const controller = this._controller();
    if (!this._online || !controller?.connected || controller.active || this._busy) return;
    this._busy = true; this._render();
    const epoch = this._epoch;
    try {
      const data = await this._hass.callWS({ type: "cul_max/pairing/start", config_entry_id: controller.config_entry_id, duration: this._config.duration });
      if (epoch === this._epoch && data?.controllers) { this._data = data; this._error = ""; }
    } catch (error) { if (epoch === this._epoch) this._error = error.message || String(error); }
    finally { this._busy = false; if (epoch === this._epoch) this._render(); }
  }
  async _editDevice(deviceId) {
    if (this._editing || !this._online) return;
    const device = this._controller()?.devices.find(item => item.device_id === deviceId);
    if (!device) return;
    this._editing = true;
    this._error = "";
    this._render();
    const epoch = this._epoch;
    try {
      await openDeviceDialog(this, this._hass, deviceId, device.device_type,
        () => epoch === this._epoch && this.isConnected && this._online, () => this._hass);
    } catch (error) {
      if (epoch === this._epoch) this._error = error.message || String(error);
    } finally {
      this._editing = false;
      if (this.isConnected) {
        this._render();
        this.shadowRoot.getElementById(`edit-${deviceId}`)?.focus();
      }
    }
  }
  _render() {
    if (!this._config) return;
    const c = this._controller();
    const focus = this.shadowRoot.activeElement?.id;
    clearInterval(this._timer); this._timer = null;
    // Keep the modal mounted independently of live result-list rendering.
    if (!this.shadowRoot.querySelector("#pairing-content")) this.shadowRoot.innerHTML = '<div id="pairing-content"></div>';
    const content = this.shadowRoot.querySelector("#pairing-content") || this.shadowRoot;
    content.innerHTML = `<style>${cardStyles}
      .device-row{display:grid;grid-template-columns:minmax(0,1fr) 11rem;align-items:start;gap:16px;border-top:1px solid var(--divider-color);padding:16px 0}
      .device-row:first-of-type{border-top:0;padding-top:0}.device-row:last-child{padding-bottom:0}
      .device-row>.edit-device{width:11rem;max-width:100%;justify-self:start}
      .device-info{min-width:0;overflow-wrap:anywhere;display:grid;gap:6px;justify-items:start}.device-name{font-weight:600;line-height:1.35}.status{margin-top:12px}
      @media(max-width:480px){.device-row{grid-template-columns:minmax(0,1fr);gap:12px}}
      </style><ha-card><div class="header"><h2>${escape(this._config.title)}</h2></div>
      ${!this._config.config_entry_id && this._data.controllers.length > 1 ? `<div class="actions"><label>CUL-Anschluss <select id="controller"><option value="">Bitte auswählen</option>${this._data.controllers.map((item) => `<option value="${escape(item.config_entry_id)}" ${item === c ? "selected" : ""}>${escape(item.name)}</option>`).join("")}</select></label></div>` : ""}
      ${this._error ? `<p class="error" role="alert">${escape(this._error)}</p>` : ""}
      <div class="actions"><button id="start" class="primary" ${!this._online || !c?.connected || c.active || this._busy ? "disabled" : ""}>Pairing starten</button></div>
      <div class="status" role="status">${c?.active ? 'Pairing aktiv · <span id="countdown"></span><p class="muted">Jetzt Pairing am Gerät aktivieren.</p>' : c?.session_id ? "Pairing beendet" : c ? "Bereit zum Anlernen" : "Bitte einen geladenen CUL-Anschluss auswählen."}</div>
      ${c && !c.connected ? '<p class="error">CUL ist nicht verbunden.</p>' : ""}
      ${c?.error ? `<p class="error">${escape(c.error)}</p>` : ""}
      <section><h3>Gefundene Geräte</h3>${(c?.devices || []).map((d) => `<div class="device-row"><div class="device-info"><div class="device-name">${escape(d.name)}</div><div class="muted">${escape(d.device_type)} · ${escape(d.serial_number || d.address)}</div><div>${escape(d.area_name || "Noch keinem Raum zugeordnet")}</div>${d.already_known ? '<span class="badge">Erneut angelernt</span>' : ""}</div>${d.device_id ? `<button id="edit-${escape(d.device_id)}" class="edit-device" data-edit="${escape(d.device_id)}" ${this._editing || !this._online ? "disabled" : ""}>Gerät bearbeiten</button>` : d.removed ? '<small>Gerät nicht mehr vorhanden</small>' : '<small>Gerät wird in HA angelegt</small>'}</div>`).join("") || '<p class="muted">Noch keine Geräte angelernt.</p>'}</section></ha-card>`;
    this.shadowRoot.querySelectorAll("[data-edit]").forEach((button) => button.addEventListener("click", () => this._editDevice(button.dataset.edit)));
    this.shadowRoot.querySelector("#start")?.addEventListener("click", () => this._start());
    this.shadowRoot.querySelector("#controller")?.addEventListener("change", (event) => { this._selected = event.target.value; this._render(); });
    if (focus) this.shadowRoot.getElementById(focus)?.focus();
    if (c?.active && this._online && this.isConnected) {
      const update = () => { const node = this.shadowRoot.querySelector("#countdown"); if (node) { const seconds = Math.max(0, Math.ceil((Date.parse(c.ends_at) - Date.now()) / 1000)); node.textContent = seconds ? `noch ${seconds} Sekunden` : "Abschluss ausstehend"; } };
      update(); this._timer = setInterval(update, 1000);
    }
  }
}
class CulMaxPairingCardEditor extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: "open" }); }
  setConfig(config) { this._config = config; this._render(); }
  set hass(hass) { this._hass = hass; if (this.isConnected) this._loadControllers(); }
  connectedCallback() { if (this._hass) this._loadControllers(); }
  disconnectedCallback() { this._editorEpoch = (this._editorEpoch || 0) + 1; this._editorUnsub?.(); this._editorUnsub = null; this._editorConnection = null; }
  async _loadControllers() {
    if (this._editorConnection === this._hass.connection) return;
    this.disconnectedCallback();
    this._editorConnection = this._hass.connection;
    const epoch = this._editorEpoch;
    try {
      const unsub = await this._editorConnection.subscribeMessage((data) => { if (epoch === this._editorEpoch) { this._controllers = data.controllers; this._updateControllerOptions(); } }, { type: "cul_max/pairing/subscribe" });
      if (epoch !== this._editorEpoch) unsub(); else this._editorUnsub = unsub;
    } catch (_) { /* The card displays connection and permission errors. */ }
  }
  _updateControllerOptions() {
    const select = this.shadowRoot.querySelector('select[data-key="config_entry_id"]');
    if (!select) return;
    const options = `<option value="">In der Karte auswählen</option>${(this._controllers || []).map(c => `<option value="${escape(c.config_entry_id)}" ${c.config_entry_id === this._config.config_entry_id ? "selected" : ""}>${escape(c.name)}</option>`).join("")}`;
    if (this._optionsMarkup === options) return;
    this._optionsMarkup = options;
    select.innerHTML = options;
    select.value = this._config.config_entry_id || "";
  }
  _render() {
    if (!this._config) return;
    this.shadowRoot.innerHTML = `<style>${cardStyles}label{display:block;margin:12px 0}input{display:block;width:100%}</style>${[["title", "Titel", "text", this._config.title || "MAX! Geräte anlernen"], ["duration", "Pairing-Dauer in Sekunden", "number", this._config.duration ?? 60]].map(([key, label, type, value]) => `<label>${label}<input data-key="${key}" type="${type}" value="${escape(value)}" ${type === "number" ? 'min="1" max="3600" step="1"' : ""}></label>`).join("")}<label>CUL-Anschluss<select data-key="config_entry_id"><option value="">In der Karte auswählen</option>${(this._controllers || []).map(c => `<option value="${escape(c.config_entry_id)}" ${c.config_entry_id === this._config.config_entry_id ? "selected" : ""}>${escape(c.name)}</option>`).join("")}</select></label>`;
    this.shadowRoot.querySelectorAll("input,select").forEach((input) => input.addEventListener("change", () => {
      const key = input.dataset.key;
      this._config = { ...this._config, [key]: key === "duration" ? Number(input.value) : input.value };
      if (!this._config.config_entry_id) delete this._config.config_entry_id;
      this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true }));
    }));
  }
}
if (!customElements.get("cul-max-pairing-card")) customElements.define("cul-max-pairing-card", CulMaxPairingCard);
if (!customElements.get("cul-max-pairing-card-editor")) customElements.define("cul-max-pairing-card-editor", CulMaxPairingCardEditor);
window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "cul-max-pairing-card")) window.customCards.push({ type: "cul-max-pairing-card", name: "MAX! Geräte anlernen", description: "Pairing starten und angelernte Geräte bearbeiten" });
