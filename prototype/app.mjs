import { can, select, readable, statistics, authenticateStudent, lessonContent } from './model.mjs';
import { icon } from './icons.mjs';
import { readState, readActor, setActor, transact, subscribe, resetDemo } from './store.mjs';
import { teacherPage } from './teacher.mjs';
import { adminPage } from './admin.mjs';
import { studentPage } from './student.mjs';
import { names, typeNames, esc as e, time, url, route, link, button, badge, notice, heading, field, textarea, selectField, check, questionStats, statsHTML } from './ui.mjs';

const root=document.querySelector('#app');
const dialog=document.querySelector('#dialog');
let dirty=false, currentHash=location.hash, suppressHash=false, rendering=false, committing=false;
let focusBeforeDialog, modalAction, toastTimer, pendingImages;
let context;
const $=selector=>document.querySelector(selector);
function updateHeaderHeight(){const header=root.querySelector('header');if(header)document.documentElement.style.setProperty('--header-height',`${header.getBoundingClientRect().height}px`);}
const staffHome=(s,actor,space='school')=>can(s,actor,space)?'T01':'C01';
const notify=message=>{const target=$('#toast');target.textContent=message;target.hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>{target.hidden=true;},4500);};
function error(message) {
  const target=dialog.open?dialog:root.querySelector('main');
  target.querySelector('.error-box')?.remove();
  const box=document.createElement('div');box.className='error-box';box.setAttribute('role','alert');box.textContent=message;target.prepend(box);box.scrollIntoView({block:'nearest'});
}
function navigate(page,params={}) { location.hash=url(page,params); }
function modal(title,body,action,submit='确认') {
  focusBeforeDialog=document.activeElement;modalAction=action;
  dialog.innerHTML=`<form id="modal-form"><div class="dialog-head"><h2 id="dialog-title">${e(title)}</h2><button type="button" data-action="close-modal" aria-label="关闭弹窗">×</button></div><div class="dialog-body">${body}</div><div class="modal-actions">${button('取消','close-modal')} ${action?`<button class="primary">${e(submit)}</button>`:''}</div></form>`;
  dialog.querySelectorAll('button[data-action]').forEach(el=>{el.type='button';});
  if(!dialog.open) dialog.showModal();
}
function closeModal(){dialog.close();modalAction=null;focusBeforeDialog?.focus();}
dialog.addEventListener('close',()=>focusBeforeDialog?.focus());
const formObject=form=>Object.fromEntries(new FormData(form));
async function act(type,data={}) {
  committing=true;
  try {return await transact(readActor(),type,data);} finally {committing=false;}
}
function safeBack(r) {
  if(r.back && /^#(?:T|C|G)\d{2}(?:\?|$)/.test(r.back)) return r.back;
  const map={T02:'T01',T03:'T02',T06:'T05',T07:'T06',T09:r.mode==='admin'?'C02':'T08',T11:'T10',G02:r.mode==='admin'?'C01':'T01'};
  return url(map[r.page]||'T01',{space:r.space||'school',activity:r.activity,lesson:r.lesson,mode:r.mode});
}
function authPage(s,r) {
  if(r.invite) {
    const invitation=s.invitations[r.invite];
    if(!invitation) throw new Error('邀请不存在或已失效。');
    return heading('加入青禾实验学校','教师邀请 · 演示流程')+notice(`受邀成员：${e(invitation.name)} · ${invitation.status==='pending'?'待本人接受':'此邀请已接受'}`,'')+(invitation.status==='pending'?button('接受邀请并进入学校','accept-invite',{invitation:invitation.id},'primary wide'):link('返回演示登录','G01',{},'btn'));
  }
  return heading('进入 OpenForm','请选择已配置的演示身份，开始体验完整课堂流程。') + notice('所有数据均为合成示例，保存在本机浏览器。可打开多个标签页演示教师、管理员和学生联动；没有连接账号服务、后端或 AI。','') + `<section class="panel"><h2>教师与校园工作台</h2><div class="demo-grid">${Object.values(s.members).filter(m=>m.active).map(m=>button(`${m.name} · ${m.roles.map(role=>role==='teacher'?'教师':'校管').join(' / ')}`,'login',{member:m.id,space:'school'})).join('')}${button('林老师 · 个人空间','login',{member:'lin',space:'personal'})}</div><h2 style="margin-top:24px">学生入口</h2><p class="muted">学生参与同一课堂时，请在另一个标签页打开入口。</p>${link('输入课堂码 / 个人码','S01',{},'btn wide')}<details style="margin-top:24px"><summary>原型工具与独立运维</summary><p class="source-note">用于设计走查；演示身份选择不代表正式登录和权限验证。</p><div class="row">${button('运维演示入口','ops-login')}${button('重置合成数据','reset',{},'danger')}<a href="http://127.0.0.1:8771/openform-html-assets-20261004/index.html" target="_blank" rel="noopener">原 23 页设计目录</a></div></details></section>`;
}
function shell(ctx,body) {
  const {state:s,actor,r,space}=ctx;const student=r.page.startsWith('S');const bare=student||r.page==='G01'||r.page==='O01';
  const admin=r.mode==='admin'||r.page.startsWith('C');
  const home=staffHome(s,actor,space);
  const homeUrl=student?url('S01',{lesson:r.lesson}):r.page==='O01'?url('O01'):r.page==='G01'?url('G01'):url(admin?'C01':home,{space,mode:admin?'admin':undefined});
  const nav=admin?[['C01','成员与权限','人'],['C02','班级与任课','班'],['C03','学生名册','册'],['T10','资源管理','库'],['C06','运行与记录','记']]:[['T01','我的活动','作'],['T05','我的课堂','课'],['T08','我的班级','班'],...(space==='school'?[['T10','校内资源库','库']]:[]),['T12','资料迁移与档案','档']];
  const selected={T02:'T01',T03:'T01',T06:'T05',T07:'T05',T09:admin?'C02':'T08',T11:'T10'}[r.page]||r.page;
  document.body.className=`${bare?'bare':''} ${student?'student':''} ${r.page==='G01'?'auth':''}`;
  return `<a class="skip" href="#main" data-action="skip">跳到主要内容</a><header class="topbar">${!bare?button('☰','menu',{},'nav-toggle'):''}<a class="logo" href="${e(homeUrl)}" aria-label="OpenForm 首页"><img src="../assets/brand/svg/openform-logo-primary.svg" alt="OpenForm"></a>${!bare?`<nav class="topnav" aria-label="工作区域">${can(s,actor,space)?link('教学工作台','T01',{space},!admin?'selected':''):''}${space==='school'&&can(s,actor,space,'admin')?link('校园管理','C01',{space,mode:'admin'},admin?'selected':''):''}</nav><div class="space">${actor?.id==='lin'?`<select aria-label="当前空间" id="space-select"><option value="school" ${space==='school'?'selected':''}>${e(s.spaces.school.name)}</option><option value="personal" ${space==='personal'?'selected':''}>${e(s.spaces.personal.name)}</option></select>`:`<span>${e(s.spaces[space]?.name)}</span>`}<span class="account">${e(s.members[actor?.id]?.name)}</span><span class="demo-label">交互原型</span>${button('退出','logout',{},'account-menu')}</div>`:`<span class="top-context">${student?(r.trial?'当前草稿 · 试做':actor?.kind==='student'?e(s.students[actor.id]?.name||'参与身份'): '学生活动入口'):'本机合成数据演示'}</span>${r.page!=='G01'?button(student?'退出身份':'退出','logout',{},'link'):''}`}</header>${!bare?`<aside class="sidebar"><div class="side-label">${admin?'校园管理':'教学工作台'}</div><nav aria-label="主要导航">${nav.map(([id,title])=>`<a href="${e(url(id,{space,mode:admin?'admin':undefined}))}" aria-label="${title}" ${selected===id?'aria-current="page"':''}>${icon(id)}<span>${title}</span></a>`).join('')}</nav><div class="side-bottom">${can(s,actor,space,'admin')?link('设置 · 当前空间','G02',{space,mode:admin?'admin':undefined}):''}${link('演示 · 切换身份','G01')}</div></aside>`:''}<main id="main" tabindex="-1">${!bare?`<div class="bread">${e(s.spaces[space]?.name)} / ${e(names[r.page]||'页面')}${['T02','T03','T06','T07','T09','T11','G02'].includes(r.page)?` · <a href="${e(safeBack(r))}">返回</a>`:''}</div>`:''}<div id="sync-notice" hidden></div>${body}</main>`;
}
function render(focus=false) {
  if(rendering)return;rendering=true;
  try {
    const state=readState(),actor=readActor(),r=route(),space=r.space||'school';context={state,actor,r,space};
    let body;
    try {
      if(!names[r.page]) throw new Error('页面地址不存在。');
      if(!r.page.startsWith('S')) for(const [param,collection] of [['activity','activities'],['lesson','lessons'],['class','classes'],['resource','resources'],['report','reports'],['archive','archives']]) {
        if(r[param] && state[collection][r[param]] && state[collection][r[param]].space !== space) throw new Error('此对象不属于当前空间，请返回对应空间的列表。');
      }
      if(r.page==='G01') body=authPage(state,r);
      else if(r.page.startsWith('S')) body=studentPage(context);
      else {
        if(r.page!=='O01'&&!actor) {
          sessionStorage.setItem('openform-return',location.hash);
          body=heading('请先进入工作台')+notice('登录后返回这个页面，并核验当前身份是否可访问。','')+link('选择演示身份','G01',{},'btn primary');
        } else {
          if(r.page!=='O01'&&!can(state,actor,space)&&!can(state,actor,space,'admin')) throw new Error('当前空间身份已停用或无访问权限。');
          if(r.page.startsWith('C')||['G02','O01'].includes(r.page)) body=adminPage(context); else body=teacherPage(context);
        }
      }
    } catch(err) {
      body=`<section class="panel page-error">${heading('当前内容不可用')}<p role="alert">${e(err.message)}</p><div class="row">${r.page.startsWith('S')?link('验证参与身份','S01',{lesson:r.lesson},'btn primary'):link('返回空间首页',staffHome(state,actor,space),{space},'btn primary')}${link('演示入口','G01',{},'btn')}</div></section>`;
    }
    root.innerHTML=shell(context,body);document.title=`${names[r.page]||'OpenForm'} · OpenForm`;updateHeaderHeight();
    const menu=root.querySelector('[data-action=menu]');if(menu){menu.setAttribute('aria-label','展开导航');menu.setAttribute('aria-expanded','false');}
    root.querySelectorAll('button[data-action]').forEach(el=>el.type='button');
    dirty=false;pendingImages=undefined;
    if(focus) root.querySelector('h1')?.focus({preventScroll:true});
  } catch(err) {root.innerHTML=`<main class="page-error"><h1>本机演示数据无法读取</h1><p>${e(err.message)}</p>${button('重置合成数据','reset')}</main>`;}
  finally{rendering=false;}
}

function launchModal(input={}) {
  const {state:s,actor,space}=context;const data=select(s,actor,space);
  const activities=data.activities.filter(a=>a.versions.length);
  if(!activities.length) throw new Error('还没有已固定版本的活动，请先制作并完成试做。');
  const activity=activities.find(a=>a.id===input.activity)||activities[0];
  const classes=data.classes.filter(c=>c.teachers.includes(actor.id));
  const requestId=crypto.randomUUID();
  modal('开展一次新课堂',`${notice('每次确认会创建独立课堂。使用固定版本，草稿之后的修改不影响本课堂。','')}${selectField('使用活动','activity',activities.map(a=>[a.id,a.draft.title]),activity.id)}${selectField('固定版本','version',activity.versions.map(v=>[v.id,v.label+' · 修订 '+v.revision]),input.version||activity.versions.at(-1).id)}${field('课堂名称','title',activity.draft.title,'text','required maxlength="100"')}${selectField('参与方式','kind',[['class','班级个人码'],['quick','快速临时参与']],classes.length?'class':'quick')}${selectField('班级','classId',classes.map(c=>[c.id,c.name]),input.class||classes[0]?.id||'')}${check('稍后开放接收','later')}${check('提交后开放本人答案与反馈','feedback')}`,async(form,values)=>{
    const id=await act('launch',{...values,requestId,later:form.later.checked,feedback:form.feedback.checked});closeModal();navigate('T06',{space,lesson:id});
  },'确认开展');
  dialog.querySelector('[name=activity]').addEventListener('change',event=>{
    const a=activities.find(a=>a.id===event.target.value);dialog.querySelector('[name=version]').innerHTML=a.versions.map(v=>`<option value="${e(v.id)}">${e(v.label)}</option>`).join('');dialog.querySelector('[name=title]').value=a.draft.title;
  });
  const sync=()=>{dialog.querySelector('[name=classId]').closest('label').hidden=dialog.querySelector('[name=kind]').value==='quick';};
  dialog.querySelector('[name=kind]').addEventListener('change',sync);sync();
}
function collectAnswer() {
  const form=$('form[data-form=answer]');if(!form)return null;
  const s=readState();const trial=form.dataset.trial==='true';const record=(trial?s.trials:s.attempts)[form.dataset.record];
  let pending;try{pending=JSON.parse(sessionStorage.getItem('openform-pending-'+record.id)||'null');}catch{pending=null;}
  return {attempt:record.id,trial,revision:Number(form.dataset.revision),answers:{...(pending?.answers||record.answers),[form.dataset.question]:form.elements.answer.value},step:Number(form.dataset.step),images:pendingImages||pending?.images||record.images};
}
function cacheAnswer(){const data=collectAnswer();if(data)sessionStorage.setItem('openform-pending-'+data.attempt,JSON.stringify(data));return data;}
async function saveAnswer(submit=false,next) {
  const data=cacheAnswer();if(!data)return;
  if(!navigator.onLine) throw new Error('当前离线，内容只暂存在本机，尚未确认提交。恢复连接后请点击保存或提交重试。');
  const id=await act(submit?'submitAttempt':'saveAttempt',data);
  sessionStorage.removeItem('openform-pending-'+id);dirty=false;
  if(data.trial) {
    if(submit){render();notify('已收到试做回执，返回制作器完成检查。');}
    else if(next!==undefined){navigate('S02',{trial:id,step:next});}else{render();notify('试做进度已确认保存。');}
  } else if(submit) navigate('S03',{lesson:context.r.lesson||readState().attempts[id].lesson,attempt:id});
  else if(next!==undefined) navigate('S02',{lesson:readState().attempts[id].lesson,attempt:id,step:next});
  else {render();notify('进度已确认保存。');}
}
function download(filename,value){
  const json=JSON.stringify(value,null,2);const blob=new Blob([json],{type:'application/json'});const href=URL.createObjectURL(blob);
  modal('导出资料包',`<p>文件：${e(filename)}</p><p class="field-help">如果当前浏览器没有开始下载，可复制下面的 JSON 并保存为同名文件。</p><a class="btn primary" href="${e(href)}" download="${e(filename)}">保存 JSON 文件</a>${button('复制资料包内容','copy-package')}<label class="field" style="margin-top:16px"><span>资料包内容</span><textarea name="export-content" rows="10" readonly>${e(json)}</textarea></label>`,null);
  dialog.addEventListener('close',()=>URL.revokeObjectURL(href),{once:true});
}

const actions={
  'close-modal':()=>closeModal(),
  'copy-package':async()=>{const input=dialog.querySelector('[name=export-content]');try{await navigator.clipboard.writeText(input.value);notify('资料包内容已复制。');}catch{input.focus();input.select();notify('内容已选中，请按复制快捷键。');}},
  menu:()=>{document.body.classList.toggle('nav-open');$('[data-action=menu]').setAttribute('aria-expanded',String(document.body.classList.contains('nav-open')));},
  skip:()=>$('#main').focus(),
  login:async d=>{if(!readState().members[d.member]?.active)throw new Error('该身份已停用。');setActor({kind:'staff',id:d.member});const back=sessionStorage.getItem('openform-return');sessionStorage.removeItem('openform-return');if(back&&/^#(?:T|C|G)\d{2}(?:\?|$)/.test(back))location.hash=back;else navigate(staffHome(readState(),readActor(),d.space),{space:d.space});},
  'ops-login':()=>{setActor({kind:'ops',id:'ops'});navigate('O01');},
  logout:()=>modal('退出当前身份', '<p>退出后清除本标签页的身份与未确认作答。已确认的课堂数据和回执保留；共享设备请勿把个人码留给他人。</p>',async()=>{
    for(const key of Object.keys(sessionStorage))if(key.startsWith('openform-pending-'))sessionStorage.removeItem(key);
    setActor(null);dirty=false;closeModal();navigate(context.r.page.startsWith('S')?'S01':'G01',context.r.lesson?{lesson:context.r.lesson}:{});render();
  },'退出身份'),
  reset:()=>modal('重置演示数据','<p>会清除当前浏览器此原型的课堂、草稿、回执和备份，并恢复初始合成数据。原单页设计稿不受影响。</p>',async()=>{await resetDemo();for(const key of Object.keys(sessionStorage))if(key.startsWith('openform-pending-'))sessionStorage.removeItem(key);dirty=false;closeModal();navigate('G01');render();},'重置'),
  'new-activity':()=>modal('新建活动',`${selectField('开始方式','source',[['教学想法','从教学想法开始'],['活动样板','使用活动样板'],['HTML 导入','导入 HTML 页面']])}${selectField('课堂样板','type',Object.entries(typeNames))}${field('活动名称','title','','text','required maxlength="80" placeholder="例如：校园词汇闯关"')}${textarea('教学想法','goal','')}${notice('原型用三类已适配样板演示制作；不会假装调用生成模型。导入 HTML 仅隔离预览，正式开展需对结构化题目重新试做。','')}<label class="field"><span>HTML 文件（仅导入方式需要）</span><input name="html" type="file" accept=".html,text/html"></label>`,async(form,values)=>{let html;if(values.source==='HTML 导入'){const file=form.html.files[0];if(!file)throw new Error('请选择 HTML 文件。');html=await file.text();}const id=await act('createActivity',{...values,space:context.space,html});dirty=false;closeModal();navigate('T03',{space:context.space,activity:id});},'创建草稿'),
  'start-trial':async d=>{const id=await act('startTrial',{activity:d.activity});navigate('S02',{trial:id});},
  launch:d=>launchModal(d),
  'html-preview':d=>{const a=readable(readState(),readActor(),'activities',d.activity);modal('导入 HTML · 隔离预览',notice('未授予脚本、同源、表单或外部资源访问权限。课堂使用制作器中的结构化题目。','')+'<iframe title="导入页面隔离预览" sandbox="" referrerpolicy="no-referrer" style="width:100%;height:340px;border:1px solid #EAECEF"></iframe>',null);dialog.querySelector('iframe').srcdoc=`<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:">${a.html}`;},
  entry:d=>{const l=readable(readState(),readActor(),'lessons',d.lesson);const href=location.href.split('#')[0]+url('S01',{lesson:l.id});const qr=window.qrcode(0,'M');qr.addData(href);qr.make();modal('学生参与入口',`<p>${e(l.title)}</p><div class="preview-card entry-code">${qr.createSvgTag({cellSize:3,margin:3,scalable:true}).replace('<svg ','<svg class="qr" aria-label="当前课堂参与链接二维码" ')}<span class="muted">课堂码</span><div class="code-large">${e(l.code)}</div></div><p>${l.kind==='class'?'课堂码只定位活动。请从班级名单领取学生个人码。':'学生填写称呼后参与当前快速活动。'}</p><label class="field"><span>本机演示参与链接</span><input value="${e(href)}" readonly></label><a class="btn primary" href="${e(href)}" target="_blank" rel="noopener">在新标签页打开学生入口</a><p class="source-note">同一浏览器标签页可联动。127.0.0.1 链接不能作为学生设备接入地址。</p>`,null);},
  'lesson-status':async d=>{await act('lessonStatus',{lesson:d.lesson,status:d.status});render();notify('课堂接收状态已更新。');},
  'end-lesson':d=>modal('结束本次课堂','<p>结束后停止接收新作答和提交，已确认内容保留。如需再上一次课，请再次开展新课堂。</p>',async()=>{await act('lessonStatus',{lesson:d.lesson,status:'ended'});closeModal();render();},'结束课堂'),
  evidence:d=>{const s=readState(),a=readable(s,readActor(),'attempts',d.attempt);modal('原始作答依据',`<p>${e(s.students[a.student]?.name)} · 第 ${a.number} 次尝试 · ${a.receipt?'已提交':'进行中'}</p><p class="source-note">${time(a.savedAt)} · ${e(a.receipt||'暂无最终回执')}</p>${Object.entries(a.answers).map(([key,value])=>`<div class="summary-question"><h3>${e(lessonContent(s,a.lesson).questions.find(q=>q.id===key)?.title||key)}</h3><p class="readonly-content">${e(value)}</p></div>`).join('')}<div class="image-grid">${a.images.map(img=>`<figure><img src="${e(img.url)}" alt="${e(img.name)}"><figcaption>${e(img.name)}</figcaption></figure>`).join('')}</div>`,null);},
  report:async d=>{const id=await act('report',{lesson:d.lesson});navigate('T07',{space:context.space,lesson:d.lesson,report:id});},
  'review-report':async d=>{await act('reviewReport',{report:d.report});render();notify('当前报告已标记教师复核。');},
  'delete-attempt':d=>modal('删除这份原始记录','<p>将从本机合成数据中删除此尝试，并使引用它的诊断、共享和导出缓存失效。已经下载到文件的副本无法收回。</p>',async()=>{await act('deleteAttempt',{attempt:d.attempt});closeModal();render();notify('记录已删除，关联内容已失效。');},'删除本条演示记录'),
  'preview-share':d=>{const s=readState();readable(s,readActor(),'lessons',d.lesson);const stats=statistics(s,d.lesson);const records=Object.values(s.attempts).filter(a=>a.lesson===d.lesson&&a.receipt);modal('预览学生将看到的共享结果',notice('默认仅题目汇总。勾选下方某份作答才会额外开放其回答文字，不含姓名、个人码和照片。','')+statsHTML(stats)+questionStats(stats)+`<details><summary>明确选择额外共享的回答（可选）</summary>${records.map((a,i)=>`<div class="summary-question"><label class="check-row"><input type="checkbox" name="selectedAttempt" value="${e(a.id)}"><span>开放示例回答 ${i+1}（第 ${a.number} 次尝试）</span></label><p class="readonly-content">${Object.values(a.answers).map(e).join(' / ')}</p></div>`).join('')}</details>`,async form=>{await act('share',{lesson:d.lesson,open:true,previewRevision:s.revision,selectedAttemptIds:new FormData(form).getAll('selectedAttempt')});closeModal();render();notify('已发布这一版共享结果。');},'确认开放此版本');},
  'revoke-share':d=>modal('撤回共享结果','<p>学生再次读取时将不再显示内容；已看过或下载的材料无法收回。</p>',async()=>{await act('share',{lesson:d.lesson,open:false});closeModal();render();},'撤回'),
  'new-class':()=>modal('新建班级',field('班级名称','name','','text','required maxlength="60"'),async(form,values)=>{await act('createClass',{...values,space:context.space});closeModal();render();notify('班级已创建，学校班级需要指定任课并添加学生。');},'创建班级'),
  assign:d=>{const s=readState(),cls=s.classes[d.class];modal('指定任课教师',`<p>${e(cls.name)}</p>${Object.values(s.members).filter(m=>can(s,{kind:'staff',id:m.id},context.space)).map(m=>`<label class="check-row"><input type="checkbox" name="teacher" value="${e(m.id)}" ${cls.teachers.includes(m.id)?'checked':''}><span>${e(m.name)}</span></label>`).join('')}<p class="source-note">任课只赋予班级范围，不自动开放其他教师已有课堂的答卷。</p>`,async form=>{await act('assign',{classId:cls.id,teachers:new FormData(form).getAll('teacher')});closeModal();render();},'保存任课');},
  'new-student':d=>modal('添加合成学生',field('姓名','name','','text','required maxlength="40"')+selectField('班级','classId',select(readState(),readActor(),context.space).classes.map(c=>[c.id,c.name]),d.class),async(form,values)=>{await act('addStudent',values);closeModal();render();},'添加学生'),
  'reset-code':d=>modal('重置学生个人码','<p>新码关联原稳定学生标识，已确认历史保持不变。旧码和该学生原有标签页身份立即失效。</p>',async()=>{await act('resetCode',{student:d.student});closeModal();render();notify('个人码已更新，请发放新码。');},'重置个人码'),
  'move-student':d=>modal('学生调班',selectField('目标班级','classId',select(readState(),readActor(),context.space).classes.map(c=>[c.id,c.name])),async(form,values)=>{await act('moveStudent',{student:d.student,...values});closeModal();render();notify('已调班并更新凭据，旧历史仍保留。');},'确认调班'),
  invite:()=>modal('邀请一位教师',field('教师姓名','name','','text','required maxlength="40"')+notice('邀请链接保存在本页，接受后成员才生效。本原型不会发送邮件或消息。',''),async(form,values)=>{await act('invite',values);closeModal();render();},'生成邀请'),
  'accept-invite':async d=>{const actor=await act('acceptInvite',{invitation:d.invitation});setActor(actor);navigate('T01',{space:'school'});},
  'member-status':d=>modal(d.active==='true'?'启用成员':'停用成员','<p>将更新该成员在学校工作台的可用权限，个人资产不参与学校交接。</p>',async()=>{await act('memberStatus',{member:d.member,active:d.active==='true'});closeModal();render();},'确认'),
  handover:d=>{const s=readState();modal('交接学校资产',`<p>交出成员：${e(s.members[d.member].name)}</p>${selectField('接收教师','to',Object.values(s.members).filter(m=>m.id!==d.member&&can(s,{kind:'staff',id:m.id},'school')).map(m=>[m.id,m.name]))}${notice('将交接其学校活动、课堂、资源和任课，个人空间保持原归属。','warn')}`,async(form,values)=>{await act('handover',{from:d.member,to:values.to});closeModal();render();notify('学校资产交接完成。');},'确认交接');},
  'publish-resource':d=>modal('发布到校内资源库','<p>仅发布所选固定版本的教学内容，不包含学生记录、班级名单和参与凭据。</p>',async()=>{const id=await act('publishResource',{activity:d.activity,version:d.version});closeModal();navigate('T11',{space:'school',resource:id});},'发布资源'),
  'copy-resource':async d=>{const id=await act('copyResource',{resource:d.resource});navigate('T03',{space:'school',activity:id});notify('独立副本已保存到我的活动。');},
  'revoke-resource':d=>modal('撤回校内资源','<p>撤回后其他教师不能再复制，已产生的独立副本仍保留。</p>',async()=>{await act('revokeResource',{resource:d.resource});closeModal();render();},'撤回资源'),
  export:async d=>{const id=await act('export',{lesson:d.lesson});navigate('T12',{space:context.space,task:id});},
  download:d=>{const task=readable(readState(),readActor(),'tasks',d.task);download('openform-classroom-archive.json',task.package);},
  'sample-package':()=>download('openform-resource-example.json',{format:'openform-demo-resource',version:1,title:'导入的分数课堂',type:'quiz',goal:'理解分数加减并描述过程。'}),
  'import-package':()=>modal('导入资料包','<p>资源包生成新草稿；数据包导入为只读档案，不进入当前学生历史。</p><label class="field"><span>OpenForm 演示 JSON 包（最大 5 MB）</span><input type="file" name="package" accept="application/json,.json" required></label>',async form=>{const file=form.package.files[0];if(!file||file.size>5000000)throw new Error('请选择不超过 5 MB 的 JSON 资料包。');let pkg;try{pkg=JSON.parse(await file.text());}catch{throw new Error('无法解析 JSON 资料包，未导入内容。');}const result=await act('importPackage',{space:context.space,package:pkg});closeModal();navigate(result.type==='activity'?'T03':'T12',{space:context.space,...(result.type==='activity'?{activity:result.id}:{tab:'archives',archive:result.id})});},'检查并导入'),
  backup:async()=>{await act('backup');render();notify('本机演示快照已保存。');},
  restore:d=>modal('演示恢复备份',notice('会替换当前合成业务数据，旧个人码和参与身份全部失效，课堂关闭。此操作只用于本机演示。','warn'),async()=>{await act('restore',{backup:d.backup});closeModal();render();notify('演示恢复完成，请在工作台重新发放个人码。');},'确认演示恢复'),
  'choose-answer':d=>{const form=$('form[data-form=answer]');form.elements.answer.value=d.value;form.querySelectorAll('.option').forEach(el=>el.setAttribute('aria-pressed',String(el.dataset.value===d.value)));dirty=true;cacheAnswer();},
  'save-answer':()=>saveAnswer(),
  'next-answer':d=>saveAnswer(false,Number(d.step)),
  step:d=>{const data=cacheAnswer();dirty=false;navigate('S02',{...(data.trial?{trial:data.attempt}:{lesson:context.r.lesson,attempt:data.attempt}),step:d.step});},
  'clear-images':()=>{pendingImages=[];dirty=true;cacheAnswer();$('#images').innerHTML='';},
  again:async d=>{const id=await act('startAttempt',{lesson:d.lesson,again:true});navigate('S02',{lesson:d.lesson,attempt:id});},
  refresh:()=>{if(dirty){modal('重新读取已确认内容','<p>当前本机未确认修改将被放弃，请确认后重新载入。</p>',()=>{const form=$('form[data-form=answer]');if(form)sessionStorage.removeItem('openform-pending-'+form.dataset.record);dirty=false;closeModal();render();},'重新读取');}else render();},
};

document.addEventListener('click',async event=>{
  const target=event.target.closest('[data-action]');if(!target)return;
  event.preventDefault();if(target.disabled)return;const handler=actions[target.dataset.action];if(!handler)return;
  target.disabled=true;
  try{await handler(target.dataset);}catch(err){error(err.message);}finally{target.disabled=false;}
});
document.addEventListener('submit',async event=>{
  event.preventDefault();const form=event.target;const submit=form.querySelector('button[type=submit],button:not([type])');if(submit?.disabled)return;
  const values=formObject(form);if(submit)submit.disabled=true;
  try {
    if(form.id==='modal-form'){if(modalAction)await modalAction(form,values);return;}
    const {state:s,r,space}=context;
    switch(form.dataset.form){
      case 'filter': navigate(r.page,{...r,q:values.q});break;
      case 'class-filter': navigate('C03',{space,mode:'admin',class:values.class});break;
      case 'editor':{
        const a=readable(readState(),readActor(),'activities',r.activity);
        await act('saveActivity',{activity:a.id,revision:Number(form.dataset.revision),title:values.title,goal:values.goal,questions:a.draft.questions.map(q=>({...q,title:values['question-'+q.id]}))});dirty=false;render();notify('草稿已保存，需要重新试做当前修订。');break;
      }
      case 'verify': await act('verifyActivity',{activity:r.activity,confirmed:form.confirmed.checked});render();notify('本修订已固定，可以开展。');break;
      case 'feedback': await act('feedback',{lesson:r.lesson,open:form.open.checked,text:values.text});dirty=false;render();notify('反馈设置已保存。');break;
      case 'settings': await act('settings',{space,name:values.name,model:form.model.checked});dirty=false;render();notify('空间设置已保存。');break;
      case 'locate-lesson': {const l=Object.values(readState().lessons).find(item=>item.code===values.code.trim().toUpperCase());if(!l)throw new Error('未找到课堂，请核对老师提供的课堂码。');navigate('S01',{lesson:l.id});break;}
      case 'student-history-login': {const actor=authenticateStudent(readState(),{code:values.code});setActor(actor);navigate('S04');break;}
      case 'student-login': {
        const lesson=form.dataset.lesson;const actor=form.dataset.kind==='class'?authenticateStudent(readState(),{lessonId:lesson,code:values.code}):await act('quickJoin',{lesson,name:values.name});setActor(actor);
        const id=await act('startAttempt',{lesson});dirty=false;navigate(readState().attempts[id].receipt?'S03':'S02',{lesson,attempt:id});break;
      }
      case 'answer':await saveAnswer(true);break;
    }
  }catch(err){error(err.message);}finally{if(submit)submit.disabled=false;}
});
document.addEventListener('input',event=>{
  const form=event.target.closest('form');if(!form||form.id==='modal-form')return;
  if(['editor','feedback','settings','answer'].includes(form.dataset.form)){dirty=true;const status=$('#save-state');if(status){status.textContent='尚有未确认修改';status.style.color='var(--warning)';}if(form.dataset.form==='answer')cacheAnswer();}
});
document.addEventListener('change',async event=>{
  if(event.target.id==='space-select'){navigate(staffHome(readState(),readActor(),event.target.value),{space:event.target.value});return;}
  if(event.target.name==='images'){
    try {
      const files=[...event.target.files];if(files.length>5)throw new Error('最多选择 5 张照片。');
      const images=[];
      for(const file of files){
        if(!['image/png','image/jpeg'].includes(file.type)||file.size>10*1024*1024)throw new Error('照片须为 PNG 或 JPEG，单张不超过 10 MB。');
        const bitmap=await createImageBitmap(file);if(bitmap.width>12000||bitmap.height>12000){bitmap.close();throw new Error('图片尺寸过大，请选择长边小于 12,000 像素的图片。');}
        const scale=Math.min(1,900/Math.max(bitmap.width,bitmap.height));const canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.round(bitmap.width*scale));canvas.height=Math.max(1,Math.round(bitmap.height*scale));canvas.getContext('2d').drawImage(bitmap,0,0,canvas.width,canvas.height);bitmap.close();const image=canvas.toDataURL('image/jpeg',.7);if(image.length>=600000)throw new Error('压缩后图片仍过大，请选择更小的照片。');images.push({name:file.name,url:image});
      }
      pendingImages=images;dirty=true;cacheAnswer();$('#images').innerHTML=images.map(img=>`<figure><img src="${e(img.url)}" alt="${e(img.name)}"><figcaption>${e(img.name)}</figcaption></figure>`).join('');
    }catch(err){error(err.message);event.target.value='';}
  }
});
document.addEventListener('click',event=>{
  const anchor=event.target.closest('a[href^="#"]');if(!anchor||event.ctrlKey||event.metaKey||event.shiftKey||anchor.dataset.action)return;
  if(dirty&&anchor.hash!==location.hash){event.preventDefault();const destination=anchor.getAttribute('href');modal('离开前处理未保存修改','<p>当前未确认修改尚未保存。可以取消并留在这里保存，或放弃未保存内容后离开。</p>',()=>{const form=$('form[data-form=answer]');if(form)sessionStorage.removeItem('openform-pending-'+form.dataset.record);dirty=false;closeModal();location.hash=destination;},'放弃修改并离开');}
},true);
window.addEventListener('hashchange',()=>{
  if(suppressHash){suppressHash=false;return;}
  if(dirty){const next=location.hash;suppressHash=true;location.hash=currentHash;modal('离开前处理未保存修改','<p>当前有未确认修改，取消可返回保存。</p>',()=>{dirty=false;closeModal();location.hash=next;},'放弃修改并离开');return;}
  if(dialog.open)closeModal();currentHash=location.hash;render(true);window.scrollTo(0,0);
});
window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
subscribe(()=>{
  if(committing)return;
  const latest=readState();const actor=readActor();
  const invalid=actor?.kind==='student'&&latest.students[actor.id]?.epoch!==actor.epoch||actor?.kind==='staff'&&!latest.members[actor.id]?.active;
  if(invalid){dirty=false;if(dialog.open)closeModal();render();return;}
  if(dirty||dialog.open){const target=$('#sync-notice');if(target){target.hidden=false;target.className='notice warn';target.innerHTML='其他标签页已更新数据。当前修改保留；保存冲突时请重新读取。 '+button('重新读取','refresh');}return;}
  render();
});
window.addEventListener('online',()=>notify('连接已恢复，请保存进度或提交以获取确认。'));
window.addEventListener('offline',()=>notify('当前离线，作答仅暂存本机。'));
window.addEventListener('resize',updateHeaderHeight);
render();
