const root=document.documentElement;
const catalog=JSON.parse(document.getElementById('tools-data').textContent);
const icons={files:'□',network:'⌁',automation:'◉'};
let lastStatus=null,busy=false;

function card(tool){
  const article=document.createElement('article');article.className='card';article.tabIndex=0;article.setAttribute('role','link');
  const top=document.createElement('div');top.className='cardtop';
  const icon=document.createElement('div');icon.className='icon';icon.setAttribute('aria-hidden','true');icon.textContent=icons[tool.category]||'◇';
  const state=document.createElement('span');state.className='state on';state.textContent=tool.status.toUpperCase();top.append(icon,state);
  const title=document.createElement('h3');title.textContent=tool.name;
  const description=document.createElement('p');description.textContent=tool.description;
  const launch=document.createElement('span');launch.className='launch';launch.textContent='OPEN TOOL →';
  article.append(top,title,description,launch);
  function open(){if(tool.url)window.location.assign(tool.url);else showMessage('This tool has no page configured yet.')}
  article.addEventListener('click',open);article.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();open()}});
  article.addEventListener('pointerdown',()=>article.classList.add('pressed'));['pointerup','pointerleave','pointercancel'].forEach(name=>article.addEventListener(name,()=>article.classList.remove('pressed')));
  return article;
}

document.getElementById('home').replaceChildren(...catalog.slice(0,3).map(card));
document.getElementById('catalog').replaceChildren(...catalog.map(card));
const tabs=[...document.querySelectorAll('.tab')];
function selectView(name,focus=false){tabs.forEach(tab=>{const selected=tab.dataset.view===name;tab.classList.toggle('active',selected);tab.setAttribute('aria-selected',String(selected));tab.tabIndex=selected?0:-1});document.querySelectorAll('.view').forEach(view=>{const selected=view.id===name;view.classList.toggle('active',selected);view.hidden=!selected;view.setAttribute('aria-hidden',String(!selected))});if(focus)tabs.find(tab=>tab.dataset.view===name)?.focus()}
tabs.forEach((tab,index)=>{tab.addEventListener('click',()=>selectView(tab.dataset.view));tab.addEventListener('keydown',event=>{if(['ArrowRight','ArrowLeft','Home','End'].includes(event.key)){event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key==='ArrowRight'?1:tabs.length-1))%tabs.length;selectView(tabs[next].dataset.view,true)}})});

function showMessage(text){const toast=document.getElementById('toast');toast.textContent=text;toast.hidden=false;clearTimeout(showMessage.timer);showMessage.timer=setTimeout(()=>toast.hidden=true,3500)}
function formatUptime(seconds){const minutes=Math.floor(seconds/60),days=Math.floor(minutes/1440),hours=Math.floor(minutes%1440/60);return days?`${days}d ${hours}h`:hours?`${hours}h ${minutes%60}m`:`${minutes}m`}
async function refresh(){if(busy||document.hidden)return;busy=true;try{const response=await fetch('/api/status',{cache:'no-store',signal:AbortSignal.timeout(7000)});if(!response.ok)throw Error('status unavailable');const data=await response.json();lastStatus=data;
  document.getElementById('online').classList.remove('offline');document.querySelector('#online span').textContent='LOCAL / ONLINE';
  document.getElementById('running-count').textContent=String(catalog.length).padStart(2,'0');document.getElementById('memory').textContent=`${Math.round(data.memory_available_mib)}MB`;document.getElementById('storage').textContent=`${data.disk_free_gib.toFixed(1)}GB`;document.getElementById('uptime').textContent=formatUptime(data.uptime_seconds);
  document.getElementById('network-address').textContent=data.hostname.toUpperCase();document.getElementById('service-status').textContent='Running · authenticated';document.getElementById('device-details').textContent=`${data.hostname} · ${data.version} · ${Math.round(data.memory_total_mib)} MiB RAM · ${data.disk_total_gib.toFixed(1)} GiB storage`;
  document.getElementById('activity-time').textContent=`Live readings refreshed · ${new Date().toLocaleTimeString()}`;
}catch(error){document.getElementById('online').classList.add('offline');document.querySelector('#online span').textContent='CORE UNAVAILABLE';document.getElementById('service-status').textContent='Health endpoint did not respond';document.getElementById('activity-time').textContent='Could not reach live device status';}finally{busy=false}}

let frame=0,lastPointer=null;
function paintPointer(){frame=0;if(lastPointer){root.style.setProperty('--mx',`${lastPointer.x}px`);root.style.setProperty('--my',`${lastPointer.y}px`)}}
window.addEventListener('pointermove',event=>{if(event.pointerType==='touch')return;lastPointer={x:event.clientX,y:event.clientY};if(!frame)frame=requestAnimationFrame(paintPointer)},{passive:true});
window.addEventListener('pointerdown',event=>{root.style.setProperty('--mx',`${event.clientX}px`);root.style.setProperty('--my',`${event.clientY}px`);root.style.setProperty('--tap-x',`${event.clientX}px`);root.style.setProperty('--tap-y',`${event.clientY}px`);const pulse=document.querySelector('.pulse');pulse.classList.remove('bloom');void pulse.offsetWidth;pulse.classList.add('bloom')},{passive:true});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh()});refresh();setInterval(refresh,15000);
