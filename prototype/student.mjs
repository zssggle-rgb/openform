import { readable, lessonContent } from './model.mjs';
import { esc as e,time,url,link,button,badge,notice,heading,field,textarea,empty,statsHTML,questionStats,statusNames } from './ui.mjs';

export function studentPage({state:s,actor,r}) {
  if(r.page==='S01') {
    const lesson=r.lesson?s.lessons[r.lesson]:Object.values(s.lessons).find(l=>l.code===r.code?.toUpperCase());
    if(r.lesson&&!lesson) throw new Error('课堂不存在或链接已失效，请向老师索取当前入口。');
    return heading(lesson?.title||'进入课堂活动',lesson?`${lesson.kind==='class'?'使用老师发放的个人码':'临时参与本次活动'} · ${badge(statusNames[lesson.status],lesson.status==='open'?'green':'amber')}`:'输入课堂码定位活动，或用个人码查看本人记录。') + `<section class="panel">${lesson ? `<form data-form="student-login" data-lesson="${e(lesson.id)}" data-kind="${lesson.kind}">${lesson.kind==='class'?field('个人码','code','','text','required autocomplete="off" placeholder="例如 DEMO-001"'):field('你的称呼','name','','text','required maxlength="30" autocomplete="off"')}${notice(lesson.kind==='class'?'个人码与课堂码不同。名字相同也要使用自己的个人码。':'临时身份只在当前浏览器、当前课堂使用；关闭身份后无法按姓名找回。','')}<button class="primary wide" ${lesson.status==='open'?'':'disabled'}>进入活动</button></form>${lesson.status!=='open'?notice('老师暂未接收新的参与。已验证身份可从“我的记录”查看已确认内容。','warn'):''}` : `<form data-form="locate-lesson">${field('课堂码','code','','text','required autocomplete="off" placeholder="例如 QH1001"')}<button class="primary wide">查找课堂</button></form><hr><form data-form="student-history-login"><h2>查看本人记录</h2>${field('个人码','code','','text','required autocomplete="off" placeholder="使用当前有效的个人码"')}<button class="wide">验证个人码</button></form>`}</section><p class="source-note">合成数据演示：第一班学生个人码 DEMO-001、DEMO-002、DEMO-003；第二班 DEMO-004。重置后请向演示教师领取新码。</p>${actor?.kind==='student'?link('我的记录','S04',{},'btn'):''}`;
  }
  if(r.page==='S02') {
    const trial=Boolean(r.trial);
    const record=readable(s,actor,trial?'trials':'attempts',trial?r.trial:r.attempt);
    const lesson=trial?null:readable(s,actor,'lessons',record.lesson);
    if(!trial&&r.lesson&&r.lesson!==record.lesson) throw new Error('作答与课堂不匹配。');
    const content=trial?record.content:lessonContent(s,lesson.id);
    if(record.receipt) return heading(trial?'试做已完成':'这次作答已提交',e(content.title)) + notice(`${trial?'试做':'提交'}回执：<span class="token">${e(record.receipt)}</span>`,'good') + (trial?link('返回制作器完成检查','T03',{space:s.activities[record.activity].space,activity:record.activity,tab:'trial'},'btn primary'):link('查看本次回执','S03',{lesson:record.lesson,attempt:record.id},'btn primary'));
    let pending;
    try { pending=JSON.parse(sessionStorage.getItem('openform-pending-'+record.id)||'null'); } catch { pending=null; }
    const answers=pending?.answers||record.answers;
    const step=Math.min(2,Math.max(0,Number(r.step??pending?.step??record.step)));
    const question=content.questions[step];
    const input=question.options?`<div class="options">${question.options.map(value=>`<button type="button" class="option" data-action="choose-answer" data-value="${e(value)}" aria-pressed="${answers[question.id]===value}">${e(value)}</button>`).join('')}</div><input type="hidden" name="answer" value="${e(answers[question.id]||'')}">`:question.type==='number'?field('你的记录（毫升）','answer',answers[question.id]??'','number','min="0" step="any" required'):textarea('你的回答','answer',answers[question.id]??'','maxlength="4000" required');
    return `${trial?notice('试做模式 · 仅检查当前草稿，不会创建正式学生记录。','warn'):''}${heading(content.title,trial?`草稿修订 ${record.revision}`:`${e(s.students[record.student]?.name)} · 第 ${record.number} 次尝试 · ${e(statusNames[lesson.status])}`)}<section class="panel"><div class="split"><span class="question-count">第 ${step+1} / ${content.questions.length} 题</span><span class="save-state" id="save-state">${pending?'本机有待确认内容':record.savedAt?`已确认保存 ${time(record.savedAt)}`:'尚未保存进度'}</span></div><div class="bar" style="margin-top:12px"><i style="width:${(step+1)/3*100}%"></i></div><form data-form="answer" data-record="${e(record.id)}" data-question="${question.id}" data-step="${step}" data-trial="${trial}" data-revision="${record.revision}"><h2 class="question">${e(question.title)}</h2>${input}${question.type==='images'?`<label class="field" style="margin-top:16px"><span>实验照片（可选，最多 5 张）</span><input type="file" name="images" accept="image/png,image/jpeg" multiple><span class="field-help">原型压缩后保存在本机；每张原图不超过 10 MB。</span></label><div id="images" class="image-grid">${(pending?.images||record.images).map(img=>`<figure><img src="${e(img.url)}" alt="${e(img.name)}"><figcaption>${e(img.name)}</figcaption></figure>`).join('')}</div>${button('移除本次照片','clear-images')}`:''}<div class="action-row">${step>0?button('上一题','step',{step:step-1}):''}${step<2?button('保存并下一题','next-answer',{step:step+1},'primary'):'<button class="primary">确认提交</button>'}</div><div class="row" style="margin-top:16px">${button('保存进度','save-answer')}${trial?link('返回制作器','T03',{space:s.activities[record.activity].space,activity:record.activity,tab:'trial'}):link('我的记录','S04')}</div></form></section><div class="notice ${lesson&&lesson.status!=='open'?'warn':''}" style="margin-top:16px">${lesson&&lesson.status!=='open'?'老师已暂停或结束接收。已确认内容保留；当前未确认内容暂存本机，恢复接收后重试。':'只有收到明确回执才表示本次提交完成。进度保存不计为完成。'}</div>`;
  }
  if(r.page==='S04') {
    const student=s.students[actor?.id];
    if(actor?.kind!=='student'||!student?.active||student.epoch!==actor.epoch) throw new Error('参与身份已失效，请用当前个人码重新验证。');
    const attempts=Object.values(s.attempts).filter(a=>a.student===actor.id&&a.space===student.space).reverse();
    return heading('我的记录',`${e(student.name)} · ${student.temporary?'本次临时课堂':'当前学校的本人记录'}`) + (attempts.length?attempts.map(a=>`<section class="panel attempt-card" style="margin-bottom:16px"><div class="split"><h2>${e(s.lessons[a.lesson]?.title)}</h2>${badge(a.receipt?'已提交':'进行中',a.receipt?'green':'amber')}</div><p class="muted">第 ${a.number} 次尝试 · ${time(a.savedAt)}</p><div class="row">${link(a.receipt?'查看回执':'继续作答',a.receipt?'S03':'S02',{lesson:a.lesson,attempt:a.id},'btn primary')}${s.lessons[a.lesson]?.sharing?link('共享结果','S05',{lesson:a.lesson},'btn'):''}</div></section>`).join(''):empty('还没有参与记录','输入课堂码后开始第一次活动。',link('进入活动','S01',{},'btn primary')));
  }
  if(r.page==='S03') {
    const a=readable(s,actor,'attempts',r.attempt); if(r.lesson&&a.lesson!==r.lesson) throw new Error('回执与课堂不匹配。');
    if(!a.receipt) return heading('尚未收到最终回执')+notice('已保存的进度不等于已提交。请返回这次作答查询或重试。','warn')+link('返回作答','S02',{lesson:a.lesson,attempt:a.id},'btn primary');
    const l=s.lessons[a.lesson]; const content=lessonContent(s,l.id);
    return heading('已提交',`${e(content.title)} · 第 ${a.number} 次尝试`) + notice('已在本浏览器的共享演示数据中保存，教师标签页可以查到这份提交。','good') + `<section class="panel"><h2>本次提交回执</h2><dl class="detail-grid"><dt>学生</dt><dd>${e(s.students[a.student]?.name)}</dd><dt>课堂</dt><dd>${e(l.title)}</dd><dt>固定版本</dt><dd>${e(content.label)}</dd><dt>确认时间</dt><dd>${time(a.submittedAt)}</dd><dt>回执编号</dt><dd class="token">${e(a.receipt)}</dd></dl></section><section class="panel" style="margin-top:16px"><h2>本人反馈</h2>${l.feedback?`${content.questions.map(q=>`<div class="summary-question"><h3>${e(q.title)}</h3><p class="readonly-content">${e(a.answers[q.id]??'未作答')}</p></div>`).join('')}<p>${e(l.feedbackText||'老师尚未补充文字反馈。')}</p>`:'<p class="muted">老师暂未开放本人答案与反馈，你的提交回执仍然有效。</p>'}</section><div class="action-row">${link('我的记录','S04',{},'btn')}${l.status==='open'?button('再做一次','again',{lesson:l.id},'primary'):''}${l.sharing?link('共享结果','S05',{lesson:l.id},'btn'):''}</div>`;
  }
  if(r.page==='S05') {
    const l=readable(s,actor,'lessons',r.lesson);
    return heading('共享结果',e(l.title)) + (l.sharing?`<section class="panel">${badge(`发布版本 ${l.sharing.number}`,'purple')}<p class="data-time">${time(l.sharing.createdAt)} · 教师确认开放的固定范围</p>${statsHTML(l.sharing.stats)}${questionStats(l.sharing.stats)}${l.sharing.selected?.length?`<h2>教师选择的回答示例</h2>${l.sharing.selected.map((entry,i)=>`<div class="summary-question"><h3>示例回答 ${i+1}</h3><p class="readonly-content">${Object.values(entry.answers).map(e).join(' / ')}</p></div>`).join('')}`:''}</section>`:notice('老师尚未开放或已撤回这份共享结果。已提交记录不受影响。','warn')) + `<div class="action-row">${link('返回我的记录','S04',{},'btn')}</div>`;
  }
  throw new Error('学生页面不存在。');
}
