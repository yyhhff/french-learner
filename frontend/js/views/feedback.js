import { apiRequest } from '../api.js';
import { esc, notify, state } from '../store.js';

const FB_CATS_FALLBACK = [
  {code:'chat', label:'口语陪练'}, {code:'read', label:'分级阅读'},
  {code:'pron', label:'读音规则'}, {code:'review', label:'复习调度'},
  {code:'exam', label:'考级冲刺'}, {code:'other', label:'其他想说的'}
];

let fbSelectedCat = null;

async function openFeedback(){
  const ov = document.getElementById('fbOverlay');
  const c = document.getElementById('fbContent');
  if(!ov || !c) return;
  // 懒拉方向（前后端单一数据源），失败用本地兜底，不阻塞打开
  let cats = FB_CATS_FALLBACK;
  if(state.online){
    try{
      const got = await apiRequest('/api/feedback/categories');
      if(Array.isArray(got) && got.length) cats = got;
    }catch(e){}
  }
  fbSelectedCat = null;
  c.innerHTML = `
    <div class="fb-emoji">💌</div>
    <div class="fb-title">说说你的想法</div>
    <p class="fb-desc">哪一块最想我们做得更好？<br>你的想法会变成下一个版本 🌱</p>
    <div class="fb-label">最想优化哪一块</div>
    <div class="fb-cats">${cats.map((x,i)=>`
      <button type="button" class="fb-cat${i===0?' on':''}" data-cat="${esc(x.code)}"
        onclick="selectFbCat(this)">${esc(x.label)}</button>`).join('')}</div>
    <div class="fb-label">具体建议</div>
    <textarea id="fbText" class="fb-text" maxlength="1000" rows="4"
      placeholder="想多一点例句？想要某个场景？都告诉我吧～"></textarea>
    <input id="fbContact" class="fb-contact" maxlength="200"
      placeholder="邮箱或微信（选填，方便我们找到你）">
    <div class="fb-actions">
      <button class="fb-btn primary" onclick="submitFeedback()">寄出想法</button>
      <button class="fb-btn" onclick="closeFeedback()">稍后再说</button>
    </div>`;
  // 默认选中第一项
  const first = c.querySelector('.fb-cat');
  if(first) fbSelectedCat = first.getAttribute('data-cat');
  ov.classList.remove('hidden');
}

function selectFbCat(el){
  document.querySelectorAll('#fbContent .fb-cat').forEach(b=>b.classList.remove('on'));
  el.classList.add('on');
  fbSelectedCat = el.getAttribute('data-cat');
}

function closeFeedback(){
  const ov = document.getElementById('fbOverlay');
  if(ov) ov.classList.add('hidden');
}

async function submitFeedback(){
  const textEl = document.getElementById('fbText');
  const contactEl = document.getElementById('fbContact');
  const content = textEl ? textEl.value.trim() : '';
  if(!content){ notify('写一句想说的话吧～'); if(textEl) textEl.focus(); return; }
  if(!fbSelectedCat){ notify('先选一个方向吧～'); return; }
  if(!state.online){ notify('联网后就能寄出想法啦，先记着～'); return; }
  const body = {category: fbSelectedCat, content: content};
  if(contactEl && contactEl.value.trim()) body.contact = contactEl.value.trim();
  const c = document.getElementById('fbContent');
  const btn = c && c.querySelector('.fb-btn.primary');
  if(btn){ btn.disabled = true; btn.textContent = '寄出中…'; }
  const res = await apiRequest('/api/feedback', {method:'POST', body:body});
  if(res){
    c.innerHTML = `
      <div class="fb-emoji">🌿</div>
      <div class="fb-title">收到啦，谢谢你</div>
      <p class="fb-desc">你的想法已经记下，<br>会在往后的版本里慢慢发芽。</p>
      <div class="fb-actions"><button class="fb-btn primary" onclick="closeFeedback()">好的</button></div>`;
  }else{
    if(btn){ btn.disabled = false; btn.textContent = '寄出想法'; }
  }
}

export { FB_CATS_FALLBACK, closeFeedback, fbSelectedCat, openFeedback, selectFbCat, submitFeedback };
