const { cardStyles } = await import(new URL("./cul-max-card-styles.js" + new URL(import.meta.url).search, import.meta.url));
const escape = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
class CulMaxRoomAssociationCard extends HTMLElement {
  static getConfigElement() { return document.createElement("cul-max-room-association-card-editor"); }
  static getStubConfig() { return { title: "MAX! Raumverknüpfung" }; }

  constructor() { super(); this.attachShadow({ mode: "open" }); this._epoch = 0; this._data = { controllers: [] }; }
  setConfig(config) { this._config = { title: "MAX! Raumverknüpfung", ...config }; this._render(); }
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
  }
  async _connect() {
    this._disconnect();
    if (!this._hass.user?.is_admin) { this._data = { controllers: [] }; this._error = "Nur für Administratoren verfügbar."; this._render(); return; }
    const epoch = this._epoch;
    this._connection = this._hass.connection;
    this._ready = () => this._connect();
    this._lost = () => { this._epoch++; this._unsubscribe?.(); this._unsubscribe = null; this._online = false; this._error = "Verbindung getrennt – Anzeige möglicherweise veraltet"; this._render(); };
    this._connection.addEventListener("ready", this._ready);
    this._connection.addEventListener("disconnected", this._lost);
    try {
      const unsub = await this._connection.subscribeMessage((data) => {
        if (epoch !== this._epoch || !this.isConnected) return;
        this._data = data; this._online = true; this._error = ""; this._render();
      }, { type: "cul_max/room_association/subscribe" });
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
    const room = controller?.rooms.find(r => r.id === this._area);
    if (!this._online || this._busy || !room?.can_start) return;
    this._busy = true; this._actionError = null; this._render();
    const epoch = this._epoch;
    try {
      await this._hass.callWS({ type: "cul_max/room_association/start", config_entry_id: controller.config_entry_id, area_id: room.id });
    } catch (err) {
      if (epoch === this._epoch && this._controller()?.config_entry_id === controller.config_entry_id && this._area === room.id) {
        this._actionError = {controller: controller.config_entry_id, area: room.id, message: err.message || String(err)};
      }
    }
    finally { this._busy = false; if (epoch === this._epoch) this._render(); }
  }
  _selectionChanged() { this._actionError = null; this._render(); }
  _render() {
    if (!this._config) return;
    const c = this._controller();
    const room = c?.rooms.find(r => r.id === this._area);
    const actionError = this._actionError && this._actionError.controller === c?.config_entry_id && this._actionError?.area === room?.id ? this._actionError.message : "";
    const states = { new:"Bereit zum Verknüpfen", running:"Verknüpfung läuft", pending_activity:"Wartet auf Fensterkontakt", partial:"Verknüpfung unvollständig", complete:"Geräte sind verknüpft" };
    this.shadowRoot.innerHTML = `<style>${cardStyles}
      .header{align-items:flex-start;flex-wrap:wrap}.header h2{flex:1;min-width:160px}.header .badge{white-space:nowrap;line-height:1.5}
      .selectors{display:grid;gap:16px;margin-top:20px}label{display:grid;gap:8px;font-size:.9rem;font-weight:500}select{width:100%;font-size:1rem;font-weight:400}
      .status{line-height:1.5;margin-top:16px;overflow-wrap:anywhere}.status p{margin:6px 0 0}
      .device-list{display:grid}.device{display:grid;gap:6px;padding:14px 0;min-width:0;overflow-wrap:anywhere}.device:first-child{padding-top:0}.device:last-child{padding-bottom:0}.device + .device{border-top:1px solid var(--divider-color,#ddd)}
      .device strong{font-weight:600;line-height:1.4}.device .pending{font-size:.85rem;line-height:1.5}.other-devices{margin:16px 0 0;overflow-wrap:anywhere}.other-devices p{margin:4px 0 0}
      .error{margin:12px 0 0;line-height:1.5}.actions{border-top:1px solid var(--divider-color,#ddd);padding-top:16px;margin-top:20px}.actions button{min-width:12rem}
      @media(max-width:480px){.actions button{width:100%;min-width:0}.header h2{min-width:0;flex-basis:100%}}
      </style><ha-card>
      <div class="header"><h2>${escape(this._config.title)}</h2>${room?.group_id ? `<span class="badge">MAX!-Gruppe ${escape(room.group_id)}</span>` : ""}</div>
      <div class="selectors">
      ${!this._config.config_entry_id && this._data.controllers.length > 1 ? `<label>CUL-Anschluss<select id="controller"><option value="">Bitte auswählen</option>${this._data.controllers.map(item => `<option value="${escape(item.config_entry_id)}" ${item === c ? "selected" : ""}>${escape(item.name)}</option>`).join("")}</select></label>` : ""}
      <label>Raum<select id="area" ${!c ? "disabled" : ""}><option value="">Bitte auswählen</option>${(c?.rooms || []).map(r => `<option value="${escape(r.id)}" ${r === room ? "selected" : ""}>${escape(r.name)}</option>`).join("")}</select></label>
      </div>
      ${!this._online ? '<p class="error">Live-Verbindung nicht verfügbar</p>' : ""}
      ${this._error ? `<p class="error" role="alert">${escape(this._error)}</p>` : ""}
      ${actionError ? `<p class="error" role="alert">${escape(actionError)}</p>` : ""}
      ${room ? `<div class="status" role="status">${escape(states[room.status] || room.status)}${room.status === "pending_activity" ? '<p class="muted">Die betroffenen Fensterkontakte einmal öffnen und schließen.</p>' : ""}</div>
        <section><h3>Geräte (${room.devices.length})</h3><div class="device-list">${room.devices.map(d => `<div class="device"><strong>${escape(d.name)}</strong><div class="muted">${escape(d.type)} · ${d.group_id ? `Gruppe ${escape(d.group_id)}` : "Keine Gruppe"}</div>${d.pending ? '<div class="pending">Befehle ausstehend</div>' : ""}</div>`).join("")}</div></section>
        ${room.other_devices?.length ? `<div class="other-devices muted">An anderen CULs, nicht Teil dieser Einrichtung:<p>${escape(room.other_devices.join(", "))}</p></div>` : ""}
        ${room.problems.map(p => `<p class="error">${escape(p)}</p>`).join("")}
        ${room.error ? `<p class="error" role="alert">${escape(room.error)}</p>` : ""}
        <div class="actions"><button class="primary" id="start" ${!this._online || this._busy || !room.can_start ? "disabled" : ""}>${this._busy ? "Wird gestartet …" : room.busy ? "Verknüpfung läuft" : room.status === "complete" ? "Geräte verknüpft" : room.status === "partial" ? "Erneut versuchen" : room.group_id ? "Verknüpfung ergänzen" : "Geräte verknüpfen"}</button></div>` : '<p class="muted">CUL und Raum auswählen.</p>'}
    </ha-card>`;
    this.shadowRoot.querySelector("#controller")?.addEventListener("change", e => { this._selected = e.target.value; this._area = ""; this._selectionChanged(); });
    this.shadowRoot.querySelector("#area")?.addEventListener("change", e => { this._area = e.target.value; this._selectionChanged(); });
    this.shadowRoot.querySelector("#start")?.addEventListener("click", () => this._start());
  }
}
if (!customElements.get("cul-max-room-association-card")) customElements.define("cul-max-room-association-card", CulMaxRoomAssociationCard);
window.customCards = window.customCards || [];
if (!window.customCards.some(c => c.type === "cul-max-room-association-card")) window.customCards.push({type:"cul-max-room-association-card",name:"MAX! Raumverknüpfung",description:"Geräte eines Raums miteinander verknüpfen"});

class CulMaxRoomAssociationCardEditor extends HTMLElement {
  constructor() { super(); this.attachShadow({mode:"open"}); }
  setConfig(config) { this._config = {...config}; this._render(); }
  set hass(hass) {
    this._hass = hass;
    const select = this.shadowRoot.querySelector("select");
    if (!select) return;
    const controllers = Object.values(hass.states || {}).filter(s => s.attributes?.cul_max_queue);
    select.innerHTML = `<option value="">In der Karte auswählen</option>${controllers.map(s => `<option value="${escape(s.attributes.config_entry_id)}">${escape(s.attributes.friendly_name || s.entity_id)}</option>`).join("")}`;
    select.value = this._config.config_entry_id || "";
  }
  _render() {
    this.shadowRoot.innerHTML = `<style>${cardStyles}label{display:grid;gap:8px;margin:16px 0;font-size:.9rem;font-weight:500}input,select{display:block;width:100%;font-size:1rem;font-weight:400}</style><label>Titel<input data-key="title" value="${escape(this._config.title || "MAX! Raumverknüpfung")}"></label><label>CUL-Anschluss<select data-key="config_entry_id"><option value="">In der Karte auswählen</option></select></label><p class="muted">Leer lassen, um den CUL in der Karte auszuwählen.</p>`;
    if (this._hass) this.hass = this._hass;
    this.shadowRoot.querySelectorAll("input,select").forEach(input => input.addEventListener("change", () => {
      const config = {...this._config, [input.dataset.key]: input.value.trim()};
      if (!config.config_entry_id) delete config.config_entry_id;
      this._config = config;
      this.dispatchEvent(new CustomEvent("config-changed", {detail:{config},bubbles:true,composed:true}));
    }));
  }
}
if (!customElements.get("cul-max-room-association-card-editor")) customElements.define("cul-max-room-association-card-editor", CulMaxRoomAssociationCardEditor);
