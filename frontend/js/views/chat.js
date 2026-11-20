import { apiRequest } from '../api.js';
import { FALLBACK_DETAILS, FALLBACK_PROFILE, FALLBACK_SCENES, RECAST_RULES, TRY_CHIPS, capitalize, esc, normalizeTurn, notify, state, userTurn } from '../store.js';
import { speak } from './audio.js';
import { grammarInlineHTML } from './grammar.js';
import { findRulesForCard, pronFocusLabel } from './pron.js';
import { setOffline } from './reading.js';
import { openWordPopover, toggleLinkingInline } from './word-popover.js';

function renderTop(){
  const p = state.profile||FALLBACK_PROFILE;
  document.getElementById('lvNow').textContent = p.cefr_level||'A2';
  document.getElementById('lvTarget').textContent = p.target_level||'B2';
  document.getElementById('topStreak').textContent = p.streak_days||0;
  document.getElementById('avatar').textContent = p.username||'YU';
  const order = ['A1','A2','B1','B2','C1','C2'];
  const cur = Math.max(0, order.indexOf(p.cefr_level));
  const tgt = Math.max(1, order.indexOf(p.target_level));
  const pct = Math.min(100, Math.max(5, Math.round(cur/tgt*100)));
  document.getElementById('lvBar').style.width = pct+'%';
}

function renderScenes(){
  const el = document.getElementById('scenarios');
  document.getElementById('scnCount').textContent = state.scenes.length+' 个';
  el.innerHTML = state.scenes.map(s=>`
    <div class="scn ${s.id===state.currentSceneId?'on':''}" onclick="selectScene('${esc(s.id)}')">
      <div class="ico" style="background:${esc(s.color)}">${esc(s.emoji)}</div>
      <div class="meta"><b>${esc(s.title)}</b><small>${esc(s.description)}</small></div>
    </div>`).join('');
}

function renderHeader(){
  const s = state.scenes.find(x=>x.id===state.currentSceneId);
  if(!s) return;
  document.getElementById('scnFlag').textContent = s.emoji;
  document.getElementById('scnTitle').textContent = s.title;
  document.getElementById('scnDesc').textContent = s.description;
}

// TASK-0034：对话气泡的连读入口——只有检测到连读对的句子才显示按钮，避免每句都挂

function chatLinkBtnHTML(sentence){
  if(!state.pron.available) return '';
  if(!detectLinkingPairs(sentence).length) return '';
  return `<button class="v-mini-btn chat-lk-btn" onclick="toggleLinkingInline(this)" data-text="${esc(sentence)}" title="连读教学：整句示范 + 联诵/连音">🔗 连读</button>`;
}

function messageHTML(m){
  if(m.role==='user'){
    return `<div class="row user">
      <div class="who">我</div>
      <div class="bubble"><span>${sentenceTokensHTML(m.fr)}</span>
        <button class="spk-btn" onclick="speak(this)" data-text="${esc(m.fr)}" title="听我的这句发音">🔊</button>
        ${chatLinkBtnHTML(m.fr)}
        ${m.cn?`<span class="cn">${esc(m.cn)}</span>`:''}
        ${m.asr_raw?`<span class="asr-note">🎧 原声识别：${esc(m.asr_raw)} → 已按法语修正</span>`:''}
      </div>
    </div>`;
  }
  // assistant：只有 recast_of != null 才是重述卡；绝无红叉/扣分
  if(m.recast_of!=null){
    return `<div class="recast">
      <div class="recast-card">
        <div class="tag">🌱 呀呀的自然重述 <small>把你说的句子，用更自然的法语轻轻说回去</small></div>
        <div class="say"><span>${sentenceTokensHTML(m.fr)}</span>
          <button class="spk-btn" onclick="speak(this)" data-text="${esc(m.fr)}" title="听呀呀的重述">🔊</button>
          ${chatLinkBtnHTML(m.fr)}
        </div>
        ${m.cn?`<span class="cn">${esc(m.cn)}</span>`:''}
        <div class="why">${m.explanation?esc(m.explanation)+'<br>':''}你说的是：${esc(m.recast_of)}</div>
        ${grammarInlineHTML(m.grammar_card)}
      </div>
    </div>`;
  }
  return `<div class="row assistant">
    <div class="who">呀</div>
    <div class="bubble"><span>${sentenceTokensHTML(m.fr)}</span>
      <button class="spk-btn" onclick="speak(this)" data-text="${esc(m.fr)}" title="听发音">🔊</button>
      ${chatLinkBtnHTML(m.fr)}
      ${m.cn?`<span class="cn">${esc(m.cn)}</span>`:''}
    </div>
  </div>`;
}

function renderChat(){
  const el = document.getElementById('chat');
  el.innerHTML = state.chatLog.map(messageHTML).join('');
  el.scrollTop = el.scrollHeight;
}

function renderTries(){
  const tries = TRY_CHIPS[state.currentSceneId]||[];
  document.getElementById('tryRow').innerHTML =
    `<small>试试点击：</small>` +
    tries.map((t,i)=>`<button class="chip ${t.bad?'bad':''}" onclick="tryIt(${i})">${esc(t.text)}</button>`).join('');
}

function sceneCards(){
  // 只显示当前场景的词：自动收卡按 source_scene_id 归位，不再回退显示全部场景卡片
  return state.cards.filter(c=>c.source_scene_id===state.currentSceneId);
}

function renderVocab(){
  const list = sceneCards();
  document.getElementById('vocabTitle').textContent = '本场景生词';
  document.getElementById('vocabSub').textContent = state.online?'自动收卡':'本地词表';
  document.getElementById('vocab').innerHTML = list.length
    ? list.map(c=>{
        const ids = findRulesForCard(c.word);
        // 仅命中规则的词才显示"怎么读"按钮：展示提取的音节（focus），规则全名放悬停提示（契约 v1.1）
        // 首选有 focus 的规则（概念规则如"字母名≠读音"无 focus，让位给更具体的音节规则）
        const r0 = ids.map(id=>state.pron.ruleById.get(id)).find(x=>x && pronFocusLabel(x))
          || (ids.length ? state.pron.ruleById.get(ids[0]) : null);
        const focus = r0 ? pronFocusLabel(r0) : '';
        const pronEntry = (state.pron.available && ids.length)
          ? `<button class="pron-word-entry" data-word="${esc(c.word)}" onclick="openWordPopover(this)" title="${r0 ? esc(r0.title) : ''}">${focus ? esc(focus)+' 🎵 怎么读' : '🎵 怎么读'}</button>`
          : '';
        return `<div class="v">
        <div class="v-top">
          <span class="w">${wordTokensHTML(c.word)}</span>
          ${c.pos?`<span class="v-pos">${esc(c.pos)}</span>`:''}
          ${c.cefr_level?`<span class="v-lv">${esc(c.cefr_level)}</span>`:''}
          <button class="spk" onclick="speak(this)" data-text="${esc(c.word)}" title="听发音">🔊</button>
        </div>
        <div class="mean">${esc(c.meaning||'')}</div>
        ${c.example?`<div class="v-ex">例：${sentenceTokensHTML(c.example)}</div>`:''}
        ${pronEntry}
      </div>`;
      }).join('')
    : '<div class="vocab-empty">还没有本场景生词，聊几句自动收卡～</div>';
}

/* ---------- TASK-0029：逐词点击学发音 + 连读教学 ---------- */
// 词形清理：只去首尾标点，保留词内省文符/连字符（aujourd'hui、rendez-vous）

function cleanToken(raw){
  return String(raw||'').replace(/^[^\p{L}\p{N}'’-]+|[^\p{L}\p{N}'’-]+$/gu, '');
}
// 主词逐词：每个单词可点开自己的读音规则卡

function wordTokensHTML(word){
  return String(word||'').trim().split(/\s+/).filter(Boolean).map(tok =>
    `<span class="v-tok" data-word="${esc(tok)}" onclick="openWordPopover(this)" title="学 ${esc(tok)} 的发音">${esc(tok)}</span>`
  ).join(' ');
}
// 例句逐词：展示保留原标点，点击学清理后的词；纯标点不包

function sentenceTokensHTML(sentence){
  return String(sentence||'').trim().split(/\s+/).filter(Boolean).map(raw => {
    const tok = cleanToken(raw);
    if(!tok || !/\p{L}/u.test(tok)) return esc(raw);
    return `<span class="v-tok" data-word="${esc(tok)}" onclick="openWordPopover(this)" title="学 ${esc(tok)} 的发音">${esc(raw)}</span>`;
  }).join(' ');
}
// 连读启发式（从宽提示、不判错）：前词末辅音字母 + 后词元音/哑音 h 开头

const LIAISON_END_RE = /[stdxznpf]$/i;

const ENCHAINEMENT_END_RE = /[rl]$/i;

const VOWEL_START_RE = /^[aeiouàâæéèêëîïôöœùûüÿyh]/i;

function detectLinkingPairs(sentence){
  const raws = String(sentence||'').trim().split(/\s+/).filter(Boolean);
  const out = [];
  for(let i=0;i<raws.length-1;i++){
    const a = cleanToken(raws[i]), b = cleanToken(raws[i+1]);
    if(!a || !b || !/\p{L}/u.test(a) || !/\p{L}/u.test(b)) continue;
    if(!VOWEL_START_RE.test(b)) continue;
    if(LIAISON_END_RE.test(a)) out.push({i, a, b, type:'liaison'});
    else if(ENCHAINEMENT_END_RE.test(a)) out.push({i, a, b, type:'enchainement'});
  }
  return out;
}
// TASK-0032：贴词气泡——学习动作原地发生，无导航无回退问题

function renderLedger(){
  // TASK-0049 方案E：账本压成吸顶条，次级指标（已掌握/正确率）归「我的成长」页
  // TASK-0051：连续天数只在顶栏展示，这里换成累计对话轮数，避免同一数据同屏两次
  const p = state.profile||FALLBACK_PROFILE;
  const s = p.stats||{};
  const due = document.getElementById('dueNum');
  if(due) due.textContent = s.due_cards_count||0;
  const wn = document.getElementById('weekNew');
  if(wn) wn.textContent = '+'+(s.new_words_week||0);
  const ct = document.getElementById('chatTotalBadge');
  if(ct) ct.textContent = '💬 累计 '+(s.dialogue_count||0)+' 轮对话';
}

/* ---------- 场景 / 对话动作 ---------- */

async function selectScene(id, opts){
  state.currentSceneId = id;
  renderScenes();
  renderHeader();
  renderTries();
  renderVocab();

  let detail = null;
  if(state.online){
    try {
      detail = await apiRequest('/api/scenes/'+encodeURIComponent(id));
    }catch(e){
      setOffline();
      detail = null;
    }
    if(detail==null) detail = detailFromFallback(id);
  }else{
    detail = detailFromFallback(id);
  }
  state.chatLog = (detail.start_dialogue||[]).map(normalizeTurn);
  // TASK-0040：在线模式恢复该场景真实历史（追加在种子开场之后；失败不阻断）
  if(!(opts && opts.withHistory === false) && state.online && detail){
    try{
      const h = await apiRequest('/api/chat/history?scene_id='+encodeURIComponent(id)+'&limit=50');
      if(h && Array.isArray(h.items) && h.items.length){
        state.chatLog = state.chatLog.concat(h.items.map(normalizeTurn));
      }
    }catch(e){ /* 离线/失败时仅显示开场 */ }
  }
  renderChat();
}

function detailFromFallback(id){
  const s = FALLBACK_SCENES.find(x=>x.id===id)||FALLBACK_SCENES[0];
  return Object.assign({}, s, {
    start_dialogue:(FALLBACK_DETAILS[id]||[]).map(normalizeTurn)
  });
}

async function resetChat(){
  const id = state.currentSceneId;
  const detail = state.online ? null : detailFromFallback(id);
  if(detail){
    state.chatLog = detail.start_dialogue.map(normalizeTurn);
    renderChat();
    return;
  }
  // 在线模式：确认后先清持久化对话轮（保留种子开场白），再重开场景（不带历史）
  if(!confirm('重置将清除本场景的对话记录（持久化存储同步清空），确定吗？')) return;
  let cleared = true;
  try{
    const r = await apiRequest('/api/chat/history?scene_id='+encodeURIComponent(id), {method:'DELETE'});
    if(r === null) cleared = false; // 服务端返回错误码时 apiRequest 已提示
  }catch(e){
    cleared = false;
    notify('对话记录清理失败，稍后再试一下～');
  }
  if(!cleared) return;
  selectScene(id, {withHistory:false});
}

function applyChatResult(data){
  const isCorrection = data.recast_of!=null;
  state.chatLog.push({
    id:null, role:'assistant', fr:data.ai_text||'', cn:data._cn||'翻译中…',
    recast_of:data.recast_of==null?null:data.recast_of,
    explanation:data.explanation==null?null:data.explanation,
    grammar_card:data.grammar_card||null, // TASK-0078：同类 recast 错误第 3 次时后端下发的语法卡
    is_correction:isCorrection, created_at:null
  });
  renderChat();
  return state.chatLog.length-1;
}

// 把「我说的」和「呀呀回的」一起送去翻译，回填到对应气泡的中文小字

async function translateTurns(texts, indexes){
  try{
    const res = await apiRequest('/api/translate', {
      method:'POST', body:{ texts:texts }
    });
    if(!res || !Array.isArray(res.translations)) return;
    res.translations.forEach((cn,i)=>{
      const idx = indexes[i];
      if(idx!=null && state.chatLog[idx]) state.chatLog[idx].cn = cn || '（暂时没有中文翻译）';
    });
    renderChat();
  }catch(e){
    // 翻译失败不打断对话，也不弹红叉
    indexes.forEach(idx=>{
      if(idx!=null && state.chatLog[idx] && state.chatLog[idx].cn==='翻译中…')
        state.chatLog[idx].cn = '（暂时没有中文翻译）';
    });
    renderChat();
  }
}

// 本地模拟 POST /api/chat：关键词命中规则 → 温柔重述；否则场景接话/通用句

function fallbackChat(sceneId, userText){
  const lower = String(userText).toLowerCase().replace(/[.,!?]/g,'').trim();
  for(const r of RECAST_RULES){
    if(r.test.test(userText)){
      return { ai_text:capitalize(r.fix(userText)), recast_of:userText,
        explanation:r.why, new_words:[] };
    }
  }
  const goods = (TRY_CHIPS[sceneId]||[]).filter(t=>!t.bad&&t.reply);
  for(const g of goods){
    const key = g.text.toLowerCase().replace(/[.,!?]/g,'').trim();
    if(lower.includes(key)||key.includes(lower)){
      return { ai_text:g.reply.fr, recast_of:null, explanation:null,
        new_words:[], _cn:g.reply.cn };
    }
  }
  return { ai_text:'Ah, je vois ! Raconte-moi encore un peu.', recast_of:null,
    explanation:null, new_words:[], _cn:'啊，我明白了！再多说一点吧。' };
}

async function submitUserText(text, rawText){
  text = String(text||'').trim();
  if(!text) return;
  const history = state.chatLog.slice(-10).map(normalizeTurn);
  state.chatLog.push(userTurn(text, rawText));
  const userIdx = state.chatLog.length-1;
  renderChat();

  if(!state.online){
    state.chatLog[userIdx].cn = '（离线演示，暂无中文翻译）';
    applyChatResult(fallbackChat(state.currentSceneId, text));
    return;
  }
  try {
    const data = await apiRequest('/api/chat', {
      method:'POST',
      body:{ scene_id:state.currentSceneId, user_text:text, history:history }
    });
    if(data==null) return; // 业务错误，已提示
    const assistantIdx = applyChatResult(data);
    translateTurns([text, data.ai_text||''], [userIdx, assistantIdx]);
    if(Array.isArray(data.new_words)&&data.new_words.length){
      let added = false;
      data.new_words.forEach(w=>{
        if(w && !state.cards.some(c=>c.word===w.word)){ state.cards.unshift(w); added=true; }
      });
      if(added){ renderVocab(); renderLedger(); }
    }
  }catch(e){
    setOffline();
    state.chatLog[userIdx].cn = '（离线演示，暂无中文翻译）';
    applyChatResult(fallbackChat(state.currentSceneId, text));
  }
}

function sendTyped(){
  const input = document.getElementById('userInput');
  const text = input.value.trim();
  if(!text) return;
  input.value='';
  submitUserText(text);
}

function tryIt(i){
  const t = (TRY_CHIPS[state.currentSceneId]||[])[i];
  if(!t) return;
  submitUserText(t.text);
}

/* ---------- 语音：ASR + TTS ---------- */

export { ENCHAINEMENT_END_RE, LIAISON_END_RE, VOWEL_START_RE, applyChatResult, chatLinkBtnHTML, cleanToken, detailFromFallback, detectLinkingPairs, fallbackChat, messageHTML, renderChat, renderHeader, renderLedger, renderScenes, renderTop, renderTries, renderVocab, resetChat, sceneCards, selectScene, sendTyped, sentenceTokensHTML, submitUserText, translateTurns, tryIt, wordTokensHTML };
