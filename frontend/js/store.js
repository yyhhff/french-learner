// Wave 0 共享状态与纯工具：从 app.js 原样搬出，零行为变更。

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

export { FALLBACK_DETAILS, FALLBACK_PROFILE, FALLBACK_SCENES, FALLBACK_VOCAB, NOW_ISO, RECAST_RULES, TODAY, TRY_CHIPS, buildFallbackCards, capitalize, esc, fmtNum, normalizeTurn, notify, setMicStatus, state, toastTimer, userTurn };
