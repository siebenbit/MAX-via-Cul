import {test} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {loadCard} from './module-loader.mjs';
test('association selection, escaping, busy states and reconnect cleanup', async () => {
  const elements = new Map();
  class Element {constructor(){this.isConnected=true;} attachShadow(){this.shadowRoot={innerHTML:'',querySelector:()=>null,querySelectorAll:()=>[]};}}
  const context=vm.createContext({HTMLElement:Element,URL,window:{customCards:[]},customElements:{get:k=>elements.get(k),define:(k,v)=>elements.set(k,v)}});
  await loadCard(new URL('../../frontend/cul-max-room-association-card.js',import.meta.url),context);
  const card=new (elements.get('cul-max-room-association-card'))();
  let push, removed=0; const calls=[];
  card.setConfig({});
  card.hass={user:{is_admin:true},connection:{addEventListener(){},removeEventListener(){},async subscribeMessage(cb){push=cb;return()=>removed++;}},callWS:async msg=>calls.push(msg)};
  await Promise.resolve();
  const room={id:'living',name:'Wohnzimmer',group_id:5,status:'partial',busy:false,can_start:true,problems:[],devices:[{name:'<Fenster>',type:'Fensterkontakt',group_id:0}]};
  const c={config_entry_id:'a',name:'CUL',rooms:[room]};
  card._area='living';push({controllers:[c]});
  assert.match(card.shadowRoot.innerHTML,/&lt;Fenster&gt;/);
  await card._start();assert.equal(calls[0].area_id,'living');assert.equal(calls[0].config_entry_id,'a');
  room.can_start=false;room.busy=true;room.status='pending_activity';push({controllers:[c]});
  assert.match(card.shadowRoot.innerHTML,/Wartet auf Fensterkontakt/);
  await card._start();assert.equal(calls.length,1);
  push({controllers:[c,{...c,config_entry_id:'b'}]});assert.equal(card._controller(),null);
  card.disconnectedCallback();assert.equal(removed,1);
  push({controllers:[c]});assert.equal(card._online,false);
});

test('action errors survive snapshots and reconnects, and clear on retry or selection change', async () => {
  const elements = new Map();
  class Element {constructor(){this.isConnected=true;} attachShadow(){this.shadowRoot={innerHTML:'',querySelector:()=>null,querySelectorAll:()=>[]};}}
  const context=vm.createContext({HTMLElement:Element,URL,window:{customCards:[]},customElements:{get:k=>elements.get(k),define:(k,v)=>elements.set(k,v)}});
  await loadCard(new URL('../../frontend/cul-max-room-association-card.js',import.meta.url),context);
  const card=new (elements.get('cul-max-room-association-card'))();
  const events=new Map(); let push; let fail=true;
  card.setConfig({});
  const hass={user:{is_admin:true},connection:{addEventListener(k,v){events.set(k,v);},removeEventListener(k){events.delete(k);},async subscribeMessage(cb){push=cb;return()=>{};}},async callWS(){if(fail)throw Error('Speichern fehlgeschlagen');}};
  card.hass=hass; await Promise.resolve();
  const data={controllers:[{config_entry_id:'a',name:'CUL',rooms:[{id:'living',name:'Wohnzimmer',status:'new',can_start:true,problems:[],devices:[]}]}]};
  card._area='living';push(data);
  await card._start();
  assert.match(card.shadowRoot.innerHTML,/Speichern fehlgeschlagen/);
  push(data);assert.match(card.shadowRoot.innerHTML,/Speichern fehlgeschlagen/);
  events.get('disconnected')();assert.match(card.shadowRoot.innerHTML,/Verbindung getrennt/);
  events.get('ready')();await Promise.resolve();push(data);
  assert.match(card.shadowRoot.innerHTML,/Speichern fehlgeschlagen/);
  assert.doesNotMatch(card.shadowRoot.innerHTML,/Verbindung getrennt/);
  fail=false;await card._start();assert.doesNotMatch(card.shadowRoot.innerHTML,/Speichern fehlgeschlagen/);
  fail=true;await card._start();card._area='other';card._selectionChanged();
  card._area='living';push(data);assert.doesNotMatch(card.shadowRoot.innerHTML,/Speichern fehlgeschlagen/);
  let reject;
  hass.callWS=()=>new Promise((resolve, fail)=>{reject=fail;});
  const pending=card._start();
  card._area='other';card._selectionChanged();reject(Error('Alter Raum fehlgeschlagen'));await pending;
  card._area='living';push(data);assert.doesNotMatch(card.shadowRoot.innerHTML,/Alter Raum fehlgeschlagen/);
  card.disconnectedCallback();
});
