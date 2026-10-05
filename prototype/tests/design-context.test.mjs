import test from 'node:test';
import assert from 'node:assert/strict';
import { seedState,command } from '../model.mjs';
import { teacherPage } from '../teacher.mjs';
import { studentPage } from '../student.mjs';
import { route,url } from '../ui.mjs';

const links=html=>[...html.matchAll(/href="([^"]+)"/g)].map(m=>route(m[1].replaceAll('&amp;','&')));
const actor={kind:'staff',id:'lin'};
globalThis.sessionStorage={getItem:()=>null};

test('FINDING-005: detail tabs, fixed versions, editor and trial preserve their actual source',()=>{
  const {state,result:trial}=command(seedState(),actor,'startTrial',{activity:'a1'},{id:'trial',now:'2026-10-05T02:00:00Z'});
  const ctx={state,actor,space:'school'};
  const back=url('T01',{space:'school',q:'词汇 & 班级'});
  const detail={page:'T02',space:'school',activity:'a1',version:'a1-v1',back};
  const detailLinks=links(teacherPage({...ctx,r:detail}));
  assert.ok(detailLinks.filter(r=>r.page==='T02').every(r=>r.back===back&&r.version==='a1-v1'));
  const editor=detailLinks.find(r=>r.page==='T03');
  assert.deepEqual(route(editor.back),detail);
  const trialTab=links(teacherPage({...ctx,r:editor})).find(r=>r.page==='T03'&&r.tab==='trial');
  assert.equal(trialTab.back,editor.back);
  const trialLink=links(teacherPage({...ctx,r:trialTab})).find(r=>r.page==='S02');
  assert.equal(trialLink.back,editor.back);
  const trialReturns=links(studentPage({...ctx,r:{page:'S02',trial,back:editor.back}})).filter(r=>r.page==='T03');
  assert.ok(trialReturns.length);
  assert.ok(trialReturns.every(r=>r.back===editor.back));
  const history={...detail,tab:'lessons'};
  const classroom=links(teacherPage({...ctx,r:history})).find(r=>r.page==='T06');
  assert.deepEqual(route(classroom.back),history);
  const classroomLinks=links(teacherPage({...ctx,r:classroom}));
  assert.ok(classroomLinks.filter(r=>r.page==='T06').every(r=>r.back===classroom.back));
  const fixed=classroomLinks.find(r=>r.page==='T02');
  assert.deepEqual(route(fixed.back),classroom);
});

test('FINDING-005: clearing a campus resource search stays in campus management',()=>{
  const html=teacherPage({state:seedState(),actor,space:'school',r:{page:'T10',mode:'admin',q:'词汇'}});
  const clear=links(html).find(r=>r.page==='T10');
  assert.equal(clear.mode,'admin');
  assert.equal(clear.q,undefined);
});
