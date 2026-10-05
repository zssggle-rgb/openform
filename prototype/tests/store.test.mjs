import test from 'node:test';
import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
const mapStorage=()=>{const data=new Map();return {getItem:key=>data.get(key)??null,setItem:(key,value)=>data.set(key,value),removeItem:key=>data.delete(key),clear:()=>data.clear()};};
const events={};globalThis.window={addEventListener:(name,fn)=>events[name]=fn};globalThis.localStorage=mapStorage();globalThis.sessionStorage=mapStorage();globalThis.location={reload:()=>{}};
Object.defineProperty(globalThis,'navigator',{value:{locks:{request:async(name,fn)=>fn()}},configurable:true});
Object.defineProperty(globalThis,'crypto',{value:webcrypto,configurable:true});
const store=await import('../store.mjs');
test('storage commits before notifications, identity remains per-tab, failure cannot report success',async()=>{
 assert.equal(store.readState().schema,1);assert.equal(store.readActor(),null);const actor={kind:'staff',id:'lin'};store.setActor(actor);assert.deepEqual(store.readActor(),actor);let calls=0;const off=store.subscribe(()=>calls++);
 const id=await store.transact(actor,'createActivity',{space:'school',type:'quiz',title:'存储测试'});assert.equal(store.readState().activities[id].draft.title,'存储测试');assert.equal(calls,1);
 const saved=localStorage.setItem;localStorage.setItem=()=>{throw new Error('quota');};await assert.rejects(store.transact(actor,'createActivity',{space:'school',type:'quiz',title:'不得显示成功'}),/存储未完成/);assert.equal(calls,1);localStorage.setItem=saved;
 events.storage({key:store.STATE_KEY});assert.equal(calls,2);events.storage({key:'unrelated'});assert.equal(calls,2);
 await store.resetDemo();assert.equal(store.readActor(),null);assert.equal(Object.keys(store.readState().activities).length,5);off();
 sessionStorage.setItem('openform-integrated-actor','bad');assert.equal(store.readActor(),null);
 localStorage.setItem(store.STATE_KEY,JSON.stringify({schema:999}));assert.throws(()=>store.readState(),/不兼容/);await store.resetDemo();
 const locks=navigator.locks;navigator.locks=null;await assert.rejects(store.transact(actor,'backup'),/不支持/);navigator.locks=locks;
});
