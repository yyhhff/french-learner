import { apiRequest } from '../api.js';
import { esc, notify, state } from '../store.js';
import { speak, unlockAudio } from './audio.js';
import { renderVocab } from './chat.js';
import { pronShadowReset, pronShadowSection } from './shadow.js';

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

export { PRON_GROUP_ORDER, PRON_SKIP_TOKENS, PRON_STAGE_LABEL, PRON_TIP_KEY, applyPronProgressItem, buildPronIndex, closePronBook, closePronCard, dismissPronTip, findRulesForCard, loadPronData, loadPronDetails, loadPronProgress, loadPronSummaries, maybeShowPronTip, normIpa, openPronBook, openPronCard, openPronCardForNoRule, postPronProgress, pronBadgeHTML, pronCurrentRuleId, pronFocusLabel, pronHitIds, pronHitWord, pronKey, pronLearnedTotal, pronProgressHTML, pronStageOf, pronTotalRules, renderPronBook, renderPronCard, switchPronCard, updatePronBookEntry, updatePronCardProgressUI };
