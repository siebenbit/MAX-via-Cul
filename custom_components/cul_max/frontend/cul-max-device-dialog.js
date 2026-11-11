const { cardStyles, dialogStyles } = await import(new URL("./cul-max-card-styles.js" + new URL(import.meta.url).search, import.meta.url));
const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

export function defaultDeviceName(deviceType, areaName) {
  return areaName ? `${deviceType} (${areaName})` : deviceType;
}

// Only changed registry fields are written, preserving HA's default-name semantics.
export function deviceChanges(device, name, areaId) {
  const updates = {};
  name = name.trim();
  if (name !== (device.name_by_user || device.name || "")) updates.name_by_user = name || null;
  if ((areaId || null) !== (device.area_id || null)) updates.area_id = areaId || null;
  return updates;
}

class CulMaxDeviceDialog extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: "open" }); }
  connectedCallback() {
    this.shadowRoot.innerHTML = `<style>${cardStyles}${dialogStyles}</style>
      <dialog aria-labelledby="device-title" aria-describedby="device-subtitle">
        <form><header><h2 id="device-title">Gerät bearbeiten</h2><p id="device-subtitle" class="muted">Name und Raum</p></header>
          <div class="dialog-body"><label for="device-area">Raum</label><select id="device-area" name="area" autofocus><option value="">Keinem Raum zugeordnet</option></select>
            <label for="device-name">Name</label><input id="device-name" name="name" type="text" autocomplete="off">
            <p class="error" role="alert" hidden></p></div>
          <footer><button type="button" id="cancel">Abbrechen</button><button type="submit" class="primary" id="save">Speichern</button></footer>
        </form></dialog>`;
    const root = this.shadowRoot;
    this._dialog = root.querySelector("dialog");
    const select = root.querySelector("#device-area");
    select.insertAdjacentHTML("beforeend", this.areas.map(area => `<option value="${escape(area.area_id)}">${escape(area.name)}</option>`).join(""));
    if (this.device.area_id && !this.areas.some(area => area.area_id === this.device.area_id)) {
      select.insertAdjacentHTML("beforeend", `<option value="${escape(this.device.area_id)}">Bisheriger Raum nicht mehr verfügbar</option>`);
    }
    select.value = this.device.area_id || "";
    const suggestName = () => {
      const area = this.areas.find(item => item.area_id === select.value);
      root.querySelector("#device-name").value = defaultDeviceName(this.deviceType, area?.name);
    };
    suggestName();
    select.addEventListener("change", suggestName);
    root.querySelector("form").addEventListener("submit", event => { event.preventDefault(); this._save(); });
    root.querySelector("#cancel").addEventListener("click", () => this._dialog.close());
    this._dialog.addEventListener("cancel", event => { if (this._saving) event.preventDefault(); });
    this._dialog.addEventListener("close", () => this.remove());
    this._resize = () => {
      const viewport = window.visualViewport;
      this.style.setProperty("--dialog-viewport-height", `${viewport?.height || window.innerHeight}px`);
      this.style.setProperty("--dialog-viewport-top", `${viewport?.offsetTop || 0}px`);
    };
    window.visualViewport?.addEventListener("resize", this._resize);
    window.visualViewport?.addEventListener("scroll", this._resize);
    window.addEventListener("resize", this._resize);
    this._resize();
    this._dialog.showModal();
  }
  disconnectedCallback() {
    window.visualViewport?.removeEventListener("resize", this._resize);
    window.visualViewport?.removeEventListener("scroll", this._resize);
    window.removeEventListener("resize", this._resize);
    this.onClosed?.();
  }
  async _save() {
    if (this._saving) return;
    const root = this.shadowRoot;
    const error = root.querySelector("[role=alert]");
    error.hidden = true;
    const updates = deviceChanges(this.device, root.querySelector("#device-name").value, root.querySelector("#device-area").value);
    if (!Object.keys(updates).length) { this._dialog.close(); return; }
    this._saving = true;
    root.querySelectorAll("input,select,button").forEach(control => { control.disabled = true; });
    root.querySelector("#save").textContent = "Wird gespeichert …";
    try {
      const hass = this.getHass();
      if (!hass.user?.is_admin) throw Error("Nur für Administratoren verfügbar.");
      await hass.callWS({ type: "config/device_registry/update", device_id: this.device.id, ...updates });
      if (this.isConnected) this._dialog.close();
    } catch (err) {
      if (this.isConnected) { error.textContent = err.message || String(err); error.hidden = false; }
    } finally {
      this._saving = false;
      if (this.isConnected) {
        root.querySelectorAll("input,select,button").forEach(control => { control.disabled = false; });
        root.querySelector("#save").textContent = "Speichern";
      }
    }
  }
}
if (!customElements.get("cul-max-device-dialog")) customElements.define("cul-max-device-dialog", CulMaxDeviceDialog);

export async function openDeviceDialog(host, hass, deviceId, deviceType, isCurrent = () => true, getHass = () => hass) {
  if (!hass.user?.is_admin) throw Error("Nur für Administratoren verfügbar.");
  const [devices, areas] = await Promise.all([
    hass.callWS({ type: "config/device_registry/list" }),
    hass.callWS({ type: "config/area_registry/list" }),
  ]);
  if (!isCurrent()) return;
  const device = devices.find(item => item.id === deviceId);
  if (!device) throw Error("Gerät nicht mehr vorhanden.");
  if (typeof HTMLDialogElement === "undefined" || !HTMLDialogElement.prototype.showModal) throw Error("Bitte den Browser beziehungsweise Android System WebView aktualisieren.");
  const element = document.createElement("cul-max-device-dialog");
  element.device = device;
  element.deviceType = deviceType;
  element.areas = [...areas].sort((a, b) => a.name.localeCompare(b.name));
  element.getHass = getHass;
  return new Promise((resolve, reject) => {
    element.onClosed = resolve;
    try {
      host.shadowRoot.appendChild(element);
      // Custom-element lifecycle errors are reported by the browser, so also
      // check that initialization reached the modal before considering it open.
      if (!element.shadowRoot.querySelector("dialog")?.open) throw Error("Dialog konnte nicht geöffnet werden.");
    } catch (err) { element.onClosed = null; element.remove(); reject(err); }
  });
}
