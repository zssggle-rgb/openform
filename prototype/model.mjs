/** Synthetic prototype domain. All permissions here are demonstrations, not a security boundary. */
export const SCHEMA = 1;
export const QUESTIONS = {
  words: [
    { id: 'q1', title: 'library 的中文意思是？', options: ['图书馆', '实验室', '操场'], correct: '图书馆' },
    { id: 'q2', title: 'laboratory 的中文意思是？', options: ['教室', '实验室', '图书馆'], correct: '实验室' },
    { id: 'q3', title: '用一句话描述你理想的校园。', type: 'text' },
  ],
  quiz: [
    { id: 'q1', title: '1/2 + 1/4 = ?', options: ['3/4', '2/6', '1/6'], correct: '3/4' },
    { id: 'q2', title: '3/4 − 1/2 = ?', options: ['1/4', '2/2', '1/2'], correct: '1/4' },
    { id: 'q3', title: '说说你的计算过程。', type: 'text' },
  ],
  lab: [
    { id: 'q1', title: '量筒内水的体积是多少毫升？', type: 'number' },
    { id: 'q2', title: '记录你的实验观察，可附上实验照片。', type: 'images' },
    { id: 'q3', title: '根据观察，你得到了什么结论？', type: 'text' },
  ],
};
const TITLES = { words: '校园词汇闯关', quiz: '分数加减随堂练习', lab: '水的体积与实验观察' };
const clone = value => structuredClone(value);
const ensure = (condition, message) => { if (!condition) throw new Error(message); };
const get = (state, collection, id) => { const value = state[collection][id]; ensure(value, '对象不存在或已不可用。请返回列表重新选择。'); return value; };
const versionFor = (state, lesson) => get(state, 'activities', lesson.activity).versions.find(v => v.id === lesson.version);
const editable = (state, actor, activity) => { requireTeacher(state, actor, activity.space); ensure(activity.owner === actor.id, '你没有这份活动的编辑权限。'); };
const manageLesson = (state, actor, lesson) => { requireTeacher(state, actor, lesson.space); ensure(lesson.owner === actor.id, '你没有这个课堂的教学数据权限。'); };
const requireTeacher = (state, actor, space) => ensure(can(state, actor, space, 'teacher'), '当前身份没有此空间的教学权限。');
const requireAdmin = (state, actor, space) => ensure(can(state, actor, space, 'admin'), '当前身份没有此空间的管理权限。');
const activeStudent = (state, actor) => {
  ensure(actor?.kind === 'student', '请先验证你的参与身份。');
  const student = get(state, 'students', actor.id);
  ensure(student.active && student.epoch === actor.epoch, '参与身份已失效，请使用新个人码重新进入。');
  return student;
};
function studentLesson(state, actor, lesson) {
  const student = activeStudent(state, actor);
  ensure(student.space === lesson.space && (lesson.kind === 'quick' ? student.lesson === lesson.id : student.classId === lesson.classId && !student.temporary), '这个课堂不在你的参与范围内。');
  return student;
}
function answerValidation(questions, answers, complete = false) {
  for (const question of questions) {
    const value = answers[question.id];
    if (complete) ensure(value !== undefined && String(value).trim() !== '', '请完成每道题后再提交。');
    if (value === undefined || value === '') continue;
    ensure(String(value).length <= 4000, '每道文字回答最多 4,000 字。');
    if (question.options) ensure(question.options.includes(value), '选项无效，请重新选择。');
    if (question.type === 'number') ensure(Number.isFinite(Number(value)) && Number(value) >= 0, '请输入有效的非负数值。');
  }
}
function content(type, title, goal) {
  return { type, title, goal, questions: clone(QUESTIONS[type]) };
}

export function seedState() {
  const state = {
    schema: SCHEMA, revision: 0,
    spaces: { school: { id: 'school', name: '青禾实验学校', model: true }, personal: { id: 'personal', name: '林老师的个人空间', owner: 'lin', model: true } },
    members: {
      lin: { id: 'lin', name: '林知夏', roles: ['teacher', 'admin'], active: true },
      chen: { id: 'chen', name: '陈明', roles: ['teacher'], active: true },
      admin: { id: 'admin', name: '周管理员', roles: ['admin'], active: true },
    },
    classes: {
      c1: { id: 'c1', space: 'school', name: '七年级（1）班', teachers: ['lin'] },
      c2: { id: 'c2', space: 'school', name: '七年级（2）班', teachers: ['chen'] },
      pc1: { id: 'pc1', space: 'personal', name: '课后学习小组', teachers: ['lin'] },
    },
    students: {}, activities: {}, lessons: {}, attempts: {}, trials: {}, reports: {}, resources: {}, tasks: {}, archives: {}, invitations: {}, backups: {}, audit: [], requests: {},
  };
  [['s1','许晨','c1','DEMO-001'],['s2','周宁','c1','DEMO-002'],['s3','许晨','c1','DEMO-003'],['s4','李可','c2','DEMO-004'],['p1','小禾','pc1','DEMO-P01']].forEach(([id,name,classId,code]) => {
    state.students[id] = { id, name, classId, space: state.classes[classId].space, code, epoch: 1, active: true };
  });
  [['a1','words','lin','school'],['a2','quiz','lin','school'],['a3','lab','lin','school'],['a4','words','chen','school'],['ap','words','lin','personal']].forEach(([id,type,owner,space]) => {
    const draft = content(type,TITLES[type],'完成活动，留下每个学生可查的学习过程。');
    state.activities[id] = { id, space, owner, draft, revision: 1, verifiedRevision: 1, source: '已验证的演示样板', versions: [{ id: `${id}-v1`, label: 'v1.0', revision: 1, ...clone(draft), createdAt: '2026-10-05T01:00:00.000Z' }] };
  });
  state.lessons.l1 = { id: 'l1', space: 'school', owner: 'lin', activity: 'a1', version: 'a1-v1', title: '校园词汇闯关 · 第一次课堂', kind: 'class', classId: 'c1', code: 'QH1001', status: 'open', feedback: false, sharing: null, createdAt: '2026-10-05T01:10:00.000Z' };
  state.lessons.l2 = { id: 'l2', space: 'school', owner: 'chen', activity: 'a4', version: 'a4-v1', title: '校园词汇闯关 · 第二班', kind: 'class', classId: 'c2', code: 'QH1002', status: 'open', feedback: false, sharing: null, createdAt: '2026-10-05T01:15:00.000Z' };
  state.resources.r1 = { id: 'r1', space: 'school', owner: 'lin', title: TITLES.words, content: clone(state.activities.a1.versions[0]), active: true, createdAt: '2026-10-05T01:00:00.000Z' };
  return state;
}

export function can(state, actor, space, role = 'teacher') {
  if (actor?.kind !== 'staff') return false;
  const member = state.members[actor.id];
  if (!member) return false;
  if (space === 'personal') return state.spaces.personal.owner === actor.id;
  if (!member.active) return false;
  return space === 'school' && member.roles.includes(role);
}

export function select(state, actor, space) {
  const values = key => Object.values(state[key]).filter(item => item.space === space);
  return {
    activities: values('activities').filter(item => can(state,actor,space) && item.owner === actor.id),
    lessons: values('lessons').filter(item => can(state,actor,space) && item.owner === actor.id),
    classes: values('classes').filter(item => can(state,actor,space,'admin') || can(state,actor,space) && item.teachers.includes(actor.id)),
    resources: values('resources').filter(() => space === 'school' && (can(state,actor,space) || can(state,actor,space,'admin'))),
    tasks: values('tasks').filter(item => can(state,actor,space,'admin') || item.owner === actor?.id),
    archives: values('archives').filter(item => can(state,actor,space,'admin') || item.owner === actor?.id),
  };
}

export function readable(state, actor, collection, id) {
  const item = get(state, collection, id);
  if (collection === 'activities') editable(state,actor,item);
  else if (collection === 'lessons') {
    if (actor?.kind === 'student') studentLesson(state,actor,item); else manageLesson(state,actor,item);
  } else if (collection === 'attempts') {
    const lesson = get(state,'lessons',item.lesson);
    if (actor?.kind === 'student') { const student = activeStudent(state,actor); ensure(item.student === actor.id && student.space === lesson.space,'这不是你的参与记录。'); }
    else manageLesson(state,actor,lesson);
  } else if (collection === 'reports') manageLesson(state,actor,get(state,'lessons',item.lesson));
  else if (collection === 'classes') ensure(select(state,actor,item.space).classes.some(c => c.id === id),'这个班级不在你的授权范围内。');
  else if (collection === 'resources') ensure(item.space === 'school' && (can(state,actor,'school') || can(state,actor,'school','admin')),'请进入学校空间查看资源。');
  else if (collection === 'trials') {
    editable(state,actor,get(state,'activities',item.activity));
    ensure(item.owner === actor.id,'这个试做会话不属于你。');
  } else if (collection === 'archives' || collection === 'tasks') ensure(select(state,actor,item.space)[collection].some(i => i.id === id),'无权查看这项资料。');
  return item;
}

export function lessonContent(state, lessonId) {
  const lesson = get(state,'lessons',lessonId);
  const version = versionFor(state,lesson);
  ensure(version,'课堂版本不可用。');
  return version;
}

export function statistics(state, lessonId) {
  const lesson = get(state,'lessons',lessonId);
  const records = Object.values(state.attempts).filter(a => a.lesson === lessonId);
  const latest = new Map();
  for (const record of records.filter(a => a.receipt).sort((a,b) => a.number - b.number)) latest.set(record.student,record);
  const completed = [...latest.values()];
  const questions = lessonContent(state,lessonId).questions.map(question => {
    const valid = completed.filter(record => String(record.answers[question.id] ?? '').trim() !== '');
    return { id: question.id, title: question.title, answered: valid.length, correct: question.correct === undefined ? null : valid.filter(record => record.answers[question.id] === question.correct).length };
  });
  return { participants: new Set(records.map(a => a.student)).size, completed: completed.length, submittedAttempts: records.filter(a => a.receipt).length, expected: lesson.kind === 'class' ? Object.values(state.students).filter(s => s.active && s.classId === lesson.classId).length : null, questions, attemptIds: completed.map(a => a.id) };
}

export function authenticateStudent(state, { lessonId, code }) {
  const student = Object.values(state.students).find(s => s.code === code.trim().toUpperCase() && s.active && !s.temporary);
  ensure(student,'个人码不正确或已失效。请向老师领取当前个人码。');
  const actor = { kind: 'student', id: student.id, epoch: student.epoch };
  if (lessonId) studentLesson(state,actor,get(state,'lessons',lessonId));
  return actor;
}

/** A single atomic local transaction; caller persists next state before showing success. */
export function command(original, actor, type, data = {}, meta = {}) {
  const state = clone(original);
  const id = meta.id || data.id;
  const now = meta.now || new Date().toISOString();
  ensure(id,'操作缺少唯一标识。');
  let result;
  const log = (text, space = data.space || 'school') => state.audit.unshift({ id, at: now, actor: actor?.id || 'demo', space, text });
  switch (type) {
    case 'createActivity': {
      requireTeacher(state,actor,data.space);
      ensure(QUESTIONS[data.type],'请选择支持的活动样板。');
      ensure(data.title?.trim(),'请填写活动名称。');
      const activity = { id, space: data.space, owner: actor.id, revision: 1, verifiedRevision: 0, versions: [], source: data.source || '教学想法', draft: content(data.type,data.title.trim(),data.goal || '') };
      if (data.html) { ensure(data.html.length <= 500000 && /<html|<!doctype|<body/i.test(data.html),'请选择有效的 HTML 文件，最大 500 KB。'); activity.html = data.html; activity.source = 'HTML 导入 · 原文仅隔离预览；课堂使用已适配题目'; }
      state.activities[id] = activity; result = id; log('创建活动草稿',data.space); break;
    }
    case 'saveActivity': {
      const activity = get(state,'activities',data.activity); editable(state,actor,activity);
      ensure(data.revision === activity.revision,'另一窗口已修改草稿。请重新载入后再编辑。');
      ensure(data.title?.trim(),'活动名称不能为空。');
      activity.draft.title = data.title.trim(); activity.draft.goal = data.goal || '';
      if (data.questions) {
        ensure(data.questions.length === 3 && data.questions.every(q => q.title?.trim()),'请保留三道完整的题目。');
        activity.draft.questions = clone(data.questions);
      }
      activity.revision++; activity.verifiedRevision = 0; result = activity.id; log('保存草稿，当前修订需重新试做',activity.space); break;
    }
    case 'startTrial': {
      const activity = get(state,'activities',data.activity); editable(state,actor,activity);
      state.trials[id] = { id, owner: actor.id, activity: activity.id, revision: activity.revision, content: clone(activity.draft), answers: {}, step: 0, images: [], saved: false, receipt: null };
      result = id; break;
    }
    case 'verifyActivity': {
      const activity = get(state,'activities',data.activity); editable(state,actor,activity);
      ensure(data.confirmed,'请确认已复核活动内容。');
      ensure(Object.values(state.trials).some(t => t.activity === activity.id && t.revision === activity.revision && t.saved && t.receipt),'本修订还没有完整试做回执。请先保存进度并提交试做。');
      activity.verifiedRevision = activity.revision;
      let version = activity.versions.find(v => v.revision === activity.revision);
      if (!version) { version = { ...clone(activity.draft), id, revision: activity.revision, label: `v${activity.versions.length + 1}.0`, createdAt: now }; activity.versions.push(version); }
      result = version.id; log('确认试做并固定发布版本',activity.space); break;
    }
    case 'launch': {
      const activity = get(state,'activities',data.activity); editable(state,actor,activity);
      ensure(data.requestId,'开展操作缺少请求标识。');
      if (state.requests[data.requestId]) { result = state.requests[data.requestId]; break; }
      const version = activity.versions.find(v => v.id === data.version);
      ensure(version,'请先完成试做并选择已固定的版本。');
      ensure(['class','quick'].includes(data.kind),'请选择参与方式。');
      if (data.kind === 'class') {
        const cls = get(state,'classes',data.classId);
        ensure(cls.space === activity.space && cls.teachers.includes(actor.id),'你尚未获授这个班级的任课权限。');
      }
      state.lessons[id] = { id, activity: activity.id, space: activity.space, owner: actor.id, version: version.id, title: data.title?.trim() || version.title, kind: data.kind, classId: data.kind === 'class' ? data.classId : null, code: `QH${id.replace(/-/g,'').slice(-8).toUpperCase()}`, status: data.later ? 'paused' : 'open', feedback: Boolean(data.feedback), sharing: null, createdAt: now };
      state.requests[data.requestId] = id; result = id; log('创建新课堂',activity.space); break;
    }
    case 'lessonStatus': {
      const lesson = get(state,'lessons',data.lesson); manageLesson(state,actor,lesson);
      ensure(lesson.status !== 'ended','课堂已结束；如需继续，请再次开展新课堂。');
      ensure(['open','paused','ended'].includes(data.status),'课堂状态无效。');
      lesson.status = data.status; result = lesson.id; log(`课堂接收状态：${data.status}`,lesson.space); break;
    }
    case 'quickJoin': {
      const lesson = get(state,'lessons',data.lesson);
      ensure(lesson.kind === 'quick' && lesson.status === 'open','当前课堂无法创建临时参与身份。');
      ensure(data.name?.trim(),'请填写你的称呼。');
      state.students[id] = { id, space: lesson.space, name: data.name.trim(), lesson: lesson.id, temporary: true, active: true, epoch: 1 };
      result = { kind: 'student', id, epoch: 1 }; break;
    }
    case 'startAttempt': {
      const lesson = get(state,'lessons',data.lesson); studentLesson(state,actor,lesson);
      const previous = Object.values(state.attempts).filter(a => a.lesson === lesson.id && a.student === actor.id).sort((a,b) => b.number-a.number);
      if (previous[0] && (!data.again || !previous[0].receipt)) { result = previous[0].id; break; }
      ensure(lesson.status === 'open','课堂暂未接收新的作答，请联系老师。');
      state.attempts[id] = { id, space: lesson.space, lesson: lesson.id, version: lesson.version, student: actor.id, number: previous.length + 1, answers: {}, images: [], step: 0, revision: 0, receipt: null, savedAt: null };
      result = id; break;
    }
    case 'saveAttempt':
    case 'submitAttempt': {
      const trial = Boolean(data.trial);
      const record = get(state,trial ? 'trials' : 'attempts',data.attempt);
      const activity = trial ? get(state,'activities',record.activity) : null;
      let questions;
      if (trial) { editable(state,actor,activity); ensure(activity.revision === record.revision,'草稿已修改，请重新开始试做。'); questions = record.content.questions; }
      else { const lesson = get(state,'lessons',record.lesson); studentLesson(state,actor,lesson); ensure(record.student === actor.id,'不能操作其他人的作答。'); questions = lessonContent(state,lesson.id).questions; }
      if (record.receipt) { result = record.id; break; }
      if (!trial) {
        ensure(get(state,'lessons',record.lesson).status === 'open','老师已暂停或结束接收。已确认进度仍保留，恢复后可重试。');
        ensure(data.revision === record.revision,'另一窗口已更新此作答。请先重新读取已确认进度。');
      }
      answerValidation(questions,data.answers,type === 'submitAttempt');
      const images = data.images || [];
      ensure(images.length <= 5 && images.every(img => /^data:image\/(png|jpeg);base64,/.test(img.url) && img.url.length < 600000),'图片格式或大小不符合原型限制，请重新选择。');
      ensure(!images.length || questions.some(q => q.type === 'images'),'这份活动不支持图片。');
      record.answers = clone(data.answers); record.images = clone(images); record.step = Math.max(0,Math.min(2,Number(data.step) || 0)); record.savedAt = now;
      if (trial) record.saved = true; else record.revision++;
      if (type === 'submitAttempt') { record.receipt = `${trial ? 'TRIAL' : 'OF'}-${id}`; record.submittedAt = now; }
      result = record.id; break;
    }
    case 'report': {
      const lesson = get(state,'lessons',data.lesson); manageLesson(state,actor,lesson);
      ensure(state.spaces[lesson.space].model,'示例模型暂不可用。规则统计、共享和导出仍可使用。');
      const stats = statistics(state,lesson.id); ensure(stats.completed > 0,'尚无完成记录，暂不能生成诊断。');
      state.reports[id] = { id, lesson: lesson.id, space: lesson.space, createdAt: now, stats, reviewed: false, number: Object.values(state.reports).filter(r => r.lesson === lesson.id).length + 1 };
      result = id; log('保存一份固定诊断示例',lesson.space); break;
    }
    case 'reviewReport': { const report = readable(state,actor,'reports',data.report); report.reviewed = true; result = report.id; break; }
    case 'deleteAttempt': {
      const record = readable(state,actor,'attempts',data.attempt);
      const lesson = get(state,'lessons',record.lesson); manageLesson(state,actor,lesson);
      delete state.attempts[record.id];
      for (const report of Object.values(state.reports)) if (report.stats.attemptIds.includes(record.id)) { report.invalid = true; report.reviewed = false; }
      if (lesson.sharing?.stats.attemptIds.includes(record.id) || lesson.sharing?.selected?.some(entry => entry.attempt === record.id)) lesson.sharing = null;
      for (const task of Object.values(state.tasks)) if (task.lesson === lesson.id && task.package) { task.status = 'invalid'; delete task.package; }
      result = lesson.id; log('删除原始记录，使相关诊断、共享及导出缓存失效',lesson.space); break;
    }
    case 'feedback': { const lesson = get(state,'lessons',data.lesson); manageLesson(state,actor,lesson); lesson.feedback = Boolean(data.open); lesson.feedbackText = data.text || ''; result = lesson.id; break; }
    case 'share': {
      const lesson = get(state,'lessons',data.lesson); manageLesson(state,actor,lesson);
      if (!data.open) lesson.sharing = null;
      else {
        ensure(data.previewRevision === original.revision,'课堂数据已变化，请重新预览后发布。');
        const stats = statistics(state,lesson.id); ensure(stats.completed > 0,'还没有可共享的题目汇总。');
        const selected = (data.selectedAttemptIds || []).map(attemptId => {
          const attempt = get(state,'attempts',attemptId);
          ensure(attempt.lesson === lesson.id && attempt.receipt,'只能选择本课堂的已提交记录。');
          return { attempt: attempt.id, answers: clone(attempt.answers) };
        });
        lesson.sharing = { id, createdAt: now, stats, selected, number: (lesson.shareNumber || 0) + 1 }; lesson.shareNumber = lesson.sharing.number;
      }
      result = lesson.id; log(data.open ? '发布共享结果版本' : '撤回共享结果',lesson.space); break;
    }
    case 'createClass': {
      requireAdmin(state,actor,data.space); ensure(data.name?.trim(),'请填写班级名称。');
      state.classes[id] = { id, space: data.space, name: data.name.trim(), teachers: data.space === 'personal' ? [actor.id] : [] }; result = id; log('新建班级',data.space); break;
    }
    case 'assign': {
      const cls = get(state,'classes',data.classId); requireAdmin(state,actor,cls.space);
      ensure(data.teachers.every(t => can(state,{kind:'staff',id:t},cls.space)), '任课教师必须是有效教学成员。');
      cls.teachers = [...new Set(data.teachers)]; result = cls.id; log('更新班级任课',cls.space); break;
    }
    case 'addStudent': {
      const cls = get(state,'classes',data.classId); requireAdmin(state,actor,cls.space); ensure(data.name?.trim(),'请填写学生姓名。');
      state.students[id] = { id, space: cls.space, classId: cls.id, name: data.name.trim(), active: true, epoch: 1, code: `DEMO-${id.slice(-6).toUpperCase()}` }; result = id; log('加入一名合成学生',cls.space); break;
    }
    case 'resetCode':
    case 'moveStudent': {
      const student = get(state,'students',data.student); const cls = get(state,'classes',student.classId);
      if (type === 'moveStudent') requireAdmin(state,actor,student.space);
      else ensure(can(state,actor,student.space,'admin') || can(state,actor,student.space) && cls.teachers.includes(actor.id),'无权发放本班个人码。');
      if (type === 'moveStudent') { const target = get(state,'classes',data.classId); ensure(target.space === student.space,'不能直接跨空间调班。'); student.classId = target.id; }
      student.epoch++; student.code = `DEMO-${id.slice(-6).toUpperCase()}`; result = student.id; log('更新学生凭据，保留稳定标识和历史',student.space); break;
    }
    case 'invite': { requireAdmin(state,actor,'school'); ensure(data.name?.trim(),'请填写受邀者姓名。'); state.invitations[id] = { id, name: data.name.trim(), status: 'pending', roles: ['teacher'] }; result = id; log('创建待接受邀请'); break; }
    case 'acceptInvite': {
      const invite = get(state,'invitations',data.invitation); ensure(invite.status === 'pending','邀请已接受或失效。');
      state.members[id] = { id, name: invite.name, roles: invite.roles, active: true }; invite.status = 'accepted'; invite.member = id; result = {kind:'staff',id}; break;
    }
    case 'memberStatus': {
      requireAdmin(state,actor,'school'); ensure(data.member !== actor.id,'不能在这里停用当前管理员本人。');
      get(state,'members',data.member).active = Boolean(data.active); result = data.member; log('更新成员启用状态'); break;
    }
    case 'handover': {
      requireAdmin(state,actor,'school'); ensure(data.from !== data.to && can(state,{kind:'staff',id:data.to},'school'),'请选择另一位有效教师接收。');
      get(state,'members',data.from);
      for (const key of ['activities','lessons','resources']) for (const item of Object.values(state[key])) if (item.space === 'school' && item.owner === data.from) item.owner = data.to;
      for (const cls of Object.values(state.classes)) if (cls.space === 'school' && cls.teachers.includes(data.from)) cls.teachers = [...new Set(cls.teachers.map(t => t === data.from ? data.to : t))];
      result = data.to; log('完成学校资产与任课交接，个人空间保持原归属'); break;
    }
    case 'publishResource': {
      const activity = get(state,'activities',data.activity); editable(state,actor,activity); ensure(activity.space === 'school','请先将资源导入学校空间再发布。');
      const version = activity.versions.find(v => v.id === data.version); ensure(version,'请选择已固定的版本。');
      state.resources[id] = { id, space: 'school', owner: actor.id, title: version.title, content: clone(version), active: true, createdAt: now }; result = id; log('发布校内资源，不包含参与记录'); break;
    }
    case 'copyResource': {
      const resource = readable(state,actor,'resources',data.resource); requireTeacher(state,actor,'school'); ensure(resource.active,'资源已撤回，无法创建新副本。');
      state.activities[id] = { id, owner: actor.id, space: 'school', draft: clone(resource.content), revision: 1, verifiedRevision: 0, versions: [], source: `校内资源：${resource.title}` }; state.activities[id].draft.title += ' · 副本'; result = id; break;
    }
    case 'revokeResource': {
      const resource = readable(state,actor,'resources',data.resource); ensure(resource.owner === actor.id || can(state,actor,'school','admin'),'无权撤回此资源。'); resource.active = false; result = resource.id; log('撤回校内资源，既有副本保留'); break;
    }
    case 'export': {
      const lesson = readable(state,actor,'lessons',data.lesson);
      const records = Object.values(state.attempts).filter(a => a.lesson === lesson.id).map(a => ({ student: a.student, number: a.number, answers: clone(a.answers), receipt: a.receipt, submittedAt: a.submittedAt || null }));
      state.tasks[id] = { id, space: lesson.space, lesson: lesson.id, owner: actor.id, title: `${lesson.title} · 数据导出`, status: 'completed', createdAt: now, package: { format: 'openform-demo-archive', version: 1, title: lesson.title, records, stats: statistics(state,lesson.id) } }; result = id; break;
    }
    case 'importPackage': {
      requireTeacher(state,actor,data.space); const pkg = data.package;
      ensure(pkg?.version === 1 && ['openform-demo-archive','openform-demo-resource'].includes(pkg.format),'资料包格式不受支持，未导入任何内容。');
      ensure(pkg.title?.trim(),'资料包缺少名称。');
      if (pkg.format === 'openform-demo-resource') {
        ensure(QUESTIONS[pkg.type],'资料包活动类型不受支持。');
        state.activities[id] = { id, space: data.space, owner: actor.id, draft: content(pkg.type,pkg.title,pkg.goal || ''), revision: 1, verifiedRevision: 0, versions: [], source: '资源包导入' };
        result = { type: 'activity', id };
      } else {
        ensure(Array.isArray(pkg.records) && pkg.records.length <= 5000,'档案记录无效。');
        state.archives[id] = { id, space: data.space, owner: actor.id, title: pkg.title, records: clone(pkg.records), createdAt: now }; result = { type: 'archive', id };
      }
      state.tasks[`${id}-task`] = { id: `${id}-task`, space: data.space, owner: actor.id, title: `${pkg.title} · 导入`, status: 'completed', target: result, createdAt: now }; log('资料包导入完成',data.space); break;
    }
    case 'settings': { requireAdmin(state,actor,data.space); ensure(data.name?.trim(),'空间名称不能为空。'); Object.assign(state.spaces[data.space],{name:data.name.trim(),model:Boolean(data.model)}); result = data.space; break; }
    case 'backup': {
      ensure(actor?.kind === 'ops','需要独立运维身份。');
      const snapshot = clone(state); snapshot.backups = {}; state.backups[id] = { id, at: now, snapshot, status: 'available' }; result = id; break;
    }
    case 'restore': {
      ensure(actor?.kind === 'ops','需要独立运维身份。');
      const backup = get(state,'backups',data.backup); const snapshots = state.backups;
      const restored = clone(backup.snapshot); Object.assign(state,restored); state.backups = snapshots;
      for (const student of Object.values(state.students)) { student.epoch = Math.max(student.epoch,original.students[student.id]?.epoch || 0)+1; student.code = null; }
      for (const lesson of Object.values(state.lessons)) { lesson.status = 'ended'; lesson.sharing = null; }
      state.requests = {}; log('演示恢复完成；旧参与凭据失效，课堂已关闭'); result = data.backup; break;
    }
    default: throw new Error('不支持的操作。');
  }
  state.revision = original.revision + 1;
  return { state, result };
}
