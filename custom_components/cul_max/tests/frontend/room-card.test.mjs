import { test } from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import { readFileSync } from "node:fs";

function sample(id = "living", name = "Wohnzimmer") {
  const week = Object.fromEntries(["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"].map((d) => [d, "17,06:00,21,09:00,18,17:00,21,22:00,17"]));
  const values = { comfort_temperature: 21, eco_temperature: 17, window_open_temperature: 12, window_open_duration: 15, week_profile: week };
  return { id, name, values, revision: { temperature: "t1", week_profile: "w1" }, mixed: [], locks: { temperature: false, week_profile: false }, has_draft: false,
    devices: [{ address: "123456", name: "Thermostat A", config_entry_id: "cul", paired: true, confirmed: structuredClone(values), values: structuredClone(values), jobs: [], draft_blocks: [] }] };
}
function setup() {
  const elements = new Map();
  class Element {
    constructor() { this.isConnected = true; }
    attachShadow() { this.shadowRoot = { innerHTML: "", activeElement: null, querySelector: () => null, querySelectorAll: () => [] }; }
    querySelector() { return null; }
    dispatchEvent() {}
  }
  let confirmed = true;
  const context = vm.createContext({ HTMLElement: Element, window: { customCards: [], confirm: () => confirmed, addEventListener() {}, removeEventListener() {} },
    customElements: { get: (name) => elements.get(name), define: (name, el) => elements.set(name, el) }, document: { createElement: (name) => new (elements.get(name))() }, CustomEvent: class {}, console });
  vm.runInContext(readFileSync(new URL("../../frontend/cul-max-room-config-card.js", import.meta.url), "utf8"), context);
  const Profile = vm.runInContext("CulMaxRoomProfile", context);
  const card = new (elements.get("cul-max-room-config-card"))();
  const calls = [], events = new Map();
  const rooms = [sample(), sample("bed", "Schlafzimmer")];
  let push;
  let failSave = false;
  let unsubscribed = 0;
  const hass = { user: { is_admin: true }, connection: {
    subscribeMessage: async (callback) => { push = callback; callback({ rooms: structuredClone(rooms) }); return () => { unsubscribed++; }; },
    addEventListener: (key, cb) => events.set(key, cb), removeEventListener: (key) => events.delete(key),
  }, callWS: async (call) => { calls.push(call); if (failSave && call.service === "save_room_config") throw Error("Konflikt");
    return { response: call.service === "get_room_config" ? { rooms: structuredClone(rooms) } : { status: "accepted", job_ids: ["job"] } }; } };
  card.setConfig({ type: "custom:cul-max-room-config-card" }); card.hass = hass;
  return { card, Profile, normalize: vm.runInContext("normalizeRoomTime", context), rooms, hass, calls, events, elements, push: () => push({ rooms: structuredClone(rooms) }),
    setConfirm: (value) => { confirmed = value; }, failSave: () => { failSave = true; }, unsubscribed: () => unsubscribed };
}
const tick = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };

test("profile round trips, five-minute times and all 13 boundaries are validated", () => {
  const { Profile } = setup();
  const raw = "17,06:00,21,09:00,18,17:00,21,22:00,17";
  assert.equal(Profile.serialize(Profile.parse(raw)), raw);
  for (const rows of [[{ time: "00:00", temperature: 18.2 }], [{ time: "00:01", temperature: 20 }],
    [{ time: "00:00", temperature: 20 }, { time: "24:00", temperature: 18 }],
    [{ time: "00:00", temperature: "" }], Array.from({ length: 14 }, (_, i) => ({ time: `0${Math.floor(i / 12)}:${String((i % 12) * 5).padStart(2, "0")}`, temperature: 20 }))]) {
    assert.notEqual(Profile.validate(rows), "");
  }
  assert.equal(Profile.validate([{ time: "00:00", temperature: 4.5 }]), "");
  assert.match(Profile.graph(Profile.parse(raw)), /role="img"/);
});

test("room and day controls render escaped data without polling on hass state changes", async () => {
  const env = setup(); await tick();
  env.rooms[0].name = "<script>Wohnzimmer</script>"; env.push();
  assert.match(env.card.shadowRoot.innerHTML, /&lt;script&gt;/);
  assert.match(env.card.shadowRoot.innerHTML, /Komforttemperatur/);
  assert.match(env.card.shadowRoot.innerHTML, /Tag auf alle Tage kopieren/);
  const html = env.card.shadowRoot.innerHTML;
  env.card.hass = { ...env.hass, states: { anything: {} } };
  assert.equal(env.card.shadowRoot.innerHTML, html);
  assert.equal(env.calls.length, 0);
});

test("editing emits no calls; one Save includes temperature and profile changes", async () => {
  const env = setup(); await tick();
  env.card._edit("comfort_temperature", "22");
  env.card._editRows(env.Profile.parse("19,06:00,22"));
  assert.equal(env.calls.length, 0);
  await env.card._save();
  const request = env.calls.find((c) => c.service === "save_room_config");
  assert.equal(request.service_data.changes.comfort_temperature, 22);
  assert.equal(request.service_data.changes.week_profile.monday, "19,06:00,22");
  assert.ok(request.service_data.operation_id);
  assert.match(env.card._message, /eingereiht/);
});

test("day copy deep clones the draft and only Save can transmit", async () => {
  const env = setup(); await tick();
  env.card._copyDay();
  assert.equal(Object.keys(env.card._changes.week_profile).length, 7);
  env.card._changes.week_profile.monday[0].temperature = 24;
  assert.equal(env.card._changes.week_profile.tuesday[0].temperature, 17);
  assert.equal(env.calls.length, 0);
  env.setConfirm(false);
  const previous = JSON.stringify(env.card._changes);
  env.card._copyDay();
  assert.equal(JSON.stringify(env.card._changes), previous);
});

test("block locks and external conflicts preserve edits and block saving", async () => {
  const env = setup(); await tick();
  env.rooms[0].locks.temperature = true; env.push();
  assert.equal(env.card._locked("temperature"), true);
  assert.equal(env.card._locked("week_profile"), false);
  env.card._editRows(env.Profile.parse("19"));
  assert.ok(env.card._canSave());
  env.rooms[0].revision.week_profile = "w2"; env.push();
  assert.equal(env.card._conflict, true);
  assert.equal(env.card._canSave(), false);
  assert.equal(env.card._changes.week_profile.monday[0].temperature, 19);
});

test("room changes confirm discarding and missing room never silently chooses another", async () => {
  const env = setup(); await tick();
  env.card._edit("eco_temperature", "18");
  env.setConfirm(false); env.card._selectRoom("bed");
  assert.equal(env.card._area, "living");
  env.setConfirm(true); env.card._selectRoom("bed");
  assert.equal(env.card._area, "bed");
  assert.equal(env.card._dirty(), false);
});

test("save failures keep drafts and reuse the operation ID for retry", async () => {
  const env = setup(); await tick(); env.failSave();
  env.card._edit("eco_temperature", "18");
  await env.card._save();
  assert.equal(env.card._changes.eco_temperature, "18");
  assert.match(env.card._error, /Konflikt/);
  await env.card._save();
  const calls = env.calls.filter((c) => c.service === "save_room_config");
  assert.equal(calls[0].service_data.operation_id, calls[1].service_data.operation_id);
});

test("reconnect subscribes again, detach cleans up, read-only clients receive explanation", async () => {
  const env = setup(); await tick();
  env.events.get("disconnected")();
  assert.equal(env.card._online, false);
  env.events.get("ready")(); await tick();
  assert.equal(env.card._online, true);
  assert.equal(env.unsubscribed(), 1);
  env.card.disconnectedCallback();
  assert.equal(env.unsubscribed(), 2);
  assert.equal(env.events.size, 0);
  env.card.hass = { ...env.hass, user: { is_admin: false } }; await tick();
  assert.match(env.card._error, /Administratoren/);
});

test("empty queue, mixed values and completed or failed jobs render safely", async () => {
  const env = setup(); await tick();
  env.rooms[0].values.eco_temperature = null; env.rooms[0].mixed = ["eco_temperature"];
  env.rooms[0].devices[0].jobs = [{ id: "j", block: "temperature", status: "queued", confirmed_steps: [], steps: ["s"], last_error: "Kein ACK <error>" }];
  env.push();
  assert.match(env.card.shadowRoot.innerHTML, /placeholder="Gemischt"/);
  assert.match(env.card.shadowRoot.innerHTML, /Kein ACK &lt;error&gt;/);
  assert.match(env.card.shadowRoot.innerHTML, /erneuter Versuch ausstehend/);
  env.rooms.length = 0; env.push();
  assert.match(env.card.shadowRoot.innerHTML, /Keine MAX!-Thermostate/);
});

test("visual editor exists and has title and initial room configuration", () => {
  const env = setup();
  const editor = new (env.elements.get("cul-max-room-config-card-editor"))();
  editor.setConfig({ title: "Raum & Plan" });
  assert.match(editor.innerHTML, /Raum &amp; Plan/);
  assert.match(editor.innerHTML, /Start-Raum/);
});

test("accepted operations report final confirmation only when all jobs complete", async () => {
  const env = setup(); await tick();
  env.card._lastOperation = "op"; env.card._lastOperationCount = 2;
  const job = { id: "j1", block: "temperature", operation_id: "op", status: "completed", confirmed_steps: ["s"], steps: ["s"] };
  env.rooms[0].devices[0].jobs = [job]; env.push();
  assert.doesNotMatch(env.card._message || "", /Alle Konfigurationsänderungen/);
  env.rooms[0].devices[0].jobs.push({ ...job, id: "j2", status: "queued", confirmed_steps: [] }); env.push();
  assert.doesNotMatch(env.card._message || "", /Alle Konfigurationsänderungen/);
  env.rooms[0].devices[0].jobs[1].status = "completed"; env.push();
  assert.match(env.card._message, /Alle Konfigurationsänderungen sind bestätigt/);
});

test("24-hour input normalization accepts numeric mobile input without AM/PM", () => {
  const env = setup();
  assert.equal(env.normalize("0630"), "06:30");
  assert.equal(env.normalize("6:30"), "06:30");
  assert.equal(env.normalize("6"), "06:00");
  env.card._editRows([{ time: "00:00", temperature: 20 }]);
  assert.match(env.card.shadowRoot.innerHTML, /type="text" inputmode="numeric"/);
});

test("a removed selected room keeps its draft and cannot save into another room", async () => {
  const env = setup(); await tick();
  env.card._edit("eco_temperature", "18");
  env.rooms.splice(0, 1); env.push();
  assert.equal(env.card._area, "living");
  assert.equal(env.card._changes.eco_temperature, "18");
  assert.match(env.card.shadowRoot.innerHTML, /Raum nicht mehr verfügbar/);
  assert.ok(!env.card._canSave());
});
