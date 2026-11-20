import { apiRequest } from '../api.js';
import { FALLBACK_PROFILE, esc, notify, state } from '../store.js';
import { renderTop } from './chat.js';
import { switchView } from './growth.js';
import { recommendNext } from './reading.js';
import { a1PathDone, openA1Path } from './a1-path.js';

const ASSESS_RESULT_KEY = 'placement_result';

const assessmentState = {
  questions:[],   // PublicQuestion[]：id/level/skill/question/options
  answers:{},     // id -> answer_idx（0..3）
  index:0,        // 当前题号
  submitting:false,
  result:null
};

// v2.2 四档：A1/A2/B1/B2；后端权重 0/1/2/3，加权满分 6*(0+1+2+3)=36。
const ASM_LEVELS = ['A1','A2','B1','B2'];
const ASM_MAX_WEIGHTED = 36;

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
  // 按 level 分组稳定排序 A1 → A2 → B1 → B2（判分按 id 匹配，顺序不影响结果）
  const order = {A1:0, A2:1, B1:2, B2:3};
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
  const level = String(data.level||'A1');
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
  // v2.2：落 A1 的新定级用户自动进入台阶路径（读音→首词→首句跟读）
  if(level==='A1' && !a1PathDone() && !sessionStorage.getItem('a1_path_launched')){
    try{ sessionStorage.setItem('a1_path_launched','1'); }catch(e){}
    setTimeout(openA1Path, 600);
  }
}

function renderAssessmentResult(data){
  const box = document.getElementById('asmResult');
  if(!box) return;
  const score = Number(data.score)||0;
  const total = Number(data.total)||24;
  const s = Number(data.weighted_score)||0;
  const pct = Math.min(100, Math.round(s/ASM_MAX_WEIGHTED*100));
  const level = String(data.level||'A1');
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
      <div class="asm-weight-row"><span>加权得分</span><b>${s} / ${ASM_MAX_WEIGHTED}</b></div>
      <div class="asm-bar"><i style="width:${pct}%"></i></div>
      <div class="asm-interpret">${esc(data.interpretation_zh||'')}</div>
      <div class="asm-result-actions">
        <button class="asm-ghost" onclick="startAssessment()">再测一次</button>
        ${level==='A1'
          ? '<button class="asm-primary" onclick="openA1Path()">🌱 进入第一步</button>'
          : '<button class="asm-primary" onclick="goAssessmentRecommend()">看看推荐内容</button>'}
      </div>
      ${level==='A1' ? '<div class="a1-path-hint">从最基础的读音开始，我陪你一步步来 🌱</div>' : ''}
      <div class="asm-result-foot">觉得不太准？随时可以再测一次 🌱</div>
    </div>`;
}

function goAssessmentRecommend(){
  switchView('read');
  recommendNext();
}

// 11) GET /api/input/levels

export { ASM_LEVELS, ASSESS_RESULT_KEY, answerAssessment, assessmentState, goAssessmentRecommend, initAssessment, jumpAssessmentLevel, nextAssessment, prevAssessment, renderAssessmentQuestion, renderAssessmentResult, showAssessmentPane, startAssessment, submitAssessment };
