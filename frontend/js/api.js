// Wave 0 API 层：统一请求封装。
import { notify } from './store.js';

async function apiRequest(path, options){
  options = options||{};
  const res = await fetch(path, {
    method: options.method||'GET',
    headers: { 'Content-Type':'application/json', 'Accept':'application/json' },
    body: options.body===undefined ? undefined : JSON.stringify(options.body)
  });
  let json;
  try { json = await res.json(); }
  catch(e){ throw new Error('服务返回了无法解析的内容'); }
  if(!json || typeof json.code!=='number'){
    throw new Error('服务响应格式异常');
  }
  if(json.code!==0){
    notify(json.message || '操作没成功，稍后再试一下～');
    return null;
  }
  return json.data;
}

/* ---------- 渲染 ---------- */

export { apiRequest };
