import { apiRequest } from '../api.js';
import { FALLBACK_PROFILE, esc, fmtNum, state } from '../store.js';
import { initAssessment } from './assessment.js';
import { speak } from './audio.js';
import { initExam } from './exam.js';
import { loadPronProgress, updatePronBookEntry } from './pron.js';
import { loadReadLevels } from './reading.js';
import { initToday } from './today.js';

function switchView(name){
  // 七个视图：today / chat / read / assessment / exam / growth / roadmap；其他值一律按 today 处理（TASK-0070 今日置首）
  const view = (name==='today'||name==='read'||name==='assessment'||name==='exam'||name==='growth'||name==='roadmap') ? name
             : (name==='chat' ? 'chat' : 'today');
  // 发音教练视图由 pron_coach.js 自管（TASK-0067）；从它切回视图时必须兜底隐藏，否则两视图重叠（TASK-0068 验收缺陷）
  const pv = document.getElementById('viewProncoach');
  if(pv) pv.classList.add('hidden');
  const pt = document.getElementById('tabProncoach');
  if(pt) pt.classList.remove('on');
  const tv = document.getElementById('viewToday');
  if(tv) tv.classList.toggle('hidden', view!=='today');
  document.getElementById('viewChat').classList.toggle('hidden', view!=='chat');
  document.getElementById('viewRead').classList.toggle('hidden', view!=='read');
  const av = document.getElementById('viewAssessment');
  if(av) av.classList.toggle('hidden', view!=='assessment');
  const ev = document.getElementById('viewExam');
  if(ev) ev.classList.toggle('hidden', view!=='exam');
  const gv = document.getElementById('viewGrowth');
  if(gv) gv.classList.toggle('hidden', view!=='growth');
  const rv = document.getElementById('viewRoadmap');
  if(rv) rv.classList.toggle('hidden', view!=='roadmap');
  const tt = document.getElementById('tabToday');
  if(tt) tt.classList.toggle('on', view==='today');
  document.getElementById('tabChat').classList.toggle('on', view==='chat');
  document.getElementById('tabRead').classList.toggle('on', view==='read');
  const at = document.getElementById('tabAssessment');
  if(at) at.classList.toggle('on', view==='assessment');
  const et = document.getElementById('tabExam');
  if(et) et.classList.toggle('on', view==='exam');
  const gt = document.getElementById('tabGrowth');
  if(gt) gt.classList.toggle('on', view==='growth');
  const rt = document.getElementById('tabRoadmap');
  if(rt) rt.classList.toggle('on', view==='roadmap');
  // 进入今日视图时刷新数据（每次都拉，保证任务状态真实）
  if(view==='today'){ initToday(); }
  // 进入词卡（对话）视图时确保进度加载一次；init 已加载则不重复请求
  if(view==='chat' && !state.pron.progressFetched){
    loadPronProgress().then(updatePronBookEntry);
  }
  // 首次进入阅读视图才拉端点，避免启动多打请求；失败也只是这里降级
  if(view==='read' && !state.read.loaded){
    state.read.loaded = true;
    loadReadLevels();
  }
  // 切到定级视图：有缓存结果就展示结果态，否则引导态
  if(view==='assessment') initAssessment();
  // 切到考级视图：拉试卷列表
  if(view==='exam') initExam();
  // 切到成长视图：每次进入都拉最新 profile（轻量端点），数字永远新鲜
  if(view==='growth') renderGrowth();
  // 切到路线图：每次进入都拉最新（后端常量），点亮状态随维护即时反映
  if(view==='roadmap') renderRoadmap();
}

/* ============================================================
   TASK-0047 我的成长 v1：真实数据聚合，零假值、温和文案
   ============================================================ */

async function renderGrowth(){
  const wrap = document.getElementById('growthWrap');
  if(!wrap) return;
  // 进入时静默刷新一次 profile，失败则用已有缓存（离线也不展示假值）
  if(state.online){
    try { const p = await apiRequest('/api/profile'); if(p) state.profile = p; } catch(e){}
    // TASK-0055 水平画像（懒计算端点，读时重放 EWMA）；失败静默，画像是增益功能
    try { const sk = await apiRequest('/api/profile/skills'); if(sk) state.skillProfile = sk; } catch(e){}
    // TASK-0058 成就（懒计算端点，读时判定 + 新解锁计 XP）；失败静默，成就是增益功能
    try { const ach = await apiRequest('/api/achievements'); if(ach) state.achievements = ach; } catch(e){}
    // TASK-0060 留存激励（纯读聚合：今日目标/微进步/streak 文案）；失败静默
    try { const rt = await apiRequest('/api/retention'); if(rt) state.retention = rt; } catch(e){}
  }
  const s = (state.profile||FALLBACK_PROFILE).stats||{};
  const num = v => fmtNum(v||0);
  const pct = a => (a>0 ? Math.round(a*100)+'%' : '—');
  wrap.innerHTML = `
    <div class="growth-hello">你走过的每一步都在这里～</div>
    <div class="growth-cards">
      <div class="growth-card">
        <div class="g-title">📚 词汇</div>
        <div class="g-nums"><span><b>${num(s.total_cards)}</b>累计收藏</span><span><b>+${num(s.new_words_week)}</b>本周新增</span><span><b>${num(s.mastered_count)}</b>已掌握</span></div>
      </div>
      <div class="growth-card">
        <div class="g-title">💬 对话</div>
        <div class="g-nums"><span><b>${num(s.dialogue_count)}</b>累计对话轮数</span></div>
        <div class="g-note">${s.dialogue_count ? '每一轮开口都算数 🌱' : '从第一段对话开始，慢慢积累就好'}</div>
      </div>
      <div class="growth-card">
        <div class="g-title">🔁 复习</div>
        <div class="g-nums"><span><b>${num(s.due_cards_count)}</b>今日想见你</span><span><b>${num(s.review_count)}</b>累计复习</span><span><b>${pct(s.accuracy)}</b>保持率</span></div>
        <div class="g-note">${s.due_cards_count ? '有 '+num(s.due_cards_count)+' 个词想再见你一面～' : '今天没有想见你的词，随时来逛逛'}</div>
      </div>
      <div class="growth-card">
        <div class="g-title">📖 阅读</div>
        ${s.read_count
          ? `<div class="g-nums"><span><b>${num(s.read_count)}</b>已读篇数</span>${s.last_read ? `<span><b>${esc(s.last_read.cefr_level||'—')}</b>最近《${esc(String(s.last_read.title||'').slice(0,10))}》</span>` : ''}</div>
        <div class="g-note">每一篇都算数，慢慢读就好 🌱</div>`
          : `<div class="g-note g-empty">读完第一篇短文，这里就会留下小脚印</div>`}
      </div>
    </div>
    ${dailyGoalsCardHTML()}
    ${microProgressCardHTML()}
    ${skillCardHTML()}
    ${achievementCardHTML()}`;
}

/* TASK-0060 今日小目标：3 项真实行为计数，完成打勾给肯定、未完成无焦虑。
   文案禁负面词（不做"未完成/断签/落后"），未完成只显示进度、不加红叉。 */

function dailyGoalsCardHTML(){
  const rt = state.retention;
  const goals = (rt && rt.daily_goals) || {};
  const order = [['read','📖'],['review','🔁'],['chat','💬']];
  const rows = order.map(([k,ico]) => {
    const g = goals[k] || {done:false,count:0,target:1,label:''};
    const frac = g.target ? Math.min(1,(g.count||0)/g.target) : 0;
    return `<div class="dg-row ${g.done?'done':''}">
      <span class="dg-ico">${g.done?'✓':ico}</span>
      <span class="dg-label">${esc(g.label||'')}</span>
      <span class="dg-bar"><i style="width:${Math.round(frac*100)}%"></i></span>
      <span class="dg-count">${g.done?('完成 🌿'):(fmtNum(g.count)+'/'+g.target)}</span>
    </div>`;
  }).join('');
  const allDone = order.every(([k])=> goals[k] && goals[k].done);
  const note = allDone ? '今天的小目标都实现了，真为你开心 🌿' : '每天一点点，就很好 🌱';
  return `<div class="skill-card dg-card">
    <div class="sk-head"><span class="sk-title">🎯 今日小目标</span><span class="sk-sub">做到了就很好</span></div>
    <div class="dg-list">${rows}</div>
    <div class="dg-note">${note}</div>
  </div>`;
}

/* TASK-0060 微进步：本周 vs 上周（新词/阅读）+ 等级趋势，全部来自真实数据。
   趋势只有 ↑/→（PM §D 禁施压）；变化为 0 时不制造"退步"焦虑。 */

function microProgressCardHTML(){
  const rt = state.retention;
  const m = (rt && rt.micro_progress) || {};
  const streak = (rt && rt.streak) || {days:0, tone:'从今天开始，慢慢来就好 🌱'};
  const wUp = (m.words_this_week||0) - (m.words_last_week||0);
  const rUp = (m.reads_this_week||0) - (m.reads_last_week||0);
  const arrow = v => v>0 ? '<b class="mp-up">↑</b>' : '<b class="mp-flat">→</b>';
  const trendHtml = m.level_trend==='up'
    ? `<span class="mp-trend up">近两周在往上走 ↑</span>`
    : `<span class="mp-trend flat">稳稳地往前走 →</span>`;
  return `<div class="skill-card mp-card">
    <div class="sk-head"><span class="sk-title">🌿 微进步</span><span class="sk-sub">和上周比一比</span></div>
    <div class="mp-grid">
      <div class="mp-cell"><span class="mp-num">${fmtNum(m.words_this_week||0)}</span><span class="mp-lbl">本周新词 ${arrow(wUp)}</span></div>
      <div class="mp-cell"><span class="mp-num">${fmtNum(m.reads_this_week||0)}</span><span class="mp-lbl">本周阅读 ${arrow(rUp)}</span></div>
      <div class="mp-cell"><span class="mp-num">${fmtNum(streak.days||0)}</span><span class="mp-lbl">连续天数</span></div>
    </div>
    <div class="mp-note">${trendHtml}<span class="mp-tone">${esc(streak.tone||'')}</span></div>
  </div>`;
}

/* ============================================================
   TASK-0059 面客建设里程图：大版本主题闭环 + 点亮
   数据源 GET /api/roadmap（后端常量唯一维护点）；前端只读渲染。
   状态 done=点亮 / active=温和高亮 / planned=灰态（无日期、不施压）。
   ============================================================ */

async function renderRoadmap(){
  const wrap = document.getElementById('roadmapWrap');
  if(!wrap) return;
  if(state.online){
    try { const r = await apiRequest('/api/roadmap'); if(r) state.roadmap = r; } catch(e){}
  }
  const data = state.roadmap;
  const items = data && Array.isArray(data.items) ? data.items : [];
  if(!items.length){
    wrap.innerHTML = `<div class="rm-empty">路线图暂未就绪，稍后再来看看～ 🌱</div>`;
    return;
  }
  const statusLabel = { done:'已点亮', active:'进行中', planned:'规划中' };
  const nodes = items.map(r => {
    const st = r.status==='done' ? 'done' : (r.status==='active' ? 'active' : 'planned');
    const feats = Array.isArray(r.features) ? r.features : [];
    const featHtml = st==='planned'
      ? `<div class="rm-feats rm-feats-gray">${feats.map(f=>`<span>${esc(f)}</span>`).join('')}</div>`
      : `<div class="rm-feats">${feats.map(f=>`<span>${esc(f)}</span>`).join('')}</div>`;
    const dateHtml = r.date ? `<span class="rm-date">${esc(String(r.date).slice(0,10))}</span>` : '';
    return `<div class="rm-node ${st}">
      <div class="rm-dot">${st==='done'?'✓':(st==='active'?'●':'○')}</div>
      <div class="rm-body">
        <div class="rm-head">
          <span class="rm-ver">${esc(r.version||'')}</span>
          <span class="rm-title">${esc(r.title||'')}</span>
          <span class="rm-status">${statusLabel[st]||''}</span>
          ${dateHtml}
        </div>
        <div class="rm-theme">${esc(r.theme||'')}</div>
        <div class="rm-desc">${esc(r.desc||'')}</div>
        ${featHtml}
      </div>
    </div>`;
  }).join('');
  const done = (data && typeof data.done_count==='number') ? data.done_count
    : items.filter(r=>r.status==='done').length;
  const current = data && data.current_version ? data.current_version : items[0].version;
  wrap.innerHTML = `
    <div class="rm-intro">
      <div class="rm-intro-h">🗺️ 呀呀法语 · 建设里程图</div>
      <div class="rm-intro-p">每一个大版本，都是一段完整的学习旅程。走过的，会亮起来；正在走的，我们慢慢来。</div>
      <div class="rm-progress"><span>已点亮 <b>${done}</b> / ${items.length} 个版本</span><span>当前 ${esc(current||'')}</span></div>
    </div>
    <div class="rm-track">${nodes}</div>
    <div class="rm-foot">我们会一个版本一个版本地把它做好，谢谢你陪着长大 🌿</div>`;
}

/* TASK-0058 成就卡：解锁点亮 + 未解锁灰态给「下一个目标」牵引；
   文案禁施压，不用"未达成/落后"，已解锁只显示名称与日期。 */

function achievementCardHTML(){
  const ach = state.achievements;
  const rows = ach && Array.isArray(ach.items) ? ach.items : [];
  const unlocked = (ach && typeof ach.unlocked_count==='number') ? ach.unlocked_count : 0;
  const badges = rows.map(a => {
    const on = !!a.unlocked;
    const day = a.earned_at ? String(a.earned_at).slice(0,10) : '';
    return `<span class="ach-badge ${on?'on':''}" title="${on?('解锁于 '+day):esc(a.desc_zh||'')}">
      <span class="ach-ico">${on?'🏅':'·'}</span><span class="ach-name">${esc(a.name_zh||'')}</span></span>`;
  }).join('');
  const next = rows.find(a => !a.unlocked);
  const note = next
    ? `下一个小目标：${esc(next.desc_zh||'')}`
    : (rows.length ? '所有小勋章都点亮啦，真为你开心 🌿' : '继续往前走，小勋章会慢慢出现');
  return `<div class="skill-card ach-card">
    <div class="sk-head"><span class="sk-title">🏅 小成就</span><span class="sk-sub">${unlocked} / ${rows.length} 点亮</span></div>
    <div class="ach-grid">${badges}</div>
    <div class="ach-note">${note}</div>
  </div>`;
}

/* TASK-0055 五维画像卡：7 维采集 → 5 维展示（词汇=vocabulary+memory、口语=speaking+fluency 融合）。
   趋势箭头只有 ↑/→（PM §E：不施压，down 也显示 →）；文案禁"未达标/只有"。 */

function skillCardHTML(){
  const sk = state.skillProfile;
  const rows = sk && Array.isArray(sk.items) ? sk.items : [];
  const by = {};
  rows.forEach(r => { by[r.skill] = r; });
  const blend = (a, wa, b, wb) => {
    const va = by[a], vb = by[b];
    if(va && vb) return va.score*wa + vb.score*wb;
    if(va) return va.score;
    if(vb) return vb.score;
    return null;
  };
  const trendOf = (a, b, wa, wb) => {
    // 融合维趋势取主导维（权重更大者）；单维则取自身
    const d = (wa >= wb) ? a : b;
    return (by[d] || by[a] || by[b] || {}).trend || 'flat';
  };
  const dims = [
    { key:'vocab',  name:'词汇',     score: blend('vocabulary',0.7,'memory',0.3),   trend: trendOf('vocabulary','memory',0.7,0.3) },
    { key:'gram',   name:'语法写作', score: by.grammar ? by.grammar.score : null,   trend: (by.grammar||{}).trend || 'flat' },
    { key:'listen', name:'听力',     score: by.listening ? by.listening.score : null, trend: (by.listening||{}).trend || 'flat' },
    { key:'read',   name:'阅读',     score: by.reading ? by.reading.score : null,   trend: (by.reading||{}).trend || 'flat' },
    { key:'speak',  name:'口语',     score: blend('speaking',0.6,'fluency',0.4),    trend: trendOf('speaking','fluency',0.6,0.4) },
  ];
  const arrow = t => t === 'up' ? '↑' : '→';
  const hasData = dims.some(d => d.score !== null);
  const body = hasData
    ? `<div class="sk-rows">` + dims.map(d => {
        const v = d.score === null ? null : Math.round(d.score);
        const w = v === null ? 0 : Math.max(4, Math.min(100, v));
        return `<div class="sk-row">
          <span class="sk-name">${d.name}</span>
          <div class="sk-bar"><i style="width:${w}%"></i></div>
          <span class="sk-trend">${v === null ? '—' : v + ' ' + arrow(d.trend)}</span>
        </div>`;
      }).join('') + `</div>
      <div class="g-note">你在慢慢往前走，这一维最近有进步的会轻轻 ↑ 一下（练习侧写，不是考试）</div>`
    : `<div class="g-note g-empty">完成一次定级、对话或阅读，画像会慢慢成形 🌱</div>`;
  return `<div class="growth-card skill-card">
    <div class="g-title">🌟 水平画像</div>
    ${body}
  </div>`;
}

/* ============================================================
   阶段0 定级：快速测一测
   GET /api/assessment/questions + POST /api/assessment/submit
   独立追加，不改写现有函数名；失败只给温和提示，不进 fallback 瞎编题
   ============================================================ */

export { achievementCardHTML, dailyGoalsCardHTML, microProgressCardHTML, renderGrowth, renderRoadmap, skillCardHTML, switchView };
