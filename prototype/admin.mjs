import { can, select, readable } from './model.mjs';
import { esc as e,time,url,link,button,badge,notice,heading,field,selectField,check,table,row,tabs } from './ui.mjs';

export function adminPage({state:s,actor,r,space}) {
  if (r.page==='O01') {
    if (actor?.kind!=='ops') throw new Error('此入口需要独立运维身份。请从演示入口使用运维演示身份。');
    return heading('实例备份与恢复','独立运维空间 · 仅操作本浏览器的合成演示数据',button('创建演示备份','backup',{},'primary')) + notice('此页面演示任务与恢复后的状态变化，不能替代数据库备份或恢复演练。恢复会关闭课堂、撤回共享并清除旧个人码，管理员需重新发码。','warn') + table(['备份','创建时间','状态','操作'],Object.values(s.backups).map(b=>row([`<span class="mono">${e(b.id.slice(0,8))}</span>`,time(b.at),badge('可演示恢复','green'),button('演示恢复此备份','restore',{backup:b.id},'danger')])));
  }
  if (!can(s,actor,space,'admin')) throw new Error('当前身份没有此空间的管理权限。');
  const p = (extra={})=>({space,mode:'admin',...extra});
  const data=select(s,actor,space);
  const members=Object.values(s.members);
  switch(r.page) {
    case 'C01': return heading('成员与权限','邀请接受后成员才生效；教学权限、班级任课与运维身份分别管理。',button('邀请教师','invite',{},'primary')) + table(['成员','角色','状态','任课班级','操作'],members.map(m=>row([e(m.name),m.roles.map(role=>role==='admin'?'校园管理员':'教师').join('、'),badge(m.active?'已启用':'已停用',m.active?'green':'amber'),data.classes.filter(c=>c.teachers.includes(m.id)).map(c=>e(c.name)).join('、')||'未分配',m.id!==actor.id?`<div class="button-group">${button(m.active?'停用':'启用','member-status',{member:m.id,active:!m.active})}${button('交接学校资产','handover',{member:m.id})}</div>`:'当前身份']))) + `<section class="panel" style="margin-top:20px"><h2>学校邀请</h2>${Object.values(s.invitations).map(inv=>`<div class="list-row"><div>${e(inv.name)} ${badge(inv.status==='pending'?'待接受':'已接受',inv.status==='pending'?'amber':'green')}</div>${inv.status==='pending'?link('打开邀请接受页','G01',{invite:inv.id},'btn'):''}</div>`).join('')||'<p class="muted">还没有发出的邀请。</p>'}</section>`;
    case 'C02': return heading('班级与任课','任课变更将同步到教师的“我的班级”和开展范围。',button('新建班级','new-class',{},'primary')) + table(['班级','学生人数','任课教师','操作'],data.classes.map(c=>row([link(c.name,'T09',p({class:c.id,back:url('C02',p())})),String(Object.values(s.students).filter(st=>st.classId===c.id).length),c.teachers.map(id=>e(s.members[id]?.name)).join('、')||badge('待指定','amber'),`<div class="button-group">${button('指定任课','assign',{class:c.id})}${link('学生名册','C03',p({class:c.id}),'btn')}</div>`])));
    case 'C03': {
      const classes = data.classes;
      const students=Object.values(s.students).filter(st=>st.space===space&&!st.temporary&&(!r.class||st.classId===r.class));
      return heading('学生名册','稳定学生标识用于区分同名与保留历史，姓名不作为身份凭据。',button('添加学生','new-student',{class:r.class||''},'primary')) + `<form data-form="class-filter" class="toolbar">${selectField('班级范围','class',[['','全部班级'],...classes.map(c=>[c.id,c.name])],r.class||'')}<button>查看</button></form>` + table(['姓名','稳定标识','班级','个人码','操作'],students.map(st=>row([e(st.name),`<span class="mono">${e(st.id)}</span>`,e(s.classes[st.classId]?.name),`<span class="token">${e(st.code||'待发放')}</span>`,`<div class="button-group">${button('重置个人码','reset-code',{student:st.id})}${button('调班','move-student',{student:st.id})}</div>`])));
    }
    case 'C06': return heading('运行状态与操作记录','仅展示本地原型可观测状态，尚无真实服务监控。') + `<div class="two-col"><section class="panel"><h2>当前状态</h2><dl class="detail-grid"><dt>本机存储</dt><dd>${badge('可读取','green')} 修订 ${s.revision}</dd><dt>示例模型</dt><dd>${badge(s.spaces[space].model?'可演示生成':'演示不可用',s.spaces[space].model?'green':'amber')}</dd><dt>真实服务</dt><dd>未连接 · 无观测数据</dd></dl><div class="action-row">${link('空间设置','G02',p(),'btn')}${link('查看迁移任务','T12',p(),'btn')}</div></section><section class="panel"><h2>异常处理</h2><p>模型不可用时，课堂接收、规则统计、共享汇总与导出继续可用。</p><p class="muted">备份恢复由独立实例运维入口处理。</p></section></div><h2 style="margin-top:24px">操作记录</h2>` + table(['时间','操作者','操作'],s.audit.filter(log=>log.space===space).slice(0,100).map(log=>row([time(log.at),e(s.members[log.actor]?.name||'独立运维'),e(log.text)])));
    case 'G02': return heading('空间设置',e(s.spaces[space].name)) + `<div class="two-col"><section class="panel"><form data-form="settings"><h2>基本设置</h2>${field('空间名称','name',s.spaces[space].name,'text','required maxlength="60"')}${check('允许生成诊断示例','model',s.spaces[space].model)}<p class="field-help">可关闭此开关，验证模型不可用时其他课堂功能是否继续工作。</p><button class="primary">保存空间设置</button></form></section><section class="panel"><h2>当前空间</h2><p>${space==='personal'?'个人空间由本人管理，活动和班级独立保留。':'校内资源共享不会默认共享学生数据。'}</p><p class="muted">实际模型供应商、密钥和服务端权限尚未接入。</p></section></div>`;
    default: throw new Error('未找到这个管理页面。');
  }
}
