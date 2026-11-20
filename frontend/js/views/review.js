import { apiRequest } from '../api.js';
import { esc, notify, state } from '../store.js';
import { speak } from './audio.js';
import { renderLedger } from './chat.js';
import { refreshGrammarBanner } from './grammar.js';
import { renderGrowth } from './growth.js';
import { setOffline } from './reading.js';

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
  refreshGrammarBanner(); // TASK-0078：复习入口按 recast 错误画像温和推语法卡（异步、静默失败）
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

export { OFFLINE_INTERVAL, closeReview, doReview, openReview, readOfflineNote, renderReviewCard, reviewQueue, updateReadVocabBadge };
