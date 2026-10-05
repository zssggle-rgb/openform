import test from 'node:test';
import assert from 'node:assert/strict';
import { seedState,command,can,select,readable,statistics,authenticateStudent,lessonContent,QUESTIONS } from '../model.mjs';

const lin={kind:'staff',id:'lin'},chen={kind:'staff',id:'chen'},admin={kind:'staff',id:'admin'},ops={kind:'ops',id:'ops'};
function fixture(){let state=seedState(),counter=0;return {get state(){return state;},run(type,data={},actor=lin){const result=command(state,actor,type,data,{id:`test-${++counter}`,now:`2026-10-05T03:${String(counter%60).padStart(2,'0')}:00.000Z`});state=result.state;return result.result;}};}
function complete(f,lesson='l1',code='DEMO-001',again=false){const actor=authenticateStudent(f.state,{lessonId:lesson,code});const id=f.run('startAttempt',{lesson,again},actor);const qs=lessonContent(f.state,lesson).questions;const answers=Object.fromEntries(qs.map(q=>[q.id,q.correct??(q.type==='number'?'120':'合成回答')]));f.run('saveAttempt',{attempt:id,revision:f.state.attempts[id].revision,answers,step:2},actor);f.run('submitAttempt',{attempt:id,revision:f.state.attempts[id].revision,answers,step:2},actor);return {id,actor,answers};}

test('seed identities, spaces and ownership are independent',()=>{
 const s=seedState();assert.equal(can(s,lin,'personal'),true);assert.equal(can(s,chen,'personal'),false);assert.equal(can(s,admin,'school'),false);assert.equal(can(s,null,'school'),false);assert.equal(can(s,admin,'school','admin'),true);
 assert.equal(select(s,lin,'school').activities.length,3);assert.equal(select(s,chen,'school').lessons.length,1);assert.equal(select(s,admin,'school').classes.length,2);
 assert.throws(()=>readable(s,lin,'activities','a4'),/编辑权限/);assert.throws(()=>readable(s,admin,'lessons','l1'),/教学权限/);assert.throws(()=>readable(s,chen,'classes','c1'),/授权范围/);assert.throws(()=>readable(s,lin,'activities','missing'),/不存在/);assert.throws(()=>readable(s,null,'resources','r1'),/学校空间/);
 assert.equal(readable(s,lin,'classes','c1').id,'c1');assert.equal(readable(s,chen,'resources','r1').id,'r1');
});
test('three creation paths create findable independent drafts and reject invalid input',()=>{
 const f=fixture();for(const [type,source] of [['words','教学想法'],['quiz','活动样板'],['lab','HTML 导入']]){const id=f.run('createActivity',{space:'school',type,title:'同名活动',source,...(type==='lab'?{html:'<!doctype html><body>实验</body>'}:{})});assert.equal(f.state.activities[id].draft.type,type);assert.equal(f.state.activities[id].versions.length,0);}
 assert.equal(select(f.state,lin,'school').activities.length,6);assert.throws(()=>f.run('createActivity',{space:'school',type:'bad',title:'x'}),/样板/);assert.throws(()=>f.run('createActivity',{space:'school',type:'words',title:''}),/名称/);assert.throws(()=>f.run('createActivity',{space:'school',type:'words',title:'x',html:'bad'}),/HTML/);assert.throws(()=>f.run('createActivity',{space:'personal',type:'words',title:'x'},chen),/权限/);
});
test('editing invalidates verification; full trial fixes immutable version',()=>{
 const f=fixture();const old=structuredClone(f.state.activities.a1.versions[0]);f.run('saveActivity',{activity:'a1',revision:1,title:'改过的词汇',goal:'新目标',questions:QUESTIONS.words});assert.equal(f.state.activities.a1.verifiedRevision,0);assert.deepEqual(f.state.activities.a1.versions[0],old);
 assert.throws(()=>f.run('saveActivity',{activity:'a1',revision:1,title:'冲突'}),/另一窗口/);assert.throws(()=>f.run('saveActivity',{activity:'a1',revision:2,title:''}),/不能为空/);assert.throws(()=>f.run('saveActivity',{activity:'a1',revision:2,title:'x',questions:[]}),/三道/);
 assert.throws(()=>f.run('verifyActivity',{activity:'a1',confirmed:false}),/复核/);assert.throws(()=>f.run('verifyActivity',{activity:'a1',confirmed:true}),/试做回执/);
 const trial=f.run('startTrial',{activity:'a1'});assert.equal(readable(f.state,lin,'trials',trial).revision,2);assert.throws(()=>readable(f.state,chen,'trials',trial),/编辑权限/);
 const data={trial:true,attempt:trial,answers:{q1:'图书馆',q2:'实验室',q3:'校园安静'},step:2};f.run('saveAttempt',data);f.run('submitAttempt',data);const version=f.run('verifyActivity',{activity:'a1',confirmed:true});assert.equal(f.state.activities.a1.versions.length,2);assert.equal(f.run('verifyActivity',{activity:'a1',confirmed:true}),version);assert.equal(Object.keys(f.state.attempts).length,0);
 f.run('saveActivity',{activity:'a1',revision:2,title:'再改'});const stale=f.run('startTrial',{activity:'a1'});f.run('saveActivity',{activity:'a1',revision:3,title:'继续改'});assert.throws(()=>f.run('saveAttempt',{trial:true,attempt:stale,answers:{}}),/重新开始/);
});
test('launch uses fixed version, assignment and duplicate request id',()=>{
 const f=fixture();const data={activity:'a1',version:'a1-v1',kind:'class',classId:'c1',requestId:'req1',title:'新的课堂'};const id=f.run('launch',data);assert.equal(f.run('launch',data),id);assert.equal(statistics(f.state,id).completed,0);assert.equal(f.state.lessons[id].title,'新的课堂');
 assert.throws(()=>f.run('launch',{...data,requestId:'other',classId:'c2'}),/任课/);assert.throws(()=>f.run('launch',{...data,requestId:'other',version:'missing'}),/试做/);assert.throws(()=>f.run('launch',{...data,requestId:''}),/请求标识/);assert.throws(()=>f.run('launch',{...data,requestId:'x',kind:'bad'}),/参与方式/);
 const quick=f.run('launch',{activity:'a2',version:'a2-v1',kind:'quick',requestId:'quick',later:true});assert.equal(f.state.lessons[quick].status,'paused');assert.equal(statistics(f.state,quick).expected,null);
});
test('student code distinguishes same names and rejects classroom/wrong class codes',()=>{
 const s=seedState();assert.equal(authenticateStudent(s,{lessonId:'l1',code:' demo-003 '}).id,'s3');assert.throws(()=>authenticateStudent(s,{lessonId:'l1',code:'QH1001'}),/个人码/);assert.throws(()=>authenticateStudent(s,{lessonId:'l2',code:'DEMO-001'}),/参与范围/);assert.throws(()=>readable(s,{kind:'student',id:'s1',epoch:0},'lessons','l1'),/失效/);
});
test('progress, receipt, retry, new attempt and a second classroom do not collide',()=>{
 const f=fixture(),student=authenticateStudent(f.state,{lessonId:'l1',code:'DEMO-001'});const id=f.run('startAttempt',{lesson:'l1'},student);assert.equal(f.run('startAttempt',{lesson:'l1'},student),id);
 f.run('saveAttempt',{attempt:id,revision:0,answers:{q1:'图书馆'},step:1},student);assert.equal(statistics(f.state,'l1').completed,0);assert.equal(statistics(f.state,'l1').participants,1);assert.throws(()=>f.run('saveAttempt',{attempt:id,revision:0,answers:{}} ,student),/另一窗口/);
 assert.throws(()=>f.run('submitAttempt',{attempt:id,revision:1,answers:{q1:'图书馆'}},student),/每道题/);
 const done=complete(f);const receipt=f.state.attempts[id].receipt;f.run('submitAttempt',{attempt:id,revision:0,answers:{}},student);assert.equal(f.state.attempts[id].receipt,receipt);assert.equal(statistics(f.state,'l1').completed,1);
 const next=complete(f,'l1','DEMO-001',true);assert.notEqual(next.id,done.id);assert.equal(statistics(f.state,'l1').completed,1);assert.equal(statistics(f.state,'l1').submittedAttempts,2);assert.equal(statistics(f.state,'l1').questions[0].correct,1);assert.equal(statistics(f.state,'l1').questions[2].correct,null);
 const other=f.run('launch',{activity:'a1',version:'a1-v1',kind:'class',classId:'c1',requestId:'second'});complete(f,other);assert.equal(statistics(f.state,other).completed,1);assert.equal(statistics(f.state,'l1').submittedAttempts,2);
 const foreign=authenticateStudent(f.state,{code:'DEMO-002'});assert.throws(()=>readable(f.state,foreign,'attempts',id),/不是你的/);assert.throws(()=>f.run('saveAttempt',{attempt:id,revision:1,answers:{}},foreign),/其他人/);assert.throws(()=>readable(f.state,chen,'attempts',id),/教学数据权限/);assert.equal(readable(f.state,lin,'attempts',id).id,id);
});
test('pause blocks writes; resume keeps progress; ended classroom cannot reopen',()=>{
 const f=fixture(),actor=authenticateStudent(f.state,{code:'DEMO-001'});const id=f.run('startAttempt',{lesson:'l1'},actor);f.run('lessonStatus',{lesson:'l1',status:'paused'});assert.throws(()=>f.run('saveAttempt',{attempt:id,revision:0,answers:{}},actor),/暂停/);f.run('lessonStatus',{lesson:'l1',status:'open'});f.run('saveAttempt',{attempt:id,revision:0,answers:{q1:'图书馆'}},actor);assert.throws(()=>f.run('lessonStatus',{lesson:'l1',status:'bad'}),/无效/);f.run('lessonStatus',{lesson:'l1',status:'ended'});assert.throws(()=>f.run('lessonStatus',{lesson:'l1',status:'open'}),/已结束/);
});
test('quick activities and all schemas, image and number validation',()=>{
 const f=fixture();for(const activity of ['a1','a2','a3']){const lesson=f.run('launch',{activity,version:activity+'-v1',kind:'quick',requestId:activity});const actor=f.run('quickJoin',{lesson,name:'临时同学'},null);const id=f.run('startAttempt',{lesson},actor);const questions=lessonContent(f.state,lesson).questions;const answers=Object.fromEntries(questions.map(q=>[q.id,q.correct??(q.type==='number'?'120':'实验记录')]));
 if(activity==='a3'){assert.throws(()=>f.run('saveAttempt',{attempt:id,revision:0,answers:{q1:'bad'}},actor),/数值/);}
 assert.throws(()=>f.run('saveAttempt',{attempt:id,revision:0,answers,images:[{url:'https://evil',name:'x'}]},actor),/图片/);
 f.run('submitAttempt',{attempt:id,revision:0,answers,images:activity==='a3'?[{name:'demo.jpg',url:'data:image/jpeg;base64,AA=='}]:[]},actor);assert.equal(statistics(f.state,lesson).completed,1);assert.equal(statistics(f.state,lesson).expected,null);
 }
 assert.throws(()=>f.run('quickJoin',{lesson:'l1',name:'x'},null),/临时/);assert.throws(()=>f.run('quickJoin',{lesson:Object.keys(f.state.lessons).at(-1),name:''},null),/称呼/);
 const actor=authenticateStudent(f.state,{code:'DEMO-001'}),id=f.run('startAttempt',{lesson:'l1'},actor);assert.throws(()=>f.run('saveAttempt',{attempt:id,revision:0,answers:{q1:'bad'}},actor),/选项/);assert.throws(()=>f.run('saveAttempt',{attempt:id,revision:0,answers:{q3:'x'.repeat(4001)}},actor),/4,000/);assert.throws(()=>f.run('saveAttempt',{attempt:id,revision:0,answers:{},images:[{url:'data:image/jpeg;base64,AA=='}]},actor),/不支持图片/);
});
test('reports are immutable snapshots, evidence stays bound and model failures do not block sharing',()=>{
 const f=fixture();assert.throws(()=>f.run('report',{lesson:'l1'}),/尚无/);complete(f);const rep=f.run('report',{lesson:'l1'});const snapshot=structuredClone(f.state.reports[rep].stats);complete(f,'l1','DEMO-002');assert.deepEqual(f.state.reports[rep].stats,snapshot);const second=f.run('report',{lesson:'l1'});assert.equal(f.state.reports[second].stats.completed,2);f.run('reviewReport',{report:rep});assert.equal(readable(f.state,lin,'reports',rep).reviewed,true);assert.throws(()=>readable(f.state,chen,'reports',rep),/权限/);
 f.run('settings',{space:'school',name:'青禾',model:false});assert.throws(()=>f.run('report',{lesson:'l1'}),/模型/);const revision=f.state.revision;f.run('share',{lesson:'l1',open:true,previewRevision:revision});assert.equal(f.state.lessons.l1.sharing.stats.completed,2);complete(f,'l1','DEMO-003');assert.equal(f.state.lessons.l1.sharing.stats.completed,2);assert.throws(()=>f.run('share',{lesson:'l1',open:true,previewRevision:revision}),/重新预览/);
 f.run('feedback',{lesson:'l1',open:true,text:'请复习第二题'});assert.equal(f.state.lessons.l1.feedback,true);f.run('share',{lesson:'l1',open:false});assert.equal(f.state.lessons.l1.sharing,null);
});
test('class roster and assignment drive teacher scope, reset invalidates old sessions without deleting receipts',()=>{
 const f=fixture();const cls=f.run('createClass',{space:'school',name:'新班级'},admin);assert.throws(()=>f.run('assign',{classId:cls,teachers:['admin']},admin),/有效教学成员/);f.run('assign',{classId:cls,teachers:['chen']},admin);assert.equal(select(f.state,chen,'school').classes.some(c=>c.id===cls),true);assert.equal(select(f.state,lin,'school').classes.find(c=>c.id===cls).teachers.includes('lin'),false);
 const st=f.run('addStudent',{classId:cls,name:'合成学生'},admin);assert.equal(f.state.students[st].classId,cls);const done=complete(f);f.run('resetCode',{student:'s1'});assert.throws(()=>authenticateStudent(f.state,{code:'DEMO-001'}),/失效/);assert.throws(()=>readable(f.state,done.actor,'attempts',done.id),/失效/);const current=authenticateStudent(f.state,{code:f.state.students.s1.code});assert.equal(readable(f.state,current,'attempts',done.id).id,done.id);
 f.run('moveStudent',{student:st,classId:'c1'},admin);assert.equal(f.state.students[st].classId,'c1');assert.throws(()=>f.run('moveStudent',{student:st,classId:'pc1'},admin),/跨空间/);assert.throws(()=>f.run('resetCode',{student:'s4'} ,{kind:'staff',id:'nobody'}),/无权/);
});
test('invitation is pending until accepted, handover respects personal space, disabled users denied',()=>{
 const f=fixture();const invite=f.run('invite',{name:'新老师'},admin);assert.equal(f.state.invitations[invite].status,'pending');const newcomer=f.run('acceptInvite',{invitation:invite},null);assert.equal(can(f.state,newcomer,'school'),true);assert.equal(select(f.state,newcomer,'school').classes.length,0);assert.throws(()=>f.run('acceptInvite',{invitation:invite},null),/已接受/);
 f.run('handover',{from:'lin',to:'chen'},admin);assert.equal(f.state.activities.a1.owner,'chen');assert.equal(f.state.activities.ap.owner,'lin');assert.equal(f.state.lessons.l1.owner,'chen');assert.equal(f.state.classes.c1.teachers[0],'chen');assert.throws(()=>f.run('handover',{from:'chen',to:'chen'},admin),/另一位/);assert.throws(()=>f.run('memberStatus',{member:'admin',active:false},admin),/本人/);f.run('memberStatus',{member:'chen',active:false},admin);assert.equal(can(f.state,chen,'school'),false);
});
test('resource copy is independent and revoked sources cannot create new copies',()=>{
 const f=fixture();const resource=f.run('publishResource',{activity:'a2',version:'a2-v1'});const copy=f.run('copyResource',{resource},chen);f.run('revokeResource',{resource},lin);assert.throws(()=>f.run('copyResource',{resource},chen),/撤回/);assert.equal(f.state.activities[copy].versions.length,0);assert.equal(f.state.activities[copy].owner,'chen');assert.equal(f.state.activities[copy].draft.type,'quiz');assert.throws(()=>f.run('publishResource',{activity:'ap',version:'ap-v1'}),/学校空间/);assert.throws(()=>f.run('publishResource',{activity:'a2',version:'missing'}),/固定/);assert.throws(()=>f.run('revokeResource',{resource:'r1'},chen),/无权/);
});
test('exports and imports are findable; archives do not produce live attempts',()=>{
 const f=fixture();complete(f);const task=f.run('export',{lesson:'l1'});assert.equal(readable(f.state,lin,'tasks',task).package.records.length,1);assert.throws(()=>readable(f.state,chen,'tasks',task),/无权/);
 const result=f.run('importPackage',{space:'school',package:f.state.tasks[task].package});assert.equal(result.type,'archive');assert.equal(readable(f.state,lin,'archives',result.id).records.length,1);assert.throws(()=>readable(f.state,chen,'archives',result.id),/无权/);assert.equal(statistics(f.state,'l1').completed,1);
 const activity=f.run('importPackage',{space:'personal',package:{format:'openform-demo-resource',version:1,type:'lab',title:'新实验'}});assert.equal(activity.type,'activity');assert.equal(f.state.activities[activity.id].space,'personal');assert.throws(()=>f.run('importPackage',{space:'school',package:{}}),/格式/);assert.throws(()=>f.run('importPackage',{space:'school',package:{format:'openform-demo-resource',version:1,type:'bad',title:'x'}}),/类型/);assert.throws(()=>f.run('importPackage',{space:'school',package:{format:'openform-demo-archive',version:1,title:'x',records:null}}),/记录/);
});
test('ops restore retains history but invalidates credentials and closes participation',()=>{
 const f=fixture();const done=complete(f);assert.throws(()=>f.run('backup',{},admin),/运维/);const backup=f.run('backup',{},ops);f.run('resetCode',{student:'s1'});f.run('restore',{backup},ops);assert.equal(f.state.students.s1.code,null);assert.equal(f.state.lessons.l1.status,'ended');assert.equal(f.state.attempts[done.id].receipt.startsWith('OF-'),true);assert.throws(()=>readable(f.state,done.actor,'attempts',done.id),/失效/);
});
test('unsupported or malformed commands never mutate original state',()=>{
 const s=seedState();const before=structuredClone(s);assert.throws(()=>command(s,lin,'unknown',{}, {id:'x'}),/不支持/);assert.throws(()=>command(s,lin,'backup'),/唯一标识/);assert.deepEqual(s,before);assert.throws(()=>lessonContent(s,'missing'),/不存在/);assert.throws(()=>command(s,lin,'settings',{space:'school',name:''},{id:'x'}),/名称/);
});
test('deleting evidence invalidates snapshots, selected shared content and cached exports',()=>{
 const f=fixture();const done=complete(f);const report=f.run('report',{lesson:'l1'});const task=f.run('export',{lesson:'l1'});
 f.run('share',{lesson:'l1',open:true,previewRevision:f.state.revision,selectedAttemptIds:[done.id]});assert.equal(f.state.lessons.l1.sharing.selected.length,1);
 assert.throws(()=>f.run('deleteAttempt',{attempt:done.id},chen),/权限/);f.run('deleteAttempt',{attempt:done.id});assert.equal(f.state.reports[report].invalid,true);assert.equal(f.state.lessons.l1.sharing,null);assert.equal(f.state.tasks[task].package,undefined);assert.equal(statistics(f.state,'l1').completed,0);
});
