import { apiRequest } from '../api.js';
import { esc, notify, state } from '../store.js';
import { checkAsr, pickMimeType } from './audio.js';
import { applyPronProgressItem, pronCurrentRuleId, pronKey, updatePronCardProgressUI } from './pron.js';

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

export { IPA_CONFUSABLE_PAIRS, SHADOW_R_HIGH, ipaEq, levDistance, pronShadowRec, pronShadowReset, pronShadowSection, scoreShadow, shadowFeedback, shadowSelfAssess, stringSim, toggleShadowRecord, transcribeShadowAudio };
