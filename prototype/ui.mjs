export const names = { G01:'登录与加入空间',G02:'空间设置',T01:'我的活动',T02:'活动详情与版本',T03:'制作活动',T05:'我的课堂',T06:'课堂详情',T07:'教学诊断',T08:'我的班级',T09:'班级详情',T10:'校内资源库',T11:'资源详情',T12:'资料迁移与档案',C01:'成员与权限',C02:'班级与任课',C03:'学生名册',C06:'运行状态与操作记录',S01:'进入活动',S02:'参与活动',S03:'提交回执与反馈',S04:'我的记录',S05:'共享结果',O01:'实例备份与恢复' };
export const typeNames = { words:'词汇 / 概念闯关',quiz:'随堂测验',lab:'实验探究' };
export const statusNames = { open:'接收中',paused:'已暂停',ended:'已结束' };
export const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const time = value => value ? new Date(value).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}) : '尚未保存';
export function url(page,params={}) { const query = new URLSearchParams(Object.entries(params).filter(([,v])=>v !== undefined && v !== null && v !== '').map(([k,v])=>[k,String(v)])); return `#${page}${query.size ? `?${query}` : ''}`; }
export function route(hash = location.hash) { const [page='G01',query=''] = hash.replace(/^#/,'').split('?'); return {...Object.fromEntries(new URLSearchParams(query)),page:page || 'G01'}; }
export const link = (label,page,params={},className='') => `<a class="${className}" href="${esc(url(page,params))}">${esc(label)}</a>`;
export const button = (label,action,data={},className='') => `<button class="${className}" data-action="${action}" ${Object.entries(data).map(([k,v])=>`data-${k}="${esc(v)}"`).join(' ')}>${esc(label)}</button>`;
export const badge = (label,color='') => `<span class="badge ${color}">${esc(label)}</span>`;
export const notice = (text,kind='info') => `<div class="notice ${kind}">${text}</div>`;
export const empty = (title,text,action='') => `<div class="empty"><h2>${esc(title)}</h2><p>${esc(text)}</p>${action}</div>`;
export const heading = (title,description='',actions='') => `<div class="page-heading"><div><h1 tabindex="-1">${esc(title)}</h1>${description ? `<p class="muted">${description}</p>` : ''}</div><div class="row">${actions}</div></div>`;
export const field = (label,name,value='',kind='text',extra='') => `<label class="field"><span>${esc(label)}</span><input name="${name}" type="${kind}" value="${esc(value)}" ${extra}></label>`;
export const textarea = (label,name,value='',extra='') => `<label class="field"><span>${esc(label)}</span><textarea name="${name}" rows="3" ${extra}>${esc(value)}</textarea></label>`;
export const selectField = (label,name,options,value='',extra='') => `<label class="field"><span>${esc(label)}</span><select name="${name}" ${extra}>${options.map(([id,text])=>`<option value="${esc(id)}" ${id === value ? 'selected' : ''}>${esc(text)}</option>`).join('')}</select></label>`;
export const check = (label,name,checked=false) => `<label class="check-row"><input type="checkbox" name="${name}" ${checked?'checked':''}><span>${esc(label)}</span></label>`;
export const table = (headers,rows) => `<div class="panel flush"><div class="table-wrap" tabindex="0" role="region" aria-label="${esc(headers.join('、'))}列表，可横向滚动"><table><thead><tr>${headers.map(h=>`<th scope="col">${h}</th>`).join('')}</tr></thead><tbody>${rows.join('') || `<tr><td colspan="${headers.length}">${empty('还没有记录','完成对应操作后会出现在这里。')}</td></tr>`}</tbody></table></div><div class="table-footer">共 ${rows.length} 项 <span>全部已加载</span></div></div>`;
export const row = cells => `<tr>${cells.map(c=>`<td>${c}</td>`).join('')}</tr>`;
export const tabs = (items,current) => `<nav class="tabs" aria-label="页内导航">${items.map(([key,label,href])=>`<a href="${esc(href)}" ${current===key?'aria-current="page"':''}>${label}</a>`).join('')}</nav>`;
export function statsHTML(stats) {
  return `<div class="metric-strip"><span>已参与<strong>${stats.participants}</strong></span><span>已完成<strong>${stats.completed}</strong>${stats.expected === null ? '' : ` / ${stats.expected}`}</span><span>已确认提交<strong>${stats.submittedAttempts}</strong>次</span></div>${stats.expected === null ? '<p class="stat-caption">快速活动仅统计已参与者，不推算缺席人数。</p>' : ''}`;
}
export function questionStats(stats) {
  return stats.questions.map(q=>`<div class="summary-question"><h3>${esc(q.title)}</h3><p>${q.answered} 人有有效回答${q.correct === null ? ' · 开放题不计算正确率' : ` · 答对 ${q.correct} / ${q.answered} ${q.answered ? `(${Math.round(q.correct/q.answered*100)}%)` : '（暂无分母）'}`}</p><div class="bar"><i style="width:${q.correct === null || !q.answered ? 0 : q.correct/q.answered*100}%"></i></div></div>`).join('');
}
