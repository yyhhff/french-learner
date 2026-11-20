import { apiRequest } from '../api.js';
import { esc, notify, state } from '../store.js';
import { buildAsrHints, pickMimeType, speak } from './audio.js';

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

export { EXAM_DISCLAIMER, answerExamChoice, backExamToPapers, examAnswerDone, examState, examTypeName, initExam, nextExam, onExamTextInput, openExamPaper, prevExam, renderExamPapers, renderExamQuestion, renderExamResult, saveExamCurrentText, showExamPane, submitExam, toggleExamRecord, transcribeExamAudio };
