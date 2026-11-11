import { test } from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { loadCard } from './module-loader.mjs';
test('pairing live results, escaping, controller selection and cleanup', async () => {
  const elements = new Map();
  class Element { constructor() { this.isConnected = true; } attachShadow() { this.shadowRoot = { innerHTML: '', activeElement:null, querySelector:()=>null, querySelectorAll:()=>[] }; } }
  const context = vm.createContext({HTMLElement:Element, URL, console, Date, setInterval, clearInterval, window:{customCards:[]},
    customElements:{get:k=>elements.get(k),define:(k,v)=>elements.set(k,v)}});
  await loadCard(new URL('../../frontend/cul-max-pairing-card.js?v=test',import.meta.url), context);
  const card = new (elements.get('cul-max-pairing-card'))();
  let push, unsubscribed=0; const calls=[];
  card.setConfig({});
  card.hass={user:{is_admin:true},connection:{addEventListener(){},removeEventListener(){}, subscribeMessage:async cb=>{push=cb; return ()=>unsubscribed++;}},callWS:async msg=>calls.push(msg)};
  await Promise.resolve();
  const c={config_entry_id:'a',name:'CUL',connected:true,active:false,session_id:'s',devices:[{name:'<img>',device_type:'Thermostat',device_id:'abc',area_name:'Bad'}]};
  push({controllers:[c]});
  assert.match(card.shadowRoot.innerHTML,/&lt;img&gt;/);
  assert.match(card.shadowRoot.innerHTML,/data-edit="abc"/);
  assert.doesNotMatch(card.shadowRoot.innerHTML,/href="\/config\/devices/);
  c.own_address = '123456';
  c.rejected = [{address:'ABCDEF', partner_address:'FEDCBA', name:'<rejected>'}];
  push({controllers:[c]});
  assert.match(card.shadowRoot.innerHTML, /Eigene Zentralenadresse: 123456/);
  assert.match(card.shadowRoot.innerHTML, /Pairing abgelehnt/);
  assert.match(card.shadowRoot.innerHTML, /Bisheriger Pairing-Partner: FEDCBA/);
  assert.match(card.shadowRoot.innerHTML, /&lt;rejected&gt;/);
  assert.doesNotMatch(card.shadowRoot.innerHTML, /<rejected>/);
  await card._start(); assert.equal(calls[0].config_entry_id,'a'); assert.equal(calls[0].duration,60);
  push({controllers:[c,{...c,config_entry_id:'b'}]});
  assert.equal(card._controller(),null);
  await card._start(); assert.equal(calls.length,1);
  card.disconnectedCallback(); assert.equal(unsubscribed,1);
  assert.throws(()=>card.setConfig({duration:0}));
});
