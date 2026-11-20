// v3.3 语法的针脚（TASK-0078）：语法微卡三嵌入 —— 阅读句扫描 chip / 复习画像 banner / 对话内联推卡。
// 零新 Tab；卡片 + patterns 来自 GET /api/grammar/cards，前端本地复扫（与后端 grammar.py 同算法）。
// 端点失败一律静默降级：不出 chip、不出 banner，不影响阅读/复习/对话主流程。
import { apiRequest } from '../api.js';
import { esc, state } from '../store.js';
import { speak } from './audio.js';

let gramPopEl = null;

// 与 backend/grammar.py normalize_for_scan 同一算法（py 侧由单测固化）：小写 +
// 标点转空格 + 空白压缩 + 首尾补空格；patterns 按「空格包裹词/短语」书写，
// 避免 \b 在 JS 中对带重音字符失效（é 不是 \w）。
function normalizeForScan(text){
  let s = String(text == null ? '' : text).toLowerCase().replace(/\u2019/g, "'");
  s = s.replace(/[.,!?;:«»]/g, ' ').replace(/\s+/g, ' ').trim();
  return s ? ' ' + s + ' ' : ' ';
}

export async function loadGrammarCards(){
  if(state.grammar.cards || !state.online || !state.grammar.available) return;
  try{
    const res = await apiRequest('/api/grammar/cards');
    if(res == null) return;
    state.grammar.cards = Array.isArray(res.items) ? res.items : [];
  }catch(e){
    state.grammar.available = false;
  }
}

// 句级扫描：命中语法卡列表（按库内顺序，天然去重）
export function findCardsForSentence(sentence){
  if(!state.grammar.available || !state.grammar.cards) return [];
  const hay = normalizeForScan(sentence);
  if(hay === ' ') return [];
  const out = [];
  for(const c of state.grammar.cards){
    for(const p of (c.patterns || [])){
      try{
        if(new RegExp(p).test(hay)){ out.push(c); break; }
      }catch(e){ /* 坏 pattern 跳过，不影响其他卡 */ }
    }
  }
  return out;
}

function grammarCardHTML(c){
  const exs = (c.examples || []).map(e =>
    `<div class="grammar-ex"><span class="fr">${esc(e.fr)}<button class="grammar-say" onclick="event.stopPropagation();speak(this)" data-text="${esc(e.fr)}" title="听例句">🔊</button></span><span class="cn">${esc(e.cn)}</span></div>`
  ).join('');
  return `<div class="grammar-card">
    <div class="grammar-card-head"><span class="grammar-tag">${esc(c.tag_label || '语法')}</span><span class="grammar-lv">${esc(c.level || '')}</span><b>${esc(c.title)}</b></div>
    <div class="grammar-card-sum">${esc(c.summary)}</div>
    ${exs}
  </div>`;
}

// 阅读句行内 chip：命中才出现；一句最多一个 chip（点击看该句全部命中卡）
export function grammarChipHTML(sentence){
  const hits = findCardsForSentence(sentence);
  if(!hits.length) return '';
  const tip = hits.length === 1 ? hits[0].title : hits[0].tag_label + ` 等 ${hits.length} 个语法点`;
  return `<button class="grammar-chip" onclick="openGrammarPop(this)" data-sentence="${esc(sentence)}" title="语法小卡：${esc(tip)}">📌 语法</button>`;
}

// 对话流内联推卡（响应 payload 的 grammar_card 字段，仅同类第 3 次出现时下发）
export function grammarInlineHTML(gc){
  if(!gc || !gc.card) return '';
  const head = gc.tag_label ? `<div class="grammar-inline-head">📌 你在「${esc(gc.tag_label)}」上常见的小错误，这张小卡送给你</div>` : '';
  return `<div class="grammar-inline">${head}${grammarCardHTML(gc.card)}</div>`;
}

export function openGrammarPop(anchor){
  if(gramPopEl && gramPopEl._anchor === anchor){ closeGrammarPop(); return; } // 再点同一 chip = 收起
  closeGrammarPop();
  const hits = findCardsForSentence(anchor.getAttribute('data-sentence') || '');
  if(!hits.length) return;
  const el = document.createElement('div');
  el.className = 'grammar-pop';
  el._anchor = anchor;
  el.innerHTML = `<button class="grammar-pop-close" onclick="event.stopPropagation();closeGrammarPop()" title="关闭">×</button>`
    + hits.map(grammarCardHTML).join('');
  document.body.appendChild(el);
  // 定位：贴 chip 下沿，视口内钳制，放不下翻上方（word-popover 同款）
  const rect = anchor.getBoundingClientRect();
  el.style.visibility = 'hidden';
  requestAnimationFrame(() => {
    const w = el.offsetWidth, h = el.offsetHeight;
    let x = rect.left + rect.width / 2 - w / 2;
    x = Math.max(8, Math.min(x, window.innerWidth - w - 8));
    let y = rect.bottom + 6;
    if(y + h + 8 > window.innerHeight) y = Math.max(8, rect.top - h - 6);
    el.style.left = x + 'px';
    el.style.top = y + 'px';
    el.style.visibility = '';
  });
  gramPopEl = el;
  setTimeout(() => document.addEventListener('click', gramPopOutside, true), 0);
}

function gramPopOutside(e){
  if(gramPopEl && !gramPopEl.contains(e.target) && e.target !== gramPopEl._anchor
     && !(gramPopEl._anchor && gramPopEl._anchor.contains(e.target))){
    closeGrammarPop();
  }
}

export function closeGrammarPop(){
  if(gramPopEl){ gramPopEl.remove(); gramPopEl = null; }
  document.removeEventListener('click', gramPopOutside, true);
}

// 复习入口的画像 banner：有「同类 ≥3 次」建议卡才出现；收起后本会话不再打扰
export async function refreshGrammarBanner(){
  const slot = document.getElementById('grammarReviewBanner');
  if(!slot || !state.online || !state.grammar.available || state.grammar.bannerDismissed) return;
  slot.classList.add('hidden');
  slot.innerHTML = '';
  try{
    const p = await apiRequest('/api/grammar/profile');
    if(p == null || !p.suggest) return;
    const s = p.suggest;
    slot.innerHTML = `<div class="grammar-banner-box">
      <div class="grammar-banner-head">📌 温柔提醒：你在「${esc(s.tag_label)}」上已经出现过 ${Number(s.count || 0)} 次同类小错误</div>
      ${grammarCardHTML(s.card)}
      <button class="grammar-banner-close" onclick="dismissGrammarBanner()">先记住啦，不用再提醒</button>
    </div>`;
    slot.classList.remove('hidden');
  }catch(e){ /* 静默：画像是增益，复习不受影响 */ }
}

export function dismissGrammarBanner(){
  state.grammar.bannerDismissed = true;
  const slot = document.getElementById('grammarReviewBanner');
  if(slot){ slot.classList.add('hidden'); slot.innerHTML = ''; }
}
