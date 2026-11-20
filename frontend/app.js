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
  id:1, username:'YU', cefr_level:'A2', target_level:'B2', xp:0,
  streak_days:0, last_active_date:TODAY,
  // TASK-0047：离线兜底也必须全 0——宁可显示"刚开始"，不拿假数字冒充
  stats:{ due_cards_count:0, new_words_week:0, mastered_count:0,
    accuracy:0, total_cards:0, dialogue_count:0, review_count:0 }
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
    reportedIds:[],     // TASK-0052：本会话已上报"读完"的 id（防重复 POST；服务端另有 UNIQUE 幂等）
    _dwellTimer:null,   // 短文（不溢出）的 8 秒停留计时器
    available:true,     // 阅读 TTS 端点可用（失败降级）
    loaded:false        // 阅读页是否已初始化加载过
  },
  skillProfile:null,    // TASK-0055 水平画像（GET /api/profile/skills，懒计算）
  achievements:null,    // TASK-0058 成就（GET /api/achievements，懒计算 + 灰态）
  roadmap:null,         // TASK-0059 面客建设里程图（GET /api/roadmap，后端常量）
  retention:null,       // TASK-0060 留存激励（GET /api/retention，纯读聚合 + 温和文案）
  feedbackCats:null,    // TASK-0062 反馈方向（GET /api/feedback/categories，服务端常量）
  pron:{
    summaries:[],       // GET /rules 摘要四字段（小册子索引用）
    detailsLoaded:false,// 是否已并发拉全详情、建好索引
    ruleById:new Map(), // rule_id -> RuleDetail
    wordToRules:new Map(), // 归一化 word_fr -> [rule_id]
    progress:null,      // GET /progress 的 ProgressView
    progressFetched:false,
    available:true,     // 规则端点是否可用（失败则词卡不显示读音入口）
    bookOpen:false
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
let pronPopEl = null;
function closePronPopover(){
  if(pronPopEl){ pronPopEl.remove(); pronPopEl = null; }
  document.removeEventListener('click', pronPopOutside, true);
}
function pronPopOutside(e){
  if(pronPopEl && !pronPopEl.contains(e.target)) closePronPopover();
}
function openWordPopover(tokEl){
  if(pronPopEl && pronPopEl._anchor === tokEl){ closePronPopover(); return; } // 再点同一词 = 收起
  closePronPopover();
  const word = tokEl.getAttribute('data-word') || '';
  const ids = findRulesForCard(word);
  const r0 = ids.map(id=>state.pron.ruleById.get(id)).find(x=>x && pronFocusLabel(x))
    || (ids.length ? state.pron.ruleById.get(ids[0]) : null);
  const el = document.createElement('div');
  el.className = 'pron-pop';
  el._anchor = tokEl;
  el.dataset.word = word;
  el.dataset.ruleIds = JSON.stringify(ids);
  el.dataset.ruleId = r0 ? r0.id : '';
  const exHtml = (r0 && Array.isArray(r0.examples)) ? r0.examples.slice(0,2).map(e =>
    `<span class="lk-mini-ex">${esc(e.word_fr)} <span class="lk-mini-ipa">${esc(e.phonetic||'')}</span></span>`).join('') : '';
  el.innerHTML = `
    <button class="pron-pop-close" onclick="event.stopPropagation();closePronPopover()" title="关闭">×</button>
    <div class="pron-pop-word"><b>${esc(word)}</b>
      <button class="v-mini-btn" onclick="event.stopPropagation();speak(this)" data-text="${esc(word)}">🔊 听发音</button>
    </div>
    ${r0 ? `
      <div class="pron-pop-rule">${esc(r0.title)}</div>
      <div class="pron-pop-desc">${esc(r0.description_zh||'')}</div>
      ${exHtml?`<div class="pron-pop-exs">${exHtml}</div>`:''}
      <button class="pron-pop-more" onclick="event.stopPropagation();openFullFromPop(this)">完整讲解 + 跟读 →</button>`
    : `<div class="pron-pop-desc">这个词暂无规则讲解，先听标准发音吧～</div>`}`;
  document.body.appendChild(el);
  // 定位：贴 token 下沿，视口内钳制，放不下翻上方
  const rect = tokEl.getBoundingClientRect();
  el.style.visibility = 'hidden';
  requestAnimationFrame(()=>{
    const w = el.offsetWidth, h = el.offsetHeight;
    let x = rect.left + rect.width/2 - w/2;
    x = Math.max(8, Math.min(x, window.innerWidth - w - 8));
    let y = rect.bottom + 6;
    if (y + h + 8 > window.innerHeight) y = Math.max(8, rect.top - h - 6);
    el.style.left = x+'px'; el.style.top = y+'px';
    el.style.visibility = '';
  });
  pronPopEl = el;
  setTimeout(()=>document.addEventListener('click', pronPopOutside, true), 0);
}
function openFullFromPop(btn){
  const pop = btn.closest('.pron-pop');
  if(!pop) return;
  let ids = [];
  try{ ids = JSON.parse(pop.dataset.ruleIds || '[]'); }catch(e){ ids = []; }
  const rid = pop.dataset.ruleId || (ids[0] || '');
  const word = pop.dataset.word || '';
  closePronPopover();
  if(rid && state.pron.ruleById.get(rid)) openPronCard(rid, ids.length?ids:[rid], word);
  else openPronCardForNoRule(word);
}

// TASK-0032：连读内嵌展开（手风琴）——取代模态连读卡，学习动作原地发生
function toggleLinkingInline(btn){
  // TASK-0034/0038：容器可为生词卡 .v、对话气泡 .bubble/重述卡 .say、阅读逐句 .rbubble、阅读整篇 .whole-fr
  const v = btn.closest('.v') || btn.closest('.bubble') || btn.closest('.say') || btn.closest('.rbubble') || btn.closest('.whole-fr');
  if(!v) return;
  const existing = v.querySelector(':scope > .lk-inline');
  if(existing){
    existing.remove();
    btn.textContent = btn.dataset.closedLabel || '🔗 连读';
    return;
  }
  if(!state.pron.detailsLoaded) loadPronDetails();
  const text = btn.dataset.text || '';
  const pairs = detectLinkingPairs(text);
  const pairsHTML = pairs.length
    ? pairs.map(p => {
        const label = p.type==='liaison' ? '联诵' : '连音';
        return `<div class="lk-pair-row"><button class="lk-pair-say" onclick="speak(this)" data-text="${esc(p.a+' '+p.b)}" title="只听这一处：${esc(p.a+' '+p.b)}">🔊</button><span class="lk-pair-words">${esc(p.a)} + ${esc(p.b)}</span><span class="lk-pair-type ${p.type==='liaison'?'li':'en'}">${label}</span></div>`;
      }).join('')
    : '<div class="lk-pair-none">这句没检测到明显的连读位置，点外面句子的 🔊 听整句感受～</div>';
  const ruleMini = rid => {
    const r = state.pron.ruleById.get(rid);
    if(!r) return '';
    const ex = (Array.isArray(r.examples)?r.examples:[]).slice(0,2).map(e =>
      `<div class="lk-mini-ex"><button class="lk-pair-say" onclick="speak(this)" data-text="${esc(e.word_fr)}" title="只听这个词：${esc(e.word_fr)}">🔊</button><span class="lk-mini-ex-body"><span class="lk-mini-ex-w">${esc(e.word_fr)}</span><span class="lk-mini-ipa">${esc(e.phonetic||'')}</span></span></div>`).join('');
    return `<div class="lk-rule-mini"><div class="lk-mini-title">${esc(r.title)}</div><div class="lk-mini-desc">${esc(r.description_zh||'')}</div>${ex?`<div class="lk-mini-exs">${ex}</div>`:''}</div>`;
  };
  // TASK-0039：块内不再重复整句与整句示范——正文句本身可逐词点击、句旁已有 🔊
  const block = document.createElement('div');
  block.className = 'lk-inline';
  block.innerHTML = `
    <div class="lk-sub">连读位置提示（从宽，仅供留意）</div>
    ${pairsHTML}
    ${ruleMini('ph_final_03')}${ruleMini('ph_final_04')}`;
  const row = btn.closest('.v-ex') || btn.parentElement;
  if(row && row.parentNode === v) row.insertAdjacentElement('afterend', block);
  else v.appendChild(block);
  btn.dataset.closedLabel = btn.textContent;
  btn.textContent = '🔗 收起连读';
}
/* ============================================================
   P1 跟读闭环（TASK-0031）：🎙 独立录音 → ASR 近似比对 → 三档温和反馈
   红线：从宽不判错；C 档永远温和；自评兜底；不显示/不存储转写文本
   ============================================================ */
const pronShadowRec = {rec:null, stream:null, chunks:[], recording:false, timer:null, startTs:0, rule:null};
// 六档评分纯函数（契约口径按序短路）；ipaEq：易混音位记 0 距离
const SHADOW_R_HIGH = 0.8;
const IPA_CONFUSABLE_PAIRS = [['ɛ̃','œ̃'], ['j','i']];
function ipaEq(x,y){ if(x===y) return true; return IPA_CONFUSABLE_PAIRS.some(g=>g.includes(x)&&g.includes(y)); }
function levDistance(a,b,eq){
  const m=a.length, n=b.length;
  if(!m) return n; if(!n) return m;
  let prev = Array.from({length:n+1}, (_,j)=>j);
  for(let i=1;i<=m;i++){
    const cur=[i];
    for(let j=1;j<=n;j++){
      const cost = eq ? (eq(a[i-1],b[j-1])?0:1) : (a[i-1]===b[j-1]?0:1);
      cur[j] = Math.min(prev[j]+1, cur[j-1]+1, prev[j-1]+cost);
    }
    prev = cur;
  }
  return prev[n];
}
function stringSim(a,b){ const L=Math.max(a.length,b.length)||1; return 1 - levDistance(a,b,null)/L; }
function scoreShadow(target, asrText, info){
  const t = pronKey(target).replace(/[^\p{L}\p{N}\s]/gu,'').replace(/\s+/g,' ').trim();
  const a = pronKey(asrText).replace(/[^\p{L}\p{N}\s]/gu,'').replace(/\s+/g,' ').trim();
  if(info && info.lowConfidence) return {band:'UNSURE', why:'lowconf'};
  if(!a) return {band:'UNSURE', why:'empty'};
  if(info && info.durationMs!=null && info.durationMs<2000) return {band:'UNSURE', why:'short'};
  if(a===t) return {band:'EXACT'};
  const sim = stringSim(a,t);
  if(sim >= SHADOW_R_HIGH) return {band:'CLOSE', sim};
  const map = (info && info.ipaMap) || new Map();
  const ti = map.get(t);
  if(ti){
    let best = Infinity;
    a.split(/\s+/).forEach(w=>{ const wi = map.get(w); if(wi){ const d = levDistance(ti, wi, ipaEq); if(d<best) best=d; } });
    if(best!==Infinity){
      if(best<=1) return {band:'CLOSE_SOUND', dist:best};
      return {band:'RETRY', dist:best};
    }
  }
  return {band:'UNSURE', why:'nodict', sim};
}
// 六档 → 用户可见三档话术（PM 口径，绝不判错）
function shadowFeedback(band){
  switch(band){
    case 'EXACT':      return {cls:'ok',     msg:'听起来很接近啦，这个音你拿捏得不错～', self:false};
    case 'CLOSE':      return {cls:'ok',     msg:'差不多啦，中间那个音可以再饱满一点，再听一遍示范就好～', self:false};
    case 'CLOSE_SOUND':return {cls:'ok',     msg:'读得挺像的！再听一遍示范顺一顺就更棒啦～', self:false};
    case 'RETRY':      return {cls:'retry',  msg:'想再听一遍示范吗？再试一次就好～', self:true};
    default:           return {cls:'unsure', msg:'这次没太听清，可能是收音的小问题，我们再来一次～', self:true};
  }
}
function pronShadowSection(r){
  if(!r || r.shadow_mode==='syllable'){
    return '<div class="pron-shadow-note">单音跟读只作口型练习：听示范，跟着模仿就好，不打分～</div>';
  }
  return `
    <div class="pron-shadow-target">跟读目标：<b>${esc(r.shadow_text_fr||'')}</b></div>
    <div class="pron-shadow-row">
      <button id="pronShadowBtn" class="pron-shadow-btn" onclick="toggleShadowRecord()">🎙 开始跟读</button>
      <div id="pronShadowStatus" class="pron-shadow-status">先听一遍示范，再开始跟读～</div>
    </div>
    <div id="pronShadowFeedback" class="pron-shadow-feedback"></div>
    <div id="pronShadowActions" class="pron-shadow-actions"></div>`;
}
function pronShadowReset(){
  if(pronShadowRec.recording && pronShadowRec.rec && pronShadowRec.rec.state!=='inactive'){
    try{ pronShadowRec.rec.stop(); }catch(e){}
  }
  if(pronShadowRec.timer) clearTimeout(pronShadowRec.timer);
  if(pronShadowRec.stream) pronShadowRec.stream.getTracks().forEach(t=>t.stop());
  pronShadowRec.rec=null; pronShadowRec.stream=null; pronShadowRec.chunks=[];
  pronShadowRec.recording=false; pronShadowRec.timer=null;
}
async function toggleShadowRecord(){
  const btn = document.getElementById('pronShadowBtn');
  if(pronShadowRec.recording){
    if(pronShadowRec.rec && pronShadowRec.rec.state!=='inactive') pronShadowRec.rec.stop();
    return;
  }
  if(!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder){
    notify('这个浏览器不支持录音，多听几遍示范也一样在进步～');
    return;
  }
  const rule = state.pron.ruleById.get(pronCurrentRuleId);
  if(!rule) return;
  if(!(await checkAsr())){
    const fb = document.getElementById('pronShadowFeedback');
    if(fb) fb.innerHTML = '<span class="pf-unsure">本地语音服务没就绪，跟读先跳过，多听几遍示范也一样棒～</span>';
    return;
  }
  let stream;
  try{ stream = await navigator.mediaDevices.getUserMedia({audio:true}); }
  catch(e){ notify('没拿到麦克风权限，稍后再试也可以～'); return; }
  try{
    const mime = pickMimeType();
    const rec = new MediaRecorder(stream, mime?{mimeType:mime}:undefined);
    pronShadowRec.rec = rec; pronShadowRec.stream = stream;
    pronShadowRec.chunks = []; pronShadowRec.recording = true;
    pronShadowRec.rule = rule; pronShadowRec.startTs = Date.now();
    if(btn){ btn.classList.add('rec'); btn.textContent='⏹ 结束跟读'; }
    const st = document.getElementById('pronShadowStatus');
    if(st) st.textContent = '🎙 在听，跟着读吧…最长 10 秒';
    rec.ondataavailable = (e)=>{ if(e.data && e.data.size) pronShadowRec.chunks.push(e.data); };
    rec.onstop = async ()=>{
      pronShadowRec.recording = false;
      const dur = Date.now() - pronShadowRec.startTs;
      if(btn){ btn.classList.remove('rec'); btn.textContent='🎙 再来一次'; }
      stream.getTracks().forEach(t=>t.stop());
      clearTimeout(pronShadowRec.timer);
      const blob = new Blob(pronShadowRec.chunks, {type: rec.mimeType || 'audio/webm'});
      if(!blob.size){
        const s2 = document.getElementById('pronShadowStatus');
        if(s2) s2.textContent = '没录到声音，再试一次～';
        return;
      }
      await transcribeShadowAudio(blob, pronShadowRec.rule, dur);
    };
    rec.start();
    pronShadowRec.timer = setTimeout(()=>{ if(pronShadowRec.recording && rec.state!=='inactive') rec.stop(); }, 10000);
  }catch(e){
    pronShadowReset();
    notify('录音启动没成功，稍后再试也可以～');
  }
}
async function transcribeShadowAudio(blob, rule, durMs){
  const st = document.getElementById('pronShadowStatus');
  if(st && pronCurrentRuleId===rule.id) st.textContent = '正在听你的发音…';
  const ext = (blob.type.includes('mp4')?'.m4a':blob.type.includes('ogg')?'.ogg':'.webm');
  let data = null;
  try{
    const fd = new FormData();
    fd.append('file', blob, 'shadow'+ext);
    fd.append('language', 'fr');
    // 热词偏置：目标词 + 同规则例词（独立链路，绝不进聊天流）
    const hints = [rule.shadow_text_fr].concat((rule.examples||[]).map(e=>e.word_fr)).join(' ');
    fd.append('hints', hints.slice(0,200));
    fd.append('context', '');
    const resp = await fetch('/api/asr/transcribe', {method:'POST', body:fd});
    data = await resp.json();
  }catch(e){ data = null; }
  // 练习计数：开了口就 +1（服务端累加，不改已学状态；失败不打断）
  try{
    const item = await apiRequest('/api/pronunciation/progress', {method:'POST', body:{rule_id: rule.id}});
    if(item) applyPronProgressItem(item);
  }catch(e){}
  const fbEl = document.getElementById('pronShadowFeedback');
  const actEl = document.getElementById('pronShadowActions');
  if(pronCurrentRuleId!==rule.id) return; // 用户已切走：不写旧反馈
  let band = 'UNSURE';
  if(data && typeof data.code==='number' && data.code===0 && data.data && data.data.text){
    const res = scoreShadow(rule.shadow_text_fr, String(data.data.text),
      {lowConfidence: !!data.data.low_confidence, durationMs: durMs, ipaMap: state.pron.ipaMap});
    band = res.band;
  }
  const fb = shadowFeedback(band);
  if(fbEl) fbEl.innerHTML = `<span class="pf-${fb.cls}">${esc(fb.msg)}</span>`;
  if(actEl) actEl.innerHTML = fb.self
    ? '<button class="pron-shadow-self" onclick="shadowSelfAssess()">我觉得读对了</button>'
    : '';
}
async function shadowSelfAssess(){
  if(!pronCurrentRuleId) return;
  const item = await apiRequest('/api/pronunciation/progress',
    {method:'POST', body:{rule_id: pronCurrentRuleId, stage:'confident', self_assessed:true}});
  if(item){ applyPronProgressItem(item); updatePronCardProgressUI(); }
  notify('记下啦，这条你越来越熟了～');
  const actEl = document.getElementById('pronShadowActions');
  if(actEl) actEl.innerHTML = '';
}

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

// TASK-0057 到期调度：在线拉 GET /api/review/due 的到期队列，离线/失败回退本地全量卡
async function openReview(){
  const overlay = document.getElementById('reviewOverlay');
  if(state.online){
    try {
      const res = await apiRequest('/api/review/due');
      if(res==null) return; // 业务错误已提示
      reviewQueue = Array.isArray(res.items) ? res.items.slice() : [];
      if(!reviewQueue.length){
        // 温和空态：不弹红叉、不催促，给一个「看看全部词卡」的软出口
        document.getElementById('reviewContent').innerHTML =
          `<div class="review-done"><div class="done-emoji">🌿</div>
            <h3>今天没有想见你的词</h3>
            <p>都记得挺好的，随时想复习再来看看就好～</p>
            <button class="review-entry" onclick="closeReview()">好呀</button></div>`;
        overlay.classList.remove('hidden');
        return;
      }
    }catch(e){
      setOffline();
      reviewQueue = state.cards.slice();
    }
  }else{
    reviewQueue = state.cards.slice();
  }
  if(!reviewQueue.length){ notify('还没有生词卡可以复习'); return; }
  reviewIdx = 0;
  overlay.classList.remove('hidden');
  renderReviewCard();
}
function closeReview(){ document.getElementById('reviewOverlay').classList.add('hidden'); }

function renderReviewCard(){
  const box = document.getElementById('reviewContent');
  if(reviewIdx>=reviewQueue.length){
    box.innerHTML = `<div class="review-done"><div class="done-emoji">🌿</div>
      <h3>今日复习完成</h3><p>温柔地记住了 ${reviewQueue.length} 张卡片，真棒！</p>
      <button class="review-entry" onclick="closeReview()">完成</button></div>`;
    // TASK-0057 复习完成后刷新真实统计，账本「今日想见你」/成长页数字即时归零
    if(state.online){
      apiRequest('/api/profile').then(p=>{
        if(!p) return;
        state.profile = p; renderLedger();
        try { if(typeof renderGrowth==='function') renderGrowth(); } catch(e){}
      }).catch(()=>{});
    }
    return;
  }
  const c = reviewQueue[reviewIdx];
  box.innerHTML = `
    <div class="rv-progress">${reviewIdx+1} / ${reviewQueue.length}</div>
    <div class="rv-word">${esc(c.word)}<button class="spk" onclick="speak(this)" data-text="${esc(c.word)}" title="听发音">🔊</button></div>
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
  // 六个视图：chat / read / assessment / exam / growth / roadmap；其他值一律按 chat 处理（保留原默认行为）
  const view = (name==='read'||name==='assessment'||name==='exam'||name==='growth'||name==='roadmap') ? name : 'chat';
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
        <span class="fr">${sentenceTokensHTML(l.fr)}<button class="rplay" onclick="speak(this)" data-text="${esc(l.fr)}" title="听这句">🔊</button>${chatLinkBtnHTML(l.fr)}</span>
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
  document.addEventListener('keydown', e=>{
    if(e.key!=='Escape') return;
    closeReview();
    closePronCard();
    closePronBook();
    closeRetention();
    closeFeedback();
  });

  // TASK-0052：阅读完成落库——内容超一屏时，滚动到文末自动标记（幂等）
  const readBody = document.getElementById('readBody');
  if(readBody){
    readBody.addEventListener('scroll', function(){
      if(!state.read.currentId) return;
      if(this.scrollHeight <= this.clientHeight + 24) return; // 短文走停留计时，不靠滚动
      if(this.scrollTop + this.clientHeight >= this.scrollHeight - 24){
        markReadComplete(state.read.currentId);
      }
    }, {passive:true});
  }

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
    // TASK-0060 留存数据单独拉取（增益功能，失败不拖垮首屏/不误进离线）
    try { const rt = await apiRequest('/api/retention'); if(rt) state.retention = rt; } catch(e){}
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
  // 读音规则 P0：静默加载（失败只降级读音入口，不影响上面已完成的界面）
  loadPronData();
  // TASK-0053：首次引导（localStorage 一次性，每步可跳过）
  const obPending = !onboardingSeen();
  maybeShowOnboarding();
  // TASK-0060：留存温和浮层（onboarding 未完成时不抢弹；有「接着上次」才弹）
  if(!obPending) maybeShowRetention();
}

function onboardingSeen(){
  try{ return localStorage.getItem(ONBOARDING_KEY)==='1'; }catch(e){ return false; }
}

/* ============================================================
   TASK-0053 首次引导（方案 F：≤3 步、每步可跳过、零强制词）
   localStorage 只存 UI 展示标志，不存学习进度
   ============================================================ */
const ONBOARDING_KEY = 'yaya_onboarding_seen';

function maybeShowOnboarding(){
  try{ if(localStorage.getItem(ONBOARDING_KEY)==='1') return; }catch(e){}
  showOnboardingStep(1);
}

function showOnboardingStep(n){
  const ov = document.getElementById('obOverlay');
  const c = document.getElementById('obContent');
  if(!ov || !c) return;
  const dots = [1,2,3].map(i=>`<i class="${i===n?'on':''}"></i>`).join('');
  let html = '';
  if(n===1){
    html = `
      <div class="ob-emoji">🌱</div>
      <div class="ob-title">你好呀，我是呀呀</div>
      <p class="ob-desc">像婴儿一样，自然地学会法语。<br>这里没有红叉，说错了也没关系——我会顺着你的话轻轻接下去。</p>
      <div class="ob-go">
        <button class="ob-btn primary" onclick="showOnboardingStep(2)">开始慢慢学</button>
        <button class="ob-btn" onclick="closeOnboarding(false)">先随便逛逛</button>
      </div>
      <div class="ob-dots">${dots}</div>`;
  }else if(n===2){
    html = `
      <div class="ob-emoji">🎯</div>
      <div class="ob-title">先看看你现在在哪一级</div>
      <p class="ob-desc">12 道小题，几分钟就好。<br>也可以先去对话和阅读里逛逛，随时回来测都行。</p>
      <div class="ob-go">
        <button class="ob-btn primary" onclick="goOnboardingTarget('assessment')">去测一测</button>
        <button class="ob-btn" onclick="showOnboardingStep(3)">先不了</button>
      </div>
      <div class="ob-dots">${dots}</div>`;
  }else{
    html = `
      <div class="ob-emoji">🧭</div>
      <div class="ob-title">三个入口，随时都在</div>
      <div class="ob-entries">
        <div class="ob-entry"><b>💬 对话陪练</b>像聊天一样开口说</div>
        <div class="ob-entry"><b>📖 分级阅读</b>读不懂有中文小字</div>
        <div class="ob-entry"><b>🌱 我的成长</b>每一步都被记下</div>
      </div>
      <div class="ob-go"><button class="ob-btn primary" onclick="closeOnboarding(false)">好，开始吧</button></div>`;
  }
  c.innerHTML = html;
  ov.classList.remove('hidden');
}

function closeOnboarding(){
  // 任何关闭路径（完成/跳过/点背景）都标记 seen：引导只出现一次，跳过也算看过
  const ov = document.getElementById('obOverlay');
  if(ov) ov.classList.add('hidden');
  try{ localStorage.setItem(ONBOARDING_KEY,'1'); }catch(e){}
}

// TASK-0054：手动重温引导（页脚入口）——直接从第 1 步重新走；关闭时会重新标记 seen，与自动弹出逻辑互不影响
function reopenOnboarding(){
  showOnboardingStep(1);
}

function goOnboardingTarget(view){
  // 去定级即视为走完引导；定级页随时可以切到其他入口
  try{ localStorage.setItem(ONBOARDING_KEY,'1'); }catch(e){}
  const ov = document.getElementById('obOverlay');
  if(ov) ov.classList.add('hidden');
  switchView(view);
}

/* ============================================================
   TASK-0060 留存温和浮层：打开即弹「接着上次」钩子（UX_PROGRESS_PLAN §D）
   仅本地 UI 标志（当天关闭不再弹），不落库、不写入学习进度。
   onboarding 未完成时不抢弹；无 last_read 时不弹；文案零负面词。
   ============================================================ */
const RETENTION_KEY = 'yaya_retention_dismissed';

function maybeShowRetention(){
  const rt = state.retention;
  if(!rt || !rt.continue_last) return;
  // 当天已关闭过 → 不再弹（按 UTC 日期，与后端 now_iso 一致）
  const today = new Date().toISOString().slice(0,10);
  try{ if(localStorage.getItem(RETENTION_KEY)===today) return; }catch(e){}
  const ov = document.getElementById('rtOverlay');
  const c = document.getElementById('rtContent');
  if(!ov || !c) return;
  const last = rt.continue_last;
  const level = esc(last.cefr_level||'');
  const title = esc(String(last.title||'').slice(0,20));
  c.innerHTML = `
    <div class="rt-emoji">📖</div>
    <div class="rt-title">又见面啦，欢迎回来</div>
    <p class="rt-desc">上次你读到 ${level?('<b>'+level+'</b> 的 '):''}《${title}》，<br>要不要接着读下去？慢慢来就好 🌱</p>
    <div class="rt-go">
      <button class="rt-btn primary" onclick="retentionContinue()">接着读</button>
      <button class="rt-btn" onclick="closeRetention()">稍后再说</button>
    </div>`;
  ov.classList.remove('hidden');
}

function closeRetention(){
  const ov = document.getElementById('rtOverlay');
  if(ov) ov.classList.add('hidden');
  const today = new Date().toISOString().slice(0,10);
  try{ localStorage.setItem(RETENTION_KEY, today); }catch(e){}
}

function retentionContinue(){
  closeRetention();
  switchView('read');
  const last = state.retention && state.retention.continue_last;
  if(last && last.text_id && typeof openReadText==='function'){
    try{ openReadText(last.text_id); }catch(e){}
  }
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

/* ============================================================
   零基础读音规则学习 P0 —— 融入式（不新增第 5 个 Tab）
   端点：GET /api/pronunciation/rules（摘要四字段）
         GET /api/pronunciation/rules/{id}（详情，首次并发拉全部建索引）
         GET /api/pronunciation/progress（ProgressView）
         POST /api/pronunciation/progress {rule_id, stage, self_assessed?}
   约束：复用 speak()/TTS；不碰 ASR 链路（buildAsrHints/transcribeExamAudio 等）；
         P0 无 🎙 跟读、无评分；practice_count 由服务端 +1，前端不传。
   ============================================================ */
const PRON_STAGE_LABEL = { seen:'已见过', learned:'已学会', confident:'能自己读' };
const PRON_GROUP_ORDER = ['字母表与读音概念','基础元音','基础辅音','元音字母组合','辅音字母组合','鼻化元音','词末辅音规则','高频例外与易错'];
const PRON_TIP_KEY = 'pron_tip_shown'; // localStorage 仅存这个 UI 展示标记，不存学习进度
// 词卡短语里常见的功能词/冠词，建映射时跳过，避免 "à"/"la" 之类误命中
const PRON_SKIP_TOKENS = new Set(['le','la','les','un','une','des','du','de','d','l','s','a','y','et','ou','en','au','aux','ce','cet','cette','mon','ma','mes','ton','ta','tes','son','sa','ses','dans','sur','avec','pour','par']);

// 归一化：小写 + œ→oe + 去重音 + 去省文符，让 maison / Maison / cœur 命中同一条规则
function pronKey(s){
  return String(s==null?'':s).toLowerCase()
    .replace(/œ/g,'oe')
    .normalize('NFD').replace(/[\u0300-\u036f]/g,'')
    .replace(/['’`]/g,'').trim();
}
// P1 跟读：IPA 串归一化（去斜杠/音节点/长短符/重音符），只留音素序列
function normIpa(p){
  return String(p==null?'':p).replace(/[/.ˈˌː:]/g,'').trim();
}

// 用详情列表建三个进程内 Map：rule_id -> 详情；word_fr -> [rule_id]；pattern 正则索引
function buildPronIndex(details){
  const byId = new Map();
  const w2r = new Map();
  const patternRules = []; // [{pattern: RegExp, ruleId: string}]
  const ipaMap = new Map(); // P1 跟读：word_fr -> 音素序列（去 /、音节点、长短符）
  (details||[]).forEach(r=>{
    if(!r || !r.id) return;
    byId.set(r.id, r);
    // 例词精确索引 + IPA 词典
    (Array.isArray(r.examples)?r.examples:[]).forEach(ex=>{
      const k = pronKey(ex && ex.word_fr);
      const ipa = normIpa(ex && ex.phonetic);
      if(k && ipa && !ipaMap.has(k)) ipaMap.set(k, ipa);
      if(!k) return;
      let arr = w2r.get(k);
      if(!arr){ arr = []; w2r.set(k, arr); }
      if(arr.indexOf(r.id)<0) arr.push(r.id);
    });
    // pattern 正则索引（契约 v1.1 锚定语法）：^词首 / $词尾 / ^..$全词 / 普通子串
    if(Array.isArray(r.patterns)){
      r.patterns.forEach(pat=>{
        if(typeof pat!=='string' || !pat.trim()) return;
        let p = pat.trim(), head = false, tail = false;
        if(p.startsWith('^')){ head = true; p = p.slice(1); }
        if(p.endsWith('$')){ tail = true; p = p.slice(0,-1); }
        if(!p) return;
        const body = p.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
        try{
          // spec：全词锚 3 > 部分锚 2 > 普通子串 1；同级 pattern 越长越具体
          const spec = (head && tail) ? 3 : (head || tail) ? 2 : 1;
          patternRules.push({pattern: new RegExp((head?'^':'')+body+(tail?'$':''), 'i'), ruleId: r.id, spec, len: p.length, order: patternRules.length});
        }catch(e){/* 编译失败忽略 */}
      });
    }
  });
  state.pron.ruleById = byId;
  state.pron.wordToRules = w2r;
  // 匹配优先级：全词锚 > 部分锚 > 普通子串；同级越长的组合越具体、越先命中
  patternRules.sort((a,b)=> (b.spec-a.spec) || (b.len-a.len) || (a.order-b.order));
  state.pron.patternRules = patternRules;
  state.pron.ipaMap = ipaMap;
  state.pron.detailsLoaded = true;
}

// 按钮展示音节（契约 v1.1）：focus 优先，兜底 patterns 去锚定符后连接；无则裸按钮
function pronFocusLabel(r){
  if(!r) return '';
  if(typeof r.focus==='string' && r.focus.trim()) return r.focus.trim();
  if(Array.isArray(r.patterns)){
    const parts = r.patterns.filter(p=>typeof p==='string' && p.trim())
      .map(p=>String(p).trim().replace(/^\^/,'').replace(/\$$/,''));
    if(parts.length) return parts.join(' / ');
  }
  return '';
}
function findRulesForCard(word){
  if(!state.pron.detailsLoaded) return [];
  const ids = [];
  const toks = String(word||'').split(/[\/,\s·]+/u);
  toks.forEach(tok=>{
    const k = pronKey(tok);
    if(!k || PRON_SKIP_TOKENS.has(k)) return;
    // ① 例词精确匹配（原有逻辑，优先）
    const arr = state.pron.wordToRules.get(k);
    if(arr) arr.forEach(id=>{ if(ids.indexOf(id)<0) ids.push(id); });
    // ② pattern 匹配（契约 v1.1）：归一化 + 原始小写双形态，带重音 pattern（é/â/ô）也可命中
    if(state.pron.patternRules && state.pron.patternRules.length){
      const kr = String(tok||'').toLowerCase();
      state.pron.patternRules.forEach(pr=>{
        if((pr.pattern.test(k) || pr.pattern.test(kr)) && ids.indexOf(pr.ruleId)<0) ids.push(pr.ruleId);
      });
    }
  });
  return ids;
}

/* ---------- 数据加载与缓存（失败只降级读音入口） ---------- */
async function loadPronSummaries(){
  try{
    const data = await apiRequest('/api/pronunciation/rules');
    if(data==null) return;
    state.pron.summaries = Array.isArray(data) ? data : [];
    state.pron.available = true;
  }catch(e){
    state.pron.available = false;
  }
}

async function loadPronDetails(){
  if(state.pron.detailsLoaded || !state.pron.summaries.length) return;
  const ids = state.pron.summaries.map(r=>r && r.id).filter(Boolean);
  // 首次需要时并发拉全部详情，缓存复用，不每个词都请求
  const results = await Promise.allSettled(ids.map(id=>
    apiRequest('/api/pronunciation/rules/'+encodeURIComponent(id))));
  const details = [];
  results.forEach(r=>{
    if(r.status==='fulfilled' && r.value && r.value.id) details.push(r.value);
  });
  if(details.length) buildPronIndex(details);
  else state.pron.available = false; // 详情全失败：词卡不显示读音入口，其余功能不受影响
}

async function loadPronProgress(){
  try{
    const data = await apiRequest('/api/pronunciation/progress');
    state.pron.progress = (data && typeof data==='object') ? data : null;
  }catch(e){
    state.pron.progress = null;
  }
  state.pron.progressFetched = true;
}

async function loadPronData(){
  // 摘要/详情 与 进度 并行加载，任何一种失败都不影响另一种
  await Promise.all([
    (async()=>{
      await loadPronSummaries();
      if(state.pron.available) await loadPronDetails();
    })(),
    loadPronProgress()
  ]);
  updatePronBookEntry();
  renderVocab();          // 数据到位后刷新词卡，挂上读音入口
  maybeShowPronTip();     // 可发现性①：首次提示（仅一次）
  if(state.pron.bookOpen) renderPronBook();
}

/* ---------- 可发现性：侧栏常驻 / 首次气泡 / 空态引导 ---------- */
function pronTotalRules(){
  return state.pron.summaries.length
    || Number(state.pron.progress && state.pron.progress.total_rules)
    || 39;
}
function pronLearnedTotal(){
  const p = state.pron.progress;
  if(!p) return 0;
  const n = Number(p.learned_total);
  if(Number.isFinite(n)) return n;
  return (Number(p.learned_count)||0) + (Number(p.confident_count)||0);
}
function updatePronBookEntry(){
  const el = document.getElementById('pronBookEntry');
  if(el) el.textContent = '📖 读音小册子 · 已学 '+pronLearnedTotal()+'/'+pronTotalRules();
}
function maybeShowPronTip(){
  const tip = document.getElementById('pronFirstTip');
  if(!tip || !state.pron.available) return;
  let shown = false;
  try{ shown = localStorage.getItem(PRON_TIP_KEY)==='1'; }catch(e){}
  if(!shown) tip.classList.remove('hidden');
}
function dismissPronTip(){
  const tip = document.getElementById('pronFirstTip');
  if(tip) tip.classList.add('hidden');
  try{ localStorage.setItem(PRON_TIP_KEY,'1'); }catch(e){}
}

/* ---------- 掌握微标 ---------- */
function pronStageOf(ruleId){
  const p = state.pron.progress;
  const items = p && Array.isArray(p.items) ? p.items : [];
  const it = items.find(x=>x && x.rule_id===ruleId);
  return it ? it.stage : null;
}
function pronBadgeHTML(ruleId){
  const s = pronStageOf(ruleId);
  return '<span class="pron-badge '+(s||'none')+'">'+(PRON_STAGE_LABEL[s]||'未见过')+'</span>';
}

/* ---------- 规则卡浮层（词卡与小册子共用同一组件） ---------- */
let pronCurrentRuleId = null;
let pronHitIds = [];    // 一个词命中多条规则时，列出可点选项，不自动弹
let pronHitWord = '';

function openPronCard(ruleId, hitIds, hitWord){
  const r = state.pron.ruleById.get(ruleId);
  if(!r){ notify('这条规则暂时没准备好，稍后再试～'); return; }
  pronCurrentRuleId = ruleId;
  pronHitIds = (Array.isArray(hitIds) && hitIds.length) ? hitIds.slice() : [ruleId];
  pronHitWord = hitWord || '';
  renderPronCard();
  const ov = document.getElementById('pronOverlay');
  if(ov){
    ov.classList.remove('hidden');
    ov.scrollTop = 0;
  }
  unlockAudio();
}
function openPronCardForNoRule(word){
  pronCurrentRuleId = null;
  pronHitWord = word;
  const ov = document.getElementById('pronOverlay');
  if(!ov) return;
  ov.classList.remove('hidden');
  const box = document.getElementById('pronCardContent');
  if(!box) return;
  box.innerHTML = `
    <div class="pron-card-head">
      <div class="pron-card-kicker">🎵 ${esc(word)} 的读音</div>
      <h3 class="pron-card-title">${esc(word)} 怎么读</h3>
    </div>
    <div class="pron-card-body">
      <div class="pron-desc">这条读音规则暂未收录，先听听标准发音吧～</div>
      <div class="pron-listen">
        <button class="pron-listen-btn" onclick="speak(this)" data-text="${esc(word)}">🔊 听 ${esc(word)}</button>
        <span class="pron-muted">再听一次也可以</span>
      </div>
    </div>`;
}
function switchPronCard(ruleId){
  if(!state.pron.ruleById.has(ruleId)) return;
  pronCurrentRuleId = ruleId;
  renderPronCard();
}
function closePronCard(){
  const ov = document.getElementById('pronOverlay');
  if(ov) ov.classList.add('hidden');
}

// 进度区单独抽成片段，POST 成功后只替换这一块（局部更新，不整页刷新）
function pronProgressHTML(ruleId){
  const st = pronStageOf(ruleId);
  return `
    <div class="pron-progress-line">现在的掌握度：${pronBadgeHTML(ruleId)}</div>
    <div class="pron-progress-hint">点一下记下来，慢慢来就好～</div>
    <div class="pron-stage-row">
      <button class="pron-stage-btn seen ${st==='seen'?'on':''}" onclick="postPronProgress('${esc(ruleId)}','seen')">👀 见过</button>
      <button class="pron-stage-btn learned ${st==='learned'?'on':''}" onclick="postPronProgress('${esc(ruleId)}','learned')">🌱 学会了</button>
      <button class="pron-stage-btn confident ${st==='confident'?'on':''}" onclick="postPronProgress('${esc(ruleId)}','confident')">✨ 能自己读</button>
    </div>`;
}
function renderPronCard(){
  pronShadowReset();
  const box = document.getElementById('pronCardContent');
  const r = state.pron.ruleById.get(pronCurrentRuleId);
  if(!box || !r) return;
  const hits = pronHitIds.filter(id=>state.pron.ruleById.has(id));
  const hitChips = hits.length>1
    ? '<div class="pron-rule-tabs">'+hits.map(id=>{
        const rr = state.pron.ruleById.get(id);
        return '<button class="pron-rule-tab '+(id===pronCurrentRuleId?'on':'')
          +'" onclick="switchPronCard(\''+esc(id)+'\')">'+esc((rr && rr.title)||id)+'</button>';
      }).join('')+'</div>'
    : '';
  const audio = String(r.audio_text||'');
  const examples = (Array.isArray(r.examples)?r.examples:[]).map(ex=>`
    <div class="pron-ex">
      <div class="pron-ex-top">
        <span class="pron-ex-word">${esc(ex.word_fr)}</span>
        <button class="pron-ex-spk" onclick="speak(this)" data-text="${esc(ex.word_fr)}" title="听这个词">🔊</button>
      </div>
      <div class="pron-ex-meta"><span>${esc(ex.meaning_zh||'')}</span>${ex.phonetic?'<span class="pron-ex-ipa">'+esc(ex.phonetic)+'</span>':''}</div>
      ${ex.note_zh?'<div class="pron-ex-note">'+esc(ex.note_zh)+'</div>':''}
    </div>`).join('');
  box.innerHTML = `
    <div class="pron-card-head">
      <div class="pron-card-kicker">🎵 ${esc(r.group||'读音规则')}${r.tier?'<span class="pron-tier">'+(r.tier==='starter'?'入门':'进阶')+'</span>':''}</div>
      <h3 class="pron-card-title">${esc(r.title||'')}</h3>
      ${pronHitWord?'<div class="pron-hit-note">这个词用的就是这条规则～</div>':''}
    </div>
    ${hitChips}
    <div class="pron-card-body">
      <div class="pron-desc">${esc(r.description_zh||'')}</div>
      <div class="pron-listen">
        <button class="pron-listen-btn" onclick="speak(this)" data-text="${esc(audio)}" title="听标准示范">🔊 这条规则是～先听一遍</button>
        <button class="pron-replay" onclick="speak(this)" data-text="${esc(audio)}" title="再听一次">↻ 再听一次也可以</button>
      </div>
      <div class="pron-sub-title">🎙 跟读试试</div>
      ${pronShadowSection(r)}
      <div class="pron-sub-title">看看这些词</div>
      <div class="pron-examples">${examples || '<div class="pron-muted">这条规则暂时没有例词，先听一遍示范吧～</div>'}</div>
      <div class="pron-progress-sec">${pronProgressHTML(pronCurrentRuleId)}</div>
    </div>`;
}
function updatePronCardProgressUI(){
  const sec = document.querySelector('#pronCardContent .pron-progress-sec');
  if(sec) sec.innerHTML = pronProgressHTML(pronCurrentRuleId);
}

// 服务端返回 ProgressItem：写入内存进度并重算计数（practice_count 服务端 +1，前端不传）
function applyPronProgressItem(item){
  if(!item || !item.rule_id) return;
  if(!state.pron.progress){
    state.pron.progress = { user_id:1, total_rules:pronTotalRules(),
      seen_count:0, learned_count:0, confident_count:0, learned_total:0, items:[] };
  }
  const p = state.pron.progress;
  const items = Array.isArray(p.items) ? p.items : [];
  const i = items.findIndex(x=>x && x.rule_id===item.rule_id);
  if(i>=0) items[i] = item; else items.push(item);
  p.items = items;
  p.seen_count = items.filter(x=>x.stage==='seen').length;
  p.learned_count = items.filter(x=>x.stage==='learned').length;
  p.confident_count = items.filter(x=>x.stage==='confident').length;
  p.learned_total = p.learned_count + p.confident_count; // 已学 = learned + confident，排除 seen
}

async function postPronProgress(ruleId, stage){
  const body = { rule_id:ruleId, stage:stage };
  // "能自己读"即自评达标：self_assessed 只增不减，由服务端保证
  if(stage==='confident') body.self_assessed = true;
  let res;
  try{
    res = await apiRequest('/api/pronunciation/progress', {method:'POST', body:body});
  }catch(e){
    notify('记录没成功，再试一次就好～');
    return;
  }
  if(res==null) return; // 业务错误已由 apiRequest 温和提示
  applyPronProgressItem(res);
  if(pronCurrentRuleId===ruleId) updatePronCardProgressUI();
  updatePronBookEntry();
  if(state.pron.bookOpen) renderPronBook();
  notify(stage==='confident' ? '记下啦，这条你越来越熟了～' : '记下啦，慢慢来就好～');
}

/* ---------- 小册子索引（可发现性关键：侧栏常驻入口） ---------- */
function openPronBook(){
  state.pron.bookOpen = true;
  renderPronBook();
  const ov = document.getElementById('pronBookOverlay');
  if(ov){ ov.classList.remove('hidden'); ov.scrollTop = 0; }
}
function closePronBook(){
  state.pron.bookOpen = false;
  const ov = document.getElementById('pronBookOverlay');
  if(ov) ov.classList.add('hidden');
}
function renderPronBook(){
  const box = document.getElementById('pronBookContent');
  if(!box) return;
  const head = document.getElementById('pronBookHead');
  if(head) head.textContent = '📖 读音小册子 · 已学 '+pronLearnedTotal()+'/'+pronTotalRules();
  const sums = state.pron.summaries;
  if(!sums.length){
    // 空态引导：给一个低门槛起点
    box.innerHTML = '<div class="pron-book-empty">小册子还没准备好，稍后再来看看～<br>从最常用的 ai / au 开始，三条就好～ 🌱</div>';
    return;
  }
  const groups = [];
  sums.forEach(s=>{
    const g = (s && s.group) || '其他';
    let grp = groups.find(x=>x.name===g);
    if(!grp){ grp = {name:g, items:[]}; groups.push(grp); }
    grp.items.push(s);
  });
  groups.sort((a,b)=>{
    const ia = PRON_GROUP_ORDER.indexOf(a.name), ib = PRON_GROUP_ORDER.indexOf(b.name);
    return (ia<0?99:ia) - (ib<0?99:ib);
  });
  box.innerHTML = groups.map(grp=>`
    <div class="pron-book-group">
      <div class="pron-book-group-h">${esc(grp.name)}<small>${grp.items.length} 条</small></div>
      <div class="pron-book-items">${grp.items.map(s=>`
        <div class="pron-book-item" onclick="openPronCard('${esc(s.id)}')">
          <span class="pron-book-item-title">${esc(s.title||s.id)}</span>
          ${pronBadgeHTML(s.id)}
        </div>`).join('')}</div>
    </div>`).join('');
}

/* ============================================================
   TASK-0062 使用反馈入口：页脚「💌 说说想法」→ 浮层表单（非打开即弹）
   方向单选（服务端下发，本地兜底）+ 文字建议 + 可选联系方式。
   提交写库；成功给温和确认。离线或失败不阻塞，用户可稍后再说。
   ============================================================ */
const FB_CATS_FALLBACK = [
  {code:'chat', label:'口语陪练'}, {code:'read', label:'分级阅读'},
  {code:'pron', label:'读音规则'}, {code:'review', label:'复习调度'},
  {code:'exam', label:'考级冲刺'}, {code:'other', label:'其他想说的'}
];
let fbSelectedCat = null;

async function openFeedback(){
  const ov = document.getElementById('fbOverlay');
  const c = document.getElementById('fbContent');
  if(!ov || !c) return;
  // 懒拉方向（前后端单一数据源），失败用本地兜底，不阻塞打开
  let cats = FB_CATS_FALLBACK;
  if(state.online){
    try{
      const got = await apiRequest('/api/feedback/categories');
      if(Array.isArray(got) && got.length) cats = got;
    }catch(e){}
  }
  fbSelectedCat = null;
  c.innerHTML = `
    <div class="fb-emoji">💌</div>
    <div class="fb-title">说说你的想法</div>
    <p class="fb-desc">哪一块最想我们做得更好？<br>你的想法会变成下一个版本 🌱</p>
    <div class="fb-label">最想优化哪一块</div>
    <div class="fb-cats">${cats.map((x,i)=>`
      <button type="button" class="fb-cat${i===0?' on':''}" data-cat="${esc(x.code)}"
        onclick="selectFbCat(this)">${esc(x.label)}</button>`).join('')}</div>
    <div class="fb-label">具体建议</div>
    <textarea id="fbText" class="fb-text" maxlength="1000" rows="4"
      placeholder="想多一点例句？想要某个场景？都告诉我吧～"></textarea>
    <input id="fbContact" class="fb-contact" maxlength="200"
      placeholder="邮箱或微信（选填，方便我们找到你）">
    <div class="fb-actions">
      <button class="fb-btn primary" onclick="submitFeedback()">寄出想法</button>
      <button class="fb-btn" onclick="closeFeedback()">稍后再说</button>
    </div>`;
  // 默认选中第一项
  const first = c.querySelector('.fb-cat');
  if(first) fbSelectedCat = first.getAttribute('data-cat');
  ov.classList.remove('hidden');
}

function selectFbCat(el){
  document.querySelectorAll('#fbContent .fb-cat').forEach(b=>b.classList.remove('on'));
  el.classList.add('on');
  fbSelectedCat = el.getAttribute('data-cat');
}

function closeFeedback(){
  const ov = document.getElementById('fbOverlay');
  if(ov) ov.classList.add('hidden');
}

async function submitFeedback(){
  const textEl = document.getElementById('fbText');
  const contactEl = document.getElementById('fbContact');
  const content = textEl ? textEl.value.trim() : '';
  if(!content){ notify('写一句想说的话吧～'); if(textEl) textEl.focus(); return; }
  if(!fbSelectedCat){ notify('先选一个方向吧～'); return; }
  if(!state.online){ notify('联网后就能寄出想法啦，先记着～'); return; }
  const body = {category: fbSelectedCat, content: content};
  if(contactEl && contactEl.value.trim()) body.contact = contactEl.value.trim();
  const c = document.getElementById('fbContent');
  const btn = c && c.querySelector('.fb-btn.primary');
  if(btn){ btn.disabled = true; btn.textContent = '寄出中…'; }
  const res = await apiRequest('/api/feedback', {method:'POST', body:body});
  if(res){
    c.innerHTML = `
      <div class="fb-emoji">🌿</div>
      <div class="fb-title">收到啦，谢谢你</div>
      <p class="fb-desc">你的想法已经记下，<br>会在往后的版本里慢慢发芽。</p>
      <div class="fb-actions"><button class="fb-btn primary" onclick="closeFeedback()">好的</button></div>`;
  }else{
    if(btn){ btn.disabled = false; btn.textContent = '寄出想法'; }
  }
}
