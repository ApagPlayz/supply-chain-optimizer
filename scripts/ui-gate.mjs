// UI GATE — the automated browser check this project did not have.
//
// Until 2026-08-28 the frontend had NO automated tests at all, so every UI claim
// rested on someone looking. This drives a real Chromium over every route at four
// viewports and asserts what a human would otherwise have to notice.
//
//   cd frontend && npm run build && npx vite preview --port 4173
//   node scripts/ui-gate.mjs                       # local build
//   BASE=https://supply-chain-ui-bhwz.onrender.com node scripts/ui-gate.mjs   # live
//
// Requires `playwright` and `axe-core` (npm i -D playwright axe-core, then
// `npx playwright install chromium`). Exits non-zero on any failure.
//
// WHAT IT CHECKS, and why each one is here — every check is a postmortem:
//   * horizontal overflow, measured against the REAL scroll container. Every route
//     renders inside `overflow-y-auto`, so the document never scrolls and
//     `document.scrollWidth` reports a false clean.
//   * emoji anywhere in the product UI (owner's standing rule).
//   * text under 11px, and prose under 12px.
//   * clipped SVG chart labels — `scrollWidth > clientWidth` NEVER fires on SVG
//     text, which is why three clipped axis labels shipped unnoticed.
//   * chart geometry: the TALLEST bar must clear 8px. A short bar is honest when
//     its value is small; a chart whose tallest bar is a hairline is a bug
//     (`barCategoryGap` as a raw number produced 0.7px bars).
//   * touch targets >= 44px, with WCAG 2.5.5's inline-link exemption.
//   * axe-core serious/critical. Do NOT hand-roll contrast: Tailwind v4 emits
//     `oklch()` and a naive rgb parser returned a FALSE CLEAN on 32 real failures.
//   * a route rendering the 404 page FAILS. A missing route trivially passes every
//     other check, so without this the gate reports a clean sheet on a dead page.
//
// VIEWPORTS: 390 / 768 / 1280 / 1440. 1280 is not decorative — a tenth nav link
// pushed the desktop row to 1371px while it collapsed only below `xl` (1280), so
// the bug lived in the gap between a breakpoint and the width content needs.
// Test AT the breakpoints, not around them.

// Final pre-push gate. Drives a real browser against a LOCAL build with the live
// API proxied in, across every route and viewport, and asserts the specific
// regressions fixed today plus the global quality bars.
const { chromium } = require('playwright');
const fs=require('fs'), path=require('path');
const axeSource = fs.readFileSync(require.resolve('axe-core/axe.min.js'),'utf8');
const L=process.env.BASE||'http://localhost:4173';
const API='https://supply-chain-api-qy8x.onrender.com';
const ROUTES=['/dashboard','/map','/components','/cart','/optimize','/benchmark','/resilience','/frontier','/model-card','/newsvendor'];
let pass=0, fail=0;
const ok=(n,c,d='')=>{c?pass++:fail++; console.log(`${c?'PASS':'FAIL'}  ${n}${d?'\n        '+d:''}`)};

const AUDIT=()=>{
  const vw=window.innerWidth;
  const desc=e=>{let s=e.tagName.toLowerCase();const c=String(e.className||'');
    if(c&&typeof e.className==='string')s+='.'+c.split(/\s+/).slice(0,5).join('.');return s.slice(0,110)};
  const scroller=[...document.querySelectorAll('body *')]
    .filter(e=>e.scrollHeight>e.clientHeight+2&&/auto|scroll/.test(getComputedStyle(e).overflowY))
    .sort((a,b)=>b.scrollHeight-a.scrollHeight)[0]||document.scrollingElement;
  const all=[...document.querySelectorAll('body *')];
  // horizontal overflow: any element crossing the viewport that is NOT inside an
  // element that legitimately scrolls horizontally (tables are allowed to)
  const overflow=all.filter(e=>{
    const r=e.getBoundingClientRect();
    if(!(r.width>0&&(r.right>vw+1||r.left<-1)))return false;
    if(e.closest('.maplibregl-map,.mapboxgl-map'))return false;     // world markers
    let n=e.parentElement;
    while(n&&n!==document.body){ if(/auto|scroll/.test(getComputedStyle(n).overflowX))return false; n=n.parentElement; }
    return true;
  }).map(e=>({sel:desc(e),right:Math.round(e.getBoundingClientRect().right),
              text:(e.textContent||'').trim().slice(0,40)})).slice(0,6);
  const emoji=all.filter(e=>[...e.childNodes].some(n=>n.nodeType===3&&
      /[\u{1F300}-\u{1FAFF}\u{2699}\u{26A0}\u{1F5FA}]/u.test(n.textContent)))
      .map(e=>(e.textContent||'').trim().slice(0,28)).slice(0,8);
  const tiny=all.filter(e=>{const cs=getComputedStyle(e);
    if(cs.display==='none'||cs.visibility==='hidden')return false;
    const own=[...e.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent).join('').trim();
    if(!own)return false;
    const px=parseFloat(cs.fontSize);
    // <11px is too small for anything. A 12px caption is a normal pattern; the
    // anti-pattern the design database names is sub-12px BODY text.
    return px<11 || (px<12 && own.length>60);})
    .map(e=>({sel:desc(e),size:getComputedStyle(e).fontSize,
              t:(e.textContent||'').trim().slice(0,30)})).slice(0,8);
  const small=[...document.querySelectorAll('button,a,[role=button],select,summary')].filter(e=>{
    const cs=getComputedStyle(e); if(cs.display==='none'||cs.visibility==='hidden')return false;
    if(e.closest('.maplibregl-map'))return false;
    if(e.ownerSVGElement||e.closest('svg'))return false;
    if(e.tagName==='A'&&e.closest('p,li,td'))return false;
    const r=e.getBoundingClientRect(); return r.width>0&&r.height>0&&(r.width<44||r.height<44);})
    .map(e=>{const r=e.getBoundingClientRect();
      return{sel:desc(e),w:Math.round(r.width),h:Math.round(r.height),t:(e.textContent||'').trim().slice(0,24)}}).slice(0,10);
  const bars=[...document.querySelectorAll('.recharts-bar-rectangle path,.recharts-rectangle')]
    .map(e=>Math.round(e.getBoundingClientRect().height));
  const svgClip=[...document.querySelectorAll('.recharts-wrapper svg')].flatMap(svg=>{
    const sr=svg.getBoundingClientRect();
    return [...svg.querySelectorAll('text')].map(t=>{const r=t.getBoundingClientRect();
      const over=Math.max(sr.left-r.left, r.right-sr.right, sr.top-r.top, r.bottom-sr.bottom);
      return over>1?{t:t.textContent.slice(0,34),over:Math.round(over)}:null}).filter(Boolean);
  }).slice(0,6);
  return {viewport:vw, scrollerW:scroller.scrollWidth, scrollerCW:scroller.clientWidth,
          overflow, emoji, tiny, small, bars, svgClip};
};

(async()=>{
  const b=await chromium.launch();
  const ctx=await b.newContext({viewport:{width:1440,height:900}});
  await ctx.route('**/api/v1/**', async r=>{const q=r.request();
    const u=API+'/api/v1'+q.url().split('/api/v1')[1];
    try{const res=await ctx.request.fetch(u,{method:q.method(),headers:q.headers(),
      data:q.postData()||undefined,timeout:180000});
      r.fulfill({status:res.status(),headers:{...res.headers(),'access-control-allow-origin':'*'},body:await res.body()});}
    catch{r.abort();}});
  const p=await ctx.newPage(); p.setDefaultTimeout(180000);
  const errs=[]; p.on('pageerror',e=>errs.push(String(e).slice(0,140)));
  p.on('console',m=>{if(m.type()==='error')errs.push('console: '+m.text().slice(0,140))});

  // ---------- document head ----------
  await p.goto(L+'/login',{waitUntil:'domcontentloaded'});
  const head=await p.evaluate(()=>({title:document.title,
    desc:(document.querySelector('meta[name=description]')||{}).content||null,
    og:[...document.querySelectorAll('meta[property^="og:"]')].map(m=>m.getAttribute('property'))}));
  ok('head: real <title>', head.title && !/^frontend$/i.test(head.title), JSON.stringify(head.title));
  ok('head: meta description', !!head.desc);
  ok('head: open graph tags', head.og.length>=3, head.og.join(','));

  await p.getByRole('button',{name:/demo login/i}).click();
  await p.waitForURL('**/dashboard',{timeout:180000});

  const report={};
  for(const route of ROUTES){
    // 1280 is here because a real regression hid exactly there: the nav collapsed
    // below Tailwind's `xl` (1280px) while the full row needed 1371px, so at
    // precisely 1280 it rendered into a bar 91px too narrow. Testing 390/768/1440
    // missed it completely — the bug lived in the gap between a breakpoint and the
    // width the content actually needs. Test AT the breakpoints, not around them.
    for(const [vp,w,h] of [['d1440',1440,900],['x1280',1280,800],['t768',768,1024],['m390',390,844]]){
      await p.setViewportSize({width:w,height:h});
      await p.goto(L+route,{waitUntil:'networkidle',timeout:180000});
      await p.waitForTimeout(vp==='d1440'?6000:3000);
      await p.evaluate(async()=>{const t=[...document.querySelectorAll('body *')]
        .filter(e=>e.scrollHeight>e.clientHeight+2&&/auto|scroll/.test(getComputedStyle(e).overflowY))
        .sort((a,b)=>b.scrollHeight-a.scrollHeight)[0]; if(!t)return;
        for(let y=0;y<=Math.min(t.scrollHeight,14000);y+=500){t.scrollTop=y;await new Promise(r=>setTimeout(r,45));}
        t.scrollTop=0;await new Promise(r=>setTimeout(r,350));});
      const notFound=await p.evaluate(()=>/page not found|404/i.test(document.body.innerText.slice(0,400)));
      if(notFound){ ok(`${route} @${w}: route exists`, false, 'renders the 404 page'); continue; }
      const a=await p.evaluate(AUDIT);
      (report[route]??={})[vp]=a;
      ok(`${route} @${w}: no horizontal overflow`, a.overflow.length===0,
         a.overflow.length?JSON.stringify(a.overflow.slice(0,3)):'');
      ok(`${route} @${w}: no emoji`, a.emoji.length===0, a.emoji.join(' | '));
      if(vp==='d1440'){
        ok(`${route}: no tiny text / small prose`, a.tiny.length===0,
           a.tiny.length?JSON.stringify(a.tiny.slice(0,4)):'');
        ok(`${route}: no clipped chart labels`, a.svgClip.length===0,
           a.svgClip.length?JSON.stringify(a.svgClip):'');
        if(a.bars.length) ok(`${route}: tallest chart bar >= 8px`, Math.max(...a.bars)>=8, JSON.stringify(a.bars));
        await p.addScriptTag({content:axeSource});
        const ax=await p.evaluate(async()=>{const r=await window.axe.run(document,
          {runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}});
          return r.violations.map(v=>({id:v.id,impact:v.impact,n:v.nodes.length,
            first:(v.nodes[0]&&v.nodes[0].html||'').slice(0,90)}))});
        report[route].axe=ax;
        const serious=ax.filter(v=>v.impact==='serious'||v.impact==='critical');
        ok(`${route}: no serious/critical axe violations`, serious.length===0,
           serious.map(v=>`${v.id}(${v.n}) ${v.first}`).join(' || '));
      }
      if(vp==='m390') ok(`${route} @390: touch targets >= 44px`, a.small.length===0,
         a.small.length?JSON.stringify(a.small.slice(0,4)):'');
      try{
        fs.mkdirSync(path.join(__dirname,'gate-shots'),{recursive:true});
        await p.screenshot({path:path.join(__dirname,'gate-shots',
          `${route.replace(/\W+/g,'')||'root'}-${vp}.png`)});
      }catch{}
    }
  }
  console.log('\nPAGE/CONSOLE ERRORS:', errs.length?[...new Set(errs)].slice(0,6):'none');
  ok('no console or page errors', errs.length===0);
  fs.writeFileSync(path.join(__dirname,'gate-report.json'), JSON.stringify(report,null,2));
  console.log(`\n════ ${pass} passed, ${fail} failed ════`);
  await b.close();
  process.exit(fail?1:0);
})().catch(e=>{console.error('FATAL',e);process.exit(2);});
