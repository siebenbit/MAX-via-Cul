import { test } from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import { loadCard } from "./module-loader.mjs";
async function setup() {
  const elements = new Map();
  const context = vm.createContext({ URL, HTMLElement: class {}, customElements: { get: key => elements.get(key), define: (key, value) => elements.set(key,value) } });
  return loadCard(new URL("../../frontend/cul-max-device-dialog.js", import.meta.url), context);
}
test("only edited fields are sent, including removing a custom name or room", async () => {
  const { deviceChanges } = await setup();
  const device = {name:"Heizung",name_by_user:null,area_id:"bad"};
  assert.equal(JSON.stringify(deviceChanges(device,"Heizung","bad")),"{}");
  assert.equal(JSON.stringify(deviceChanges(device," Heizung Bad ","bad")),JSON.stringify({name_by_user:"Heizung Bad"}));
  assert.equal(JSON.stringify(deviceChanges(device,"Heizung","")),JSON.stringify({area_id:null}));
  assert.equal(JSON.stringify(deviceChanges({...device,name_by_user:"Bad"},"","bad")),JSON.stringify({name_by_user:null}));
});
test("canceled loads, missing devices and permissions never open a dialog", async () => {
  const { openDeviceDialog } = await setup();
  const hass = {user:{is_admin:false},callWS:async()=>[]};
  await assert.rejects(openDeviceDialog({},hass,"dev"),/Administrator/);
  hass.user.is_admin=true;
  await openDeviceDialog({},hass,"dev",()=>false);
  await assert.rejects(openDeviceDialog({},hass,"dev"),/nicht mehr vorhanden/);
});
