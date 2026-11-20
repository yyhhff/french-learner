import { apiRequest } from '../api.js';
import { FALLBACK_PROFILE, FALLBACK_SCENES, buildFallbackCards, esc, notify, state } from '../store.js';
import { speak } from './audio.js';
import { chatLinkBtnHTML, renderLedger, renderScenes, renderTop, sentenceTokensHTML } from './chat.js';
import { grammarChipHTML, loadGrammarCards } from './grammar.js';
import { readOfflineNote, updateReadVocabBadge } from './review.js';
import { openWordPopover } from './word-popover.js';

async function loadReadLevels(){
  try{
    const levels = await apiRequest('/api/input/levels');
    if(levels==null) return;
    state.read.available = true;
    loadGrammarCards(); // TASK-0078：语法卡库懒加载（异步、失败静默），命中句子出 📌 chip
    state.read.levels = Array.isArray(levels) ? levels : [];
    renderReadLevels();
    if(state.read.levels.length){
      selectReadLevel(state.read.levels[0].level);
    }else{
      const tl = document.getElementById('textList');
      if(tl) tl.innerHTML = '<div class="read-empty">还没有语料，先去对话里练练吧 🌱</div>';
    }
  }catch(e){
    readOfflineNote();
  }
}

function renderReadLevels(){
  const row = document.getElementById('levelRow');
  if(!row) return;
  const sub = document.getElementById('readLevelSub');
  if(sub) sub.textContent = state.read.levels.length+' 个等级';
  row.innerHTML = state.read.levels.map(l=>
    `<button class="lv-chip ${l.level===state.read.level?'on':''}" onclick="selectReadLevel('${esc(l.level)}')">${esc(l.level)}<small>${Number(l.count||0)}篇</small></button>`
  ).join('');
}

// 12) GET /api/input/texts?level=&limit=&offset=

async function selectReadLevel(level){
  state.read.level = level;
  renderReadLevels();
  const tl = document.getElementById('textList');
  if(tl) tl.innerHTML = '<div class="read-empty">正在整理短文…</div>';
  try{
    const res = await apiRequest('/api/input/texts?level='+encodeURIComponent(level)+'&limit=50&offset=0');
    if(res==null) return;
    state.read.texts = (res && Array.isArray(res.items)) ? res.items : [];
    renderReadTexts();
  }catch(e){
    readOfflineNote();
  }
}

function renderReadTexts(){
  const tl = document.getElementById('textList');
  if(!tl) return;
  if(!state.read.texts.length){
    tl.innerHTML = '<div class="read-empty">这一级还没有短文，换个等级看看～</div>';
    return;
  }
  tl.innerHTML = state.read.texts.map(t=>`
    <div class="txt-item ${t.id===state.read.currentId?'on':''}" onclick="openReadText('${esc(t.id)}')">
      <div class="tflag">${t.format==='dialogue'?'💬':'📄'}</div>
      <div class="tmeta"><b>${esc(t.title)}</b><small>${esc(t.topic||'')} · ${esc(t.cefr_level||'')} · ${Number(t.word_count||0)} 词</small></div>
    </div>`).join('');
}

// 13) GET /api/input/texts/{id}

async function openReadText(id){
  try{
    const detail = await apiRequest('/api/input/texts/'+encodeURIComponent(id));
    if(detail==null) return;
    showReadDetail(detail);
  }catch(e){
    readOfflineNote();
  }
}

function showReadDetail(detail){
  if(!detail) return;
  state.read.current = detail;
  state.read.currentId = detail.id;
  if(detail.id && state.read.readIds.indexOf(detail.id)<0) state.read.readIds.push(detail.id);
  document.getElementById('readFlag').textContent = detail.format==='dialogue'?'💬':'📄';
  document.getElementById('readTitle').textContent = detail.title||'短文';
  document.getElementById('readMeta').textContent =
    [detail.cefr_level, detail.topic, (Number(detail.word_count||0)+' 词')].filter(Boolean).join(' · ');
  const ab = document.getElementById('readAudioBtn');
  if(ab){
    ab.setAttribute('data-text', detail.audio_text || detail.body_fr || '');
    ab.classList.remove('speaking');
  }
  const note = document.getElementById('readNote');
  if(note) note.innerHTML = '';
  // TASK-0052：内容不足一屏的短文，停留 8 秒视为读完（切换文章即取消）
  clearTimeout(state.read._dwellTimer);
  state.read._dwellTimer = setTimeout(function(){
    const el = document.getElementById('readBody');
    if(el && el.scrollHeight <= el.clientHeight + 24 && state.read.currentId === detail.id){
      markReadComplete(detail.id);
    }
  }, 8000);
  renderReadLines(detail);
  renderReadWords(detail);
  renderReadTexts();
}

// TASK-0052：阅读完成落库——幂等上报，成功且首次时温和提示

async function markReadComplete(textId){
  if(!textId || !state.online) return;
  if(state.read.reportedIds.indexOf(textId) >= 0) return;
  state.read.reportedIds.push(textId);
  try{
    const r = await apiRequest('/api/input/texts/'+encodeURIComponent(textId)+'/complete', {method:'POST'});
    if(r && r.first_time){
      if(state.read.readIds.indexOf(textId) < 0) state.read.readIds.push(textId);
      gentleReadNote('读完了，这一篇已经记下 🌱 已读 '+(r.read_count||1)+' 篇');
    }
  }catch(e){
    // 失败回滚本会话标记，下次到文末可重试；不打断阅读
    const i = state.read.reportedIds.indexOf(textId);
    if(i >= 0) state.read.reportedIds.splice(i, 1);
  }
}

function renderReadLines(detail){
  const body = document.getElementById('readBody');
  if(!body) return;
  const lines = Array.isArray(detail.lines) ? detail.lines : [];
  const isDia = detail.format==='dialogue';
  let html = `<div class="read-section-title">${isDia?'逐句对话':'逐段阅读'}</div>`;
  lines.forEach(l=>{
    const speaker = isDia ? (l.speaker==='B'?'B':'A') : null;
    const cls = isDia ? (speaker==='B'?'dialogue b':'dialogue a') : 'mono';
    const who = isDia ? (speaker==='B'?'呀':'我') : '📄';
    html += `<div class="rline ${cls}">
      <div class="rspk">${who}</div>
      <div class="rbubble">
        <span class="fr">${sentenceTokensHTML(l.fr)}<button class="rplay" onclick="speak(this)" data-text="${esc(l.fr)}" title="听这句">🔊</button>${chatLinkBtnHTML(l.fr)}${grammarChipHTML(l.fr)}</span>
        ${l.cn?`<span class="cn">${esc(l.cn)}</span>`:''}
      </div>
    </div>`;
  });
  html += `<div class="whole-fr"><h4>整篇法语原文</h4><p>${sentenceTokensHTML(detail.body_fr||'')}${chatLinkBtnHTML(detail.body_fr||'')}</p></div>`;
  html += `<div class="whole-fr"><h4>整篇中文译文</h4><p class="cn">${esc(detail.body_cn||'')}</p></div>`;
  body.innerHTML = html;
  body.scrollTop = 0;
}

function renderReadWords(detail){
  const box = document.getElementById('readWords');
  if(!box) return;
  const words = Array.isArray(detail.words) ? detail.words : [];
  const sub = document.getElementById('readWordSub');
  if(sub) sub.textContent = words.length ? ('共 '+words.length+' 个') : '本篇无生词';
  const btn = document.getElementById('collectAllBtn');
  if(btn) btn.style.display = words.length ? '' : 'none';
  if(!words.length){
    box.innerHTML = '<div class="vocab-empty">这篇没有生词标注，专心读故事吧～</div>';
    return;
  }
  box.innerHTML = words.map((w,i)=>{
    const done = w.word_card_id!=null;
    return `<div class="rw">
      <div class="rw-top">
        <span class="rw-word v-tok" data-word="${esc(w.word)}" onclick="openWordPopover(this)" title="学 ${esc(w.word)} 的发音">${esc(w.word)}</span>
        ${w.pos?`<span class="rw-pos">${esc(w.pos)}</span>`:''}
        ${w.cefr_level?`<span class="rw-lv">${esc(w.cefr_level)}</span>`:''}
      </div>
      <div class="rw-mean">${esc(w.meaning)}</div>
      ${w.example?`<div class="rw-ex">例：${esc(w.example)}</div>`:''}
      <div class="rw-actions">
        <button class="rw-say" onclick="speak(this)" data-text="${esc(w.word)}" title="听发音">🔊 听</button>
        ${done
          ? '<span class="rw-done">✓ 已在词库</span>'
          : `<button class="rw-collect" onclick="collectReadWord(${i})">+ 收入词库</button>`}
      </div>
    </div>`;
  }).join('');
}

// 音频：audio_url 非空走 <audio>（复用 unlockAudio），否则 speak()/fallbackSpeak() 读 audio_text||body_fr

async function collectReadWord(index){
  const detail = state.read.current;
  if(!detail) return;
  const w = (detail.words||[])[index];
  if(!w || w.word_card_id!=null) return;
  await postCollect(detail.id, [w.word]);
}

async function collectAllWords(){
  const detail = state.read.current;
  if(!detail) return;
  await postCollect(detail.id, null);
}

async function postCollect(textId, words){
  try{
    const res = await apiRequest('/api/input/texts/'+encodeURIComponent(textId)+'/collect', {
      method:'POST', body: words ? { words:words } : undefined
    });
    if(res==null) return;
    applyCollectResult(res);
  }catch(e){
    notify('收词暂时没成功，稍后再试一下～');
  }
}

function applyCollectResult(res){
  const collected = Array.isArray(res.collected) ? res.collected : [];
  const existed = Array.isArray(res.already_existed) ? res.already_existed : [];
  const skipped = Array.isArray(res.skipped) ? res.skipped : [];
  // 新卡并入全局词库（按 word 去重），复习浮层与词库徽标同步受益
  collected.forEach(c=>{
    if(c && c.word && !state.cards.some(x=>x.word===c.word)) state.cards.unshift(c);
  });
  const detail = state.read.current;
  if(detail && Array.isArray(detail.words)){
    detail.words.forEach(w=>{
      const c = collected.find(x=>x && x.word===w.word);
      if(c && w.word_card_id==null) w.word_card_id = c.id;
    });
  }
  const parts = [];
  if(collected.length) parts.push('已收入 '+collected.length+' 个生词');
  if(existed.length) parts.push(existed.length+' 个本来就在词库');
  if(skipped.length) parts.push(skipped.length+' 个暂时跳过');
  notify(parts.length ? (parts.join('，')+' 🌱') : '这些词都已经收好啦 🌱');
  if(detail) renderReadWords(detail);
  updateReadVocabBadge();
}

function gentleReadNote(msg){
  const note = document.getElementById('readNote');
  if(note) note.innerHTML = '<span class="gentle">'+esc(msg)+'</span>';
}

// 15) GET /api/input/recommend?exclude_ids=&limit=1

async function recommendNext(){
  const note = document.getElementById('readNote');
  if(note) note.innerHTML = '';
  let url = '/api/input/recommend?limit=1';
  if(state.read.readIds.length) url += '&exclude_ids='+encodeURIComponent(state.read.readIds.join(','));
  try{
    const res = await apiRequest(url);
    if(res==null) return;
    if(res.reason==='no_candidate' || !res.text){
      gentleReadNote('这一级都读完啦，去对话里练练吧 🌱');
      return;
    }
    showReadDetail(res.text); // text 即完整 InputTextDetail，直接渲染
    if(res.reason==='level_only_fallback'){
      gentleReadNote('先读这篇熟悉一下主题，慢慢来～');
    }else{
      gentleReadNote('为你挑了一篇难度刚刚好的短文，目标 '+(res.target_level||'下一级')+' ✨');
    }
  }catch(e){
    readOfflineNote();
  }
}

/* ---------- 降级切换 ---------- */

function setOffline(){
  if(!state.online) return;
  state.online = false;
  if(!state.scenes.length) state.scenes = FALLBACK_SCENES.slice();
  if(!state.cards.length) state.cards = buildFallbackCards();
  if(!state.profile) state.profile = FALLBACK_PROFILE;
  document.getElementById('offlineBadge').classList.remove('hidden');
  renderTop(); renderScenes(); renderLedger();
}

/* ---------- 初始化 ---------- */

export { applyCollectResult, collectAllWords, collectReadWord, gentleReadNote, loadReadLevels, markReadComplete, openReadText, postCollect, recommendNext, renderReadLevels, renderReadLines, renderReadTexts, renderReadWords, selectReadLevel, setOffline, showReadDetail };
