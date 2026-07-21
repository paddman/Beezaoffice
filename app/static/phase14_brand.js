(() => {
  let timer=null;
  function safeColor(value,fallback){return /^#[0-9a-f]{6}$/i.test(String(value||''))?value:fallback;}
  function applyBrand(brand){if(!brand)return;const root=document.documentElement;root.style.setProperty('--blue',safeColor(brand.accent_color,'#1268ff'));root.style.setProperty('--blue-2',safeColor(brand.primary_color,'#dc285c'));root.style.setProperty('--bg',safeColor(brand.background_color,'#f5f9ff'));const title=brand.product_name||'BeezaOffice';const company=brand.company_name||title;document.title=`${title} — AI Workforce Command Center`;const name=document.querySelector('.brand strong');if(name)name.textContent=title;const subtitle=document.querySelector('.brand span');if(subtitle)subtitle.textContent=`${company} · AI Workforce OS`;const mark=document.querySelector('.brand-mark');if(mark){if(brand.logo_url){mark.textContent='';mark.style.backgroundImage=`url("${String(brand.logo_url).replace(/["\\]/g,'')}")`;mark.style.backgroundSize='cover';mark.style.backgroundPosition='center';}else{mark.style.backgroundImage='';mark.textContent=title.slice(0,1).toUpperCase();}}if(brand.favicon_url){let icon=document.querySelector('link[rel="icon"]');if(!icon){icon=document.createElement('link');icon.rel='icon';document.head.appendChild(icon);}icon.href=brand.favicon_url;}}
  async function load(){try{const brand=await operatorApi('/api/commercial/brand',{},true);applyBrand(brand);}catch(_error){}}
  function start(){if(timer)clearInterval(timer);timer=setInterval(()=>{if(!document.hidden)void load();},30000);}
  void load();start();
})();
