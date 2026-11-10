import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

function setup() {
  const elements = new Map();
  const timers = new Map();
  class Element {
    constructor() { this.isConnected = true; }
    attachShadow() { this.shadowRoot = { innerHTML: "", querySelector: () => null, querySelectorAll: () => [] }; }
    querySelectorAll() { return []; }
  }
  const context = vm.createContext({ HTMLElement: Element, window: { confirm: () => true, setInterval: (callback) => { const id = timers.size + 1; timers.set(id, callback); return id; }, clearInterval: (id) => timers.delete(id) },
    customElements: { get: (key) => elements.get(key), define: (key, value) => elements.set(key, value) },
    document: { createElement: (name) => new (elements.get(name))() }, CustomEvent: class {}, console });
  vm.runInContext(readFileSync(new URL("../../frontend/cul-max-queue-card.js", import.meta.url), "utf8"), context);
  const Card = elements.get("cul-max-queue-card");
  const card = new Card();
  const listeners = new Map();
  const calls = [];
  const controller = { config_entry_id: "controller", name: "CUL", budget: { reported_credits: 185, budget_valid: true },
    entries: [], jobs: [] };
  const connection = { addEventListener: (key, callback) => listeners.set(key, callback), removeEventListener: (key) => listeners.delete(key) };
  const hass = { connection, states: {}, callWS: async (call) => { calls.push(call); return { response: { controllers: [controller] } }; } };
  card.setConfig({ title: "MAX! Warteschlange" });
  card.hass = hass;
  return { card, controller, hass, calls, listeners, elements, timers };
}
const tick = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };

test("empty queue, credits and escaped descriptions render safely", async () => {
  const { card, controller } = setup();
  await tick();
  assert.match(card.shadowRoot.innerHTML, /Keine wartenden Aufträge/);
  assert.match(card.shadowRoot.innerHTML, /185 \/ 900/);
  controller.entries.push({ id: "1", scope: "general", status: "queued", cancellable: true,
    device_name: "<script>bad</script>", description: "SetTemperature 23°C", command_type: "SetTemperature", attempts: 0 });
  card._render();
  assert.doesNotMatch(card.shadowRoot.innerHTML, /<script>bad/);
  assert.match(card.shadowRoot.innerHTML, /&lt;script&gt;/);
});

test("filters preserve protected entries and separate configuration jobs", async () => {
  const { card, controller } = setup();
  await tick();
  controller.entries.push({ id: "1", scope: "general", device_address: "ABCDEF", status: "awaiting_ack", cancellable: false, description: "Temperature" });
  controller.jobs.push({ id: "job", scope: "configuration", kind: "climate", device_address: "123456", status: "queued", description: "Monday" });
  card.setConfig({ address: "abcdef", scope: "general" });
  assert.equal(card._items().length, 1);
  card._render();
  assert.match(card.shadowRoot.innerHTML, /Nicht löschbar/);
  card.setConfig({ scope: "configuration" });
  assert.equal(card._items()[0].id, "job");
});

test("actions use response API and explain racing failures", async () => {
  const { card, hass, calls } = setup();
  await tick();
  await card._action("delete_queue_entry", { entry_id: "1" }, "Gelöscht");
  const command = calls.find((call) => call.service === "delete_queue_entry");
  assert.equal(command.return_response, true);
  assert.equal(command.service_data.entry_id, "1");
  hass.callWS = async (call) => {
    if (call.service !== "get_queue") throw Error("Bereits gesendet");
    return { response: { controllers: [] } };
  };
  await card._action("delete_queue_entry", { entry_id: "1" }, "Gelöscht");
  assert.match(card._message, /Nicht ausgeführt: Bereits gesendet/);
});

test("reconnect refreshes, detach removes listeners, stale snapshots are discarded", async () => {
  const { card, hass, listeners } = setup();
  await tick();
  assert.equal(listeners.size, 2);
  let resolve;
  hass.callWS = () => new Promise((done) => { resolve = done; });
  const pending = card._refresh();
  card.disconnectedCallback();
  resolve({ response: { controllers: [{ config_entry_id: "obsolete" }] } });
  await pending;
  assert.notEqual(card._data.controllers[0]?.config_entry_id, "obsolete");
  assert.equal(listeners.size, 0);
});

test("unchanged sensor revisions cause no polling", async () => {
  const { card, hass, calls } = setup();
  await tick();
  const initial = calls.length;
  for (let i = 0; i < 100; i++) card.hass = hass;
  await tick();
  assert.equal(calls.length, initial);
});

test("editor exposes title, controller, device, status and scope", () => {
  const { elements } = setup();
  const Editor = elements.get("cul-max-queue-card-editor");
  const editor = new Editor();
  editor.setConfig({ title: "My queue" });
  for (const key of ["title", "config_entry_id", "address", "status", "scope"])
    assert.match(editor.innerHTML, new RegExp(`data-key="${key}"`));
});


test("debouncing is visible, cancellable and counts down locally without polling", async () => {
  const { card, controller, timers, calls } = setup();
  await tick();
  controller.entries.push({ id: "debounce", scope: "general", device_address: "ABCDEF",
    device_name: "Bad", description: "SetTemperature 23 °C", command_type: "SetTemperature",
    status: "debouncing", cancellable: true, attempts: 0,
    debounce_until: new Date(Date.now() + 2000).toISOString() });
  card._render();
  assert.match(card.shadowRoot.innerHTML, /Wird gesammelt/);
  assert.match(card.shadowRoot.innerHTML, /Wartend: 1/);
  assert.match(card.shadowRoot.innerHTML, /data-delete="debounce"/);
  assert.equal(timers.size, 1);
  const previous = calls.length;
  for (const callback of timers.values()) callback();
  await tick();
  assert.equal(calls.length, previous);
  card.disconnectedCallback();
  assert.equal(timers.size, 0);
});
