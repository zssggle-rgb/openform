import test from 'node:test';
import assert from 'node:assert/strict';
import {workspaceLinks} from '../ui.mjs';

test('FINDING-006: both navigation surfaces can use the same permission-scoped areas',()=>{
  const dual=workspaceLinks({space:'school',teaching:true,administration:true});
  assert.match(dual,/教学工作台/);
  assert.match(dual,/校园管理/);
  assert.match(dual,/mode=admin/);
  const admin=workspaceLinks({space:'school',teaching:false,administration:true,admin:true});
  assert.doesNotMatch(admin,/教学工作台/);
  assert.match(admin,/class="selected"/);
  const teacher=workspaceLinks({space:'personal',teaching:true,administration:false});
  assert.match(teacher,/space=personal/);
  assert.doesNotMatch(teacher,/校园管理/);
  assert.equal(workspaceLinks({space:'school',teaching:false,administration:false}),'');
});
