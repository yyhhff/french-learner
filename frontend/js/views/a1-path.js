/* ============================================================
   TASK-0065 v2.2 零基础台阶路径（车道 A）
   新用户定级落 A1 → 自动弹出三步薄引导：
     读音 → 首词 → 首句跟读
   只做导航与温和鼓励，学习动作全部复用现有组件：
     · 读音 → openPronBook()（读音小册子）
     · 首词 → 切到阅读 A1 档 + 打开首篇（逐词点击学发音 / 生词卡）
     · 首句跟读 → 读音小册子里带 🎙 的跟读段（沿用 ASR 三道门控）
   localStorage 仅存"是否已完成路径"的 UI 标志，不写学习进度。
   ============================================================ */
import { esc, notify } from '../store.js';
import { switchView } from './growth.js';
import { openPronBook } from './pron.js';
import { selectReadLevel, openReadText } from './reading.js';

const A1_PATH_KEY = 'yaya_a1_path_done';

function a1PathDone(){
  try{ return localStorage.getItem(A1_PATH_KEY)==='1'; }catch(e){ return false; }
}

const STEPS = [
  {n:1, emoji:'🔤', title:'先听读音', desc:'从最常见的法语读音开始，点开小册子，听一听、跟着念，不打分也没关系。', btn:'打开读音小册子'},
  {n:2, emoji:'📖', title:'再认第一个词', desc:'读一篇最短的短文，点一点里面的词，就能听到发音、看到意思。看不懂有中文小字。', btn:'去读第一篇'},
  {n:3, emoji:'🎙', title:'说出第一句', desc:'回到读音小册子，找带 🎙 的句子跟读一句。没听清就再来一次，说错也没关系。', btn:'去跟读一句'},
];

function openA1Path(){
  const ov = document.getElementById('a1PathOverlay');
  const c = document.getElementById('a1PathContent');
  if(!ov || !c) return;
  renderA1Path(1);
  ov.classList.remove('hidden');
}

function closeA1Path(){
  const ov = document.getElementById('a1PathOverlay');
  if(ov) ov.classList.add('hidden');
}

function renderA1Path(step){
  const c = document.getElementById('a1PathContent');
  if(!c) return;
  step = Math.max(1, Math.min(3, step));
  const dots = STEPS.map(s=>`<i class="${s.n===step?'on':''} ${s.n<step?'done':''}"></i>`).join('');
  const s = STEPS[step-1];
  c.innerHTML = `
    <div class="a1p-emoji">${s.emoji}</div>
    <div class="a1p-title">第 ${step} 步 · ${esc(s.title)}</div>
    <p class="a1p-desc">${esc(s.desc)}</p>
    <div class="a1p-go">
      <button class="a1p-btn primary" onclick="a1PathGo(${step})">${esc(s.btn)}</button>
      ${step<3
        ? '<button class="a1p-btn" onclick="a1PathNext('+(step+1)+')">下一步 →</button>'
        : '<button class="a1p-btn" onclick="a1PathFinish()">我完成啦 🌱</button>'}
    </div>
    <div class="a1p-dots">${dots}</div>`;
}

function a1PathNext(n){
  renderA1Path(n);
}

function a1PathGo(step){
  closeA1Path();
  if(step===1){
    openPronBook();
  }else if(step===2){
    switchView('read');
    selectReadLevel('A1');
    openReadText('inp_a1_001');
  }else if(step===3){
    openPronBook();  // 读音小册子内带 🎙 的跟读段，沿用既有 ASR 三道门控
  }
}

function a1PathFinish(){
  closeA1Path();
  try{ localStorage.setItem(A1_PATH_KEY,'1'); }catch(e){}
  notify('太棒啦，你已经说出第一句法语了 🌱');
}

export { A1_PATH_KEY, a1PathDone, a1PathFinish, a1PathGo, a1PathNext, closeA1Path, openA1Path, renderA1Path };
