'use strict';
// Free GitHub Pages edition. Data are built server-side by scheduled Actions;
// the browser never scrapes other websites or shows invented prayer times.
const PRAYERS = [
  {key:'fajr',label:'الفجر'}, {key:'dhuhr',label:'الظهر'},
  {key:'asr',label:'العصر'}, {key:'maghrib',label:'المغرب'},
  {key:'isha',label:'العشاء'}
];
const EMPTY = () => Object.fromEntries(PRAYERS.map(p => [p.key, null]));
const DIRECTORY = [
  {id:'huda',name_ar:'مسجد الهدى',name_en:'Al-Huda Islamic Centre',area:'Broomhall',address:'Hanover St, Sheffield S3 7WT',timetable_url:'https://masjidhudasheff.com/'},
  {id:'sunnah',name_ar:'مسجد السنة',name_en:'Masjid Sunnah Sheffield',area:'Pitsmoor',address:'18 Kirk St, Sheffield S4 7JX',timetable_url:'https://masjidsunnahsheffield.co.uk/'},
  {id:'mwh',name_ar:'مسجد بيت الرعاية الإسلامية',name_en:'Muslim Welfare House',area:'Broomhall',address:'10-12 Severn Rd, Sheffield S10 2SU',timetable_url:'https://www.mwhs.org.uk/'},
  {id:'baitul',name_ar:'مسجد بيت المكرم',name_en:'Baitul Mukarram Jame Masjid',area:'Highfield',address:'358 London Rd, Sheffield S2 4NB',timetable_url:'https://www.baitulmukarramjamemasjid.com/'},
  {id:'umar',name_ar:'مسجد عمر',name_en:'Masjid Umar (YMA)',area:'Pitsmoor',address:'306 Barnsley Rd, Sheffield S4 7AH',timetable_url:'https://www.ymasheffield.org/prayer-timetable'},
  {id:'madina',name_ar:'مسجد المدينة',name_en:'Madina Masjid Sheffield',area:'Lowfield',address:'24 Wolseley Rd, Sheffield S8 0ZU',timetable_url:'https://mawaqit.net/en/madina-masjid-sheffield-sheffield-s8-0zu-united-kingdom'},
  {id:'grand',name_ar:'مسجد شيفلد الكبير',name_en:'Sheffield Grand Mosque',area:'Grimesthorpe',address:'Grimesthorpe Rd, Sheffield S4 8DE',timetable_url:'https://emaantrust.mosqueprayertimes.org/prayer-times'},
  {id:'industry',name_ar:'مسجد الجامع المركزي',name_en:'Markazi Jamia Mosque',area:'Darnall',address:'13 Industry Rd, Sheffield S9 5FP',timetable_url:'https://www.industryroadmosque.com/prayer-times/'}
];
const OFFLINE_MOSQUES = DIRECTORY.map(m => ({...m,adhan:EMPTY(),iqamah:EMPTY(),status:'needs_review',note:'المصدر الرسمي متاح عبر الرابط. بيانات النشر غير متوفرة.',source_date:null,checked_at:null}));
const offlinePayload = {date:'',timezone:'Europe/London',generated_at:null,mosques:OFFLINE_MOSQUES};
const MAX_DATA_AGE_MS = 5 * 60 * 60 * 1000; // three-hour scheduler plus margin
const state = {payload:offlinePayload, query:'', filter:'all', prayer:'all', mode:'iqamah', offline:true};
const $ = id => document.getElementById(id);
const escapeHtml = input => String(input ?? '').replace(/[&<>"']/g, x => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));
const londonTime = (v = new Date()) => new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/London',hour:'2-digit',minute:'2-digit',hour12:false}).format(v);
const londonDate = (v = new Date()) => {
  const parts = new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/London',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(v);
  const fields = Object.fromEntries(parts.filter(p => p.type !== 'literal').map(p=>[p.type,p.value]));
  return `${fields.year}-${fields.month}-${fields.day}`;
};
function freshPublication(){
  if(state.offline || state.payload.date !== londonDate()) return false;
  const published = Date.parse(state.payload.generated_at ?? '');
  const age = Date.now() - published;
  return Number.isFinite(published) && age >= -10*60*1000 && age <= MAX_DATA_AGE_MS;
}
const approvedRow = m => freshPublication() && m.source_date === state.payload.date &&
  ['updated','partial'].includes(m.status);
const hasTime = m => Object.values(m.iqamah || {}).some(Boolean);
const usableRow = m => approvedRow(m) && hasTime(m);
const clockFromISO = v => {const d = new Date(v||'');return Number.isNaN(d.getTime()) ? '' : londonTime(d);};
function parseMinutes(v){
  if(!/^\d\d:\d\d$/.test(v ?? ''))return null;
  const [h,m]=v.split(':').map(Number);
  return h<=23&&m<=59?h*60+m:null;
}
function safeUrl(url){
  try{const v=new URL(url); return ['https:','http:'].includes(v.protocol)?v.toString():'#';}
  catch{return '#';}
}
function mapLink(m){return 'https://www.google.com/maps/search/?api=1&query='+encodeURIComponent(m.address||m.name_en+' Sheffield');}
const statuses = {
  updated:['مواعيد مؤرخة اليوم','status-updated'],
  partial:['مواعيد جزئية اليوم','status-partial'],
  undated:['جدول غير مؤرخ','status-partial'],
  needs_review:['بحاجة للتحقق','status-needs_review'],
  not_connected:['قيد الربط','status-not_connected']
};
function statusHtml(m){
  const s = !freshPublication() && ['updated','partial'].includes(m.status) ?
    ['البيانات قديمة','status-needs_review'] : (statuses[m.status]||statuses.not_connected);
  return `<span class="status-badge ${s[1]}" title="${escapeHtml(m.note||'')}">${s[0]}</span>`;
}
function sourceNote(m){
  const checked=m.checked_at||m.updated_at;
  const parts=[m.note,m.source_date?`تاريخ الجدول: ${m.source_date}`:null,checked?`آخر فحص: ${clockFromISO(checked)}`:null];
  return parts.filter(Boolean).join(' · ') || 'اطلع على المصدر الرسمي';
}
function formatCell(m,p,mobile=false){
  const trust = approvedRow(m);
  const main = trust ? m[state.mode]?.[p] : null;
  const secondary = trust ? m[state.mode==='iqamah'?'adhan':'iqamah']?.[p] : null;
  const showTime = main && parseMinutes(main)!==null;
  const time = showTime ? escapeHtml(main) : '<span class="unknown-time">—</span>';
  const sub = secondary && parseMinutes(secondary)!==null ? (state.mode==='iqamah'?'بدء ':'إقامة ')+escapeHtml(secondary) : 'غير متوفر';
  if(mobile)return `<span class="p-label">${PRAYERS.find(x=>x.key===p)?.label}</span><span class="p-time">${time}</span><span class="p-sub">${sub}</span>`;
  return `<span class="prayer-time">${time}</span><span class="prayer-sub">${sub}</span>`;
}
function listFiltered(){
  const q=state.query.trim().toLowerCase();
  const found=state.payload.mosques.filter(m=>{
    const matches=!q||[m.name_ar,m.name_en,m.area,m.address].some(s=>(s||'').toLowerCase().includes(q));
    const inStatus=state.filter==='all'||(state.filter==='available'&&usableRow(m))||(state.filter==='pending'&&!usableRow(m));
    return matches&&inStatus;
  });
  if(state.prayer!=='all')found.sort((a,b)=>{
    const aTime=approvedRow(a)?parseMinutes(a[state.mode]?.[state.prayer]):null;
    const bTime=approvedRow(b)?parseMinutes(b[state.mode]?.[state.prayer]):null;
    return (aTime===null?Infinity:aTime)-(bTime===null?Infinity:bTime);
  });
  return found;
}
function nextIqamah(){
  if(!freshPublication())return null;
  const now=parseMinutes(londonTime());
  const options=[];
  for(const m of state.payload.mosques){
    if(!approvedRow(m))continue;
    for(const prayer of PRAYERS){
      const at=m.iqamah?.[prayer.key],minutes=parseMinutes(at);
      if(minutes!==null&&minutes>=now) options.push({m,prayer,at,minutes});
    }
  }
  return options.sort((a,b)=>a.minutes-b.minutes)[0]||null;
}
function renderSummary(){
  const data=state.payload;
  $('mosques-count').textContent=String(data.mosques.length);
  $('verified-count').textContent=String(data.mosques.filter(usableRow).length);
  const next=nextIqamah();
  $('next-prayer').textContent=next?`${next.prayer.label} ${next.at}`:'—';
  $('next-description').textContent=next?`${next.m.name_ar} · أقرب إقامة منشورة اليوم`:'لا تتوفر إقامة قادمة مؤكدة اليوم';
  $('source-status').textContent=state.offline?'بيانات النشر غير متاحة':freshPublication()?'آخر نسخة منشورة متاحة':'البيانات قديمة';
  $('last-checked').textContent=data.generated_at ?
    `آخر بناء: ${clockFromISO(data.generated_at)} · التحديث الآلي كل 3 ساعات تقريبًا`:'';
}
function renderBanner(){
  const banner=$('information-banner');
  banner.hidden=false;
  if(state.offline){
    banner.textContent='لم نتمكن من تحميل ملف المواعيد. روابط المساجد الرسمية متاحة أدناه؛ لا توجد أوقات معتمدة للعرض.';
  }else if(state.payload.date!==londonDate()){
    banner.textContent='البيانات ليست بتاريخ شيفلد اليوم؛ أخفينا المواعيد إلى أن تصل نسخة جديدة.';
  }else if(!freshPublication()){
    banner.textContent='آخر تحديث قديم أو ساعة الجهاز غير متطابقة. أخفينا الأوقات احتياطًا؛ افتح المصدر الرسمي.';
  }else if(!state.payload.mosques.some(usableRow)){
    banner.textContent='لم تتوفر أوقات إقامة مؤرخة من أي مصدر حاليًا. يمكنك فتح مواقع المساجد الرسمية من الجدول.';
  }else{
    banner.hidden=true;
  }
}
function renderTable(list,prayers){
  $('table-head').innerHTML=`<tr><th>المسجد والمنطقة</th>${prayers.map(p=>`<th>${p.label}</th>`).join('')}<th>المصدر</th></tr>`;
  $('table-body').innerHTML=list.map(m=>`<tr><td><div class="masjid-name"><strong>${escapeHtml(m.name_ar)}</strong><span>${escapeHtml(m.name_en)}</span></div><span class="masjid-area">⌖ ${escapeHtml(m.area)}</span></td>${prayers.map(p=>`<td class="${state.prayer!=='all'?'focus-cell':''}">${formatCell(m,p.key)}</td>`).join('')}<td class="status-cell">${statusHtml(m)}<a class="source-link" href="${escapeHtml(safeUrl(m.timetable_url))}" target="_blank" rel="noopener noreferrer">المصدر الرسمي ↗</a><span class="source-small">${escapeHtml(sourceNote(m))}</span></td></tr>`).join('');
}
function renderMobile(list,prayers){
  $('mobile-cards').innerHTML=list.map(m=>`<article class="masjid-card"><div class="masjid-card-head"><div><h3>${escapeHtml(m.name_ar)}</h3><div class="en-name">${escapeHtml(m.name_en)}</div><p class="area-name">⌖ ${escapeHtml(m.area)}</p></div>${statusHtml(m)}</div><div class="mobile-grid ${prayers.length===1?'focus-one':''}">${prayers.map(p=>`<div class="mobile-prayer ${state.prayer!=='all'?'is-focus':''}">${formatCell(m,p.key,true)}</div>`).join('')}</div><div class="card-footer"><div class="card-links"><a href="${escapeHtml(safeUrl(m.timetable_url))}" target="_blank" rel="noopener noreferrer">المصدر الرسمي ↗</a><a href="${escapeHtml(mapLink(m))}" target="_blank" rel="noopener noreferrer">الموقع ⌖</a></div><span class="source-small">${escapeHtml(m.source_type==='pdf'?'PDF':'موقع المسجد')}</span></div>${sourceNote(m)?`<p class="card-note">${escapeHtml(sourceNote(m))}</p>`:''}</article>`).join('');
}
function render(){
  renderSummary();renderBanner();
  const list=listFiltered(),prayers=PRAYERS.filter(p=>state.prayer==='all'||p.key===state.prayer);
  $('results-label').textContent=`عرض ${list.length} من ${state.payload.mosques.length} مساجد · ${state.mode==='iqamah'?'أوقات الإقامة':'أوقات دخول الصلاة'}`;
  $('no-results').hidden=list.length!==0;
  if(!list.length){$('table-body').innerHTML='';$('mobile-cards').innerHTML='';return;}
  renderTable(list,prayers);renderMobile(list,prayers);
}
function updateClock(){
  $('london-clock').textContent=londonTime();
  $('today-label').textContent=new Intl.DateTimeFormat('ar-GB',{timeZone:'Europe/London',weekday:'long',day:'numeric',month:'long',year:'numeric'}).format(new Date());
  render(); // also hides times promptly when the date or five-hour freshness expires
}
function bindControls(){
  $('search').addEventListener('input',e=>{state.query=e.target.value;render();});
  $('status-filter').addEventListener('change',e=>{state.filter=e.target.value;render();});
  for(const mode of ['iqamah','adhan'])$('mode-'+mode).addEventListener('click',()=>{
    state.mode=mode;
    for(const k of ['iqamah','adhan']){$('mode-'+k).classList.toggle('active',k===mode);$('mode-'+k).setAttribute('aria-pressed',String(k===mode));}
    render();
  });
  for(const button of document.querySelectorAll('[data-prayer]'))button.addEventListener('click',()=>{
    state.prayer=button.dataset.prayer;
    for(const b of document.querySelectorAll('[data-prayer]'))b.classList.toggle('selected',b.dataset.prayer===state.prayer);
    render();
  });
  $('refresh-times').addEventListener('click',refreshPublishedData);
}
async function refreshPublishedData(){
  const button=$('refresh-times');
  button.disabled=true;button.textContent='جارٍ التحميل…';
  try{
    // Relative URL works both at a user site root and at /<repository>/.
    const url=new URL('data/mosques.json',document.baseURI);
    url.searchParams.set('v',String(Date.now()));
    const response=await fetch(url.toString(),{cache:'no-store'});
    if(!response.ok)throw new Error(`HTTP ${response.status}`);
    const body=await response.json();
    if(body.demo===true || body.timezone!=='Europe/London' || !Array.isArray(body.mosques) ||
       !/^\d{4}-\d\d-\d\d$/.test(body.date || '') || !body.generated_at || body.mosques.length>250) throw new Error('Invalid data');
    state.payload=body;state.offline=false;
  }catch(err){
    console.info('Published mosque times could not be retrieved:',err.message);
    // Never keep possibly stale values when the JSON update fails.
    state.payload=offlinePayload;state.offline=true;
  }finally{
    button.disabled=false;button.textContent='↻ تحميل أحدث نسخة';render();
  }
}
function boot(){
  bindControls();updateClock();
  refreshPublishedData();
  setInterval(updateClock,60*1000);
  setInterval(refreshPublishedData,30*60*1000);
}
boot();
