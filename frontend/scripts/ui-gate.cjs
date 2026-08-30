// UI GATE — the automated browser check this project did not have.
//
// Until 2026-08-28 the frontend had NO automated tests at all, so every UI claim
// rested on someone looking. This drives a real Chromium over every route at four
// viewports and asserts what a human would otherwise have to notice.
//
//   cd frontend
//   npm run build && npx vite preview --port 4173 &
//   node scripts/ui-gate.cjs                                       # local build
//   BASE=https://supply-chain-ui-bhwz.onrender.com node scripts/ui-gate.cjs   # live
//
// It lives under frontend/ and is .cjs on purpose: it uses require(), and Node
// resolves modules from the SCRIPT's directory upward — so it must sit beside the
// node_modules that holds playwright and axe-core. Both are devDependencies here;
// run `npx playwright install chromium` once. Exits non-zero on any failure.
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
//   * a chart legend overlapping its own axis labels. The Price-of-Resilience
//     chart shipped with `k — minimum distinct distributors per BOM (count)`
//     drawn ON TOP of its legend at all four viewports — the whole 286x15px
//     caption inside the legend's box, not a near miss. Recharts stacks a
//     bottom-aligned legend directly beneath the x-axis, which is exactly where
//     an `insideBottom` axis label lands, and neither reserves space from the
//     other. Nothing else here could see it: the label is SVG text, the legend
//     is an HTML sibling, neither overflows any container, and both render at a
//     legal size.
//   * chart legend contrast, hand-rolled ON PURPOSE and only here. axe-core
//     returns "incomplete" rather than a violation for recharts legend labels —
//     it colours them with the SERIES colour via an inline style over several
//     translucent ancestors — so two 12px labels shipped at 3.34:1 and 3.55:1
//     against a 4.5:1 requirement. This walks the ancestor chain compositing
//     alpha, and sidesteps the false-clean trap below by resolving colours
//     through a 1px canvas instead of a regex: the browser paints `oklch()` and
//     everything else correctly, and a colour it genuinely cannot resolve comes
//     back with alpha 0 and is REPORTED, never skipped.
//   * axe-core serious/critical. Do NOT hand-roll contrast for TAILWIND colours:
//     Tailwind v4 emits `oklch()` and a naive rgb parser returned a FALSE CLEAN
//     on 32 real failures.
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
// "Jul 2026" — what a published data vintage has to look like.
const MONTH_YEAR=/\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(19|20)\d{2}\b/;
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
  // Leaked JS placeholders in USER-VISIBLE text. Postmortem 2026-08-28: /frontier
  // shipped the sentence "...instead of the risk-neutral undefined." for real, to
  // production. `${riskNeutral?.n_suppliers}` interpolates the STRING "undefined"
  // when optional chaining short-circuits, and a template literal will happily
  // print it. Nothing in this gate looked at rendered words, so 10 routes x 4
  // viewports of green said nothing about it. Only own text nodes are inspected,
  // so a parent never inherits a child's match; word boundaries keep legitimate
  // prose ("undefined behaviour", "NaN is returned") from tripping it.
  const leaks=all.filter(e=>{const cs=getComputedStyle(e);
    if(cs.display==='none'||cs.visibility==='hidden')return false;
    const own=[...e.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent).join('').trim();
    if(!own)return false;
    return /(^|[\s\[(>:,])(undefined|NaN|null|\[object Object\])([\s\])<:,.]|$)/.test(own);})
    .map(e=>({sel:desc(e),t:(e.textContent||'').trim().slice(0,80)})).slice(0,8);
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
  // ── chart legend vs axis labels ────────────────────────────────────────────
  // Recharts renders the legend as an HTML sibling of the plot SVG. A bottom
  // legend is stacked immediately under the x-axis — the same band an
  // `insideBottom` axis label is placed into — and neither reserves space from
  // the other, so `k — minimum distinct distributors per BOM (count)` was drawn
  // straight through the legend at all four viewports. Take the plot surface by
  // its CLASS: a plain `querySelector('svg')` can return a legend swatch,
  // because recharts emits the legend wrapper BEFORE the surface in the DOM —
  // that is exactly why an earlier hand-check of this reported a clean sheet.
  const legendCharts=[...document.querySelectorAll('.recharts-wrapper')].filter(w=>{
    const lw=w.querySelector('.recharts-legend-wrapper');
    if(!lw)return false; const r=lw.getBoundingClientRect();
    return r.width>1&&r.height>1;});
  // Measure against the legend's ITEM boxes, not the wrapper. The wrapper is a
  // full-width band that includes whatever padding holds the plot off it, so a
  // y-axis tick label — which is centred on its tick and therefore always pokes
  // half its height above the plot area — reads as an overlap against the
  // wrapper while no glyph is anywhere near a legend entry. Items are what the
  // reader actually sees collide.
  const legendOverlap=legendCharts.flatMap(w=>{
    const surface=w.querySelector('svg.recharts-surface');
    const lw=w.querySelector('.recharts-legend-wrapper');
    const items=[...lw.querySelectorAll('li,.recharts-legend-item')];
    const boxes=(items.length?items:[lw]).map(e=>e.getBoundingClientRect())
      .filter(r=>r.width>1&&r.height>1);
    if(!surface||!boxes.length)return [];
    return [...surface.querySelectorAll('text')].map(t=>{
      const r=t.getBoundingClientRect();
      if(r.width<1||r.height<1)return null;
      let worst=null;
      for(const lr of boxes){
        const ox=Math.min(r.right,lr.right)-Math.max(r.left,lr.left);
        const oy=Math.min(r.bottom,lr.bottom)-Math.max(r.top,lr.top);
        if(ox>1&&oy>1&&(!worst||ox*oy>worst.ox*worst.oy))worst={ox,oy};
      }
      return worst
        ?{t:(t.textContent||'').trim().slice(0,44),
          over:`${Math.round(worst.ox)}x${Math.round(worst.oy)}`}:null;
    }).filter(Boolean);
  }).slice(0,6);

  // ── chart legend contrast ──────────────────────────────────────────────────
  // Colours are resolved by PAINTING them, not by parsing them. A hand-written
  // rgb() parser returned a false clean on 32 real failures here once, because
  // Tailwind v4 emits `oklch()`; the canvas resolves every syntax the browser
  // supports, and anything it still cannot resolve comes back with alpha 0 and
  // is REPORTED as unreadable rather than silently skipped.
  const _c=document.createElement('canvas'); _c.width=_c.height=1;
  const _x=_c.getContext('2d',{willReadFrequently:true});
  const paint=css=>{ if(!css)return null;
    _x.clearRect(0,0,1,1); _x.fillStyle='rgba(0,0,0,0)'; _x.fillStyle=css;
    _x.fillRect(0,0,1,1); const d=_x.getImageData(0,0,1,1).data;
    return {r:d[0],g:d[1],b:d[2],a:d[3]/255}; };
  const bgOf=el=>{ const st=[]; let n=el;
    while(n&&n.nodeType===1){ const c=paint(getComputedStyle(n).backgroundColor);
      if(c&&c.a>0)st.push(c); if(c&&c.a>=1)break; n=n.parentElement; }
    st.push(paint(getComputedStyle(document.body).backgroundColor)||{r:255,g:255,b:255,a:1});
    let o=st[st.length-1];
    for(let i=st.length-2;i>=0;i--){ const f=st[i];
      o={r:f.r*f.a+o.r*(1-f.a),g:f.g*f.a+o.g*(1-f.a),b:f.b*f.a+o.b*(1-f.a),a:1}; }
    return o; };
  const lumi=c=>{const f=v=>{v/=255;return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4)};
    return 0.2126*f(c.r)+0.7152*f(c.g)+0.0722*f(c.b)};
  const cratio=(a,b)=>{const l1=lumi(a),l2=lumi(b);
    return (Math.max(l1,l2)+0.05)/(Math.min(l1,l2)+0.05)};
  const legendLabels=[...document.querySelectorAll('.recharts-legend-wrapper *')].filter(e=>{
    const cs=getComputedStyle(e);
    if(cs.display==='none'||cs.visibility==='hidden')return false;
    return [...e.childNodes].some(n=>n.nodeType===3&&n.textContent.trim().length>1);});
  const legendContrast=legendLabels.map(e=>{
    const cs=getComputedStyle(e); const fg=paint(cs.color);
    const t=(e.textContent||'').trim().slice(0,24);
    if(!fg||fg.a===0)return {t,color:cs.color,ratio:null,need:null,why:'colour unreadable'};
    const px=parseFloat(cs.fontSize), bold=parseInt(cs.fontWeight,10)>=700;
    const need=(px>=24||(px>=18.66&&bold))?3:4.5;      // WCAG 1.4.3 large-text carve-out
    const ratio=Math.round(cratio(fg,bgOf(e))*100)/100;
    return ratio<need?{t,color:cs.color,size:cs.fontSize,ratio,need}:null;
  }).filter(Boolean).slice(0,8);

  const svgClip=[...document.querySelectorAll('.recharts-wrapper svg')].flatMap(svg=>{
    const sr=svg.getBoundingClientRect();
    return [...svg.querySelectorAll('text')].map(t=>{const r=t.getBoundingClientRect();
      const over=Math.max(sr.left-r.left, r.right-sr.right, sr.top-r.top, r.bottom-sr.bottom);
      return over>1?{t:t.textContent.slice(0,34),over:Math.round(over)}:null}).filter(Boolean);
  }).slice(0,6);
  return {viewport:vw, scrollerW:scroller.scrollWidth, scrollerCW:scroller.clientWidth,
          overflow, emoji, tiny, leaks, small, bars, svgClip,
          nLegends:legendCharts.length, legendOverlap,
          nLegendLabels:legendLabels.length, legendContrast};
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
      // Only asserted where a legend actually renders — a check that cannot fail
      // is worse than no check, and on the seven routes with no charted legend
      // this would be exactly that.
      if(a.nLegends>0)
        ok(`${route} @${w}: chart legend clear of the axis labels`,
           a.legendOverlap.length===0, JSON.stringify(a.legendOverlap));
      if(vp==='d1440'){
        ok(`${route}: no tiny text / small prose`, a.tiny.length===0,
           a.tiny.length?JSON.stringify(a.tiny.slice(0,4)):'');
        ok(`${route}: no clipped chart labels`, a.svgClip.length===0,
           a.svgClip.length?JSON.stringify(a.svgClip):'');
        if(a.bars.length) ok(`${route}: tallest chart bar >= 8px`, Math.max(...a.bars)>=8, JSON.stringify(a.bars));
        // Contrast does not move with the viewport, so this runs once, beside axe
        // — which does NOT cover these labels (it reports them "incomplete").
        if(a.nLegendLabels>0)
          ok(`${route}: chart legend text meets its WCAG contrast minimum`,
             a.legendContrast.length===0, JSON.stringify(a.legendContrast));
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
      ok(`${route} @${vp.replace(/^\D+/,'')}: no leaked undefined/NaN/null in visible text`,
         a.leaks.length===0, a.leaks.length?JSON.stringify(a.leaks.slice(0,3)):'');
      if(vp==='m390') ok(`${route} @390: touch targets >= 44px`, a.small.length===0,
         a.small.length?JSON.stringify(a.small.slice(0,4)):'');
      try{
        fs.mkdirSync(path.join(__dirname,'gate-shots'),{recursive:true});
        await p.screenshot({path:path.join(__dirname,'gate-shots',
          `${route.replace(/\W+/g,'')||'root'}-${vp}.png`)});
      }catch{}
    }
  }
  // ── /optimize solver options: the flags must reach the API ────────────────
  // Until 2026-08-28 `optimizeAPI.vrp()` posted NO BODY, so `us_only` and
  // `graph_aware` were unreachable from the UI — the endpoint parsed two flags
  // that nothing could ever set, and every plan the site ever showed was solved
  // with both off. These assertions watch the WIRE, not the page text: a toggle
  // that renders "On" while sending nothing is precisely the failure being
  // guarded, and no amount of markup checking would catch it.
  //
  // The last assertion is the honest-UI one. A re-run must visibly resolve: the
  // cards change, or the page says the answer did not change, or it reports an
  // error. Silently returning the same screen is not an allowed outcome —
  // `graph_aware` genuinely is a no-op on some carts (raw betweenness runs small
  // across this catalogue) and the page has to say so rather than look broken.
  await p.setViewportSize({width:1440,height:900});
  await p.goto(L+'/optimize',{waitUntil:'networkidle',timeout:180000});
  await p.waitForTimeout(6000);
  ok('/optimize: solver options panel renders',
     await p.locator('[data-testid="solver-options"]').count()===1);
  const usOnly=p.locator('[data-testid="toggle-us-only"]');
  const graphAware=p.locator('[data-testid="toggle-graph-aware"]');
  ok('/optimize: both solver flags default to off',
     (await usOnly.getAttribute('aria-pressed'))==='false' &&
     (await graphAware.getAttribute('aria-pressed'))==='false',
     'defaults must match the historical run — nothing published may move on load');
  const beforeCards=await p.locator('[data-testid="route-cards"]').innerText().catch(()=>'');
  const vrpBodies=[];
  const watchVrp=r=>{if(r.url().includes('/optimize/vrp')&&r.method()==='POST')vrpBodies.push(r.postData()||'')};
  p.on('request',watchVrp);
  await usOnly.click();
  await p.waitForTimeout(2500);
  ok('/optimize: toggling a flag re-solves', vrpBodies.length>=1, JSON.stringify(vrpBodies));
  ok('/optimize: the POST body carries us_only=true',
     /"us_only"\s*:\s*true/.test(vrpBodies.join('')), JSON.stringify(vrpBodies));
  await p.waitForFunction(()=>!/Solving sourcing MILP/i.test(document.body.innerText),
                          null,{timeout:180000});
  await p.waitForTimeout(2000);
  p.off('request',watchVrp);
  ok('/optimize: the toggle reflects the run it produced',
     (await usOnly.getAttribute('aria-pressed'))==='true');
  const afterCards=await p.locator('[data-testid="route-cards"]').innerText().catch(()=>'');
  const saidNoChange=await p.locator('[data-testid="solver-options-no-change"]').count();
  const saidError=await p.locator('[data-testid="optimize-error"]').count();
  ok('/optimize: a re-run resolves visibly (new plans, "same answer", or an error)',
     (beforeCards!==afterCards)||saidNoChange>0||saidError>0,
     `cardsChanged=${beforeCards!==afterCards} noChangeNotice=${saidNoChange} error=${saidError}`);

  // ── the macro stress banner must publish its DATA VINTAGE ─────────────────
  // The percentage in this banner is scored from ONE row of a MONTHLY feature
  // frame and prices a real stock-out surcharge into the plan above it. Until
  // 2026-08-28 it was rendered with no date at all, so a reading describing a
  // month already two months gone read as the state of the world right now.
  // Asserted only when a probability is actually on screen — when the regime
  // model is unavailable the banner prints "unavailable" and there is no claim
  // to qualify, and a check that cannot fail is worse than no check.
  {
    const sv=await p.evaluate(()=>{
      const px=e=>e?parseFloat(getComputedStyle(e).fontSize):null;
      const c=document.querySelector('[data-testid="stress-claim"]');
      const v=document.querySelector('[data-testid="stress-vintage"]');
      const n=document.querySelector('[data-testid="stress-vintage-note"]');
      return {present:!!document.querySelector('[data-testid="macro-stress-banner"]'),
              claim:(c&&c.innerText||'').trim(), claimPx:px(c),
              vintage:(v&&v.innerText||'').trim(), vintagePx:px(v),
              note:(n&&n.innerText||'').trim(), notePx:px(n),
              vintageVisible:!!(v&&v.getClientRects().length)};
    });
    if(sv.present && /\d/.test(sv.claim)){
      ok('/optimize: the macro stress banner names the observation month',
         sv.vintageVisible && MONTH_YEAR.test(sv.vintage), JSON.stringify(sv));
      ok('/optimize: the stress vintage is not smaller print than the % it qualifies',
         sv.vintagePx!==null && sv.claimPx!==null && sv.vintagePx>=sv.claimPx, JSON.stringify(sv));
      ok('/optimize: the banner says the surcharge is priced off that observation month',
         /observation month/i.test(sv.note) && sv.notePx>=sv.claimPx, JSON.stringify(sv));
    }
  }
  {
    const a=await p.evaluate(AUDIT);
    ok('/optimize after toggling a flag: no horizontal overflow', a.overflow.length===0,
       JSON.stringify(a.overflow.slice(0,3)));
    await p.addScriptTag({content:axeSource});
    const ax=await p.evaluate(async()=>{const r=await window.axe.run(document,
      {runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}});
      return r.violations.map(v=>({id:v.id,impact:v.impact,n:v.nodes.length,
        first:(v.nodes[0]&&v.nodes[0].html||'').slice(0,90)}))});
    const serious=ax.filter(v=>v.impact==='serious'||v.impact==='critical');
    ok('/optimize after toggling a flag: no serious/critical axe violations',
       serious.length===0, serious.map(v=>`${v.id}(${v.n}) ${v.first}`).join(' || '));
  }

  // ── /model-card: the same figure, the same rule ───────────────────────────
  // The model card is the page a reader lands on to check whether a number is
  // trustworthy, so it is the last place a probability may appear undated. The
  // observation month is rendered at the SAME font size as the percentage, on
  // the same line — this asserts that, in pixels, rather than trusting a class
  // name. A vintage set in smaller print than its claim has shipped from this
  // repo before and is the specific regression being guarded.
  await p.setViewportSize({width:1440,height:900});
  await p.goto(L+'/model-card',{waitUntil:'networkidle',timeout:180000});
  await p.waitForTimeout(6000);
  {
    const figs=await p.locator('[data-testid="stress-figure"]').count();
    ok('/model-card: the macro stress figure renders', figs===1,
       'without it every vintage assertion below would be vacuous');
    if(figs===1){
      const v=await p.evaluate(()=>{
        const px=e=>e?parseFloat(getComputedStyle(e).fontSize):null;
        const f=document.querySelector('[data-testid="stress-probability"]');
        const d=document.querySelector('[data-testid="stress-vintage"]');
        return {claim:(f&&f.innerText||'').trim(), claimPx:px(f),
                vintage:(d&&d.innerText||'').trim(), vintagePx:px(d),
                visible:!!(d&&d.getClientRects().length)};
      });
      ok('/model-card: the stress probability is printed with a visible vintage',
         v.visible, JSON.stringify(v));
      if(/\d/.test(v.claim)){
        ok('/model-card: the vintage names the observation month',
           MONTH_YEAR.test(v.vintage), JSON.stringify(v));
        ok('/model-card: the vintage is not smaller print than the figure it qualifies',
           v.vintagePx!==null && v.claimPx!==null && v.vintagePx>=v.claimPx, JSON.stringify(v));
      }
    }
  }

  console.log('\nPAGE/CONSOLE ERRORS:', errs.length?[...new Set(errs)].slice(0,6):'none');
  ok('no console or page errors', errs.length===0);
  fs.writeFileSync(path.join(__dirname,'gate-report.json'), JSON.stringify(report,null,2));
  console.log(`\n════ ${pass} passed, ${fail} failed ════`);
  await b.close();
  process.exit(fail?1:0);
})().catch(e=>{console.error('FATAL',e);process.exit(2);});
