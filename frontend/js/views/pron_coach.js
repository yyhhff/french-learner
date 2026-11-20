// TASK-0067 v3.2 发音教练视图：听标准音 → 录音 → 词级对齐三维评分 → 中文反馈。
// 独立链路，复用 audio.js 的 checkAsr/pickMimeType/speak，绝不进聊天流。
import { apiRequest } from '../api.js';
import { esc, notify, state } from '../store.js';
import { checkAsr, pickMimeType, speak } from './audio.js';

const pcState = {
  tags: [],
  current: null,
  exclude: [],
  focus: '',
  level: '',
  loaded: false,
  rec: null, stream: null, chunks: [], recording: false, timer: null, startTs: 0,
};

function el(id){ return document.getElementById(id); }

// ---- 视图切换：独立函数，不进 growth.js 的 switchView（避免改他人模块）----
// TASK-0070 v3.0：视图列表加入 today（容器/Tab 命名恰好符合 viewToday/tabToday 拼接规则）
const VIEWS = ['today','chat','read','assessment','exam','growth','roadmap','proncoach'];
function switchPronCoachView(name){
  const view = VIEWS.includes(name) ? name : 'chat';
  VIEWS.forEach(v=>{
    const c = el('view'+v.charAt(0).toUpperCase()+v.slice(1));
    if(c) c.classList.toggle('hidden', v!==view);
    const t = el('tab'+v.charAt(0).toUpperCase()+v.slice(1));
    if(t) t.classList.toggle('on', v===view);
  });
  if(view==='proncoach') initPronCoach();
}

// ---- 初始化：拉标签 + 选第一句 ----
let initPromise = null;
function initPronCoach(){
  if(initPromise) return initPromise;
  initPromise = (async ()=>{
    if(!pcState.loaded){
      try{
        const r = await apiRequest('/api/pron-coach/focus-tags');
        if(r) pcState.tags = r.tags || [];
      }catch(e){}
      pcState.loaded = true;
      renderPronCoachFilters();
    }
    if(!pcState.current) await nextPronCoachSentence();
    else renderPronCoachCard();
  })().finally(()=>{ initPromise = null; });
  return initPromise;
}

function renderPronCoachFilters(){
  const box = el('proncoachFilters');
  if(!box) return;
  const all = `<button class="proncoach-chip ${pcState.focus?'':'on'}" onclick="setPronCoachFocus('')">全部</button>`;
  const chips = pcState.tags.map(t=>
    `<button class="proncoach-chip ${pcState.focus===t.key?'on':''}" onclick="setPronCoachFocus('${t.key}')">${esc(t.label)}</button>`
  ).join('');
  box.innerHTML = all + chips;
}

function setPronCoachFocus(tag){
  pcState.focus = tag;
  pcState.current = null;
  renderPronCoachFilters();
  nextPronCoachSentence();
}

async function nextPronCoachSentence(){
  const params = new URLSearchParams();
  if(pcState.focus) params.set('focus', pcState.focus);
  if(pcState.level) params.set('level', pcState.level);
  if(pcState.exclude.length) params.set('exclude', pcState.exclude.join(','));
  let data = null;
  try{
    data = await apiRequest('/api/pron-coach/sentences'+(params.toString()?'?'+params.toString():''));
  }catch(e){}
  const s = data && data.sentence;
  if(!s){
    const card = el('proncoachCard');
    if(card) card.innerHTML = '<div class="proncoach-empty">这一类暂时没有句子啦，换个标签试试～</div>';
    return;
  }
  pcState.current = s;
  renderPronCoachCard();
}

function renderPronCoachCard(){
  const card = el('proncoachCard');
  const s = pcState.current;
  if(!card || !s) return;
  const tagLabel = (pcState.tags.find(t=>t.key===pcState.focus)||{}).label || '自由练习';
  card.innerHTML = `
    <div class="proncoach-card-head">
      <span class="proncoach-badge">${esc(s.cefr||'')}</span>
      <span class="proncoach-tag">${esc(tagLabel)}</span>
      <span class="proncoach-src">${esc(s.source==='focus'?'发音难点':s.source==='corpus'?'分级语料':'词卡例句')}</span>
    </div>
    <div class="proncoach-sentence">
      <button class="proncoach-play" data-text="${esc(s.fr)}" onclick="speak(this)" title="听标准音">🔊</button>
      <span class="proncoach-fr">${esc(s.fr)}</span>
    </div>
    <div class="proncoach-cn">${esc(s.cn||'')}</div>
    <div class="proncoach-record-row">
      <button id="proncoachRecBtn" class="proncoach-rec-btn" onclick="togglePronCoachRecord()">🎙 开始跟读</button>
      <span id="proncoachStatus" class="proncoach-status">先听一遍标准音，再开始跟读～</span>
    </div>
    <div id="proncoachResult" class="proncoach-result"></div>
    <div class="proncoach-next-row">
      <button class="proncoach-next" onclick="nextPronCoachSentence()">换一句 →</button>
    </div>`;
}

function pronCoachReset(){
  if(pcState.recording && pcState.rec && pcState.rec.state!=='inactive'){
    try{ pcState.rec.stop(); }catch(e){}
  }
  if(pcState.timer) clearTimeout(pcState.timer);
  if(pcState.stream) pcState.stream.getTracks().forEach(t=>t.stop());
  Object.assign(pcState, {rec:null, stream:null, chunks:[], recording:false, timer:null});
}

async function togglePronCoachRecord(){
  if(pcState.recording){
    if(pcState.rec && pcState.rec.state!=='inactive') pcState.rec.stop();
    return;
  }
  const s = pcState.current;
  if(!s) return;
  if(!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder){
    notify('这个浏览器不支持录音，多听几遍标准音也一样在进步～'); return;
  }
  if(!(await checkAsr())){
    const st = el('proncoachStatus');
    if(st) st.textContent = '本地语音服务没就绪，跟读先跳过～';
    return;
  }
  let stream;
  try{ stream = await navigator.mediaDevices.getUserMedia({audio:true}); }
  catch(e){ notify('没拿到麦克风权限，稍后再试也可以～'); return; }
  const btn = el('proncoachRecBtn');
  try{
    const mime = pickMimeType();
    const rec = new MediaRecorder(stream, mime?{mimeType:mime}:undefined);
    Object.assign(pcState, {rec, stream, chunks:[], recording:true, startTs:Date.now()});
    if(btn){ btn.classList.add('rec'); btn.textContent='⏹ 结束跟读'; }
    const st = el('proncoachStatus'); if(st) st.textContent='🎙 在听，跟着读吧…最长 10 秒';
    const result = el('proncoachResult'); if(result) result.innerHTML='';
    rec.ondataavailable = (e)=>{ if(e.data && e.data.size) pcState.chunks.push(e.data); };
    rec.onstop = async ()=>{
      pcState.recording = false;
      if(btn){ btn.classList.remove('rec'); btn.textContent='🎙 再来一次'; }
      stream.getTracks().forEach(t=>t.stop());
      clearTimeout(pcState.timer);
      const blob = new Blob(pcState.chunks, {type: rec.mimeType || 'audio/webm'});
      if(!blob.size){ const s2=el('proncoachStatus'); if(s2) s2.textContent='没录到声音，再试一次～'; return; }
      await evaluatePronCoach(blob, s);
    };
    rec.start();
    pcState.timer = setTimeout(()=>{ if(pcState.recording && rec.state!=='inactive') rec.stop(); }, 10000);
  }catch(e){ pronCoachReset(); notify('录音启动没成功，稍后再试～'); }
}

function scoreBar(label, value){
  if(value==null) return '';
  const cls = value>=80?'high':value>=55?'mid':'low';
  return `<div class="proncoach-dim"><span>${label}</span><div class="proncoach-bar"><i class="${cls}" style="width:${value}%"></i></div><b>${value}</b></div>`;
}

async function evaluatePronCoach(blob, sentence){
  const st = el('proncoachStatus');
  if(st) st.textContent = '正在听你的发音…';
  const ext = blob.type.includes('mp4')?'.m4a':blob.type.includes('ogg')?'.ogg':'.webm';
  let data = null;
  try{
    const fd = new FormData();
    fd.append('file', blob, 'proncoach'+ext);
    fd.append('target_text', sentence.fr);
    fd.append('sentence_id', sentence.id);
    const resp = await fetch('/api/pron-coach/evaluate', {method:'POST', body:fd});
    data = await resp.json();
  }catch(e){ data = null; }

  // 当前句已切走则不写旧反馈
  if(!pcState.current || pcState.current.id!==sentence.id) return;
  if(st) st.textContent = '跟读完成～';
  const result = el('proncoachResult');
  if(!result) return;

  if(!data || data.code!==0 || !data.data){
    result.innerHTML = '<div class="proncoach-fb unsure">这次没算出来，再来一次就好～</div>';
    return;
  }
  const d = data.data;
  if(d.band==='UNSURE'){
    result.innerHTML = `<div class="proncoach-fb unsure">${esc(d.feedback.title)}<div class="proncoach-fb-detail">${esc(d.feedback.detail)}</div></div>`;
    return;
  }
  const sc = d.scores || {};
  const bars = scoreBar('内容命中', sc.content) + scoreBar('流利度', sc.fluency) + scoreBar('稳定度', sc.stability);
  const miss = (d.missing_words||[]).length
    ? `<div class="proncoach-miss">待加强：${d.missing_words.map(w=>`<span>${esc(w)}</span>`).join('')}</div>` : '';
  result.innerHTML = `
    <div class="proncoach-fb ${esc(d.feedback.cls)}">
      <b>${esc(d.feedback.title)}</b>
      <div class="proncoach-fb-detail">${esc(d.feedback.detail)}</div>
    </div>
    <div class="proncoach-scores">
      ${bars}
      <div class="proncoach-overall">综合 <b>${d.overall}</b> / 100</div>
    </div>
    ${miss}`;

  // 练过的句加入排除列表，便于「换一句」不重复
  if(!pcState.exclude.includes(sentence.id)) pcState.exclude.push(sentence.id);
}

export {
  initPronCoach, nextPronCoachSentence, setPronCoachFocus, switchPronCoachView,
  togglePronCoachRecord, evaluatePronCoach, renderPronCoachFilters, renderPronCoachCard,
  pronCoachReset, scoreBar, pcState,
};
