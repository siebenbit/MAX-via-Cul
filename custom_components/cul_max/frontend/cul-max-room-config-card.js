/* Room configuration uses only the documented cul_max actions and subscription. */
const ROOM_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];
const ROOM_DAY_LABELS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
const ROOM_FIELDS = {
  comfort_temperature: ["Komforttemperatur", 4.5, 30.5, 0.5, "°C"],
  eco_temperature: ["Ecotemperatur", 4.5, 30.5, 0.5, "°C"],
  window_open_temperature: ["Fenster-offen-Temperatur", 4.5, 30.5, 0.5, "°C"],
  window_open_duration: ["Fenster-offen-Dauer", 0, 60, 5, "min"],
};
const roomEscape = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const roomNumber = (value) => new Intl.NumberFormat("de-DE", { maximumFractionDigits: 1 }).format(value);
const roomMinutes = (time) => /^\d\d:\d\d$/.test(time) ? Number(time.slice(0, 2)) * 60 + Number(time.slice(3)) : NaN;
const normalizeRoomTime = (value) => {
  const text = value.trim();
  if (/^\d{1,2}$/.test(text)) return `${text.padStart(2, "0")}:00`;
  if (/^\d{3,4}$/.test(text)) { const padded = text.padStart(4, "0"); return `${padded.slice(0, 2)}:${padded.slice(2)}`; }
  if (/^\d:\d\d$/.test(text)) return `0${text}`;
  return text;
};
const roomTime = (minutes) => `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
const cloneRoomValue = (value) => JSON.parse(JSON.stringify(value));

class CulMaxRoomProfile {
  static parse(raw) {
    if (!raw) return null;
    const tokens = raw.split(",").map((item) => item.trim());
    const rows = [];
    for (let i = 0; i < tokens.length; i += 2) rows.push({ time: i ? tokens[i - 1] : "00:00", temperature: Number(tokens[i]) });
    return rows;
  }
  static validate(rows) {
    if (!rows?.length || rows.length > 13 || rows[0].time !== "00:00") return "Ein Tag benötigt 1 bis 13 Abschnitte ab 00:00.";
    let previous = -1;
    for (const row of rows) {
      const minute = roomMinutes(row.time);
      const temperature = row.temperature === "" || row.temperature == null ? NaN : Number(row.temperature);
      if (!Number.isFinite(minute) || Number(row.time.slice(3)) > 59 || minute <= previous || minute >= 1440 || minute % 5) return "Schaltzeiten müssen aufsteigend im 5-Minuten-Raster liegen.";
      if (!Number.isFinite(temperature) || temperature < 4.5 || temperature > 30.5 || temperature * 2 % 1) return "Temperaturen: 4,5 bis 30,5 °C in 0,5-Grad-Schritten.";
      previous = minute;
    }
    return "";
  }
  static serialize(rows) {
    const error = this.validate(rows);
    if (error) throw new Error(error);
    return rows.map((row, index) => `${index ? `${row.time},` : ""}${Number(row.temperature)}`).join(",");
  }
  static graph(rows, compact = false) {
    if (this.validate(rows)) return '<div class="empty">Das Diagramm erscheint, sobald der Tagesplan gültig ist.</div>';
    const temperatures = rows.map((row) => Number(row.temperature));
    const low = Math.floor(Math.min(...temperatures) - 1);
    const high = Math.ceil(Math.max(...temperatures) + 1);
    const width = compact ? 380 : 760;
    const left = compact ? 38 : 55;
    const right = width - 25;
    const x = (minute) => left + minute / 1440 * (right - left);
    const y = (temperature) => 175 - (temperature - low) / (high - low) * 150;
    let path = `M ${x(0)} ${y(temperatures[0])}`;
    rows.forEach((row, index) => { if (index) path += ` H ${x(roomMinutes(row.time))} V ${y(temperatures[index])}`; });
    path += ` H ${x(1440)}`;
    let grid = "";
    for (let temp = low; temp <= high; temp += high - low > 6 ? 2 : 1) grid += `<line x1="${left}" x2="${right}" y1="${y(temp)}" y2="${y(temp)}"/><text x="6" y="${y(temp) + 5}">${temp}°</text>`;
    return `<svg viewBox="0 0 ${width} 215" role="img" aria-label="Temperaturverlauf des ausgewählten Tages"><g class="grid">${grid}</g><path class="fill" d="${path} V 185 H ${left} Z"/><path class="curve" d="${path}"/>${[0, 360, 720, 1080, 1440].map((minute) => `<text text-anchor="${minute === 0 ? "start" : minute === 1440 ? "end" : "middle"}" x="${x(minute)}" y="210">${roomTime(minute)}</text>`).join("")}</svg>`;
  }
}

class CulMaxRoomConfigCard extends HTMLElement {
  static getStubConfig() { return { title: "MAX! Raumkonfiguration" }; }
  static getConfigElement() { return document.createElement("cul-max-room-config-card-editor"); }
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._rooms = [];
    this._changes = {};
    this._baseRevision = {};
    this._day = "monday";
    this._epoch = 0;
    this._version = 0;
    this._online = false;
    this._beforeUnload = (event) => { if (this._dirty()) { event.preventDefault(); event.returnValue = ""; } };
  }
  setConfig(config) { this._config = { title: "MAX! Raumkonfiguration", ...config }; this._render(); }
  set hass(hass) {
    const different = this._hass?.connection !== hass.connection || this._hass?.user?.is_admin !== hass.user?.is_admin;
    this._hass = hass;
    if (different && this.isConnected) this._connect();
    if (different || !this._rendered) this._render();
  }
  connectedCallback() {
    window.addEventListener?.("beforeunload", this._beforeUnload);
    if (globalThis.ResizeObserver) {
      this._resizeObserver = new ResizeObserver(() => this._updatePreview());
      this._resizeObserver.observe(this);
    }
    if (this._hass) this._connect();
  }
  disconnectedCallback() {
    this._disconnect();
    this._resizeObserver?.disconnect();
    window.removeEventListener?.("beforeunload", this._beforeUnload);
  }
  getCardSize() { return 12; }
  getGridOptions() { return { columns: "full", rows: "auto", min_columns: 6 }; }
  _disconnect() {
    this._epoch++;
    this._unsubscribe?.(); this._unsubscribe = null;
    this._connection?.removeEventListener?.("ready", this._ready);
    this._connection?.removeEventListener?.("disconnected", this._lost);
    this._online = false;
  }
  async _connect() {
    this._disconnect();
    if (this._hass.user?.is_admin === false) { this._rooms = []; this._error = "Diese Konfiguration ist nur für Administratoren verfügbar."; this._render(); return; }
    const epoch = this._epoch;
    this._connection = this._hass.connection;
    this._ready = () => this._connect();
    this._lost = () => { this._online = false; this._render(); };
    this._connection?.addEventListener?.("ready", this._ready);
    this._connection?.addEventListener?.("disconnected", this._lost);
    try {
      const unsubscribe = await this._connection.subscribeMessage((data) => {
        if (epoch !== this._epoch || !this.isConnected) return;
        this._online = true; this._error = ""; this._receive(data);
      }, { type: "cul_max/room_config/subscribe" });
      if (epoch !== this._epoch || !this.isConnected) { unsubscribe(); return; }
      this._unsubscribe = unsubscribe;
    } catch (error) {
      if (epoch !== this._epoch) return;
      this._error = `Live-Verbindung fehlgeschlagen: ${error.message || error}`;
      await this._load(epoch);
    }
  }
  async _call(service, data = {}) {
    const result = await this._hass.callWS({ type: "call_service", domain: "cul_max", service, service_data: data, return_response: true });
    if (!result?.response) throw new Error("Keine gültige Antwort von MAX! via CUL.");
    return result.response;
  }
  async _load(epoch = this._epoch) {
    try {
      const data = await this._call("get_room_config");
      if (epoch !== this._epoch || !this.isConnected) return;
      this._receive(data);
    } catch (error) { if (epoch === this._epoch) { this._error = error.message || String(error); this._render(); } }
  }
  _room() { return this._rooms.find((room) => room.id === this._area); }
  _blocks() {
    const blocks = new Set();
    if (Object.keys(this._changes).some((key) => ROOM_FIELDS[key])) blocks.add("temperature");
    if (Object.keys(this._changes.week_profile || {}).length) blocks.add("week_profile");
    for (const device of this._room()?.devices || []) for (const block of device.draft_blocks || []) if (!this._room().locks[block]) blocks.add(block);
    return blocks;
  }
  _dirty() { return this._blocks().size > 0; }
  _receive(data) {
    if (!Array.isArray(data?.rooms)) { this._error = "Ungültige Raumübersicht erhalten."; this._render(); return; }
    this._rooms = data.rooms;
    if (!this._area) this._area = this._config?.area_id || this._rooms[0]?.id;
    const room = this._room();
    if (room && this._pendingOperation?.area_id === room.id && room.devices.some((d) => d.jobs.some((j) => j.operation_id === this._pendingOperation.operation_id))) {
      this._lastOperation = this._pendingOperation.operation_id;
      const jobs = room.devices.flatMap((d) => d.jobs).filter((j) => j.operation_id === this._lastOperation);
      this._lastOperationCount = jobs[0]?.operation_size || jobs.length;
      this._changes = {}; this._pendingOperation = null; this._message = "Auftrag eingereiht. Der Übertragungsfortschritt wird unten angezeigt.";
    }
    if (room) {
      const jobs = room.devices.flatMap((d) => d.jobs).filter((j) => j.operation_id === this._lastOperation);
      if (jobs.length && jobs.length >= this._lastOperationCount && jobs.every((j) => j.status === "completed")) this._message = "Alle Konfigurationsänderungen sind bestätigt.";
      else if (jobs.some((j) => ["cancelled", "failed"].includes(j.status))) this._message = "Der Auftrag wurde nicht vollständig bestätigt. Bitte den Gerätefortschritt prüfen.";
      const dirty = this._blocks();
      for (const block of ["temperature", "week_profile"]) if (!dirty.has(block) || !this._baseRevision[block]) this._baseRevision[block] = room.revision[block];
      this._conflict = [...dirty].some((block) => this._baseRevision[block] !== room.revision[block] || room.locks[block]);
    }
    this._render();
  }
  _locked(block) { return !this._online || this._saving || !!this._room()?.locks[block]; }
  _rows() { return this._changes.week_profile?.[this._day] ?? CulMaxRoomProfile.parse(this._room()?.values.week_profile[this._day]); }
  _edit(key, value) {
    this._changes[key] = value;
    this._version++;
    this._pendingOperation = null;
    this._updatePreview();
  }
  _editRows(rows) {
    this._changes.week_profile = { ...(this._changes.week_profile || {}), [this._day]: rows };
    this._version++; this._pendingOperation = null;
    this._updatePreview();
  }
  _errors() {
    const errors = [];
    const unpaired = this._room()?.devices.filter((device) => !device.paired) || [];
    if (unpaired.length) errors.push(`Noch nicht gepairt: ${unpaired.map((device) => device.name).join(", ")}. Erst anlernen, dann gemeinsam speichern.`);
    for (const [key, value] of Object.entries(this._changes)) {
      if (key === "week_profile") {
        for (const [day, rows] of Object.entries(value)) {
          const error = CulMaxRoomProfile.validate(rows);
          if (error) errors.push(`${ROOM_DAY_LABELS[ROOM_DAYS.indexOf(day)]}: ${error}`);
        }
      } else {
        const [label, min, max, step] = ROOM_FIELDS[key];
        const number = value === "" ? NaN : Number(value);
        if (!Number.isFinite(number) || number < min || number > max || number / step % 1) errors.push(`${label}: ${min} bis ${max} ${ROOM_FIELDS[key][4]}, Schritt ${step}.`);
      }
    }
    return errors;
  }
  _canSave() {
    const room = this._room();
    return room && this._online && !this._saving && this._dirty() && !this._conflict && !this._errors().length && room.devices.every((d) => d.paired) && [...this._blocks()].every((b) => !room.locks[b]);
  }
  _updatePreview() {
    const graph = this.shadowRoot.querySelector("[data-graph]");
    if (graph) graph.innerHTML = this._rows() ? CulMaxRoomProfile.graph(this._rows(), (this.clientWidth || 760) < 480) : '<div class="empty">Kein gemeinsames Tagesprofil.</div>';
    const save = this.shadowRoot.querySelector("[data-save]");
    if (save) save.disabled = !this._canSave();
    const discard = this.shadowRoot.querySelector("[data-discard]");
    if (discard) discard.disabled = !this._dirty() || this._saving;
    const errors = this.shadowRoot.querySelector("[data-errors]");
    if (errors) errors.textContent = this._errors().join(" ");
    const badge = this.shadowRoot.querySelector("[data-badge]");
    if (badge) badge.textContent = this._dirty() ? "Entwurf" : "Bereit";
    const add = this.shadowRoot.querySelector("[data-add]");
    if (add) add.disabled = this._locked("week_profile") || (this._rows()?.length || 0) >= 13 || !!CulMaxRoomProfile.validate(this._rows());
    const copy = this.shadowRoot.querySelector("[data-copy]");
    if (copy) copy.disabled = this._locked("week_profile") || !!CulMaxRoomProfile.validate(this._rows());
  }
  _selectRoom(area) {
    if (area !== this._area && this._dirty() && !window.confirm("Ungespeicherte Änderungen verwerfen und den Raum wechseln?")) { this._render(); return; }
    this._area = area; this._changes = {}; this._baseRevision = {}; this._conflict = false; this._error = ""; this._message = ""; this._pendingOperation = null;
    this._receive({ rooms: this._rooms });
  }
  async _save() {
    if (!this._canSave()) return;
    const changes = {};
    for (const [key, value] of Object.entries(this._changes)) changes[key] = key === "week_profile"
      ? Object.fromEntries(Object.entries(value).map(([day, rows]) => [day, CulMaxRoomProfile.serialize(rows)])) : Number(value);
    const request = this._pendingOperation || { area_id: this._area, changes, expected_revision: { ...this._baseRevision },
      operation_id: globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}` };
    this._pendingOperation = request;
    this._saving = true; this._error = ""; this._render();
    try {
      const result = await this._call("save_room_config", request);
      this._changes = {}; this._baseRevision = {}; this._conflict = false; this._pendingOperation = null;
      this._lastOperation = result.status === "unchanged" ? null : request.operation_id;
      this._lastOperationCount = result.job_ids.length;
      this._message = result.status === "unchanged" ? "Keine Übertragung erforderlich." : "Auftrag eingereiht. Noch nicht am Gerät bestätigt.";
      await this._load();
    } catch (error) { this._error = error.message || String(error); }
    finally { this._saving = false; this._render(); }
  }
  async _discard() {
    if (this._room()?.has_draft && !this._conflict) {
      if (!window.confirm("Auch vorhandene Entwürfe aus den Geräte-Entitäten dieses Raums verwerfen? Eingereihte Aufträge bleiben erhalten.")) return;
      try { await this._call("discard_room_config", { area_id: this._area, expected_revision: { ...this._baseRevision } }); }
      catch (error) { this._error = error.message || String(error); this._render(); return; }
    }
    this._changes = {}; this._baseRevision = {}; this._conflict = false; this._pendingOperation = null; this._error = "";
    this._receive({ rooms: this._rooms });
    await this._load();
  }
  _addRow() {
    const rows = cloneRoomValue(this._rows() || [{ time: "00:00", temperature: "" }]);
    if (rows.length >= 13 || this._locked("week_profile") || CulMaxRoomProfile.validate(rows)) return;
    let index = rows.length - 1;
    if (roomMinutes(rows[index].time) >= 1435) index = rows.findIndex((row, i) => (i + 1 < rows.length ? roomMinutes(rows[i + 1].time) : 1440) - roomMinutes(row.time) > 5);
    if (index < 0) return;
    const start = roomMinutes(rows[index].time);
    const end = index + 1 < rows.length ? roomMinutes(rows[index + 1].time) : 1440;
    rows.splice(index + 1, 0, { time: roomTime(Math.min(start + 60, end - 5)), temperature: rows[index].temperature });
    this._editRows(rows); this._render();
  }
  _copyDay() {
    if (this._locked("week_profile") || CulMaxRoomProfile.validate(this._rows())) return;
    if (!window.confirm("Diesen Tagesplan auf alle sieben Tage im Entwurf übertragen? Vorhandene Tagesentwürfe werden ersetzt. Erst Speichern sendet die Änderungen.")) return;
    const rows = this._rows();
    this._changes.week_profile = Object.fromEntries(ROOM_DAYS.map((day) => [day, cloneRoomValue(rows)]));
    this._version++; this._pendingOperation = null; this._render();
  }
  async _cancel(job, owner) {
    if (!window.confirm("Gesamten Konfigurationsauftrag abbrechen? Bereits bestätigte Teile bleiben übertragen; eine laufende Übertragung wird zuerst abgeschlossen.")) return;
    try { await this._call("cancel_config_job", { config_entry_id: owner, job_id: job.id, confirm: true }); await this._load(); }
    catch (error) { this._error = error.message || String(error); this._render(); }
  }
  _progress(room) {
    const labels = { queued: "Eingereiht", waiting_for_credits: "Wartet auf Funkbudget", sending: "Wird gesendet", awaiting_ack: "Wartet auf Bestätigung", retrying: "Wiederholung", completed: "Bestätigt", failed: "Fehlgeschlagen", cancelled: "Abgebrochen", cancelling: "Abbruch nach laufendem Paket" };
    return room.devices.map((device) => {
      const active = device.jobs.filter((j) => !["completed", "cancelled", "failed"].includes(j.status));
      const jobs = [...active, ...device.jobs.filter((j) => !active.includes(j)).slice(-2)];
      return `<div class="device"><strong>${roomEscape(device.name)}</strong>${!device.paired ? '<div class="error">Noch nicht gepairt · Speichern nicht möglich</div>' : ""}${jobs.map((job) => `<div class="job"><span>${roomEscape(job.block === "temperature" ? "Temperaturparameter" : "Wochenplan")} · ${roomEscape(labels[job.status] || job.status)}<small>${job.confirmed_steps.length} / ${job.steps.length} Pakete bestätigt${job.last_error ? ` · ${roomEscape(job.last_error)} · erneuter Versuch ausstehend` : ""}</small></span>${!job.direct && !['completed', 'cancelled', 'failed'].includes(job.status) ? `<button data-cancel="${roomEscape(job.id)}" data-owner="${roomEscape(device.config_entry_id)}" class="compact">Abbrechen</button>` : ""}</div>`).join("") || '<small>Kein ausstehender Konfigurationsauftrag</small>'}</div>`;
    }).join("");
  }
  _render() {
    if (!this.shadowRoot || !this._config) return;
    this._rendered = true;
    const focused = this.shadowRoot.activeElement;
    const focusKey = focused?.dataset.focus;
    const selection = focused?.selectionStart;
    const room = this._room();
    const rows = this._rows();
    const disabledTemp = this._locked("temperature") ? "disabled" : "";
    const disabledWeek = this._locked("week_profile") ? "disabled" : "";
    this.shadowRoot.innerHTML = `<style>${CulMaxRoomConfigCard.styles}</style><ha-card><div class="header"><h2>${roomEscape(this._config.title)}</h2><span class="badge" data-badge>${this._dirty() ? "Entwurf" : "Bereit"}</span></div>
      <label class="room">Raum<select data-room ${this._saving ? "disabled" : ""}>${this._area && !room ? `<option value="${roomEscape(this._area)}" selected disabled>Raum nicht mehr verfügbar</option>` : ""}${this._rooms.map((r) => `<option value="${roomEscape(r.id)}" ${r.id === this._area ? "selected" : ""}>${roomEscape(r.name)}</option>`).join("")}</select></label>
      ${!this._online ? '<div class="notice">Live-Verbindung nicht verfügbar. <button data-reconnect class="compact">Erneut verbinden</button></div>' : ""}
      ${this._error ? `<div class="error" role="alert">${roomEscape(this._error)}</div>` : ""}
      ${this._message ? `<div class="notice" role="status">${roomEscape(this._message)}</div>` : ""}
      ${this._conflict ? '<div class="error">Die Konfiguration wurde zwischenzeitlich geändert. Dein Entwurf bleibt erhalten. Bitte Änderungen verwerfen und den aktuellen Stand neu laden.</div>' : ""}
      ${room ? `<p class="subtitle">Gemeinsame Konfiguration für ${room.devices.length} Thermostat${room.devices.length === 1 ? "" : "e"} · Änderungen werden erst mit Speichern eingereiht.</p>
      <section><h3>Temperaturparameter ${room.locks.temperature ? '<span class="status">Übertragung läuft · gesperrt</span>' : ""}</h3><div class="fields">${Object.entries(ROOM_FIELDS).map(([key, [label, min, max, step, unit]]) => `<label>${label}<div class="input-unit"><input data-focus="${key}" data-key="${key}" aria-label="${label}" type="number" min="${min}" max="${max}" step="${step}" value="${roomEscape(this._changes[key] ?? room.values[key])}" placeholder="${room.mixed.includes(key) ? "Gemischt" : "Unbekannt"}" ${disabledTemp}><span>${unit}</span></div></label>`).join("")}</div></section>
      <section><h3>Wochenplan ${room.locks.week_profile ? '<span class="status">Übertragung läuft · gesperrt</span>' : ""}</h3><div class="days" role="tablist">${ROOM_DAYS.map((day, i) => `<button role="tab" aria-selected="${day === this._day}" data-day="${day}" class="${day === this._day ? "selected" : ""}">${ROOM_DAY_LABELS[i]}${this._changes.week_profile?.[day] ? " ·" : ""}</button>`).join("")}</div>
      <div data-graph>${rows ? CulMaxRoomProfile.graph(rows, (this.clientWidth || 760) < 480) : '<div class="empty">Kein gemeinsames Tagesprofil. Vorlage wählen oder einen neuen Tagesplan anlegen.</div>'}</div>
      <div class="row-heading"><h4>Schaltzeiten</h4><span>Ab Uhrzeit → Temperatur</span></div>
      ${rows ? rows.map((row, index) => `<div class="switch-row"><input data-focus="time-${index}" aria-label="Schaltzeit ${index + 1}" data-index="${index}" data-part="time" type="text" inputmode="numeric" maxlength="5" placeholder="HH:MM" title="24-Stunden-Format, z. B. 06:30 oder 0630" value="${roomEscape(row.time)}" ${index === 0 ? "disabled" : disabledWeek}><span aria-hidden="true">→</span><input data-focus="temperature-${index}" aria-label="Temperatur Abschnitt ${index + 1}" data-index="${index}" data-part="temperature" type="number" min="4.5" max="30.5" step="0.5" value="${roomEscape(row.temperature)}" ${disabledWeek}><span>°C</span><button data-remove="${index}" aria-label="Schaltzeit ${index + 1} löschen" title="Schaltzeit löschen" class="icon" ${!index ? "disabled" : disabledWeek}>${CulMaxRoomConfigCard.trash}</button></div>`).join("") : `<button data-new ${disabledWeek}>Neuen Tagesplan anlegen</button>`}
      ${rows ? `<button class="wide" data-add ${disabledWeek || (rows.length >= 13 || CulMaxRoomProfile.validate(rows) ? "disabled" : "")}>＋ Schaltzeit hinzufügen</button><button class="wide" data-copy ${disabledWeek || (CulMaxRoomProfile.validate(rows) ? "disabled" : "")}>Tag auf alle Tage kopieren</button>` : ""}
      <label class="template">Tagesprofil von einem Raumgerät übernehmen<select data-template ${disabledWeek}><option value="">Vorlage auswählen …</option>${room.devices.map((d, i) => `<option value="${i}" ${!d.confirmed.week_profile[this._day] ? "disabled" : ""}>${roomEscape(d.name)}</option>`).join("")}</select></label></section>
      <div class="error" data-errors role="alert">${roomEscape(this._errors().join(" "))}</div>
      <div class="actions"><button data-discard ${!this._dirty() || this._saving ? "disabled" : ""}>Verwerfen</button><button class="primary" data-save ${this._canSave() ? "" : "disabled"}>${this._saving ? "Wird eingereiht …" : "Speichern"}</button></div>
      <details ${room.devices.some((d) => d.jobs.length) ? "open" : ""}><summary>Geräte und Übertragungsfortschritt</summary>${this._progress(room)}</details>`
        : '<div class="empty">Keine MAX!-Thermostate in einem HA-Bereich gefunden. Ordne die Geräte in Home Assistant einem Bereich zu.</div>'}</ha-card>`;
    const query = (s) => this.shadowRoot.querySelector(s);
    query("[data-room]")?.addEventListener("change", (event) => this._selectRoom(event.target.value));
    query("[data-save]")?.addEventListener("click", () => this._save());
    query("[data-discard]")?.addEventListener("click", () => this._discard());
    query("[data-reconnect]")?.addEventListener("click", () => this._connect());
    this.shadowRoot.querySelectorAll("[data-key]").forEach((input) => input.addEventListener("input", () => this._edit(input.dataset.key, input.value)));
    this.shadowRoot.querySelectorAll("[data-day]").forEach((button) => button.addEventListener("click", () => { this._day = button.dataset.day; this._render(); }));
    this.shadowRoot.querySelectorAll("[data-part]").forEach((input) => input.addEventListener("input", () => { const copy = cloneRoomValue(this._rows()); copy[Number(input.dataset.index)][input.dataset.part] = input.value; this._editRows(copy); }));
    this.shadowRoot.querySelectorAll('[data-part="time"]').forEach((input) => input.addEventListener("change", () => {
      const value = normalizeRoomTime(input.value); input.value = value;
      const copy = cloneRoomValue(this._rows()); copy[Number(input.dataset.index)].time = value; this._editRows(copy);
    }));
    this.shadowRoot.querySelectorAll("[data-remove]").forEach((button) => button.addEventListener("click", () => { const index = Number(button.dataset.remove); if (!index || this._locked("week_profile")) return; const copy = cloneRoomValue(this._rows()); copy.splice(index, 1); this._editRows(copy); this._render(); }));
    query("[data-add]")?.addEventListener("click", () => this._addRow());
    query("[data-copy]")?.addEventListener("click", () => this._copyDay());
    query("[data-new]")?.addEventListener("click", () => { this._editRows([{ time: "00:00", temperature: "" }]); this._render(); });
    query("[data-template]")?.addEventListener("change", (event) => { const device = room.devices[event.target.value]; if (device) { this._editRows(CulMaxRoomProfile.parse(device.confirmed.week_profile[this._day])); this._render(); } });
    this.shadowRoot.querySelectorAll("[data-cancel]").forEach((button) => button.addEventListener("click", () => { const device = room.devices.find((d) => d.config_entry_id === button.dataset.owner && d.jobs.some((j) => j.id === button.dataset.cancel)); const job = device?.jobs.find((j) => j.id === button.dataset.cancel); if (job) this._cancel(job, device.config_entry_id); }));
    if (focusKey) {
      const input = this.shadowRoot.querySelector(`[data-focus="${focusKey}"]`);
      input?.focus?.({ preventScroll: true });
      if (selection != null) { try { input.setSelectionRange(selection, selection); } catch (_) { /* number/time input */ } }
    }
  }
  static trash = '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path fill="currentColor" d="M9 3h6l1 2h4v2H4V5h4l1-2m-3 6h12l-1 12H7L6 9m4 2v8h1v-8h-1m3 0v8h1v-8h-1Z"/></svg>';
  static styles = `:host{display:block;color:var(--primary-text-color);font-family:var(--paper-font-body1_-_font-family,inherit)}*{box-sizing:border-box}ha-card{display:block;background:var(--ha-card-background,var(--card-background-color,#fff));border:1px solid var(--divider-color,#ddd);border-radius:var(--ha-card-border-radius,20px);padding:20px}.header{display:flex;align-items:center;justify-content:space-between;gap:12px}h2{font-size:1.35rem;margin:0;min-width:0;overflow-wrap:anywhere}h3{font-size:1.05rem;margin:0 0 16px}h4{font-size:1rem;margin:0}.subtitle,.template,.row-heading span,small{color:var(--secondary-text-color,#666);font-size:.88rem;line-height:1.5}.badge{background:var(--secondary-background-color,#eee);padding:6px 10px;border-radius:20px;font-size:.8rem}.room{display:grid;gap:6px;margin:20px 0 10px;font-weight:600}section{border-top:1px solid var(--divider-color,#ddd);margin-top:22px;padding-top:20px}.fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.fields label{font-size:.9rem}.input-unit{display:flex;align-items:center;gap:8px;margin-top:7px}.input-unit input{width:100%}input,select,button{font:inherit;color:var(--primary-text-color);background:var(--ha-card-background,var(--card-background-color,#fff));border:1px solid var(--divider-color,#ccc);border-radius:22px;min-height:44px;padding:9px 14px;max-width:100%;min-width:0}select{width:100%}input:focus,select:focus,button:focus-visible{outline:2px solid var(--primary-color,#519eb5);outline-offset:2px}button{cursor:pointer;transition:background .15s}button:hover:not(:disabled){background:var(--secondary-background-color,#eee)}button:disabled,input:disabled,select:disabled{opacity:.5;cursor:default}button.primary,button.selected{background:var(--primary-text-color,#111);color:var(--card-background-color,#fff);border-color:transparent}button.primary:hover:not(:disabled){opacity:.85;background:var(--primary-text-color,#111)}.days{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:5px}.days button{padding:7px 2px;min-height:38px}.switch-row{display:grid;grid-template-columns:minmax(0,1fr) 18px minmax(0,1fr) 23px 32px;align-items:center;gap:10px;margin:9px 0}.switch-row input{width:100%}.icon{border:0;border-radius:50%;padding:6px;min-height:36px;display:flex;justify-content:center}.wide{display:block;width:100%;margin-top:12px}.row-heading{display:flex;justify-content:space-between;gap:8px;margin:18px 0 12px}.status{display:block;color:var(--secondary-text-color);font-size:.8rem;font-weight:400;margin-top:6px}.template{display:grid;gap:6px;margin-top:16px}.actions{display:grid;grid-template-columns:1fr 1fr;gap:12px;border-top:1px solid var(--divider-color);padding-top:20px;margin-top:22px}.error{color:var(--error-color,#b33);margin-top:12px;font-size:.9rem;overflow-wrap:anywhere}.error:empty{display:none}.notice{background:var(--secondary-background-color,#eee);border-radius:12px;padding:12px;margin:12px 0;font-size:.9rem}.compact{min-height:34px;padding:5px 10px;font-size:.8rem}.empty{padding:32px 8px;color:var(--secondary-text-color);text-align:center;line-height:1.5}[data-graph]{min-height:180px;margin-top:12px}svg{display:block;width:100%;max-height:310px}svg text{fill:var(--secondary-text-color,#777);font-size:14px}.grid line{stroke:var(--divider-color,#ddd);stroke-dasharray:6 5}.curve{stroke:var(--primary-color,#519eb5);stroke-width:4;fill:none;stroke-linejoin:round}.fill{fill:var(--primary-color,#519eb5);opacity:.12}details{margin-top:22px;font-size:.9rem}summary{cursor:pointer;min-height:30px}.device{padding:12px 0;border-top:1px solid var(--divider-color);margin-top:8px}.device strong{overflow-wrap:anywhere}.device small{display:block}.job{display:flex;align-items:center;gap:8px;justify-content:space-between;margin-top:8px;overflow-wrap:anywhere}@media(max-width:480px){ha-card{padding:14px}.fields{grid-template-columns:1fr}.switch-row{gap:5px;grid-template-columns:minmax(0,1fr) 12px minmax(0,1fr) 20px 28px}.switch-row input{padding:9px 8px}.row-heading span{font-size:.75rem}h2{font-size:1.12rem}.header{align-items:flex-start}.badge{font-size:.7rem}.days button{font-size:.85rem}.job{align-items:flex-start}}`;
}

class CulMaxRoomConfigCardEditor extends HTMLElement {
  setConfig(config) { this._config = config; this._render(); }
  set hass(hass) {
    const changed = this._hass?.connection !== hass.connection;
    this._hass = hass;
    if (changed) hass.callWS({ type: "call_service", domain: "cul_max", service: "get_room_config", service_data: {}, return_response: true }).then((r) => { this._rooms = r.response?.rooms || []; this._render(); }).catch(() => {});
    this._render();
  }
  _render() {
    if (!this._config) return;
    this.innerHTML = `<div style="display:grid;gap:12px;padding:12px"><label>Titel<input style="display:block;width:100%;padding:10px" data-title value="${roomEscape(this._config.title || "MAX! Raumkonfiguration")}"></label><label>Start-Raum<select style="display:block;width:100%;padding:10px" data-area><option value="">Ersten verfügbaren Raum verwenden</option>${(this._rooms || []).map((r) => `<option value="${roomEscape(r.id)}" ${r.id === this._config.area_id ? "selected" : ""}>${roomEscape(r.name)}</option>`).join("")}</select></label></div>`;
    const update = (key, value) => { this._config = { ...this._config, [key]: value }; this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true })); };
    this.querySelector("[data-title]")?.addEventListener("change", (e) => update("title", e.target.value));
    this.querySelector("[data-area]")?.addEventListener("change", (e) => update("area_id", e.target.value));
  }
}
if (!customElements.get("cul-max-room-config-card")) customElements.define("cul-max-room-config-card", CulMaxRoomConfigCard);
if (!customElements.get("cul-max-room-config-card-editor")) customElements.define("cul-max-room-config-card-editor", CulMaxRoomConfigCardEditor);
window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "cul-max-room-config-card")) window.customCards.push({ type: "cul-max-room-config-card", name: "MAX! Raumkonfiguration", description: "Gemeinsame Raumkonfiguration mit grafischem Wochenplan" });
