import { esc, state } from '../store.js';
import { speak } from './audio.js';
import { detectLinkingPairs } from './chat.js';
import { findRulesForCard, loadPronDetails, openPronCard, openPronCardForNoRule, pronFocusLabel } from './pron.js';

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

export { closePronPopover, openFullFromPop, openWordPopover, pronPopEl, pronPopOutside, toggleLinkingInline };
