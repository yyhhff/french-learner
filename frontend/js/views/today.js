// TASK-0070 v3.0「每天十五分钟」：今日三件事 + XP/等级 + streak + 呀呀陪伴态。
// 数据源 GET /api/today（gamify.today_summary 实时聚合，无状态任务表）。
// 文件边界：样式 .today- 前缀；深链只做视图切换与 openReview，不动其他模块内部。
import { apiRequest } from '../api.js';
import { esc } from '../store.js';
import { openReview } from './review.js';
import { switchView } from './growth.js';

const TASK_ICONS = { review: '🔁', read: '📖', chat: '💬' };
const TASK_TITLES = { review: '词词回来见你', read: '读一小段', chat: '和呀呀说说话' };
// 呀呀形象：真猫贴纸（用户自家猫照片，抠图 PNG）。mood 关系隐喻：初见/熟悉=并排，老友/灵魂伙伴=依偎
const MOOD_IMG = {
  newcomer: '/assets/yaya-cats-side.png',
  buddy: '/assets/yaya-cats-side.png',
  oldfriend: '/assets/yaya-cats-cuddle.png',
  soulmate: '/assets/yaya-cats-cuddle.png',
};

export async function initToday(){
  try{
    const d = await apiRequest('/api/today');
    if(!d) throw new Error('empty');
    renderToday(d);
  }catch(e){
    const wrap = document.getElementById('todayWrap');
    if(wrap) wrap.innerHTML = '<div class="today-empty">今天的数据没取到，稍后再来看看呀～</div>';
  }
}

export function renderToday(d){
  const wrap = document.getElementById('todayWrap');
  if(!wrap) return;
  const tasks = (d.tasks || []).map(t => taskCardHTML(t)).join('');
  const xp = d.xp || {};
  const pct = xp.need > 0 ? Math.min(100, Math.round((xp.cur / xp.need) * 100)) : 0;
  const streak = d.streak || {};
  const yaya = d.yaya || {};
  const allDone = (d.tasks || []).every(t => t.done);
  wrap.innerHTML = `
    <div class="today-hero">
      <div class="today-yaya-img-wrap today-yaya--${esc(yaya.mood || 'newcomer')}" title="呀呀">
        <img class="today-yaya-img" src="${MOOD_IMG[yaya.mood] || MOOD_IMG.newcomer}" alt="呀呀和小伙伴">
        ${(yaya.mood === 'soulmate') ? '<i class="today-yaya-heart">♥</i>' : ''}
      </div>
      <div class="today-hero-txt">
        <h2>${allDone ? '今天的小目标都完成啦' : '今天想做的事'}</h2>
        <p>${esc(yaya.message || '想做点什么都可以呀。')}</p>
      </div>
      <div class="today-streak ${streak.state === 'active' ? 'on' : ''}">
        <b>🔥 ${streak.days ?? 0}</b><span>${esc(streak.copy || '')}</span>
      </div>
    </div>
    <div class="today-tasks">${tasks}</div>
    <div class="today-xp">
      <div class="today-xp-head">
        <span class="today-lv">Lv.${xp.level ?? 1} ${esc(xp.name || '初识')}</span>
        <span class="today-xp-num">今日 +${xp.today ?? 0} xp · 总计 ${xp.total ?? 0} xp</span>
      </div>
      <div class="today-xp-bar"><i style="width:${pct}%"></i></div>
      <div class="today-xp-hint">升到 Lv.${(xp.level ?? 1) + 1} 还差 ${Math.max(0, (xp.need ?? 0) - (xp.cur ?? 0))} xp</div>
    </div>`;
}

function taskCardHTML(t){
  const done = !!t.done;
  const deep = t.key === 'review' ? 'goTodayTask(\'review\')'
             : t.key === 'read' ? 'goTodayTask(\'read\')'
             : 'goTodayTask(\'chat\')';
  const btnTxt = done ? '再练练也行' : (t.key === 'review' ? '去复习' : t.key === 'read' ? '去阅读' : '去聊天');
  const pct = t.target > 0 ? Math.min(100, Math.round((t.count / t.target) * 100)) : 100;
  return `
    <div class="today-task ${done ? 'done' : ''}">
      <div class="today-task-head">
        <span class="today-task-ico">${TASK_ICONS[t.key] || '🌟'}</span>
        <div class="today-task-txt">
          <b>${esc(TASK_TITLES[t.key] || t.label)}</b>
          <span>${esc(t.label)}${t.target > 0 ? ` · ${t.count}/${t.target}` : ''}</span>
        </div>
        ${done ? '<span class="today-task-check">✓</span>'
               : `<button class="today-task-btn" onclick="${deep}">${btnTxt}</button>`}
      </div>
      ${t.target > 0 ? `<div class="today-task-bar"><i style="width:${pct}%"></i></div>` : ''}
    </div>`;
}

// 深链：复习 → 对话视图 + 打开复习面板；阅读/对话 → 对应视图
export function goTodayTask(key){
  if(key === 'review'){
    switchView('chat');
    try { if (window.openReview) window.openReview(); } catch(e) { /* 面板打开失败不阻塞 */ }
  } else if(key === 'read'){
    switchView('read');
  } else {
    switchView('chat');
  }
}
