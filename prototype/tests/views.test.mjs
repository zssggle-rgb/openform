import test from 'node:test';
import assert from 'node:assert/strict';
import { seedState,command,authenticateStudent } from '../model.mjs';
import { teacherPage } from '../teacher.mjs';
import { adminPage } from '../admin.mjs';
import { studentPage } from '../student.mjs';
import * as ui from '../ui.mjs';
import { icon } from '../icons.mjs';
const lin={kind:'staff',id:'lin'},admin={kind:'staff',id:'admin'};
globalThis.sessionStorage={getItem:()=>null};
function setup(){let state=seedState(),n=0;const run=(type,data,actor=lin)=>{const out=command(state,actor,type,data,{id:`view-${++n}`,now:'2026-10-05T02:00:00Z'});state=out.state;return out.result;};const actor=authenticateStudent(state,{code:'DEMO-001'});const attempt=run('startAttempt',{lesson:'l1'},actor);const trial=run('startTrial',{activity:'a1'});run('submitAttempt',{attempt,revision:0,answers:{q1:'图书馆',q2:'实验室',q3:'合成回答'}},actor);const report=run('report',{lesson:'l1'});run('share',{lesson:'l1',open:true,previewRevision:state.revision});run('feedback',{lesson:'l1',open:true});run('export',{lesson:'l1'});const archive=run('importPackage',{space:'school',package:{format:'openform-demo-archive',version:1,title:'示例档案',records:[]}}).id;return{get state(){return state;},run,actor,attempt,trial,report,archive};}

test('all teaching routes resolve their own objects and major tabs render',()=>{
 const f=setup();const base={activity:'a1',lesson:'l1',class:'c1',resource:'r1',report:f.report};
 for(const page of ['T01','T02','T03','T05','T06','T07','T08','T09','T10','T11','T12']){
  const html=teacherPage({state:f.state,actor:lin,space:'school',r:{page,...base}});assert.ok(html.includes('<h1'));assert.ok(!html.includes('undefined'),page);
 }
 for(const [page,tab] of [['T02','lessons'],['T03','trial'],['T06','records'],['T06','reports'],['T06','sharing'],['T12','archives']]) assert.ok(teacherPage({state:f.state,actor:lin,space:'school',r:{page,tab,...base,archive:page==='T12'?f.archive:undefined}}).length>100);
 assert.ok(teacherPage({state:f.state,actor:lin,space:'personal',r:{page:'T01'}}).includes('校园词汇闯关'));
 assert.throws(()=>teacherPage({state:f.state,actor:lin,space:'school',r:{page:'T02',activity:'a4'}}),/权限/);
 assert.throws(()=>teacherPage({state:f.state,actor:lin,space:'school',r:{page:'T07',lesson:'l2',report:f.report}}),/不匹配/);
 assert.throws(()=>teacherPage({state:f.state,actor:lin,space:'school',r:{page:'missing'}}),/未找到/);
});
test('management routes reject teacher-only roles and preserve management class context',()=>{
 const f=setup();f.run('invite',{name:'新老师'},admin);f.run('backup',{}, {kind:'ops',id:'ops'});
 for(const page of ['C01','C02','C03','C06','G02'])assert.ok(adminPage({state:f.state,actor:admin,space:'school',r:{page}}).includes('<h1'));
 assert.ok(teacherPage({state:f.state,actor:admin,space:'school',r:{page:'T09',class:'c1',mode:'admin'}}).includes('管理视图'));
 assert.ok(adminPage({state:f.state,actor:{kind:'ops',id:'ops'},r:{page:'O01'}}).includes('演示恢复'));
 assert.throws(()=>adminPage({state:f.state,actor:admin,r:{page:'O01'}}),/独立运维/);
 assert.throws(()=>adminPage({state:f.state,actor:{kind:'staff',id:'chen'},space:'school',r:{page:'C01'}}),/管理权限/);
 assert.throws(()=>adminPage({state:f.state,actor:admin,space:'school',r:{page:'missing'}}),/未找到/);
});
test('student pages show verified history, receipt and share, never fabricate missing receipts',()=>{
 const f=setup();const ctx={state:f.state,actor:f.actor};
 for(const page of ['S01','S02','S03','S04','S05']) assert.ok(studentPage({...ctx,r:{page,lesson:'l1',attempt:f.attempt}}).includes('<h1'));
 assert.ok(studentPage({...ctx,r:{page:'S01'}}).includes('课堂码'));assert.ok(studentPage({...ctx,r:{page:'S02',trial:f.trial},actor:lin}).includes('试做模式'));
 assert.throws(()=>studentPage({...ctx,r:{page:'S03',attempt:'missing'}}),/不存在/);assert.throws(()=>studentPage({...ctx,r:{page:'S01',lesson:'missing'}}),/课堂不存在/);
 assert.throws(()=>studentPage({...ctx,r:{page:'S03',attempt:f.attempt,lesson:'l2'}}),/不匹配/);
 assert.throws(()=>studentPage({...ctx,r:{page:'S04'},actor:null}),/参与身份/);
 assert.throws(()=>studentPage({...ctx,r:{page:'missing'}}),/不存在/);
 f.run('share',{lesson:'l1',open:false});assert.ok(studentPage({state:f.state,actor:f.actor,r:{page:'S05',lesson:'l1'}}).includes('已撤回'));
 const id=f.run('startAttempt',{lesson:'l1',again:true},f.actor);assert.ok(studentPage({state:f.state,actor:f.actor,r:{page:'S03',attempt:id}}).includes('尚未收到'));
 assert.ok(studentPage({state:f.state,actor:f.actor,r:{page:'S02',attempt:id,lesson:'l1',step:2}}).includes('你的回答'));
});
test('UI helpers escape input and round-trip route context without losing unicode',()=>{
 assert.equal(ui.esc('<img src="x">'), '&lt;img src=&quot;x&quot;&gt;');
 const address=ui.url('T01',{space:'school',q:'词汇 & 班级',empty:'',none:null});assert.deepEqual(ui.route(address),{page:'T01',space:'school',q:'词汇 & 班级'});
 assert.equal(ui.time(null),'尚未保存');assert.ok(ui.time('2026-10-05T00:00:00Z'));
 for(const html of [ui.link('<x>','T01'),ui.button('test','test',{id:'<x>'}),ui.badge('x'),ui.notice('x'),ui.empty('x','y'),ui.heading('x'),ui.field('x','name','<x>'),ui.textarea('x','name','<x>'),ui.selectField('x','name',[['a','A']],'a'),ui.check('x','c'),ui.table(['A'],[]),ui.row(['A']),ui.tabs([['a','A','#a']],'a'),ui.statsHTML({participants:0,completed:0,submittedAttempts:0,expected:null}),ui.questionStats({questions:[]})])assert.equal(typeof html,'string');
 assert.equal(Object.keys(ui.names).length,23);
 assert.match(icon('T01'),/svg/);assert.equal(icon('missing'),icon('T01'));
});
