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

// 起始对话：demo 的 me→user、bot→assistant；其余字段按契约补 null/false
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
  chatLog:[]
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
    created_at: t.created_at==null ? null : t.created_at
  };
}
function userTurn(fr){
  return { id:null, role:'user', fr:fr, cn:'（你刚说的）', recast_of:null,
    explanation:null, is_correction:false, created_at:null };
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
      <div class="bubble"><span>${esc(m.fr)}</span>${m.cn?`<span class="cn">${esc(m.cn)}</span>`:''}</div>
    </div>`;
  }
  // assistant：只有 recast_of != null 才是重述卡；绝无红叉/扣分
  if(m.recast_of!=null){
    return `<div class="recast">
      <div class="recast-card">
        <div class="tag">🌱 呀呀的自然重述</div>
        <div class="say"><span>${esc(m.fr)}</span>
          <button class="spk-btn" onclick="speak(this)" data-text="${esc(m.fr)}" title="听发音">🔊</button>
        </div>
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
        <div class="w">${esc(c.word)}</div>
        <div class="mean">${esc(c.meaning)}<small>${esc(c.pos||'')}</small></div>
        <button class="spk" onclick="speak(this)" data-text="${esc(c.word)}" title="听发音">🔊</button>
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
    id:null, role:'assistant', fr:data.ai_text||'', cn:data._cn||'',
    recast_of:data.recast_of==null?null:data.recast_of,
    explanation:data.explanation==null?null:data.explanation,
    is_correction:isCorrection, created_at:null
  });
  renderChat();
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

async function submitUserText(text){
  text = String(text||'').trim();
  if(!text) return;
  const history = state.chatLog.slice(-10).map(normalizeTurn);
  state.chatLog.push(userTurn(text));
  renderChat();

  if(!state.online){
    applyChatResult(fallbackChat(state.currentSceneId, text));
    return;
  }
  try {
    const data = await apiRequest('/api/chat', {
      method:'POST',
      body:{ scene_id:state.currentSceneId, user_text:text, history:history }
    });
    if(data==null) return; // 业务错误，已提示
    applyChatResult(data);
    if(Array.isArray(data.new_words)&&data.new_words.length){
      let added = false;
      data.new_words.forEach(w=>{
        if(w && !state.cards.some(c=>c.word===w.word)){ state.cards.unshift(w); added=true; }
      });
      if(added){ renderVocab(); renderLedger(); }
    }
  }catch(e){
    setOffline();
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
function speak(btn){
  const text = btn.getAttribute('data-text')||'';
  if(!('speechSynthesis' in window)){ notify('当前浏览器不支持语音朗读'); return; }
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = 'fr-FR';
  u.rate = 0.95;
  window.speechSynthesis.speak(u);
}

const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognizer = null, recording = false;

function toggleMic(){
  if(!SpeechRec){
    setMicStatus('当前浏览器不支持语音识别，请用 Chrome / Edge，或直接在输入框打字。');
    notify('这个浏览器不支持语音识别，可以直接打字哦');
    return;
  }
  if(recording){ if(recognizer) recognizer.stop(); return; }

  recognizer = new SpeechRec();
  recognizer.lang = 'fr-FR';
  recognizer.interimResults = false;
  recognizer.continuous = false;

  recognizer.onstart = ()=>{
    recording = true;
    document.getElementById('micBtn').classList.add('rec');
    setMicStatus('🎙 在听了，请说法语…（再点麦克风可结束）');
  };
  recognizer.onresult = (e)=>{
    const text = e.results[0][0].transcript.trim();
    if(text){
      document.getElementById('userInput').value = text;
      submitUserText(text);
    }
  };
  recognizer.onerror = (e)=>{
    let msg = '';
    switch(e.error){
      case 'not-allowed':
      case 'service-not-allowed':
        msg = '麦克风权限被拒绝。请点浏览器地址栏左侧的锁图标允许麦克风，或直接在下方打字。'; break;
      case 'no-speech':
        msg = '没听到声音，再点一次麦克风试试，也可以直接打字。'; break;
      case 'network':
        msg = '语音服务连不上啦：浏览器自带的法语识别依赖境外服务，国内网络通常无法访问。请暂时用打字，输入框已经为你准备好了。'; break;
      case 'aborted':
        msg = '识别已取消。'; break;
      default:
        msg = '识别出错（'+e.error+'），请直接打字重试。';
    }
    setMicStatus(msg);
    const input = document.getElementById('userInput');
    if(input) input.focus();
  };
  recognizer.onend = ()=>{
    recording = false;
    document.getElementById('micBtn').classList.remove('rec');
  };
  try { recognizer.start(); }
  catch(err){ setMicStatus('无法启动语音识别：'+err.message+'（可直接打字）'); }
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
  const firstId = state.scenes[0].id;
  await selectScene(firstId);
}

init();
