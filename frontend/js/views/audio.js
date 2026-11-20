import { apiRequest } from '../api.js';
import { notify, setMicStatus, state } from '../store.js';
import { submitUserText } from './chat.js';
import { showReadDetail } from './reading.js';

let _ttsAudio = null;
// Chrome 自动播放策略：音频必须由用户手势"解锁"后才允许出声。
// 首次任意点击时用一段静音 audio 解锁，之后 fetch 回调里的 play() 才不会被拒。

let _audioUnlocked = false;

function unlockAudio(){
  if(_audioUnlocked) return;
  _audioUnlocked = true;
  try{
    const a = new Audio('data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQAAAAA=');
    const p = a.play();
    if(p && p.then) p.then(()=>a.pause()).catch(()=>{});
  }catch(e){}
}

function speak(btn){
  const text = btn.getAttribute('data-text')||'';
  if(!text) return;
  unlockAudio();
  if(window.speechSynthesis) window.speechSynthesis.cancel();
  if(_ttsAudio){ try{ _ttsAudio.pause(); }catch(e){} _ttsAudio=null; }
  btn.classList.add('speaking');
  const clear = ()=>btn.classList.remove('speaking');
  // 优先用本地神经语音合成（le/la/les 等功能词连读准确，不会读成字母）
  fetch('/api/tts?text='+encodeURIComponent(text))
    .then(r=>{ if(!r.ok) throw new Error('tts '+r.status); return r.blob(); })
    .then(blob=>{
      const url = URL.createObjectURL(blob);
      const a = new Audio(url);
      _ttsAudio = a;
      a.onended = ()=>{ URL.revokeObjectURL(url); clear(); };
      a.onerror = ()=>{ URL.revokeObjectURL(url); clear(); fallbackSpeak(text); };
      return a.play();
    })
    .then(()=>{})
    .catch(()=>{ clear(); fallbackSpeak(text); });
}

function fallbackSpeak(text){
  if(!('speechSynthesis' in window)){ notify('当前浏览器不支持语音朗读'); return; }
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = 'fr-FR';
  u.rate = 0.95;
  // 尽量挑一个真正的法语 voice，减少英语引擎硬读法语
  try{
    const fr = (window.speechSynthesis.getVoices()||[])
      .find(v=>/^fr/i.test(v.lang));
    if(fr) u.voice = fr;
  }catch(e){}
  window.speechSynthesis.speak(u);
}

/* 语音输入：MediaRecorder 录音 → 上传本地 Whisper 服务转写（不依赖境外服务）
   降级顺序：本地 ASR 服务 → 浏览器自带识别（若在境外网络可用）→ 打字 */

let mediaRecorder = null, audioChunks = [], recording = false;

let asrAvailable = null; // null=未探测 true/false

function pickMimeType(){
  const candidates = ['audio/webm;codecs=opus','audio/webm','audio/ogg;codecs=opus','audio/mp4'];
  for(const t of candidates){ if(window.MediaRecorder && MediaRecorder.isTypeSupported(t)) return t; }
  return '';
}

async function checkAsr(){
  if(asrAvailable!==null) return asrAvailable;
  try{
    const r = await apiRequest('/api/asr/status');
    asrAvailable = !!(r && r.available);
  }catch(e){ asrAvailable = false; }
  return asrAvailable;
}

async function toggleMic(){
  const btn = document.getElementById('micBtn');
  if(recording){ if(mediaRecorder && mediaRecorder.state!=='inactive') mediaRecorder.stop(); return; }

  if(!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder){
    setMicStatus('这个浏览器不支持录音，请用 Chrome / Edge，或直接打字。');
    notify('浏览器不支持录音，可以直接打字哦');
    return;
  }

  let stream;
  try{
    stream = await navigator.mediaDevices.getUserMedia({audio:true});
  }catch(e){
    setMicStatus('麦克风权限被拒绝。请点地址栏左侧锁图标允许麦克风，或直接打字。');
    notify('需要麦克风权限，也可以直接打字');
    return;
  }

  try{
    const mime = pickMimeType();
    mediaRecorder = new MediaRecorder(stream, mime?{mimeType:mime}:undefined);
    audioChunks = [];
    mediaRecorder.ondataavailable = (e)=>{ if(e.data && e.data.size) audioChunks.push(e.data); };
    mediaRecorder.onstart = ()=>{
      recording = true;
      btn.classList.add('rec');
      setMicStatus('🎙 在听，请说法语…说完自动结束，最长 15 秒');
    };
    mediaRecorder.onstop = async ()=>{
      recording = false;
      btn.classList.remove('rec');
      stream.getTracks().forEach(t=>t.stop());
      const blob = new Blob(audioChunks, {type: mediaRecorder.mimeType || 'audio/webm'});
      if(!blob.size){ setMicStatus('没录到声音，再试一次或直接打字。'); return; }
      await transcribeAudio(blob);
    };
    mediaRecorder.start();
    // 最长 15 秒自动结束，避免一直占着麦克风
    setTimeout(()=>{ if(recording && mediaRecorder.state!=='inactive') mediaRecorder.stop(); }, 15000);
  }catch(e){
    stream.getTracks().forEach(t=>t.stop());
    setMicStatus('录音启动失败：'+e.message+'（可直接打字）');
  }
}

// 从最近对话与生词卡取法语词作 ASR 热词；只留字母、限量，避免长提示稀释偏置

function buildAsrHints(){
  const seen = new Set();
  const add = s => String(s||'').replace(/['’]/g,' ').split(/[^\p{L}]+/u)
    .forEach(w=>{ if(w.length>1) seen.add(w.toLowerCase()); });
  state.chatLog.slice(-6).forEach(m=>add(m.fr));
  state.cards.slice(0,40).forEach(c=>add(c && c.word));
  return [...seen].slice(0,40).join(' ');
}
// 前一句对话整句作为 ASR 上下文（实验证明：前一句够用，前两句无额外收益）

function buildAsrContext(){
  for(let i=state.chatLog.length-1;i>=0;i--){
    const fr = String(state.chatLog[i] && state.chatLog[i].fr || '').trim();
    if(fr) return fr.slice(0,200);
  }
  return '';
}

async function transcribeAudio(blob){
  setMicStatus('正在识别你说的话…');
  const ext = (blob.type.includes('mp4')?'.m4a':blob.type.includes('ogg')?'.ogg':'.webm');
  const available = await checkAsr();
  let data = null;
  if(available){
    try{
      const fd = new FormData();
      fd.append('file', blob, 'voice'+ext);
      fd.append('language', 'fr');
      fd.append('hints', buildAsrHints());
      fd.append('context', buildAsrContext());
      const resp = await fetch('/api/asr/transcribe', {method:'POST', body:fd});
      data = await resp.json();
    }catch(e){
      // 真正的网络异常（连接失败 / 响应非 JSON）才落到浏览器兜底
      data = null;
    }
    if(data){
      // 业务错误：服务端已给出明确 message（如"没听清"），如实展示后直接返回。
      // 绝不走浏览器兜底，否则会显示"本地语音服务未启动"这类误导文案。
      if(typeof data.code==='number' && data.code!==0){
        setMicStatus(data.message || '识别没成功，再试一次或直接打字～');
        document.getElementById('userInput').focus();
        return;
      }
      if(data.code===0 && data.data && data.data.text){
        const text = String(data.data.text).trim();
        const rawText = data.data.raw_text==null ? '' : String(data.data.raw_text).trim();
        const corrected = !!data.data.corrected;
        // 解析置信度；low_confidence 是权威标志，缺失时以极低 confidence 兜底
        const confidence = Number(data.data.confidence);
        const flagMissing = data.data.low_confidence==null;
        const lowConfidence = !!data.data.low_confidence
          || (flagMissing && Number.isFinite(confidence) && confidence>0 && confidence<0.5);
        document.getElementById('userInput').value = text;
        if(lowConfidence){
          // 低置信：只把识别文本放进输入框，温和提示，聚焦输入框，绝不自动提交
          setMicStatus('没太听清，改一下或再录一次都行～');
          document.getElementById('userInput').focus();
          return;
        }
        // ASR 明确标记已修正且原声与结果不同：温和小字提示，不打红叉、不弹错误
        if(corrected && rawText && rawText!==text){
          setMicStatus('已按法语发音把识别结果修正为：'+text);
          submitUserText(text, rawText);
        }else{
          setMicStatus('识别到：'+text);
          submitUserText(text);
        }
        return;
      }
    }
  }
  // 降级：浏览器自带识别（多数国内网络不可用，但保留兜底）
  await browserRecognizeFallback();
}

function browserRecognizeFallback(){
  return new Promise((resolve)=>{
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if(!SpeechRec){
      setMicStatus('本地语音服务未启动，请直接打字（或先启动 ASR 服务）。');
      document.getElementById('userInput').focus();
      resolve(); return;
    }
    const rec = new SpeechRec();
    rec.lang='fr-FR'; rec.interimResults=false; rec.continuous=false;
    rec.onresult=(e)=>{
      const text=(e.results[0][0].transcript||'').trim();
      if(text){ document.getElementById('userInput').value=text; setMicStatus('识别到：'+text); submitUserText(text); }
      resolve();
    };
    rec.onerror=(e)=>{
      const msg = e.error==='network'
        ? '本地语音服务未启动，浏览器识别也连不上（境外服务）。请直接打字。'
        : '识别未成功（'+e.error+'），请直接打字。';
      setMicStatus(msg); document.getElementById('userInput').focus(); resolve();
    };
    try{ rec.start(); }catch(e){ setMicStatus('请直接打字。'); resolve(); }
  });
}

/* ---------- 复习：4 档评分调 POST /api/cards/{id}/review ---------- */

function playCurrentAudio(){
  const t = state.read.current;
  if(!t) return;
  unlockAudio();
  const btn = document.getElementById('readAudioBtn');
  if(!btn) return;
  if(_ttsAudio){ try{ _ttsAudio.pause(); }catch(e){} _ttsAudio=null; }
  if(t.audio_url){
    btn.classList.add('speaking');
    try{
      const a = new Audio(t.audio_url);
      _ttsAudio = a;
      a.onended = ()=>btn.classList.remove('speaking');
      const fb = ()=>{ btn.classList.remove('speaking'); fallbackSpeak(t.audio_text || t.body_fr || ''); };
      a.onerror = fb;
      a.play().catch(fb);
      return;
    }catch(e){ /* 落到 TTS 兜底 */ }
  }
  speak(btn); // data-text 已在 showReadDetail 设为 audio_text || body_fr
}

// 14) POST /api/input/texts/{id}/collect —— 单收传 words，收全部省略 words

export { _audioUnlocked, _ttsAudio, asrAvailable, browserRecognizeFallback, buildAsrContext, buildAsrHints, checkAsr, fallbackSpeak, mediaRecorder, pickMimeType, playCurrentAudio, speak, toggleMic, transcribeAudio, unlockAudio };
