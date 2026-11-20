/* TASK-0071 v3.1 听力磨耳：分级听力 + 变速播放 + 精听听写填空 + 真实语速变体。
   视图切换自管（镜像 pron_coach 先例）：从本页切走由 growth.js switchView 兜底隐藏。 */
import { apiRequest } from '../api.js';
import { esc, notify } from '../store.js';

const home = { loaded: false, level: '', levels: [], texts: [] };
const detail = {
  tid: null, title: '', lines: [], bySeq: {},
  variant: 'std', speed: 1.0, loop: false, dictation: false,
  attempted: new Set(), playingSeq: null,
};

let audio = null;
function getAudio() {
  if (!audio) audio = new Audio();
  return audio;
}

/* ---------------------------------------------------------------- 视图切换（自管） */

function switchListenView(name) {
  const on = name === 'listen';
  // 隐藏其余全部视图（含发音教练自管视图），防两视图重叠（TASK-0068 教训）
  ['viewChat', 'viewRead', 'viewAssessment', 'viewExam', 'viewGrowth', 'viewRoadmap', 'viewProncoach', 'viewListen']
    .forEach(id => { const el = document.getElementById(id); if (el) el.classList.toggle('hidden', id !== 'viewListen'); });
  ['tabChat', 'tabRead', 'tabAssessment', 'tabExam', 'tabGrowth', 'tabRoadmap', 'tabProncoach', 'tabListen']
    .forEach(id => { const el = document.getElementById(id); if (el) el.classList.toggle('on', on && id === 'tabListen'); });
  if (on) initListen();
}

/* ---------------------------------------------------------------- 素材列表 */

async function initListen() {
  if (!home.loaded) {
    home.loaded = true;
    try {
      const [lv, tx] = await Promise.all([
        apiRequest('/api/listen/levels'),
        apiRequest('/api/listen/texts'),
      ]);
      home.levels = lv.levels || [];
      home.texts = tx.texts || [];
    } catch (e) {
      notify('听力素材加载失败：' + (e.message || e));
      home.loaded = false;
      return;
    }
    renderChips();
    renderList();
  }
}

function renderChips() {
  const box = document.getElementById('listenChips');
  const total = home.levels.reduce((s, l) => s + l.texts, 0);
  const ready = home.levels.reduce((s, l) => s + l.audio_ready, 0);
  const lineCount = home.levels.reduce((s, l) => s + l.lines, 0);
  const chips = [{ level: '', label: `全部（${total} 篇）` }]
    .concat(home.levels.map(l => ({ level: l.level, label: `${l.level}（${l.texts} 篇）` })));
  box.innerHTML = chips.map(c =>
    `<button class="listen-chip ${home.level === c.level ? 'on' : ''}" onclick="listenPickLevel('${c.level}')">${c.label}</button>`
  ).join('') +
    `<div class="listen-stat">句音频 ${ready}/${lineCount} 就绪 · 变体持续生成中</div>`;
}

async function renderList() {
  const box = document.getElementById('listenList');
  box.innerHTML = '<div class="listen-loading">加载中…</div>';
  try {
    const r = await apiRequest('/api/listen/texts' + (home.level ? `?level=${home.level}` : ''));
    home.texts = r.texts || [];
  } catch (e) {
    box.innerHTML = '<div class="listen-loading">加载失败，稍后再试</div>';
    return;
  }
  box.innerHTML = home.texts.map(t => `
    <div class="listen-card" onclick="listenOpen('${esc(t.id)}')">
      <div class="listen-card-top">
        <b>${esc(t.title)}</b>
        <span class="listen-badge lv-${esc(t.cefr_level)}">${esc(t.cefr_level)}</span>
      </div>
      <div class="listen-card-sub">${esc(t.topic || '')} · ${t.format === 'dialogue' ? '对话' : '独白'} · ${t.lines} 句</div>
      <div class="listen-card-audio">🔊 ${t.audio_ready}/${t.lines} · 变体 v1 ${t.v1_ready} v2 ${t.v2_ready}</div>
    </div>`).join('') || '<div class="listen-loading">该等级暂无素材</div>';
}

function listenPickLevel(level) {
  home.level = level;
  renderChips();
  renderList();
}

/* ---------------------------------------------------------------- 篇详情：播放器 + 精听 */

async function listenOpen(tid) {
  let d;
  try {
    d = await apiRequest(`/api/listen/texts/${encodeURIComponent(tid)}`);
  } catch (e) {
    notify('素材详情加载失败：' + (e.message || e));
    return;
  }
  detail.tid = d.id; detail.title = d.title;
  detail.lines = d.lines || [];
  detail.bySeq = {};
  detail.lines.forEach(l => { detail.bySeq[l.seq] = l; });
  detail.variant = 'std'; detail.speed = 1.0; detail.loop = false; detail.dictation = false;
  detail.attempted = new Set(); detail.playingSeq = null;
  document.getElementById('listenHome').classList.add('hidden');
  document.getElementById('listenDetail').classList.remove('hidden');
  document.getElementById('listenTitle').textContent = d.title;
  document.getElementById('listenMeta').textContent =
    `${d.cefr_level} · ${d.format === 'dialogue' ? '对话' : '独白'} · ${d.lines.length} 句 · ${d.topic || ''}`;
  renderVariantBtns(); renderSpeedBtns(); renderLoopBtn(); renderDictBtn();
  renderSentences();
}

function listenBack() {
  stopAudio();
  document.getElementById('listenDetail').classList.add('hidden');
  document.getElementById('listenHome').classList.remove('hidden');
  home.loaded = false; // 返回时刷新就绪数
  initListen();
}

function renderVariantBtns() {
  const anyV1 = detail.lines.some(l => l.v1_ready);
  const anyV2 = detail.lines.some(l => l.v2_ready);
  const opts = [
    { v: 'std', label: '标准音', ok: true },
    { v: 'v1', label: '男声 Henri', ok: anyV1 },
    { v: 'v2', label: '真实语速', ok: anyV2 },
  ];
  document.getElementById('listenVariants').innerHTML = opts.map(o =>
    `<button class="listen-variant ${detail.variant === o.v ? 'on' : ''}" ${o.ok ? '' : 'title="变体音频生成中，未就绪句将回退标准音"'}
      onclick="listenSetVariant('${o.v}')">${o.label}${o.ok ? '' : ' ⏳'}</button>`).join('');
}

function listenSetVariant(v) {
  detail.variant = v;
  renderVariantBtns();
  if (detail.playingSeq !== null) listenPlay(detail.playingSeq, true);
}

function renderSpeedBtns() {
  document.getElementById('listenSpeeds').innerHTML = [0.75, 1.0, 1.25].map(s =>
    `<button class="listen-speed ${detail.speed === s ? 'on' : ''}" onclick="listenSetSpeed(${s})">${s}x</button>`).join('');
}

function listenSetSpeed(s) {
  detail.speed = s;
  const a = getAudio();
  if (a.src) a.playbackRate = s;
  renderSpeedBtns();
}

function renderLoopBtn() {
  document.getElementById('listenLoopBtn').textContent = `🔁 单句循环:${detail.loop ? '开' : '关'}`;
  document.getElementById('listenLoopBtn').classList.toggle('on', detail.loop);
}

function listenToggleLoop() {
  detail.loop = !detail.loop;
  const a = getAudio();
  a.loop = detail.loop;
  renderLoopBtn();
}

function renderDictBtn() {
  document.getElementById('listenDictBtn').textContent = `✍️ 精听模式:${detail.dictation ? '开' : '关'}`;
  document.getElementById('listenDictBtn').classList.toggle('on', detail.dictation);
}

function listenToggleDictation() {
  detail.dictation = !detail.dictation;
  renderDictBtn();
  renderSentences();
}

/* ---------------------------------------------------------------- 音频播放 */

function audioUrl(seq, variant) {
  const q = variant && variant !== 'std' ? `?variant=${variant}` : '';
  return `/api/listen/line-audio/${encodeURIComponent(detail.tid)}/${seq}${q}`;
}

function stopAudio() {
  const a = getAudio();
  try { a.pause(); } catch (e) {}
  a.onended = null;
  detail.playingSeq = null;
  document.querySelectorAll('.listen-row.playing').forEach(el => el.classList.remove('playing'));
}

function listenPlay(seq, force) {
  if (detail.playingSeq === seq && !force) { stopAudio(); return; }
  const a = getAudio();
  stopAudio();
  const row = document.getElementById(`lrow-${seq}`);
  if (row) row.classList.add('playing');
  detail.playingSeq = seq;
  // 变体未就绪的句子回退标准音（服务端 line-audio 兜底合成同样按此口径）
  const line = detail.bySeq[seq];
  let variant = detail.variant;
  if (variant === 'v1' && line && !line.v1_ready) variant = 'std';
  if (variant === 'v2' && line && !line.v2_ready) variant = 'std';
  a.src = audioUrl(seq, variant);
  a.playbackRate = detail.speed;
  a.loop = detail.loop;
  a.play().catch(() => notify('播放失败（浏览器需先点击页面解锁音频）'));
}

/* 整篇连播：一句结束自动接下一句（循环模式交给 audio.loop） */
function listenPlayAll() {
  const seqs = detail.lines.map(l => l.seq);
  if (!seqs.length) return;
  let i = seqs.indexOf(detail.playingSeq);
  i = i < 0 ? 0 : i + 1;
  if (i >= seqs.length) i = 0;
  const a = getAudio();
  a.loop = false; // 连播期间关闭单句循环
  listenPlay(seqs[i], true);
  a.onended = () => {
    a.onended = null;
    if (!detail.loop && detail.playingSeq !== null) listenPlayAll();
  };
}

/* ---------------------------------------------------------------- 渲染句子行 */

function renderSentences() {
  const box = document.getElementById('listenSentences');
  box.innerHTML = detail.lines.map(l => {
    const done = detail.attempted.has(l.seq);
    if (detail.dictation) {
      const inputs = (l.blanks || []).map((b, i) =>
        `<span class="listen-blank"><i>${i + 1}</i><input type="text" class="listen-input" id="lin-${l.seq}-${i}"
           style="width:${Math.max(b.letters, 3)}em" maxlength="${b.letters + 4}" placeholder="${'_'.repeat(b.letters)}" autocomplete="off"></span>`).join('');
      return `
      <div class="listen-row listen-dict ${done ? 'done' : ''}" id="lrow-${l.seq}">
        <button class="listen-play" onclick="listenPlay(${l.seq})">▶</button>
        <span class="listen-seq">${l.seq}</span>
        <div class="listen-dict-main">
          <div class="listen-cn">${esc(l.cn)}</div>
          <div class="listen-blanks">${inputs}
            <button class="listen-submit" onclick="listenSubmit(${l.seq})">提交</button>
          </div>
          <div class="listen-reveal" id="lrev-${l.seq}"></div>
        </div>
      </div>`;
    }
    return `
    <div class="listen-row" id="lrow-${l.seq}">
      <button class="listen-play" onclick="listenPlay(${l.seq})">▶</button>
      <span class="listen-seq">${l.seq}</span>
      <div class="listen-dict-main"><div class="listen-cn">${esc(l.cn)}</div></div>
    </div>`;
  }).join('');
  updateFinishBtn();
}

function updateFinishBtn() {
  const btn = document.getElementById('listenFinishBtn');
  const msg = document.getElementById('listenFinishMsg');
  const all = detail.lines.length && detail.lines.every(l => detail.attempted.has(l.seq));
  btn.disabled = !all;
  msg.textContent = all ? '全篇精听完成，收口记入画像' : `精听进度 ${detail.attempted.size}/${detail.lines.length}`;
}

async function listenSubmit(seq) {
  const line = detail.bySeq[seq];
  const typed = (line.blanks || []).map((b, i) => {
    const el = document.getElementById(`lin-${seq}-${i}`);
    return el ? el.value : '';
  });
  try {
    const r = await apiRequest('/api/listen/answer', { method: 'POST', body: { text_id: detail.tid, seq, typed } });
    detail.attempted.add(seq);
    const row = document.getElementById(`lrow-${seq}`);
    row.classList.add(r.correct ? 'right' : 'wrong');
    const marks = r.per_word.map((ok, i) =>
      `<span class="${ok ? 'w-ok' : 'w-no'}">${esc(r.answers[i])}</span>`).join(' ');
    document.getElementById(`lrev-${seq}`).innerHTML =
      `<div class="listen-fr">${esc(r.fr)}</div>` +
      (r.fr !== r.fr_reduced ? `<div class="listen-frred">口语：${esc(r.fr_reduced)}</div>` : '') +
      `<div class="listen-ans">${r.correct ? '✅ 全对' : '答案：'} ${marks}</div>`;
    row.querySelectorAll('.listen-input').forEach(el => el.disabled = true);
    row.querySelector('.listen-submit').disabled = true;
    updateFinishBtn();
  } catch (e) {
    notify('提交失败：' + (e.message || e));
  }
}

async function listenFinish() {
  try {
    const r = await apiRequest('/api/listen/finish', { method: 'POST', body: { text_id: detail.tid } });
    document.getElementById('listenFinishMsg').textContent =
      `✅ 已记入画像：${r.title} 正确句 ${r.correct_seqs}/${r.lines_total}（${r.score} 分）· 「我的成长」听力维度已更新`;
    notify(`听力画像 +1：${r.score} 分`);
  } catch (e) {
    notify('收口失败：' + (e.message || e));
  }
}

export { switchListenView, listenBack, listenPickLevel, listenOpen, listenPlay, listenPlayAll,
         listenSetVariant, listenSetSpeed, listenToggleLoop, listenToggleDictation,
         listenSubmit, listenFinish };
