/* ============================================================
   呀呀法语 YaYa French — 前端交互逻辑
   数据：fetch /api/*（统一包裹 {code,data,message}），失败自动降级到本地演示数据
   语音：Web Speech API 识别(ASR) + SpeechSynthesis 朗读(TTS)，fr-FR
   角色枚举严格使用 'user' / 'assistant'
   ============================================================ */

/* ---------- 离线演示数据：从 demo.html 迁移，字段对齐契约 ---------- */
const TODAY = new Date().toISOString().slice(0, 10);
const NOW_ISO = new Date().toISOString();

const FALLBACK_SCENES = [
  { id:'cafe',   title:'在咖啡馆点单', description:'日常交流 · A2 难度', emoji:'☕', color:'#FBEDE5', cefr_level:'A2', sort_order:1 },
  { id:'office', title:'和同事聊周末', description:'职场闲聊 · B1 难度', emoji:'💼', color:'#EAF1FB', cefr_level:'B1', sort_order:2 },
  { id:'street', title:'问路',         description:'出行 · A2 难度',     emoji:'🗺️', color:'#E6F4EE', cefr_level:'A2', sort_order:3 },
  { id:'doctor', title:'看医生',       description:'生活办事 · B1 难度', emoji:'🩺', color:'#FBF1DC', cefr_level:'B1', sort_order:4 }
];

// 起始对话：字段按契约补 null/false，role 严格用 user / assistant
const FALLBACK_DETAILS = {
  cafe: [
    { role:'assistant', fr:"Bonjour ! Qu'est-ce que vous voulez ?", cn:'你好！您想要点什么？' },
    { role:'user',      fr:"Je veux un café, s'il vous plaît.",      cn:'我想要一杯咖啡，谢谢。' },
    { role:'assistant', fr:'Très bien ! Vous le voulez chaud ou froid ?', cn:'好的！您要热的还是冷的？' }
  ],
  office: [
    { role:'assistant', fr:'Salut ! Tu as fait quelque chose de sympa ce week-end ?', cn:'嗨！这周末做了什么好玩的事吗？' },
    { role:'user',      fr:'Oui, je suis allé au cinéma.', cn:'是的，我去了电影院。' },
    { role:'assistant', fr:'Ah, cools ! Quel film as-tu vu ?', cn:'哦不错！看了什么电影？' }
  ],
  street: [
    { role:'user',      fr:"Excusez-moi, où est la gare, s'il vous plaît ?", cn:'打扰一下，请问火车站在哪里？' },
    { role:'assistant', fr:"La gare ? C'est à cinq minutes d'ici, tout droit.", cn:'火车站？离这五分钟，一直往前走。' },
    { role:'user',      fr:'Merci beaucoup !', cn:'非常感谢！' }
  ],
  doctor: [
    { role:'assistant', fr:"Bonjour, qu'est-ce qui ne va pas ?", cn:'你好，哪里不舒服？' },
    { role:'user',      fr:"J'ai mal à la tête depuis hier.", cn:'我从昨天起就头疼。' },
    { role:'assistant', fr:"D'accord. Vous avez de la fièvre ?", cn:'好的。您发烧吗？' }
  ]
};

// 生词卡：来自 demo 各场景 vocab [word, meaning, pos]
const FALLBACK_VOCAB = {
  cafe:   [['un café','一杯咖啡','n.m.'],['voudrais','想要（礼貌）','cond.'],['chaud / froid','热 / 冷','adj.']],
  office: [['allé','去了','p.p.'],['le week-end','周末','n.m.'],['un film','电影','n.m.']],
  street: [['la gare','火车站','n.f.'],['tout droit','一直走','adv.'],['à pied','步行','loc.']],
  doctor: [['avoir mal à','……疼','loc.'],['la fièvre','发烧','n.f.'],['la douleur','疼痛','n.f.']]
};

function buildFallbackCards(){
  const cards = [];
  let id = 1;
  FALLBACK_SCENES.forEach(s=>{
    (FALLBACK_VOCAB[s.id]||[]).forEach(v=>{
      cards.push({ id:id++, word:v[0], meaning:v[1], pos:v[2], example:null,
        pronunciation:null, cefr_level:s.cefr_level, source_scene_id:s.id, created_at:NOW_ISO });
    });
  });
  return cards;
}

const FALLBACK_PROFILE = {
  id:1, username:'YU', cefr_level:'A2', target_level:'B2', xp:1280,
  streak_days:12, last_active_date:TODAY,
  stats:{ due_cards_count:8, new_words_week:46, mastered_count:1024, accuracy:0.87 }
};

// 试试点击的建议句（UI 提示，不来自 API）
const TRY_CHIPS = {
  cafe: [
    { text:'Je veux un thé.', bad:true },
    { text:'Je voudrais un croissant.', bad:false,
      reply:{ fr:'Un croissant ! Bien sûr. Vous en voulez un autre ?', cn:'一个可颂！当然。您还要再来一个吗？' } }
  ],
  office: [
    { text:'Je suis aller au musée.', bad:true },
    { text:"J'ai vu un film français.", bad:false,
      reply:{ fr:"Vraiment ? Lequel ? J'adore les films français !", cn:'真的吗？哪一部？我超爱法国电影！' } }
  ],
  street: [
    { text:'Où est le gare ?', bad:true },
    { text:"C'est loin d'ici ?", bad:false,
      reply:{ fr:'Non, pas du tout ! Tu peux y aller à pied.', cn:'不，一点都不远！你可以走路去。' } }
  ],
  doctor: [
    { text:"J'ai mal au tête.", bad:true },
    { text:"Non, je n'ai pas de fièvre.", bad:false,
      reply:{ fr:'Bien. Je vais vous donner quelque chose pour la douleur.', cn:'好的。我给您开点止痛的。' } }
  ]
};

// 规则式重述（来自契约 7.1 表）：命中即温柔重述，不打红叉、不扣分
const RECAST_RULES = [
  { test:/je\s+veux/i, fix:t=>t.replace(/je\s+veux/gi,'Je voudrais'),
    why:'想礼貌点单，法国人更常说 voudrais（条件式），比 veux 更自然——不过你这样说也完全能懂！' },
  { test:/je\s+suis\s+aller/i, fix:t=>t.replace(/je\s+suis\s+aller/gi,'Je suis allé'),
    why:'复合过去时里，être 后面要用过去分词 allé，不是 aller。别担心，我说清楚了吧？接着聊～' },
  { test:/le\s+gare/i, fix:t=>t.replace(/le\s+gare/gi,'la gare'),
    why:'gare 是阴性名词，要用 la 不是 le。记住 la gare（火车站）就好啦！' },
  { test:/(au|à\s+le)\s+tête/i, fix:t=>t.replace(/(au|à\s+le)\s+tête/gi,'à la tête'),
    why:'「身体部位疼」用 à + 定冠词：tête 是阴性，所以是 à la tête。这个搭配记住就能用了！' }
];

/* ---------- 全局状态 ---------- */
const state = {
  online:true,
  scenes:[],
  cards:[],
  profile:null,
  currentSceneId:null,
  chatLog:[],
  // 输入流（分级阅读）独立状态：端点失败只降级阅读区，不动 state.online，不拖垮对话
  read:{
    levels:[],          // LevelInfo[]
    level:null,         // 当前筛选等级
    texts:[],           // InputTextSummary[]
    current:null,       // 当前 InputTextDetail
    currentId:null,
    readIds:[],         // 已读 id 集合，供 recommend exclude_ids
    available:true,
    loaded:false
  }
};
let toastTimer = null;

/* ---------- 工具 ---------- */
function esc(s){
  return String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function fmtNum(n){ return Number(n||0).toLocaleString('en-US'); }
function capitalize(s){ s=String(s||''); return s.charAt(0).toUpperCase()+s.slice(1); }
function notify(msg){
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(()=>el.classList.remove('show'), 3200);
}
function setMicStatus(text){ document.getElementById('micStatus').textContent = text; }
function normalizeTurn(t){
  t = t||{};
  return {
    id: t.id==null ? null : t.id,
    role: t.role==='user' ? 'user' : 'assistant',
    fr: t.fr||'', cn: t.cn||'',
    recast_of: t.recast_of==null ? null : t.recast_of,
    explanation: t.explanation==null ? null : t.explanation,
    is_correction: !!(t.is_correction),
    asr_raw: t.asr_raw==null ? null : t.asr_raw,
    created_at: t.created_at==null ? null : t.created_at
  };
}
function userTurn(fr, rawText){
  const t = { id:null, role:'user', fr:fr, cn:'翻译中…', recast_of:null,
    explanation:null, is_correction:false, created_at:null };
  // 语音识别被修正过：记住原声文本，在气泡里用一行小字低调说明（打字输入不带此字段）
  const raw = rawText==null ? '' : String(rawText).trim();
  if(raw && raw!==String(fr).trim()) t.asr_raw = raw;
  return t;
}

/* ---------- API 层：统一解析 {code,data,message} ---------- */
// 网络异常 / 非 JSON → throw（由调用方决定是否降级）
// 业务错误 code!==0 → 友好提示并返回 null（不抛，不触发降级）
async function apiRequest(path, options){
  options = options||{};
  const res = await fetch(path, {
    method: options.method||'GET',
    headers: { 'Content-Type':'application/json', 'Accept':'application/json' },
    body: options.body===undefined ? undefined : JSON.stringify(options.body)
  });
  let json;
  try { json = await res.json(); }
  catch(e){ throw new Error('服务返回了无法解析的内容'); }
  if(!json || typeof json.code!=='number'){
    throw new Error('服务响应格式异常');
  }
  if(json.code!==0){
    notify(json.message || '操作没成功，稍后再试一下～');
    return null;
  }
  return json.data;
}

/* ---------- 渲染 ---------- */
function renderTop(){
  const p = state.profile||FALLBACK_PROFILE;
  document.getElementById('lvNow').textContent = p.cefr_level||'A2';
  document.getElementById('lvTarget').textContent = p.target_level||'B2';
  document.getElementById('vocabCount').textContent = fmtNum(p.xp);
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

function messageHTML(m){
  if(m.role==='user'){
    return `<div class="row user">
      <div class="who">我</div>
      <div class="bubble"><span>${esc(m.fr)}</span>
        <button class="spk-btn" onclick="speak(this)" data-text="${esc(m.fr)}" title="听我的这句发音">🔊</button>
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
        <div class="say"><span>${esc(m.fr)}</span>
          <button class="spk-btn" onclick="speak(this)" data-text="${esc(m.fr)}" title="听呀呀的重述">🔊</button>
        </div>
        ${m.cn?`<span class="cn">${esc(m.cn)}</span>`:''}
        <div class="why">${m.explanation?esc(m.explanation)+'<br>':''}你说的是：${esc(m.recast_of)}</div>
      </div>
    </div>`;
  }
  return `<div class="row assistant">
    <div class="who">呀</div>
    <div class="bubble"><span>${esc(m.fr)}</span>
      <button class="spk-btn" onclick="speak(this)" data-text="${esc(m.fr)}" title="听发音">🔊</button>
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
  const filtered = state.cards.filter(c=>c.source_scene_id===state.currentSceneId);
  return filtered.length ? filtered : state.cards;
}
function renderVocab(){
  const list = sceneCards();
  document.getElementById('vocabTitle').textContent = '本场景生词';
  document.getElementById('vocabSub').textContent = state.online?'自动收卡':'本地词表';
  document.getElementById('vocab').innerHTML = list.length
    ? list.map(c=>`<div class="v">
        <div class="v-top">
          <span class="w">${esc(c.word)}</span>
          ${c.pos?`<span class="v-pos">${esc(c.pos)}</span>`:''}
          ${c.cefr_level?`<span class="v-lv">${esc(c.cefr_level)}</span>`:''}
          <button class="spk" onclick="speak(this)" data-text="${esc(c.word)}" title="听发音">🔊</button>
        </div>
        <div class="mean">${esc(c.meaning||'')}</div>
        ${c.example?`<div class="v-ex">例：${esc(c.example)}</div>`:''}
      </div>`).join('')
    : '<div class="vocab-empty">还没有生词，聊几句自动收卡～</div>';
}

function renderLedger(){
  const s = (state.profile||FALLBACK_PROFILE).stats||{};
  document.getElementById('dueNum').textContent = s.due_cards_count||0;
  document.getElementById('weekNew').textContent = '+'+(s.new_words_week||0);
  document.getElementById('mastered').textContent = fmtNum(s.mastered_count);
  let acc = s.accuracy||0;
  if(acc<=1) acc=acc*100;
  document.getElementById('accuracy').textContent = Math.round(acc)+'%';
  document.getElementById('streakBadge').textContent = '连续学习 '+(state.profile||FALLBACK_PROFILE).streak_days+' 天 🔥';
}

/* ---------- 场景 / 对话动作 ---------- */
async function selectScene(id){
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
  renderChat();
}

function detailFromFallback(id){
  const s = FALLBACK_SCENES.find(x=>x.id===id)||FALLBACK_SCENES[0];
  return Object.assign({}, s, {
    start_dialogue:(FALLBACK_DETAILS[id]||[]).map(normalizeTurn)
  });
}

function resetChat(){
  const id = state.currentSceneId;
  const detail = state.online ? null : detailFromFallback(id);
  if(detail){
    state.chatLog = detail.start_dialogue.map(normalizeTurn);
    renderChat();
  }else{
    // 在线模式重载起始对话
    selectScene(id);
  }
}

function applyChatResult(data){
  const isCorrection = data.recast_of!=null;
  state.chatLog.push({
    id:null, role:'assistant', fr:data.ai_text||'', cn:data._cn||'翻译中…',
    recast_of:data.recast_of==null?null:data.recast_of,
    explanation:data.explanation==null?null:data.explanation,
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
let _ttsAudio = null;
// Chrome 自动播放策略：音频必须由用户手势"解锁"后才允许出声。
// 首次任意点击时用一段静音 audio 解锁，之后 fetch 回调里的 play() 才不会被拒。
let _audioUnlocked = false;
function unlockAudio(){
  if(_audioUnlocked) return;
  _audioUnlocked = true;
  try{
    const a = new Audio('data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQAAAAA=');
    const p = a.play();
    if(p && p.then) p.then(()=>a.pause()).catch(()=>{});
  }catch(e){}
}
document.addEventListener('pointerdown', unlockAudio, {once:false});
document.addEventListener('keydown', unlockAudio, {once:false});

function speak(btn){
  const text = btn.getAttribute('data-text')||'';
  if(!text) return;
  unlockAudio();
  if(window.speechSynthesis) window.speechSynthesis.cancel();
  if(_ttsAudio){ try{ _ttsAudio.pause(); }catch(e){} _ttsAudio=null; }
  btn.classList.add('speaking');
  const clear = ()=>btn.classList.remove('speaking');
  // 优先用本地神经语音合成（le/la/les 等功能词连读准确，不会读成字母）
  fetch('/api/tts?text='+encodeURIComponent(text))
    .then(r=>{ if(!r.ok) throw new Error('tts '+r.status); return r.blob(); })
    .then(blob=>{
      const url = URL.createObjectURL(blob);
      const a = new Audio(url);
      _ttsAudio = a;
      a.onended = ()=>{ URL.revokeObjectURL(url); clear(); };
      a.onerror = ()=>{ URL.revokeObjectURL(url); clear(); fallbackSpeak(text); };
      return a.play();
    })
    .then(()=>{})
    .catch(()=>{ clear(); fallbackSpeak(text); });
}
function fallbackSpeak(text){
  if(!('speechSynthesis' in window)){ notify('当前浏览器不支持语音朗读'); return; }
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = 'fr-FR';
  u.rate = 0.95;
  // 尽量挑一个真正的法语 voice，减少英语引擎硬读法语
  try{
    const fr = (window.speechSynthesis.getVoices()||[])
      .find(v=>/^fr/i.test(v.lang));
    if(fr) u.voice = fr;
  }catch(e){}
  window.speechSynthesis.speak(u);
}

/* 语音输入：MediaRecorder 录音 → 上传本地 Whisper 服务转写（不依赖境外服务）
   降级顺序：本地 ASR 服务 → 浏览器自带识别（若在境外网络可用）→ 打字 */
let mediaRecorder = null, audioChunks = [], recording = false;
let asrAvailable = null; // null=未探测 true/false

function pickMimeType(){
  const candidates = ['audio/webm;codecs=opus','audio/webm','audio/ogg;codecs=opus','audio/mp4'];
  for(const t of candidates){ if(window.MediaRecorder && MediaRecorder.isTypeSupported(t)) return t; }
  return '';
}

async function checkAsr(){
  if(asrAvailable!==null) return asrAvailable;
  try{
    const r = await apiRequest('/api/asr/status');
    asrAvailable = !!(r && r.available);
  }catch(e){ asrAvailable = false; }
  return asrAvailable;
}

async function toggleMic(){
  const btn = document.getElementById('micBtn');
  if(recording){ if(mediaRecorder && mediaRecorder.state!=='inactive') mediaRecorder.stop(); return; }

  if(!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder){
    setMicStatus('这个浏览器不支持录音，请用 Chrome / Edge，或直接打字。');
    notify('浏览器不支持录音，可以直接打字哦');
    return;
  }

  let stream;
  try{
    stream = await navigator.mediaDevices.getUserMedia({audio:true});
  }catch(e){
    setMicStatus('麦克风权限被拒绝。请点地址栏左侧锁图标允许麦克风，或直接打字。');
    notify('需要麦克风权限，也可以直接打字');
    return;
  }

  try{
    const mime = pickMimeType();
    mediaRecorder = new MediaRecorder(stream, mime?{mimeType:mime}:undefined);
    audioChunks = [];
    mediaRecorder.ondataavailable = (e)=>{ if(e.data && e.data.size) audioChunks.push(e.data); };
    mediaRecorder.onstart = ()=>{
      recording = true;
      btn.classList.add('rec');
      setMicStatus('🎙 在听，请说法语…说完自动结束，最长 15 秒');
    };
    mediaRecorder.onstop = async ()=>{
      recording = false;
      btn.classList.remove('rec');
      stream.getTracks().forEach(t=>t.stop());
      const blob = new Blob(audioChunks, {type: mediaRecorder.mimeType || 'audio/webm'});
      if(!blob.size){ setMicStatus('没录到声音，再试一次或直接打字。'); return; }
      await transcribeAudio(blob);
    };
    mediaRecorder.start();
    // 最长 15 秒自动结束，避免一直占着麦克风
    setTimeout(()=>{ if(recording && mediaRecorder.state!=='inactive') mediaRecorder.stop(); }, 15000);
  }catch(e){
    stream.getTracks().forEach(t=>t.stop());
    setMicStatus('录音启动失败：'+e.message+'（可直接打字）');
  }
}

// 从最近对话与生词卡取法语词作 ASR 热词；只留字母、限量，避免长提示稀释偏置
function buildAsrHints(){
  const seen = new Set();
  const add = s => String(s||'').replace(/['’]/g,' ').split(/[^\p{L}]+/u)
    .forEach(w=>{ if(w.length>1) seen.add(w.toLowerCase()); });
  state.chatLog.slice(-6).forEach(m=>add(m.fr));
  state.cards.slice(0,40).forEach(c=>add(c && c.word));
  return [...seen].slice(0,40).join(' ');
}
// 前一句对话整句作为 ASR 上下文（实验证明：前一句够用，前两句无额外收益）
function buildAsrContext(){
  for(let i=state.chatLog.length-1;i>=0;i--){
    const fr = String(state.chatLog[i] && state.chatLog[i].fr || '').trim();
    if(fr) return fr.slice(0,200);
  }
  return '';
}
async function transcribeAudio(blob){
  setMicStatus('正在识别你说的话…');
  const ext = (blob.type.includes('mp4')?'.m4a':blob.type.includes('ogg')?'.ogg':'.webm');
  const available = await checkAsr();
  let data = null;
  if(available){
    try{
      const fd = new FormData();
      fd.append('file', blob, 'voice'+ext);
      fd.append('language', 'fr');
      fd.append('hints', buildAsrHints());
      fd.append('context', buildAsrContext());
      const resp = await fetch('/api/asr/transcribe', {method:'POST', body:fd});
      data = await resp.json();
    }catch(e){
      // 真正的网络异常（连接失败 / 响应非 JSON）才落到浏览器兜底
      data = null;
    }
    if(data){
      // 业务错误：服务端已给出明确 message（如"没听清"），如实展示后直接返回。
      // 绝不走浏览器兜底，否则会显示"本地语音服务未启动"这类误导文案。
      if(typeof data.code==='number' && data.code!==0){
        setMicStatus(data.message || '识别没成功，再试一次或直接打字～');
        document.getElementById('userInput').focus();
        return;
      }
      if(data.code===0 && data.data && data.data.text){
        const text = String(data.data.text).trim();
        const rawText = data.data.raw_text==null ? '' : String(data.data.raw_text).trim();
        const corrected = !!data.data.corrected;
        // 解析置信度；low_confidence 是权威标志，缺失时以极低 confidence 兜底
        const confidence = Number(data.data.confidence);
        const flagMissing = data.data.low_confidence==null;
        const lowConfidence = !!data.data.low_confidence
          || (flagMissing && Number.isFinite(confidence) && confidence>0 && confidence<0.5);
        document.getElementById('userInput').value = text;
        if(lowConfidence){
          // 低置信：只把识别文本放进输入框，温和提示，聚焦输入框，绝不自动提交
          setMicStatus('没太听清，改一下或再录一次都行～');
          document.getElementById('userInput').focus();
          return;
        }
        // ASR 明确标记已修正且原声与结果不同：温和小字提示，不打红叉、不弹错误
        if(corrected && rawText && rawText!==text){
          setMicStatus('已按法语发音把识别结果修正为：'+text);
          submitUserText(text, rawText);
        }else{
          setMicStatus('识别到：'+text);
          submitUserText(text);
        }
        return;
      }
    }
  }
  // 降级：浏览器自带识别（多数国内网络不可用，但保留兜底）
  await browserRecognizeFallback();
}

function browserRecognizeFallback(){
  return new Promise((resolve)=>{
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if(!SpeechRec){
      setMicStatus('本地语音服务未启动，请直接打字（或先启动 ASR 服务）。');
      document.getElementById('userInput').focus();
      resolve(); return;
    }
    const rec = new SpeechRec();
    rec.lang='fr-FR'; rec.interimResults=false; rec.continuous=false;
    rec.onresult=(e)=>{
      const text=(e.results[0][0].transcript||'').trim();
      if(text){ document.getElementById('userInput').value=text; setMicStatus('识别到：'+text); submitUserText(text); }
      resolve();
    };
    rec.onerror=(e)=>{
      const msg = e.error==='network'
        ? '本地语音服务未启动，浏览器识别也连不上（境外服务）。请直接打字。'
        : '识别未成功（'+e.error+'），请直接打字。';
      setMicStatus(msg); document.getElementById('userInput').focus(); resolve();
    };
    try{ rec.start(); }catch(e){ setMicStatus('请直接打字。'); resolve(); }
  });
}

/* ---------- 复习：4 档评分调 POST /api/cards/{id}/review ---------- */
let reviewQueue = [], reviewIdx = 0;
const OFFLINE_INTERVAL = {1:1, 2:2, 3:4, 4:7};

function openReview(){
  reviewQueue = state.cards.slice();
  if(!reviewQueue.length){ notify('还没有生词卡可以复习'); return; }
  reviewIdx = 0;
  document.getElementById('reviewOverlay').classList.remove('hidden');
  renderReviewCard();
}
function closeReview(){ document.getElementById('reviewOverlay').classList.add('hidden'); }

function renderReviewCard(){
  const box = document.getElementById('reviewContent');
  if(reviewIdx>=reviewQueue.length){
    box.innerHTML = `<div class="review-done"><div class="done-emoji">🌿</div>
      <h3>今日复习完成</h3><p>温柔地记住了 ${reviewQueue.length} 张卡片，真棒！</p>
      <button class="review-entry" onclick="closeReview()">完成</button></div>`;
    return;
  }
  const c = reviewQueue[reviewIdx];
  box.innerHTML = `
    <div class="rv-progress">${reviewIdx+1} / ${reviewQueue.length}</div>
    <div class="rv-word">${esc(c.word)}</div>
    ${c.pos?`<span class="rv-pos">${esc(c.pos)}</span>`:''}
    <div class="rv-mean">${esc(c.meaning||'')}</div>
    <div class="rv-example">${c.example?esc(c.example):'（这张卡还没有例句，先记住词吧～）'}</div>
    <div class="rating-row">
      <button class="rate-btn again" onclick="doReview(1)">再看看<small>1</small></button>
      <button class="rate-btn hard"  onclick="doReview(2)">有点难<small>2</small></button>
      <button class="rate-btn good"  onclick="doReview(3)">记住啦<small>3</small></button>
      <button class="rate-btn easy"  onclick="doReview(4)">太简单<small>4</small></button>
    </div>`;
}

async function doReview(rating){
  const c = reviewQueue[reviewIdx];
  if(!c) return;
  let interval;
  if(state.online){
    try {
      const res = await apiRequest('/api/cards/'+encodeURIComponent(c.id)+'/review', {
        method:'POST', body:{ rating:rating }
      });
      if(res==null) return; // 业务错误已提示，留在本卡
      interval = res.interval_days;
    }catch(e){
      setOffline();
      interval = OFFLINE_INTERVAL[rating];
    }
  }else{
    interval = OFFLINE_INTERVAL[rating];
  }
  notify(rating<=2 ? '没关系，'+interval+' 天后再温柔相遇 🌱' : '太棒了，'+interval+' 天后见 ✨');
  reviewIdx++;
  renderReviewCard();
}

/* ============================================================
   输入流：分级阅读（i+1）—— 5 个 /api/input/* 端点
   原则：端点失败只给阅读区低调提示，不进入全局离线态、不弹红叉、不影响对话主流程
   ============================================================ */
function readOfflineNote(msg){
  state.read.available = false;
  const body = document.getElementById('readBody');
  const note = document.getElementById('readNote');
  if(note) note.innerHTML = '';
  if(body) body.innerHTML = `<div class="read-offline-note">📖 ${esc(msg||'阅读功能需要后端服务，稍后再来看看吧～')}<br>对话陪练不受影响，可以继续聊天 🌱</div>`;
  const lv = document.getElementById('levelRow');
  const tl = document.getElementById('textList');
  if(lv) lv.innerHTML = '';
  if(tl) tl.innerHTML = '';
}

function updateReadVocabBadge(){
  const b = document.getElementById('readVocabBadge');
  if(b) b.textContent = '词库 '+state.cards.length+' 词';
}

function switchView(name){
  // 四个视图：chat / read / assessment / exam；其他值一律按 chat 处理（保留原默认行为）
  const view = (name==='read'||name==='assessment'||name==='exam') ? name : 'chat';
  document.getElementById('viewChat').classList.toggle('hidden', view!=='chat');
  document.getElementById('viewRead').classList.toggle('hidden', view!=='read');
  const av = document.getElementById('viewAssessment');
  if(av) av.classList.toggle('hidden', view!=='assessment');
  const ev = document.getElementById('viewExam');
  if(ev) ev.classList.toggle('hidden', view!=='exam');
  document.getElementById('tabChat').classList.toggle('on', view==='chat');
  document.getElementById('tabRead').classList.toggle('on', view==='read');
  const at = document.getElementById('tabAssessment');
  if(at) at.classList.toggle('on', view==='assessment');
  const et = document.getElementById('tabExam');
  if(et) et.classList.toggle('on', view==='exam');
  // 首次进入阅读视图才拉端点，避免启动多打请求；失败也只是这里降级
  if(view==='read' && !state.read.loaded){
    state.read.loaded = true;
    loadReadLevels();
  }
  // 切到定级视图：有缓存结果就展示结果态，否则引导态
  if(view==='assessment') initAssessment();
  // 切到考级视图：拉试卷列表
  if(view==='exam') initExam();
}

/* ============================================================
   阶段0 定级：快速测一测
   GET /api/assessment/questions + POST /api/assessment/submit
   独立追加，不改写现有函数名；失败只给温和提示，不进 fallback 瞎编题
   ============================================================ */
const ASSESS_RESULT_KEY = 'placement_result';
const assessmentState = {
  questions:[],   // PublicQuestion[]：id/level/skill/question/options
  answers:{},     // id -> answer_idx（0..3）
  index:0,        // 当前题号
  submitting:false,
  result:null
};
const ASM_LEVELS = ['A2','B1','B2'];

function showAssessmentPane(which){
  const map = {intro:'asmIntro', quiz:'asmQuiz', result:'asmResult'};
  Object.keys(map).forEach(k=>{
    const el = document.getElementById(map[k]);
    if(el) el.classList.toggle('hidden', k!==which);
  });
}

function initAssessment(){
  let cached = null;
  try{
    if(localStorage.getItem('placement_done')==='1'){
      cached = JSON.parse(localStorage.getItem(ASSESS_RESULT_KEY)||'null');
    }
  }catch(e){ cached = null; }
  if(cached && cached.level){
    assessmentState.result = cached;
    showAssessmentPane('result');
    renderAssessmentResult(cached);
  }else{
    showAssessmentPane('intro');
  }
}

async function startAssessment(){
  const btn = document.getElementById('asmStartBtn');
  if(btn) btn.disabled = true;
  let data = null;
  try{
    data = await apiRequest('/api/assessment/questions');
  }catch(e){ data = null; }
  const qs = (data && Array.isArray(data.questions)) ? data.questions : [];
  if(!qs.length){
    notify('题库暂时没准备好，稍后再试～');
    if(btn) btn.disabled = false;
    return;
  }
  // 按 level 分组稳定排序 A2 → B1 → B2（判分按 id 匹配，顺序不影响结果）
  const order = {A2:0, B1:1, B2:2};
  assessmentState.questions = qs.slice().sort((a,b)=>
    (order[a.level]==null?9:order[a.level]) - (order[b.level]==null?9:order[b.level]));
  assessmentState.answers = {};
  assessmentState.index = 0;
  assessmentState.submitting = false;
  assessmentState.result = null;
  showAssessmentPane('quiz');
  renderAssessmentQuestion();
}

function renderAssessmentQuestion(){
  const box = document.getElementById('asmQuiz');
  if(!box) return;
  const qs = assessmentState.questions;
  const i = assessmentState.index;
  const q = qs[i];
  if(!q) return;
  const answered = qs.filter(x=>assessmentState.answers[x.id]!=null).length;
  // level 胶囊可点击跳到该组第一题，形成分组导航
  const pills = ASM_LEVELS.map(l=>
    `<button class="asm-lv-pill ${l.toLowerCase()} ${q.level===l?'on':''}" onclick="jumpAssessmentLevel('${l}')">${l}</button>`
  ).join('');
  const opts = (Array.isArray(q.options)?q.options:[]).map((o,j)=>{
    const sel = assessmentState.answers[q.id]===j;
    return `<button class="asm-opt ${sel?'on':''}" onclick="answerAssessment(${j})">
      <span class="asm-opt-key">${'ABCD'[j]||(j+1)}</span><span class="asm-opt-text">${esc(o)}</span>
    </button>`;
  }).join('');
  box.innerHTML = `
    <div class="card asm-quiz-card">
      <div class="asm-progress-top">
        <span>第 ${i+1} / ${qs.length} 题</span>
        <span id="asmAnswered">已答 ${answered} / ${qs.length} 题</span>
      </div>
      <div class="asm-bar"><i style="width:${Math.round((i+1)/qs.length*100)}%"></i></div>
      <div class="asm-q-head">
        <div class="asm-lv-row">${pills}</div>
        <span class="asm-skill">${esc(q.skill||'')}</span>
      </div>
      <div class="asm-q">${esc(q.question||'')}</div>
      <div class="asm-opts">${opts}</div>
      <div class="asm-nav">
        <button class="asm-nav-btn" onclick="prevAssessment()" ${i===0?'disabled':''}>← 上一题</button>
        <button class="asm-nav-btn" onclick="nextAssessment()" ${i===qs.length-1?'disabled':''}>下一题 →</button>
      </div>
      <div class="asm-submit-row">
        <button class="asm-primary" id="asmSubmitBtn" onclick="submitAssessment()">看看我的等级</button>
      </div>
    </div>`;
}

function answerAssessment(idx){
  const q = assessmentState.questions[assessmentState.index];
  if(!q) return;
  assessmentState.answers[q.id] = idx;
  // 只切换选中态，不整页重绘（保留翻页位置）
  document.querySelectorAll('#asmQuiz .asm-opt').forEach((b,j)=>b.classList.toggle('on', j===idx));
  const a = document.getElementById('asmAnswered');
  if(a) a.textContent = '已答 '+assessmentState.questions.filter(x=>assessmentState.answers[x.id]!=null).length+' / '+assessmentState.questions.length+' 题';
}

function nextAssessment(){
  if(assessmentState.index < assessmentState.questions.length-1){
    assessmentState.index++;
    renderAssessmentQuestion();
  }
}
function prevAssessment(){
  if(assessmentState.index>0){ assessmentState.index--; renderAssessmentQuestion(); }
}
function jumpAssessmentLevel(level){
  const i = assessmentState.questions.findIndex(q=>q.level===level);
  if(i>=0){ assessmentState.index=i; renderAssessmentQuestion(); }
}

async function submitAssessment(){
  if(assessmentState.submitting) return;
  const qs = assessmentState.questions;
  const missing = qs.filter(q=>assessmentState.answers[q.id]==null).length;
  if(missing){
    notify('还有 '+missing+' 题没做哦，要不要再看看？');
    return;
  }
  assessmentState.submitting = true;
  const btn = document.getElementById('asmSubmitBtn');
  if(btn) btn.disabled = true;
  const answers = qs.map(q=>({id:q.id, answer_idx:assessmentState.answers[q.id]}));
  let data = null;
  try{
    data = await apiRequest('/api/assessment/submit', {method:'POST', body:{answers:answers}});
  }catch(e){ data = null; }
  if(!data){
    // 业务错误已由 apiRequest 提示；网络异常统一走温和文案；保留答案、恢复按钮
    assessmentState.submitting = false;
    if(btn) btn.disabled = false;
    notify('网络开小差了，再试一次就好');
    return;
  }
  const level = String(data.level||'A2');
  assessmentState.result = data;
  if(state.profile) state.profile.cefr_level = level;
  else state.profile = Object.assign({}, FALLBACK_PROFILE, {cefr_level:level});
  renderTop(); // 顶部等级即时刷新
  try{
    localStorage.setItem('placement_done','1');
    localStorage.setItem(ASSESS_RESULT_KEY, JSON.stringify(data));
  }catch(e){}
  showAssessmentPane('result');
  renderAssessmentResult(data);
}

function renderAssessmentResult(data){
  const box = document.getElementById('asmResult');
  if(!box) return;
  const score = Number(data.score)||0;
  const total = Number(data.total)||12;
  const s = Number(data.weighted_score)||0;
  const pct = Math.min(100, Math.round(s/24*100));
  const level = String(data.level||'A2');
  box.innerHTML = `
    <div class="card asm-result-card">
      <div class="asm-result-top">
        <div class="asm-result-emoji">🎯</div>
        <div>
          <div class="asm-level-badge">${esc(level)}</div>
          <div class="asm-result-label">你的参考等级</div>
        </div>
        <div class="asm-result-score">答对 <b>${score}</b> 题<span> / 共 ${total} 题</span></div>
      </div>
      <div class="asm-weight-row"><span>加权得分</span><b>${s} / 24</b></div>
      <div class="asm-bar"><i style="width:${pct}%"></i></div>
      <div class="asm-interpret">${esc(data.interpretation_zh||'')}</div>
      <div class="asm-result-actions">
        <button class="asm-ghost" onclick="startAssessment()">再测一次</button>
        <button class="asm-primary" onclick="goAssessmentRecommend()">看看推荐内容</button>
      </div>
      <div class="asm-result-foot">觉得不太准？随时可以再测一次 🌱</div>
    </div>`;
}

function goAssessmentRecommend(){
  switchView('read');
  recommendNext();
}

// 11) GET /api/input/levels
async function loadReadLevels(){
  try{
    const levels = await apiRequest('/api/input/levels');
    if(levels==null) return;
    state.read.available = true;
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
  renderReadLines(detail);
  renderReadWords(detail);
  renderReadTexts();
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
        <span class="fr">${esc(l.fr)}<button class="rplay" onclick="speak(this)" data-text="${esc(l.fr)}" title="听这句">🔊</button></span>
        ${l.cn?`<span class="cn">${esc(l.cn)}</span>`:''}
      </div>
    </div>`;
  });
  html += `<div class="whole-fr"><h4>整篇法语原文</h4><p>${esc(detail.body_fr||'')}</p></div>`;
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
        <span class="rw-word">${esc(w.word)}</span>
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
function playCurrentAudio(){
  const t = state.read.current;
  if(!t) return;
  unlockAudio();
  const btn = document.getElementById('readAudioBtn');
  if(!btn) return;
  if(_ttsAudio){ try{ _ttsAudio.pause(); }catch(e){} _ttsAudio=null; }
  if(t.audio_url){
    btn.classList.add('speaking');
    try{
      const a = new Audio(t.audio_url);
      _ttsAudio = a;
      a.onended = ()=>btn.classList.remove('speaking');
      const fb = ()=>{ btn.classList.remove('speaking'); fallbackSpeak(t.audio_text || t.body_fr || ''); };
      a.onerror = fb;
      a.play().catch(fb);
      return;
    }catch(e){ /* 落到 TTS 兜底 */ }
  }
  speak(btn); // data-text 已在 showReadDetail 设为 audio_text || body_fr
}

// 14) POST /api/input/texts/{id}/collect —— 单收传 words，收全部省略 words
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
async function init(){
  document.addEventListener('keydown', e=>{ if(e.key==='Escape') closeReview(); });

  // 先健康检查：网络不通即进入离线演示模式
  try {
    const health = await apiRequest('/api/health');
    if(health==null){ setOffline(); }
  }catch(e){
    setOffline();
  }

  if(state.online){
    try {
      const [scenes, cards, profile] = await Promise.all([
        apiRequest('/api/scenes'),
        apiRequest('/api/cards'),
        apiRequest('/api/profile')
      ]);
      state.scenes = Array.isArray(scenes) ? scenes : [];
      state.cards  = Array.isArray(cards)  ? cards  : [];
      state.profile = profile || FALLBACK_PROFILE;
    }catch(e){
      setOffline();
    }
  }

  if(!state.scenes.length){
    setOffline();
    state.scenes = FALLBACK_SCENES.slice();
  }
  if(!state.cards.length) state.cards = buildFallbackCards();
  if(!state.profile) state.profile = FALLBACK_PROFILE;

  renderTop();
  renderScenes();
  renderVocab();
  renderLedger();
  updateReadVocabBadge();
  const firstId = state.scenes[0].id;
  await selectScene(firstId);
}

init();

/* ============================================================
   阶段4 考级冲刺：原创模拟练习（第 4 个 Tab）
   GET /api/exam/papers + GET /api/exam/papers/{id} + POST /api/exam/submit
   独立追加，不改写现有函数名：
   - 听力/口语 🔊 复用 speak(btn)（data-text 已 esc）
   - 口语 🎙 用本模块独立录音→上传→取文本，只填本题文本框，
     不触碰对话流、不写对话输入框、不复用对话麦克风状态
   - 失败只给温和提示，不瞎编卷
   ============================================================ */
const EXAM_DISCLAIMER = '本卷为原创模拟练习，非 DELF/TCF 官方真题，成绩仅供练习参考';
const examState = {
  papers:[],        // PaperSummary[]
  paper:null,       // 当前 PaperDetail
  paperId:null,
  answers:{},       // id -> choice:int(0..3) | writing/speaking:string
  index:0,
  submitting:false,
  recording:false,  // 本模块独立录音标志（与对话麦克风互不相干）
  rec:null,
  recStream:null,
  recChunks:[],
  recTimer:null
};

function examTypeName(t){
  return t==='choice' ? '单项选择' : (t==='writing' ? '书面表达' : '口语表达');
}
function examAnswerDone(q){
  if(q.type==='choice') return examState.answers[q.id]!=null;
  const v = examState.answers[q.id];
  return typeof v==='string' && v.trim().length>0;
}
function showExamPane(which){
  const map = {papers:'exPapers', quiz:'exQuiz', result:'exResult'};
  Object.keys(map).forEach(k=>{
    const el = document.getElementById(map[k]);
    if(el) el.classList.toggle('hidden', k!==which);
  });
}

async function initExam(){
  let data = null;
  try{ data = await apiRequest('/api/exam/papers'); }
  catch(e){ data = null; }
  const papers = Array.isArray(data) ? data : [];
  showExamPane('papers');
  if(!papers.length){
    const box = document.getElementById('exPapers');
    if(box) box.innerHTML = '<div class="card ex-empty-card">卷子暂时没准备好，稍后再来看看～ 🌱</div>';
    return;
  }
  examState.papers = papers;
  renderExamPapers(papers);
}

function renderExamPapers(papers){
  const box = document.getElementById('exPapers');
  if(!box) return;
  box.innerHTML = `
    <div class="ex-papers-head">
      <div class="ex-papers-emoji">🏆</div>
      <h2>挑一套卷子练练</h2>
      <p>原创模拟练习，练题型与思路，按自己的节奏来就好～</p>
    </div>
    <div class="ex-paper-list">
      ${papers.map(p=>`
        <div class="card ex-paper-card" onclick="openExamPaper('${esc(p.id)}')">
          <div class="ex-paper-top">
            <span class="ex-type-pill">${esc(p.exam_type||'')}</span>
            <span class="ex-paper-meta">${Number(p.question_count)||0} 题 · 满分 ${Number(p.total_points)||0} 分</span>
          </div>
          <div class="ex-paper-title">${esc(p.title||'')}</div>
          <div class="ex-paper-desc">${esc(p.description_zh||'')}</div>
          <div class="ex-paper-go">开始练习 →</div>
        </div>`).join('')}
    </div>
    <div class="ex-disclaimer">${EXAM_DISCLAIMER}</div>`;
}

async function openExamPaper(pid){
  let data = null;
  try{ data = await apiRequest('/api/exam/papers/'+encodeURIComponent(pid)); }
  catch(e){ data = null; }
  if(!data || !Array.isArray(data.questions) || !data.questions.length){
    notify('这套卷子暂时找不到，换一套试试～');
    return;
  }
  examState.paper = data;
  examState.paperId = data.id || pid;
  examState.answers = {};
  examState.index = 0;
  examState.submitting = false;
  showExamPane('quiz');
  renderExamQuestion();
}

function renderExamQuestion(){
  const box = document.getElementById('exQuiz');
  if(!box || !examState.paper) return;
  const qs = examState.paper.questions;
  const i = examState.index;
  const q = qs[i];
  if(!q) return;
  let body = '';
  if(q.type==='choice'){
    const opts = (Array.isArray(q.options)?q.options:[]).map((o,j)=>{
      const sel = examState.answers[q.id]===j;
      return `<button class="ex-opt ${sel?'on':''}" onclick="answerExamChoice(${j})">
        <span class="ex-opt-key">${'ABCD'[j]||(j+1)}</span><span class="ex-opt-text">${esc(o)}</span>
      </button>`;
    }).join('');
    const audio = q.audio_text
      ? `<div class="ex-audio"><button class="spk" onclick="speak(this)" data-text="${esc(q.audio_text)}" title="听这段法语">🔊 听一听</button><span>听力材料，点小喇叭听法语～</span></div>`
      : '';
    body = `
      <div class="ex-prompt-fr">${esc(q.prompt_fr||'')}</div>
      ${audio}
      <div class="ex-opts">${opts}</div>`;
  }else if(q.type==='writing'){
    const val = typeof examState.answers[q.id]==='string' ? examState.answers[q.id] : '';
    body = `
      <div class="ex-prompt-zh">${esc(q.prompt_zh||'')}</div>
      <div class="ex-hint">建议写满 ${Number(q.min_words)||80} 词以上，慢慢写就好～</div>
      <textarea id="exTextInput" class="ex-textarea" maxlength="5000"
        oninput="onExamTextInput(this)" placeholder="在这里用法语写下你的想法…">${esc(val)}</textarea>`;
  }else{
    const val = typeof examState.answers[q.id]==='string' ? examState.answers[q.id] : '';
    body = `
      <div class="ex-prompt-zh">${esc(q.prompt_zh||'')}</div>
      <div class="ex-audio"><button class="spk" onclick="speak(this)" data-text="${esc(q.prompt_fr||'')}" title="听法语题目">🔊 听题目</button><span>先听听法语题目～</span></div>
      <div class="ex-hint">可以点 🎙 说出回答，也可以直接打字，两种方式都行～</div>
      <textarea id="exTextInput" class="ex-textarea" maxlength="5000"
        oninput="onExamTextInput(this)" placeholder="转写结果会出现在这里，也可以直接输入法语…">${esc(val)}</textarea>
      <div class="ex-record-row">
        <button class="ex-record-btn" id="exRecordBtn" onclick="toggleExamRecord()">🎙 录音作答</button>
        <span class="ex-record-status" id="exRecordStatus">最长录 15 秒，说完点一下结束即可</span>
      </div>`;
  }
  box.innerHTML = `
    <div class="card ex-quiz-card">
      <div class="ex-progress-top">
        <span>第 ${i+1} / ${qs.length} 题</span>
        <span>${esc(q.section||'')} · ${esc(examTypeName(q.type))}</span>
      </div>
      <div class="ex-bar"><i style="width:${Math.round((i+1)/qs.length*100)}%"></i></div>
      <div class="ex-q-title">${esc(examTypeName(q.type))}<span class="ex-points">${Number(q.points)||0} 分</span></div>
      ${body}
      <div class="ex-nav">
        <button class="ex-nav-btn" onclick="prevExam()" ${i===0?'disabled':''}>← 上一题</button>
        <button class="ex-nav-btn" onclick="nextExam()" ${i===qs.length-1?'disabled':''}>下一题 →</button>
      </div>
      <div class="ex-submit-row">
        <button class="ex-primary" id="exSubmitBtn" onclick="submitExam()">交卷看看</button>
      </div>
      <div class="ex-foot-note">原创模拟练习 · 按自己的节奏来 · 可随时返回修改 🌱</div>
    </div>`;
}

function answerExamChoice(idx){
  const q = examState.paper.questions[examState.index];
  if(!q) return;
  examState.answers[q.id] = idx;
  document.querySelectorAll('#exQuiz .ex-opt').forEach((b,j)=>b.classList.toggle('on', j===idx));
}
function onExamTextInput(el){
  const q = examState.paper && examState.paper.questions[examState.index];
  if(q) examState.answers[q.id] = el.value;
}
function saveExamCurrentText(){
  const ta = document.getElementById('exTextInput');
  if(!ta || !examState.paper) return;
  const q = examState.paper.questions[examState.index];
  if(q && q.type!=='choice') examState.answers[q.id] = ta.value;
}
function nextExam(){
  saveExamCurrentText();
  if(examState.index < examState.paper.questions.length-1){ examState.index++; renderExamQuestion(); }
}
function prevExam(){
  saveExamCurrentText();
  if(examState.index>0){ examState.index--; renderExamQuestion(); }
}

/* 口语题独立录音：只用本模块状态，结果只填本题文本框 */
async function toggleExamRecord(){
  const btn = document.getElementById('exRecordBtn');
  if(examState.recording){
    if(examState.rec && examState.rec.state!=='inactive') examState.rec.stop();
    return;
  }
  if(!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder){
    notify('这个浏览器不支持录音，直接打字作答就好～');
    return;
  }
  let stream;
  try{
    stream = await navigator.mediaDevices.getUserMedia({audio:true});
  }catch(e){
    notify('没拿到麦克风权限，直接打字作答也可以～');
    return;
  }
  try{
    const mime = pickMimeType();
    const rec = new MediaRecorder(stream, mime?{mimeType:mime}:undefined);
    examState.rec = rec;
    examState.recStream = stream;
    examState.recChunks = [];
    examState.recording = true;              // 先置位，防连点
    if(btn){ btn.classList.add('rec'); btn.textContent='⏹ 结束录音'; }
    rec.ondataavailable = (e)=>{ if(e.data && e.data.size) examState.recChunks.push(e.data); };
    rec.onstop = async ()=>{
      examState.recording = false;
      if(btn){ btn.classList.remove('rec'); btn.textContent='🎙 录音作答'; }
      stream.getTracks().forEach(t=>t.stop());
      clearTimeout(examState.recTimer);
      const blob = new Blob(examState.recChunks, {type: rec.mimeType || 'audio/webm'});
      if(!blob.size){
        const st = document.getElementById('exRecordStatus');
        if(st) st.textContent = '没录到声音，再试一次或直接打字～';
        return;
      }
      await transcribeExamAudio(blob);
    };
    rec.start();
    const st = document.getElementById('exRecordStatus');
    if(st) st.textContent = '🎙 在听，请说法语…最长 15 秒';
    examState.recTimer = setTimeout(()=>{
      if(examState.recording && rec.state!=='inactive') rec.stop();
    }, 15000);
  }catch(e){
    examState.recording = false;
    if(btn){ btn.classList.remove('rec'); btn.textContent='🎙 录音作答'; }
    stream.getTracks().forEach(t=>t.stop());
    notify('录音启动没成功，直接打字作答也可以～');
  }
}

async function transcribeExamAudio(blob){
  const st = document.getElementById('exRecordStatus');
  if(st) st.textContent = '正在识别你说的话…';
  const ext = (blob.type.includes('mp4')?'.m4a':blob.type.includes('ogg')?'.ogg':'.webm');
  let data = null;
  try{
    const fd = new FormData();
    fd.append('file', blob, 'exam'+ext);
    fd.append('language', 'fr');
    fd.append('hints', '');
    fd.append('context', '');
    const resp = await fetch('/api/asr/transcribe', {method:'POST', body:fd});
    data = await resp.json();
  }catch(e){ data = null; }
  if(!data || typeof data.code!=='number' || data.code!==0 || !data.data || !data.data.text){
    if(st) st.textContent = '这次没转写出来，再试一次或直接打字～';
    return;
  }
  const text = String(data.data.text).trim();
  const lowConfidence = !!data.data.low_confidence;
  const ta = document.getElementById('exTextInput');
  if(ta) ta.value = text;
  const q = examState.paper && examState.paper.questions[examState.index];
  if(q) examState.answers[q.id] = text;
  if(lowConfidence){
    notify('没太听清，可以自己改一下～');
    if(st) st.textContent = '没太听清，可以自己改一下，或再录一次～';
  }else{
    if(st) st.textContent = '转写好啦，也可以直接在上面修改～';
  }
}

async function submitExam(){
  if(examState.submitting || !examState.paper) return;
  const qs = examState.paper.questions;
  saveExamCurrentText();
  const missing = qs.filter(q=>!examAnswerDone(q)).length;
  if(missing){
    notify('还有 '+missing+' 题没做哦，要不要再看看？');
    return;
  }
  examState.submitting = true;
  const btn = document.getElementById('exSubmitBtn');
  if(btn) btn.disabled = true;
  const answers = qs.map(q=> q.type==='choice'
    ? {id:q.id, answer_idx:examState.answers[q.id]}
    : {id:q.id, text:String(examState.answers[q.id]||'').trim()});
  let data = null;
  try{
    data = await apiRequest('/api/exam/submit', {
      method:'POST', body:{ paper_id:examState.paperId, answers:answers }
    });
  }catch(e){ data = null; }
  if(!data){
    examState.submitting = false;
    if(btn) btn.disabled = false;
    notify('网络开小差了，再试一次就好');
    return;
  }
  showExamPane('result');
  renderExamResult(data);
}

function renderExamResult(data){
  const box = document.getElementById('exResult');
  if(!box) return;
  const total = Number(data.total_score)||0;
  const max = Number(data.max_score)||100;
  const obj = Number(data.objective_score)||0;
  const subj = Number(data.subjective_score)||0;
  const pct = Math.min(100, Math.round(total/(max||100)*100));
  const unscored = Number(data.unscored_count)||0;
  const items = Array.isArray(data.items) ? data.items : [];
  // 显式展示后端 unscored_items：换算成题号，温和不施压；后端未给该字段时按 items 推导
  const unscoredIds = Array.isArray(data.unscored_items) ? data.unscored_items : [];
  const unscoredNo = items
    .map((it,i)=>({it,i}))
    .filter(x=>!x.it.scored && (!unscoredIds.length || unscoredIds.indexOf(x.it.id)>=0))
    .map(x=>'第 '+(x.i+1)+' 题')
    .join('、');
  const itemCards = items.map((it,i)=>{
    const scored = !!it.scored;
    const scoreTxt = scored
      ? (Number(it.score)||0)+' / '+(Number(it.max_score)||0)+' 分'
      : '暂未评分';
    return `<div class="ex-item ${scored?'':'unscored'}">
      <div class="ex-item-top">
        <span class="ex-item-no">第 ${i+1} 题</span>
        <span class="ex-item-type">${esc(examTypeName(it.type))}</span>
        <span class="ex-item-score ${scored?'':'na'}">${scoreTxt}</span>
      </div>
      <div class="ex-item-feedback">${esc(it.feedback_zh||'')}</div>
    </div>`;
  }).join('');
  box.innerHTML = `
    <div class="card ex-result-card">
      <div class="ex-result-head">
        <div class="ex-result-emoji">🌿</div>
        <div class="ex-result-label">这次练习的参考成绩</div>
        <div class="ex-total"><b>${total}</b><span> / ${max} 分</span></div>
        <div class="ex-bar ex-bar-result"><i style="width:${pct}%"></i></div>
      </div>
      <div class="ex-score-grid">
        <div class="ex-score-cell"><span>客观题</span><b>${obj} 分</b></div>
        <div class="ex-score-cell"><span>书面 / 口语</span><b>${subj} 分</b></div>
      </div>
      <div class="ex-level-hint">${esc(data.level_hint||'')}</div>
      <div class="ex-summary">${esc(data.summary_zh||'')}</div>
      ${unscored>0 ? `<div class="ex-unscored-note">本次有 ${unscored} 题暂未评分，分数只作参考${unscoredNo ? '（'+unscoredNo+'）' : ''}</div>` : ''}
      <div class="ex-items-title">逐题看看</div>
      <div class="ex-items">${itemCards}</div>
      <div class="ex-disclaimer ex-disclaimer-result">${EXAM_DISCLAIMER}</div>
      <div class="ex-result-actions">
        <button class="ex-ghost" onclick="backExamToPapers()">再做一次</button>
      </div>
      <div class="ex-result-foot">想再练一遍？随时可以～ 🌱</div>
    </div>`;
}

function backExamToPapers(){
  examState.paper = null;
  examState.paperId = null;
  examState.answers = {};
  examState.index = 0;
  examState.submitting = false;
  initExam();
}
