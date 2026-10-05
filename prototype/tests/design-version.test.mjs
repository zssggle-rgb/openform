import test from 'node:test';
import assert from 'node:assert/strict';
import {seedState,command} from '../model.mjs';
import {teacherPage} from '../teacher.mjs';
import {route} from '../ui.mjs';

test('FINDING-007: a classroom version stays readable after its draft changes',()=>{
  const actor={kind:'staff',id:'lin'};
  let state=seedState();
  state=command(state,actor,'saveActivity',{activity:'a1',revision:1,title:'下一版草稿',goal:'下一版目标',questions:state.activities.a1.draft.questions.map(q=>({...q,title:'下一版题目'}))},{id:'edit',now:'2026-10-05T02:00:00Z'}).state;
  const ctx={state,actor,space:'school'};
  const fixed=teacherPage({...ctx,r:{page:'T02',activity:'a1',version:'a1-v1'}});
  assert.match(fixed,/>校园词汇闯关<\/h1>/);
  assert.match(fixed,/固定版本 v1.0/);
  assert.match(fixed,/library 的中文意思是/);
  assert.doesNotMatch(fixed,/下一版草稿|下一版目标|下一版题目/);
  const tabRoutes=[...fixed.matchAll(/href="([^"]+)"/g)].map(m=>route(m[1].replaceAll('&amp;','&'))).filter(r=>r.page==='T02');
  assert.ok(tabRoutes.length>=2);
  assert.ok(tabRoutes.every(r=>r.version==='a1-v1'));
  const draft=teacherPage({...ctx,r:{page:'T02',activity:'a1'}});
  assert.match(draft,/下一版草稿/);
  assert.match(draft,/下一版题目/);
  assert.throws(()=>teacherPage({...ctx,r:{page:'T02',activity:'a1',version:'missing'}}),/版本不存在/);
});
