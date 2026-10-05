import test from 'node:test';
import assert from 'node:assert/strict';
import {seedState,command} from '../model.mjs';
import {trialReturn,route} from '../ui.mjs';

test('FINDING-001: teacher trial navigation belongs to its actual activity and space',()=>{
  const actor={kind:'staff',id:'lin'};
  const {state,result:id}=command(seedState(),actor,'startTrial',{activity:'ap'},{id:'trial',now:'2026-10-05T02:00:00Z'});
  const r={page:'S02',trial:id,space:'school',back:'#T01?space=personal&q=词汇'};
  assert.deepEqual(route(trialReturn(state,actor,r)),{page:'T03',space:'personal',activity:'ap',tab:'trial',back:r.back});
  assert.equal(trialReturn(state,{kind:'student',id:'s1'},r),null);
  assert.equal(trialReturn(state,{kind:'staff',id:'chen'},r),null);
  assert.equal(trialReturn(state,actor,{...r,trial:'missing'}),null);
  assert.equal(trialReturn(state,null,r),null);
  assert.equal(trialReturn(state,actor,{...r,page:'S01'}),null);
});
