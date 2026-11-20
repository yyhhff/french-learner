import { esc, state } from '../store.js';
import { speak } from './audio.js';
import { switchView } from './growth.js';
import { openReadText } from './reading.js';

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


/* ============================================================
   阶段4 考级冲刺：原创模拟练习（第 4 个 Tab）
   GET /api/exam/papers + GET /api/exam/papers/{id} + POST /api/exam/submit
   独立追加，不改写现有函数名：
   - 听力/口语 🔊 复用 speak(btn)（data-text 已 esc）
   - 口语 🎙 用本模块独立录音→上传→取文本，只填本题文本框，
     不触碰对话流、不写对话输入框、不复用对话麦克风状态
   - 失败只给温和提示，不瞎编卷
   ============================================================ */

export { ONBOARDING_KEY, RETENTION_KEY, closeOnboarding, closeRetention, goOnboardingTarget, maybeShowOnboarding, maybeShowRetention, onboardingSeen, reopenOnboarding, retentionContinue, showOnboardingStep };
