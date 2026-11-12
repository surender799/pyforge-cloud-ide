const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function notice(message,error=false){const n=$('#notice');n.textContent=message;n.className=error?'error':'';n.style.display='block';}
async function api(path,method='GET',body){const r=await fetch(path,{method,headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});const text=await r.text();let data;try{data=JSON.parse(text)}catch{data={detail:text}}if(!r.ok)throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail||data));return data;}
function action(selector,fn){$(selector).addEventListener('click',async e=>{e.preventDefault();const b=e.currentTarget;b.disabled=true;try{await fn()}catch(e){notice(e.message,true)}finally{b.disabled=false}})}
function badge(state){return `<span class="badge ${esc(state)}">${esc(state)}</span>`}
window.addEventListener('unhandledrejection',e=>{notice(e.reason?.message||String(e.reason),true)});
