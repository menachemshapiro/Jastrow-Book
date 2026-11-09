"""A line-review check page (linereview / kraken_prep review: work/audit/lines/<run>/check.html) made into one
self-contained claude.ai Artifact page for the phone: the line images built in (data: URIs, only the lines on the
page), marks saved online in the artifact's database (collection "marks", one document per line, id "<page>-<rank>")
as well as in the browser, and a debug log (the user, 8 Nov: artifacts have been hard to open on the phone).

  python3 build/audit/phone_check.py b2 --out <file.html>
  python3 build/audit/phone_check.py marks <rows.json> --run b2 --out <export.json>   # database rows -> an export
                                                                                     # kraken_prep.py --marks reads
"""
import argparse, base64, glob, json, os, re, sys, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import paths  # noqa: E402

LINES = os.path.join(paths.WORK, "audit", "lines")

CSS_EXTRA = """
:root{color-scheme:light}
html,body{background:#f4f1ea}
body{padding-left:max(0px,env(safe-area-inset-left,0px));padding-right:max(0px,env(safe-area-inset-right,0px))}
body::before{content:"";position:fixed;inset:0 0 auto;height:env(safe-area-inset-top,0px);z-index:10;background:#fff}
header{top:env(safe-area-inset-top,0px);padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
main{padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
#sync{font-size:13px;padding:2px 8px;border-radius:10px;background:#eee;color:#444}
#sync.ok{background:#e2f2e2;color:#245c24}#sync.wait{background:#fff4d6;color:#7a5a00}#sync.err{background:#ffe0e0;color:#8a1f1f}
#dbgbtn{font-size:12px;padding:2px 8px;border:1px solid #bbb;background:#fafafa;border-radius:4px;color:#555}
#dbg{background:#1e1e1e;color:#d6d6d6;font:12px/1.45 ui-monospace,Menlo,Consolas,monospace;padding:10px 12px;border-radius:6px;margin-top:14px;white-space:pre-wrap;word-break:break-word;max-height:60vh;overflow:auto}
#dbg .e{color:#ff9a8a}#dbg .w{color:#ffd27a}#dbg .k{color:#9ad59a}
#ssbtn{font-size:13px;padding:3px 10px;border:1px solid #2f6fd0;background:#eef4ff;color:#1d4f9c;border-radius:4px}
#slide{padding-block:45vh 55vh}
#slidecard .card{margin:0}
.core{overflow:hidden;position:relative}
.zin{display:flex;flex-direction:column;gap:4px;transform-origin:0 0}
.core .scan{margin:0}
.core .btns{margin-top:4px;row-gap:6px}
.ssnav{display:inline-flex;gap:6px;margin-left:auto}
.ssnav button{font-size:13px!important;padding:6px 10px!important;border:1px solid #bbb;background:#fbfbfb;border-radius:6px;color:#444}
.ssnav button:disabled{opacity:.4}
.cfm{font-size:14px;color:#1d4f9c;font-weight:600;flex-basis:100%}
.btns button.cfmok{background:#2f6fd0;color:#fff;border-color:#2f6fd0;font-weight:600}
.more{margin-top:10px;border-top:1px dashed #ddd;padding-top:8px}
.core .btns .note{flex:1 1 80px;min-width:70px;width:auto;box-sizing:border-box;margin:0;font-size:14px;padding:6px;transition:flex-basis .15s}
.core .btns .note:focus,.core .btns .note.has{flex-basis:260px}
#slidetip{font-size:13px;color:#666;line-height:1.4;margin-top:10px}
#slide.fit1 .core .txt,#slide.fit1 .core .prev{font-size:18px;line-height:1.35}#slide.fit1 .core .txt [lang=he]{font-size:20px}
#slide.fit1 .core .rd{font-size:13px;margin:0 0 0 4px}
#slide.fit2 .core .txt,#slide.fit2 .core .prev{font-size:17px;line-height:1.3}#slide.fit2 .core .txt [lang=he]{font-size:19px}
#slide.fit2 .core .rd{font-size:12px;line-height:1.3;margin:0 0 0 4px}#slide.fit2 .core .rd b{width:66px}
#slide.fit2 .core .flag,#slide.fit2 .core .agree,#slide.fit2 .core .miss{font-size:11px;margin:0}
#slide.fit2 .zin{gap:2px}#slide.fit2 #slidecard .card{padding:6px 10px}
#slide.fit3 .core .txt,#slide.fit3 .core .prev{font-size:16px;line-height:1.25}#slide.fit3 .core .txt [lang=he]{font-size:18px}
#slide.fit3 .core .rd{font-size:11px;line-height:1.2;margin:0 0 0 2px}#slide.fit3 .core .rd b{width:60px}
#slide.fit3 .core .flag,#slide.fit3 .core .agree,#slide.fit3 .core .miss{font-size:10px;margin:0;padding:0 4px}
#slide.fit3 .zin{gap:1px}#slide.fit3 #slidecard .card{padding:4px 8px}#slide.fit3 .core .btns button{padding:6px 12px}
#slide.fit4 .core .txt,#slide.fit4 .core .prev{font-size:15px;line-height:1.2}#slide.fit4 .core .txt [lang=he]{font-size:17px}
#slide.fit4 .core .rd{font-size:10px;line-height:1.15;margin:0}#slide.fit4 .core .rd b{width:54px}
#slide.fit4 .core .flag,#slide.fit4 .core .agree,#slide.fit4 .core .miss{font-size:10px;margin:0;padding:0 3px}
#slide.fit4 .zin{gap:0}#slide.fit4 #slidecard .card{padding:3px 6px}#slide.fit4 .core .btns{margin-top:2px}#slide.fit4 .core .btns button{padding:5px 10px;font-size:14px}
#slide.fit4 .core .scan{max-height:46px;width:auto;max-width:100%}
#railtab{display:none}
@media (orientation:landscape) and (max-height:600px){
 header{position:fixed;top:0;bottom:0;left:0;width:240px;box-sizing:border-box;flex-direction:column;align-items:stretch;flex-wrap:nowrap;gap:12px;overflow:auto;
  padding-top:max(12px,env(safe-area-inset-top,0px));padding-bottom:max(12px,env(safe-area-inset-bottom,0px));padding-left:max(14px,env(safe-area-inset-left,0px));padding-right:14px;
  border-bottom:0;border-right:1px solid #ccc;box-shadow:2px 0 12px rgba(0,0,0,.18);transform:translateX(-110%);transition:transform .2s;z-index:5}
 body.railopen header{transform:none}
 header nav{flex-wrap:wrap}
 header button,header select{font-size:15px;padding:7px 10px}
 #railtab{display:flex;flex-direction:column;align-items:center;gap:7px;position:fixed;left:env(safe-area-inset-left,0px);top:50%;transform:translateY(-50%);z-index:4;
  width:30px;padding:9px 0;border:1px solid #bbb;border-left:0;border-radius:0 9px 9px 0;background:rgba(255,255,255,.92);color:#444}
 #railtab .ico{font-size:18px;line-height:1}
 #tabcount{writing-mode:vertical-rl;transform:rotate(180deg);font-size:11px;color:#777;white-space:nowrap;font-variant-numeric:tabular-nums}
 #tabsync{width:8px;height:8px;border-radius:50%;background:#bbb}
 #tabsync.ok{background:#3a8d3a}#tabsync.wait{background:#d9a400}#tabsync.err{background:#c33}
 main{padding-left:max(42px,calc(env(safe-area-inset-left,0px) + 34px))}
 .btns button{font-size:15px;padding:9px 18px}
}
@media (prefers-reduced-motion:reduce){header{transition:none}}
#dbgbar{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}#dbgbar button{font-size:13px;padding:4px 10px}
@media (max-width:640px){
 header{gap:8px;padding-block:6px}
 header b{display:none}
 .card{padding:8px 10px;margin:10px 0}
 .txt,.prev{font-size:19px}.txt [lang=he]{font-size:21px}
 .btns button{font-size:15px;padding:9px 14px}
 .note{width:100%;font-size:15px;padding:6px}
 .edit{font-size:18px}
 .rd b{width:72px}
 .intro{font-size:13px}
}
"""

HEADER_TOOLS = ('<button id="ssbtn" type="button">One at a time</button>'
                '<span id="sync">loading…</span><button id="dbgbtn" type="button">Debug</button>')

SLIDE_HTML = """<div id="slide" hidden><div id="slidecard"></div><div id="slidetip">Right, Bad line and Skip move on to the next line
by themselves. After an edit (Enter or tap outside the box) the card stays so you can look at it; <b>Yes, next line</b> moves on. <b>Next</b> moves on without marking; <b>Undo</b> takes back the
last mark and returns to that line. The note box is below each card; the position is in the menu. In landscape the menu is behind the tab
on the left edge.</div></div>"""

RAILTAB = ('<button id="railtab" type="button" aria-label="Menu"><span class="ico">&#9776;</span>'
           '<span id="tabsync"></span><span id="tabcount"></span></button>')

# one card at a time: the page's own render(), set() and rerender() wrapped, so its keys, buttons and edits all work as before.
# Each card is split into a core (scan, text, mark buttons, Back / Undo / Next), centred on the screen, and the rest below it.
SS_JS = r"""<script>
(function(){
const SKEY=KEY+"-slides", el=id=>document.getElementById(id);
const SS={on:false,list:[],i:0}, UNDO=[];
const LAND=matchMedia("(orientation: landscape) and (max-height: 600px)");
let slidePrev, slideCid, reports=0;
const clone=m=>m?JSON.parse(JSON.stringify(m)):undefined;
try{const v=JSON.parse(LS.get(SKEY)||"{}"); SS.on=!!v.on; SS.at=v.at}catch(e){}
function keep(){LS.set(SKEY,JSON.stringify({on:SS.on,at:SS.list[SS.i]}))}
function rebuild(at){SS.list=visible().map(id);
  let i=at?SS.list.indexOf(at):-1;
  if(i<0) i=SS.list.findIndex(c=>!(M[c]&&M[c].status));
  SS.i=Math.max(0,i)}
const NAV='<span class="ssnav"><button type="button" data-ss="back">&lsaquo; Back</button><button type="button" data-ss="undo">Undo</button>'+
  '<button type="button" data-ss="next">Next &rsaquo;</button></span>';
let confirmCid=null, fitLevel=0;
const TOP='<div class="sstop"><span class="pos"></span><span class="syncmini"></span></div>';
function structure(){const c=el("slidecard").querySelector(".card[data-id]"); if(!c) return;
  const meta=c.querySelector(":scope > .meta"), note=c.querySelector(".btns .note");
  const parts=[...c.children];
  const core=document.createElement("div"); core.className="core"; const zi=document.createElement("div"); zi.className="zin"; core.append(zi);
  zi.append(...parts); const btns=core.querySelector(".btns");
  if(confirmCid==c.dataset.id){btns.querySelectorAll("button[data-s=ok],button[data-s=bad],button[data-s=skip]").forEach(b=>b.hidden=true);
    btns.insertAdjacentHTML("afterbegin",'<span class="cfm">Your edit is above. Is it right?</span><button type="button" data-ss="confirm" class="cfmok">Yes, next line &rsaquo;</button>')}
  btns.insertAdjacentHTML("beforeend",NAV); const rest=[];
  const more=document.createElement("div"); more.className="more"; more.append(...rest);
  if(note){note.classList.toggle("has",!!note.value)}
  c.append(core,more); const im=core.querySelector("img"); if(im) im.loading="eager"; applyZ(); fill()}
function fill(){const n=SS.list.length, marked=SS.list.filter(c=>M[c]&&M[c].status).length;
  el("where").textContent=(SS.i<n?"Line "+(SS.i+1)+" of "+n:"End of "+n);
  document.querySelectorAll("#slidecard [data-ss=back]").forEach(b=>b.disabled=SS.i==0);
  document.querySelectorAll("#slidecard [data-ss=undo]").forEach(b=>b.disabled=!UNDO.length);
  document.querySelectorAll("#slidecard [data-ss=next]").forEach(b=>b.disabled=SS.i>=n);
  mirror()}
function mirror(){const s=el("sync"); const ts=el("tabsync"); if(ts){ts.className=s.className; ts.title=s.textContent} document.querySelectorAll(".syncmini").forEach(m=>{m.className="syncmini "+s.className; m.textContent=s.textContent})}
new MutationObserver(mirror).observe(el("sync"),{childList:true,characterData:true,subtree:true,attributes:true});
function hdrH(){return LAND.matches?0:document.querySelector("header").getBoundingClientRect().height}
function center(tag){const core=document.querySelector("#slidecard .core"); if(!core) return;
  const im=core.querySelector("img"), go=()=>{const h=hdrH(), avail=innerHeight-h, sl=el("slide");
    for(fitLevel=0;fitLevel<=4;fitLevel++){sl.className="fit"+fitLevel; if(core.getBoundingClientRect().height<=avail-4) break}
    if(fitLevel>4) fitLevel=4; sl.className="fit"+fitLevel;
    const r=core.getBoundingClientRect();
    scrollTo(0,Math.max(0,scrollY+r.top-h-Math.max(0,(avail-r.height)/2)));
    requestAnimationFrame(()=>report(tag,false))};
  (im&&!im.complete&&im.decode?im.decode().catch(()=>{}):Promise.resolve()).then(go)}
function report(tag,force){const core=document.querySelector("#slidecard .core");
  if(!core){if(force) dlog("w","layout "+tag+": no card on screen"+(SS.on?"":" (one at a time is off)")); return}
  const r=core.getBoundingClientRect(), b=(core.querySelector(".btns")||core).getBoundingClientRect(), h=hdrH(), vv=window.visualViewport;
  const fit=r.top>=h-1&&r.bottom<=innerHeight+1;
  if(!force&&fit&&reports>=3) return; reports++;
  dlog(fit?"":"w","layout "+tag+": "+(LAND.matches?"landscape, side menu":"portrait or tall, top bar")+"; view "+innerWidth+"x"+innerHeight+
    (vv?" (visible "+Math.round(vv.width)+"x"+Math.round(vv.height)+", zoom "+vv.scale.toFixed(2)+")":"")+"; screen "+screen.width+"x"+screen.height+" "+(screen.orientation?screen.orientation.type:"")+
    "; top bar "+Math.round(h)+"px; size step "+fitLevel+"; card magnified "+Z.s.toFixed(2)+"; card core "+Math.round(r.top)+" to "+Math.round(r.bottom)+" ("+Math.round(r.height)+"px), mark buttons end at "+Math.round(b.bottom)+
    "; scrolled "+Math.round(scrollY)+" of "+Math.round(document.documentElement.scrollHeight-innerHeight)+"; "+(fit?"fits on screen":"DOES NOT FIT ON SCREEN"))}
const VP=document.querySelector('meta[name="viewport"]');
function zoom(){const v=window.visualViewport; return v?v.scale:1}
function resetZoom(){const z=zoom(); if(z<=1.02) return;
  if(!VP){dlog("w","zoomed "+z.toFixed(2)+"x but the page has no viewport setting to reset"); return}
  const c=VP.content; VP.content=c.replace(/,\s*(maximum|minimum)-scale=[^,]*/g,"")+", maximum-scale=1, minimum-scale=1";
  setTimeout(()=>{VP.content=c; dlog(zoom()>1.02?"w":"","zoom was "+z.toFixed(2)+"x; now "+zoom().toFixed(2)+"x")},350)}
// the page's own magnifier on the card: pinch scales the card like a photo around the fingers, one finger drags it
// while magnified; the Claude app's zoom is held off (its zoom can't be reset from the page); every new card at 1x
let Z={s:1,x:0,y:0}, P=null, pinchSeen=false;
const zbox=()=>el("slidecard").querySelector(".core"), zin=()=>el("slidecard").querySelector(".zin");
function applyZ(){const z=zin(), b=zbox(); if(!z||!b) return; const w=b.clientWidth, h=b.clientHeight;
  Z.s=Math.max(1,Math.min(4,Z.s)); Z.x=Math.min(0,Math.max(w-w*Z.s,Z.x)); Z.y=Math.min(0,Math.max(h-h*Z.s,Z.y));
  z.style.transform=Z.s>1.001?"translate("+Z.x+"px,"+Z.y+"px) scale("+Z.s+")":""}
for(const g of ["gesturestart","gesturechange","gestureend"]) document.addEventListener(g,e=>{if(SS.on) e.preventDefault()},{passive:false});
const mid=(e,r)=>[(e.touches[0].clientX+e.touches[1].clientX)/2-r.left,(e.touches[0].clientY+e.touches[1].clientY)/2-r.top];
const tdist=e=>Math.hypot(e.touches[0].clientX-e.touches[1].clientX,e.touches[0].clientY-e.touches[1].clientY);
const typing=t=>!!(t&&t.closest&&t.closest("input,textarea,select,[contenteditable]"));
document.addEventListener("touchstart",e=>{const b=zbox(); if(!SS.on||!b||!b.contains(e.target)) return;
  if(e.touches.length==1&&(typing(e.target)||typing(document.activeElement))){P=null; return}   // text boxes: the touch moves the cursor or selection
  if(e.touches.length==2){const r=b.getBoundingClientRect(), [mx,my]=mid(e,r); P={pinch:true,d0:tdist(e),s0:Z.s,cx:(mx-Z.x)/Z.s,cy:(my-Z.y)/Z.s};
    if(!pinchSeen){pinchSeen=true; dlog("k","pinch caught by the page: the card is magnified, the app does not zoom")}}
  else if(e.touches.length==1&&Z.s>1.01) P={pinch:false,x0:e.touches[0].clientX,y0:e.touches[0].clientY,zx:Z.x,zy:Z.y,moved:false}},{passive:true});
document.addEventListener("touchmove",e=>{if(!P) return; const b=zbox(); if(!b) return;
  if(P.pinch&&e.touches.length==2){e.preventDefault(); const r=b.getBoundingClientRect(), [mx,my]=mid(e,r), s2=P.s0*tdist(e)/P.d0;
    Z.s=s2; Z.x=mx-P.cx*s2; Z.y=my-P.cy*s2; applyZ()}
  else if(!P.pinch&&e.touches.length==1){const dx=e.touches[0].clientX-P.x0, dy=e.touches[0].clientY-P.y0;
    if(P.moved||Math.abs(dx)+Math.abs(dy)>6){P.moved=true; e.preventDefault(); Z.x=P.zx+dx; Z.y=P.zy+dy; applyZ()}}},{passive:false});
document.addEventListener("touchend",e=>{if(!P) return; if(P.pinch&&e.touches.length<2){dlog("","card magnified "+Z.s.toFixed(2)+"x"); P=null}
  else if(!P.pinch&&!e.touches.length) P=null},{passive:true});
function show(tag){const n=SS.list.length; if(tag=="next"||tag=="back"||tag=="undo"||tag=="first unmarked") resetZoom();
  if(!n||SS.i>=n){const left=SS.list.some(c=>!(M[c]&&M[c].status));
    el("slidecard").innerHTML='<div class="card"><div class="core"><p>'+(!n?'No lines in this view. Choose another in the menu.':'<b>End of the list.</b> '+
      (left?'Some lines are still unmarked. <button id="ssfirst" type="button">Go to the first unmarked line</button>':'Every line here is marked.'))+'</p><div class="btns">'+NAV+'</div></div></div>';
    const b=el("ssfirst"); if(b) b.onclick=()=>{rebuild(); show("first unmarked")}}
  else{const cid=SS.list[SS.i]; if(cid!=slideCid){confirmCid=null; if(Z.s>1.01) dlog("","card back to 1x from "+Z.s.toFixed(2)+"x"); Z={s:1,x:0,y:0}} slideCid=cid; slidePrev=clone(M[cid]); el("slidecard").innerHTML=card(rec(cid)); structure()}
  fill(); count(); keep(); center(tag||"card")}
function go(i,tag){SS.i=Math.max(0,Math.min(SS.list.length,i)); show(tag)}
function mode(on){SS.on=on; el("ssbtn").textContent=on?"Show the list":"One at a time";
  document.querySelector(".intro").hidden=on; el("cards").hidden=on; el("slide").hidden=!on;
  el("prev").hidden=on; el("next").hidden=on; document.body.classList.remove("railopen");
  if(on){rebuild(SS.at); show("start")} else {_render(); keep(); scrollTo(0,0)}
  dlog("","one at a time: "+(on?"on":"off"))}
const _render=render; render=function(){if(SS.on){rebuild(SS.list[SS.i]); show("redraw")} else _render()};
const _rerender=rerender; rerender=function(cid){if(SS.on&&cid==slideCid){el("slidecard").innerHTML=card(rec(cid)); structure()} else _rerender(cid)};
document.addEventListener("click",e=>{const b=e.target.closest("button[data-s=reset]"); if(b&&SS.on) confirmCid=null},true);
function tabCount(){const t=el("tabcount"); if(!t) return; const VL=typeof inView=="function"?L.filter(inView):L, m=VL.filter(r=>M[id(r)]&&M[id(r)].status).length;
  t.textContent=m+" marked · "+(VL.length-m)+" left"}
const _count=count; count=function(){_count(); tabCount()};
document.addEventListener("input",e=>{if(e.target.classList.contains("note")) e.target.classList.toggle("has",!!e.target.value)});
const _set=set; set=function(cid,st){const prev=clone(M[cid]); _set(cid,st);
  if(SS.on&&cid==slideCid){UNDO.push({cid,prev}); go(SS.i+1,"next")}};
document.addEventListener("change",e=>{if(!SS.on||!e.target.classList.contains("edit")) return;
  const c=e.target.closest(".card"), cid=c&&c.dataset.id; if(cid!=slideCid) return;
  const m=M[cid]; if(m&&m.status=="fixed"&&JSON.stringify(m)!=JSON.stringify(slidePrev)){confirmCid=cid; rerender(cid); center("edit to confirm")}});
document.addEventListener("click",e=>{const b=e.target.closest("[data-ss]");
  if(b){const a=b.dataset.ss;
    if(a=="confirm"){UNDO.push({cid:slideCid,prev:slidePrev}); confirmCid=null; go(SS.i+1,"next"); return}
    if(a=="back") go(SS.i-1,"back"); else if(a=="next") go(SS.i+1,"next");
    else if(a=="undo"){const u=UNDO.pop(); if(!u) return; if(u.prev) M[u.cid]=u.prev; else delete M[u.cid];
      save(u.cid); const i=SS.list.indexOf(u.cid); if(i<0) rebuild(u.cid); else SS.i=i; show("undo")}
    return}
  if(e.target.closest("#railtab")){document.body.classList.toggle("railopen"); return}
  if(document.body.classList.contains("railopen")&&!e.target.closest("header")) document.body.classList.remove("railopen")});
el("ssbtn").onclick=()=>mode(!SS.on);
el("dbglayout").onclick=()=>report("check",true);
window.recenter=()=>{if(SS.on) center("images loaded")};
let rt; addEventListener("resize",()=>{clearTimeout(rt); rt=setTimeout(()=>{
  if(!LAND.matches) document.body.classList.remove("railopen");
  const a=document.activeElement; if(!SS.on) return; if(a&&(a.tagName=="INPUT"||a.tagName=="SELECT")) return report("after resize (typing, not moved)",true);
  center("after resize"); setTimeout(()=>report("after resize",true),400)},300)});
tabCount(); mirror();
if(SS.on) mode(true);
})();
</script>"""

DEBUG_HTML = """<div id="dbgwrap" hidden><div id="dbg"></div><div id="dbgbar">
<button id="dbgcopy" type="button">Copy log</button><button id="dbgping" type="button">Test online save</button>
<button id="dbgretry" type="button">Retry saving</button><button id="dbglayout" type="button">Layout check</button></div></div>"""

# runs first, before the page's own script: the log, errors from anywhere, and storage that never throws
PRE_JS = r"""<script>
const T0=Date.now(), LOG=[];
function dlog(kind,msg){const s="+"+((Date.now()-T0)/1000).toFixed(1)+"s "+msg; LOG.push([kind,s]);
  const el=document.getElementById("dbg"); if(el){const d=document.createElement("div"); if(kind) d.className=kind; d.textContent=s; el.appendChild(d)}
  if(kind=="e"){const w=document.getElementById("dbgwrap"); if(w) w.hidden=false}
  if(window.logOnline) window.logOnline()}
addEventListener("error",e=>{if(e.target&&e.target!==window&&e.target.tagName) return; dlog("e","error: "+(e.message||e.type)+(e.filename?" at "+e.filename.split("/").pop()+":"+e.lineno:""))},true);
addEventListener("unhandledrejection",e=>dlog("e","unhandled rejection: "+(e.reason&&(e.reason.code||e.reason.message)||e.reason)));
const LS={get(k){try{return localStorage.getItem(k)}catch(e){dlog("w","browser storage unreadable: "+e.name); return null}},
  set(k,v){try{localStorage.setItem(k,v)}catch(e){dlog("w","browser storage unwritable: "+e.name)}}};
dlog("","page script started; "+navigator.userAgent);
dlog("","screen "+screen.width+"x"+screen.height+", window "+innerWidth+"x"+innerHeight+", dpr "+devicePixelRatio);
dlog("","window.claude: "+(window.claude?("present, use="+typeof window.claude.use):"absent (not inside the claude.ai viewer)"));
</script>"""

# runs after the page's own script: the online store
POST_JS = r"""<script>
(function(){
const docId=cid=>cid.replace(":","-");
const syncEl=document.getElementById("sync");
const panel=document.getElementById("dbg"); panel.textContent=""; for(const [k,t] of LOG){const d=document.createElement("div"); if(k) d.className=k; d.textContent=t; panel.appendChild(d)}
let DB=null, busy=false, lastErr="";
function status(){const n=DIRTY.size;
  if(!DB){syncEl.className="err"; syncEl.textContent=lastErr?"not saving online":"connecting…"; return}
  if(lastErr&&n){syncEl.className="err"; syncEl.textContent=n+" not saved online"; return}
  syncEl.className=n?"wait":"ok"; syncEl.textContent=n?n+" saving…":"saved online"}
window.syncStatus=status;
async function flush(){if(!DB||busy) return; busy=true;
  try{for(const cid of [...DIRTY]){const r=rec(cid), m=M[cid];
      const body=m?Object.assign({},m,{page:r.page,rank:r.rank,kid:r.kid,xml:r.xml,eids:r.eids,site:r.site,run:(r.run||RUN)}):{deleted:true,page:r.page,rank:r.rank,run:(r.run||RUN)};
      for(const k of Object.keys(body)) if(body[k]===undefined) delete body[k];
      try{await DB.collection("marks").doc(docId(cid)).set(body); DIRTY.delete(cid); keepDirty(); lastErr=""}
      catch(e){lastErr=(e&&(e.code||e.message))||String(e); dlog("e","save "+cid+" failed: "+lastErr+(e&&e.message?" ("+e.message+")":"")); break}
      status()}}
  finally{busy=false; status()}}
window.flushOnline=flush;
let lt=null, lbusy=false;
window.logOnline=()=>{if(!DB||lt) return; lt=setTimeout(async()=>{lt=null; if(lbusy) return; lbusy=true;
  try{await DB.doc("debug/log").set({updated:new Date().toISOString(),ua:navigator.userAgent,lines:LOG.slice(-400).map(x=>x[1])})}
  catch(e){} finally{lbusy=false}},4000)};
document.getElementById("dbgbtn").onclick=()=>{const w=document.getElementById("dbgwrap"); w.hidden=!w.hidden; if(!w.hidden) w.scrollIntoView({block:"start"})};
document.getElementById("dbgcopy").onclick=()=>{const t=LOG.map(x=>x[1]).join("\n");
  navigator.clipboard.writeText(t).then(()=>dlog("k","log copied"),()=>{const r=document.createRange(); r.selectNodeContents(document.getElementById("dbg")); const s=getSelection(); s.removeAllRanges(); s.addRange(r); dlog("w","copy refused: the log is selected, copy it by hand")})};
document.getElementById("dbgretry").onclick=()=>{lastErr=""; flush()};
document.getElementById("dbgping").onclick=async()=>{if(!DB) return dlog("e","no online store in this view");
  const t=Date.now(); try{await DB.doc("debug/ping").set({at:new Date().toISOString(),ua:navigator.userAgent});
    const g=await DB.doc("debug/ping").get(); dlog("k","test save and read back: "+(g.exists?"ok":"not found")+", "+(Date.now()-t)+" ms")}
  catch(e){dlog("e","test save failed: "+(e&&(e.code||e.message))+" "+(e&&e.message||""))}};
let bad=0; document.addEventListener("error",e=>{if(e.target&&e.target.tagName=="IMG"&&++bad<=3) dlog("e","a line image did not load")},true);
status();
if(!window.claude||typeof window.claude.use!="function"){lastErr="no viewer"; status(); dlog("e","not inside the claude.ai viewer: marks are kept only in this browser"); return}
const t=Date.now(); dlog("","asking the viewer for the online store…");
const timer=setTimeout(()=>dlog("w","no answer from the online store after 10 s; still waiting"),10000);
window.claude.use("db").then(async db=>{
  dlog(db?"k":"e","online store "+(db?"ready":"not available in this view (null)")+" after "+(Date.now()-t)+" ms");
  if(!db){clearTimeout(timer); lastErr="null"; status(); return}
  try{const snap=await db.collection("marks").get(); clearTimeout(timer);
    let took=0;
    for(const d of snap.docs){const x=d.data(); const cid=x.page+":"+x.rank; if(!rec(cid)) continue;
      const m=M[cid]; if(DIRTY.has(cid)&&m&&m.time&&x.time&&m.time>x.time) continue;
      if(x.deleted){delete M[cid]; took++; continue}
      M[cid]={status:x.status,site:x.site,time:x.time}; if(x.text!=null) M[cid].text=x.text; if(x.note) M[cid].note=x.note; took++}
    dlog("k","read "+snap.size+" saved marks ("+(Date.now()-t)+" ms"+(snap.metadata&&snap.metadata.fromCache?", from cache":"")+"); "+took+" taken in");
    LS.set(KEY,JSON.stringify(M)); DB=db; render(); status(); flush(); window.logOnline()}
  catch(e){clearTimeout(timer); lastErr=(e&&(e.code||e.message))||String(e); dlog("e","reading saved marks failed: "+lastErr+" "+(e&&e.message||"")); DB=db; status(); flush()}
},e=>{clearTimeout(timer); lastErr=String(e); dlog("e","claude.use(\"db\") rejected: "+e); status()});
})();
</script>"""

# A "Use" button on each reader's line (and on a Greek OCR line), added on claude.ai on 9 Nov and brought here:
# when a reader read the line right and the site is wrong, one tap puts that reading in the edit box, to look at,
# change if need be, and keep as the line's text (marked Fixed). The Greek OCR lines (Tesseract with Greek, for
# lines with Greek; notes on what it got wrong) are in work/audit/lines/phone/greek_ocr.json, {"page:rank": {t, n}}.
GREEK_OCR = os.path.join(paths.WORK, "audit", "lines", "phone", "greek_ocr.json")
USE_CSS = ".rd .use{font-size:12px;padding:1px 9px;margin-left:8px;border:1px solid #9ab;border-radius:6px;background:#f4f8fb;color:#246;vertical-align:1px}"
USE_JS = r"""document.addEventListener("click",e=>{const b=e.target.closest("button[data-use]"); if(!b) return; e.preventDefault(); const el=b.closest(".card"), cid=el.dataset.id, r=rec(cid), rd=b.dataset.use;
  const t=rd=="greek"?(GREEK[r.page+":"+r.rank]||{}).t:r.readers[rd]; if(!t||!t.trim()) return;
  startEdit(el); const inp=el.querySelector(".edit"); inp.value=lrmText(t.trim()); showPrev(el); inp.dispatchEvent(new Event("change",{bubbles:true}))});
"""
GREEK_JS = """greekHTML=r=>{const g=GREEK[r.page+":"+r.rank]; if(!g) return ""; return '<div class="rd"><b>Greek OCR</b><span>'+esc(g.t)+'</span><button class="use" data-use="greek" title="use this reading as the line\\'s text">Use</button></div>'+(g.n&&g.n.length?'<div class="miss">'+g.n.map(esc).join("; ")+'</div>':"")}"""


def use_buttons(src):
    def rep(old, new):
        nonlocal src
        if old not in src: sys.exit("use_buttons: the check page has changed (no %r)" % old[:60])
        src = src.replace(old, new, 1)
    if 'data-use="' in src: return src
    rep(".rd .x{background:#ffd6cc}", ".rd .x{background:#ffd6cc}\n" + USE_CSS)
    rep("""+'</span></div>';""", """+'</span><button class="use" data-use="'+rd+'" title="use this reading as the line\\'s text">Use</button></div>';""")
    rep('.map(rd=>readerHTML(r,rd)).join("")}', '.map(rd=>readerHTML(r,rd)).join("")}${greekHTML(r)}')
    g = json.load(open(GREEK_OCR, encoding="utf-8")) if os.path.exists(GREEK_OCR) else {}
    rep(", FLAGS={", ", GREEK=" + json.dumps(g, ensure_ascii=False) + ", " + GREEK_JS + ", FLAGS={")
    rep('document.addEventListener("click",e=>{const b=e.target.closest("button[data-s]")',
        USE_JS + 'document.addEventListener("click",e=>{const b=e.target.closest("button[data-s]")')
    return src


def build(run, out, pages_=None, src=None, title=None, view_js=""):
    src = src or open(os.path.join(LINES, run, "check.html"), encoding="utf-8").read()
    if pages_:                                             # only these pages (a page over 16 MB is split by pages)
        lo, hi = (int(x) for x in pages_.split("-"))
        i = src.index(", L=") + 4
        L, end = json.JSONDecoder().raw_decode(src, i)
        L = [r for r in L if lo <= int(r["page"]) <= hi]
        src = src[:i] + json.dumps(L, ensure_ascii=False) + src[end:]
    pages = sorted({int(p) for p in re.findall(r'"page": "(\d+)"', src)})
    title = title or ("Line Check pp. %d–%d" % (pages[0], pages[-1]) if pages else "Line Check " + run)
    # the publish wraps the page in its own skeleton
    src = re.sub(r'^<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>[^<]*</title>',
                 '<title>%s</title>\n<meta name="claude:viewport-fit-sides" content="cover">' % title, src)
    # typed-out dots ("....", ". . . .", "….") keep a Hebrew phrase in one right-to-left run, as "…" does
    # (check pages built before 9 Nov; linereview has it since)
    src = src.replace('| *\\u2026 *|', '| *\\u2026 *| *[.\\u2026](?: ?[.\\u2026])+ *|', 1)
    src = use_buttons(src)
    src = src.replace("</style></head><body>", CSS_EXTRA + "</style>\n" + PRE_JS, 1)
    src = re.sub(r"</body></html>\s*$", "", src)
    # header: Export / Import give way to the save status (downloads are blocked in the viewer; Claude reads the marks)
    src = re.sub(r'<button id="export">Export</button><label[^>]*>Import <input type="file" id="import" accept=".json"></label>',
                 HEADER_TOOLS, src, count=1)
    src = src.replace("Marks are kept in this browser; <b>Export</b> saves them to a file",
                      "Marks are saved online as you go (the badge at the top says so), and Claude reads them from there; "
                      "<b>Debug</b> shows what the page is doing", 1).replace(" (send it, or keep it for the training export)", "", 1)
    src = src.replace("</div></main>", "</div>" + SLIDE_HTML + DEBUG_HTML + "</main>", 1)
    src = src.replace("</header>", "</header>" + RAILTAB, 1)
    # the line images, built in
    n = [0, 0]

    def img(m):
        f = os.path.join(LINES, run, m.group(1))
        b = open(f, "rb").read(); n[0] += 1; n[1] += len(b)
        return '"img": "data:image/jpeg;base64,%s"' % base64.b64encode(b).decode()
    src = re.sub(r'"img": "(img/[^"]+\.jpg)"', img, src)
    # storage: the browser's never throws; every change also queued for the online store
    js = [
        ('let M=JSON.parse(localStorage.getItem(KEY)||"{}");',
         'let M={}; try{M=JSON.parse(LS.get(KEY)||"{}")}catch(e){dlog("w","browser marks unreadable")}\n'
         'const DIRTY=new Set((()=>{try{return JSON.parse(LS.get(KEY+"-unsaved")||"[]")}catch(e){return []}})());\n'
         'function keepDirty(){LS.set(KEY+"-unsaved",JSON.stringify([...DIRTY]))}'),
        ("function save(){localStorage.setItem(KEY,JSON.stringify(M)); count()}",
         "function save(cid){LS.set(KEY,JSON.stringify(M)); if(cid){DIRTY.add(cid); keepDirty(); if(window.syncStatus) syncStatus(); if(window.flushOnline) flushOnline()} count()}"),
        ("m.time=new Date().toISOString(); save(); rerender(cid)}\nfunction rerender", "m.time=new Date().toISOString(); save(cid); rerender(cid)}\nfunction rerender"),
        ('if(m.status=="fixed") delete m.status; save(); return rerender(cid)}', 'if(m.status=="fixed") delete m.status; m.time=new Date().toISOString(); save(cid); return rerender(cid)}'),
        ('m.note=e.target.value; save()}', 'm.note=e.target.value; m.time=m.time||new Date().toISOString(); save(cid)}'),
        ('m.time=new Date().toISOString(); save(); rerender(cid)}});', 'm.time=new Date().toISOString(); save(cid); rerender(cid)}});'),
    ]
    for a, b in js:
        if src.count(a) != 1: sys.exit("phone_check: the page's script changed (%r found %d times)" % (a[:50], src.count(a)))
        src = src.replace(a, b)
    # Export / Import handlers go (their buttons are gone)
    src, k = re.subn(r'document\.getElementById\("export"\)\.onclick=.*?\n  save\(\); render\(\)\}\)\};\n', "", src, flags=re.S)
    if k != 1: sys.exit("phone_check: export/import handlers not found")
    src = src.replace("render();\n</script>", view_js + 'render(); dlog("","first page drawn: "+L.length+" lines");\n</script>' + POST_JS + SS_JS, 1)
    open(out, "w", encoding="utf-8").write(src)
    print("%s: %d lines, %d images (%.1f MB), page %.1f MB -> %s" % (
        run, src.count('"rank":'), n[0], n[1] / 1e6, len(src.encode()) / 1e6, out))


VIEW_JS = r"""
const BLANK="data:image/gif;base64,R0lGODlhAQABAIAAAP///wAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw==";
const VIEWS=__VIEWS__;
const IDX=new Map(L.map(r=>[id(r),r])); rec=cid=>IDX.get(cid);
const vtest=v=>r=>v.hard?r.hard>0:(r.run==v.run&&(!v.pages||(+r.page>=v.pages[0]&&+r.page<=v.pages[1])));
let VIEW=(()=>{const v=LS.get(KEY+"-view"); return VIEWS.some(x=>x.id==v)?v:VIEWS[0].id})();
function curView(){return VIEWS.find(x=>x.id==VIEW)}
function inView(r){return vtest(curView())(r)}
const _visible=visible; visible=function(){let V=_visible().filter(inView); if(curView().hard) V=V.slice().sort((a,b)=>b.hard-a.hard); return V};
const LOADED={};
let GOOD=null;   // the address form that worked, kept for the other files
async function getJSON(f){
  const dir=location.href.replace(/[?#].*$/,"").replace(/[^/]*$/,"");
  const q=location.search||"";
  if(!getJSON.said){getJSON.said=1; dlog("","page address: query part "+(q?q.length+" characters, keys "+[...new URLSearchParams(q).keys()].join(","):"none")+"; referrer "+(document.referrer?"set":"none"))}
  const cands=[...(GOOD?[GOOD(f)]:[]), ...(q?[f+q, dir+f+q]:[]), f, dir+f];
  const tried=new Set(); let last="";
  for(const u of cands){if(tried.has(u)) continue; tried.add(u);
    try{const r=await fetch(u,{credentials:"include"}), ct=r.headers.get("content-type")||"", t=await r.text();
      if(r.ok&&t.charAt(0)=="{"){const j=JSON.parse(t);
        if(!GOOD){const i=u.indexOf(f), pre=u.slice(0,i), post=u.slice(i+f.length); GOOD=x=>pre+x+post; dlog("k","image files found (with the page's key: "+(post?"yes":"no")+")")}
        return j}
      last=u+": "+r.status+" "+ct+" "+JSON.stringify(t.slice(0,60))}
    catch(e){last=u+": "+e}
    dlog("w","tried "+last.slice(0,200))}
  throw new Error("no address worked; base "+document.baseURI.slice(0,80))}
async function loadImgs(){for(const f of curView().files){if(LOADED[f]) continue; LOADED[f]="loading"; const t=Date.now();
  try{const j=await getJSON(f); let n=0; for(const k in j){const r=rec(k); if(r){r.img=j[k]; n++}} LOADED[f]=true;
    dlog("","images "+f+": "+n+" lines, "+(Date.now()-t)+" ms");
    document.querySelectorAll("img.scan[data-cid]").forEach(im=>{const r=rec(im.dataset.cid); if(r&&r.img&&im.getAttribute("src")!=r.img) im.src=r.img});
    if(window.recenter) window.recenter()}
  catch(e){LOADED[f]=false; dlog("e","images "+f+" did not load: "+e)}}}
const vsel=document.getElementById("view");
function viewOpts(){vsel.innerHTML=VIEWS.map(v=>{const V=L.filter(vtest(v)), left=V.filter(r=>!(M[id(r)]&&M[id(r)].status)).length;
  return '<option value="'+v.id+'"'+(v.id==VIEW?" selected":"")+'>'+v.name+' ('+left+' left)</option>'}).join("")}
vsel.onchange=()=>{VIEW=vsel.value; LS.set(KEY+"-view",VIEW); start=0; dlog("","view: "+VIEW); loadImgs(); render()};
const _count0=count; count=function(){_count0(); viewOpts()};
viewOpts(); loadImgs();
"""


def build_all(out, datadir):
    """one page for every batch (pp. 1-100) and a view of the hard lines, so that a line is marked once whichever
    view it is in; the line images in data files beside the page, fetched for the view on screen"""
    tr = {}
    for f in glob.glob(os.path.join(paths.WORK, "ocrtrain", "lines", "*", "*.gt.txt")):
        for c in unicodedata.normalize("NFC", open(f, encoding="utf-8").read().strip()): tr[c] = tr.get(c, 0) + 1
    POINTS = re.compile("[֑-ׇ]")
    L, FL, PRIOR, RECHECK, MADE = [], {}, [], [], ""
    imgs = {}
    for b in ("b1", "b2", "b3"):
        s = open(os.path.join(LINES, b, "check.html"), encoding="utf-8").read()
        line = s.split("\n")[42]
        run = re.search(r'const RUN="([^"]+)"', line).group(1)
        i = line.index(", L=") + 4
        Lb, end = json.JSONDecoder().raw_decode(line, i)
        rest = line[end:]
        FL.update(json.JSONDecoder().raw_decode(rest, rest.index("FLAGS=") + 6)[0])
        PRIOR += json.JSONDecoder().raw_decode(rest, rest.index("PRIOR=") + 6)[0]
        RECHECK += json.JSONDecoder().raw_decode(rest, rest.index("RECHECK=") + 8)[0]
        MADE = max(MADE, re.search(r'MADE="([^"]*)"', rest).group(1))
        for r in Lb:
            r["run"] = run
            imgs["%s:%d" % (r["page"], r["rank"])] = (b, r["img"]); r["img"] = ""
            text = unicodedata.normalize("NFC", POINTS.sub("", unicodedata.normalize("NFD", r["site"])))
            rare = sorted({c for c in text if not c.isspace() and tr.get(c, 0) < 30})
            r["hard"] = round(sum(100.0 / (tr.get(c, 0) + 1) for c in rare), 2)
            if rare: r["flags"] = r["flags"] + ["rare in the training: " + " ".join(rare)]
        L += Lb
    tmpl = open(os.path.join(LINES, "b2", "check.html"), encoding="utf-8").read().split("\n")
    tmpl[42] = 'const RUN="all", L=%s, FLAGS=%s, PRIOR=%s, RECHECK=%s, MADE="%s";' % (
        json.dumps(L, ensure_ascii=False), json.dumps(FL, ensure_ascii=False), json.dumps(PRIOR, ensure_ascii=False),
        json.dumps(RECHECK), MADE)
    src = "\n".join(tmpl)
    a = '<img class="scan" src="${r.img}" loading="lazy">'
    if src.count(a) != 1: sys.exit("phone_check: the card's image changed")
    src = src.replace(a, '<img class="scan" src="${r.img||BLANK}" data-cid="${id(r)}" loading="lazy">')
    views = [{"id": "b1", "name": "pp. 1–20", "run": "b1-check", "files": ["img-b1.json"]},
             {"id": "b2", "name": "pp. 21–40", "run": "b2-check", "files": ["img-b2.json"]},
             {"id": "b3a", "name": "pp. 41–60", "run": "b3-check", "pages": [41, 60], "files": ["img-b3-41.json"]},
             {"id": "b3b", "name": "pp. 61–80", "run": "b3-check", "pages": [61, 80], "files": ["img-b3-61.json"]},
             {"id": "b3c", "name": "pp. 81–100", "run": "b3-check", "pages": [81, 100], "files": ["img-b3-81.json"]},
             {"id": "hard", "name": "Hard lines (all pages)", "hard": True, "files": ["img-hard.json"]}]
    order = ["b2", "hard", "b1", "b3a", "b3b", "b3c"]
    views.sort(key=lambda v: order.index(v["id"]))
    os.makedirs(datadir, exist_ok=True)
    files = {}
    for v in views:
        keep = {}
        for r in L:
            k = "%s:%d" % (r["page"], r["rank"])
            if v.get("hard"):
                if r["hard"] <= 0: continue
            elif r["run"] != v["run"] or ("pages" in v and not v["pages"][0] <= int(r["page"]) <= v["pages"][1]): continue
            b, rel = imgs[k]
            keep[k] = "data:image/jpeg;base64," + base64.b64encode(open(os.path.join(LINES, b, rel), "rb").read()).decode()
        f = os.path.join(datadir, v["files"][0])
        json.dump(keep, open(f, "w"))
        files[v["files"][0]] = f
        print("  %-24s %4d lines, images %.1f MB" % (v["name"], len(keep), os.path.getsize(f) / 1e6))
    tools = '<select id="view" aria-label="Which lines"></select>'
    build("all", out, src=src.replace('<button id="export">Export</button>', tools + '<button id="export">Export</button>', 1),
          title="Line Check pp. 1–100", view_js=VIEW_JS.replace("__VIEWS__", json.dumps(views, ensure_ascii=False)))
    print("hard lines: %d (ranked by how rare their characters are in the training)" % sum(1 for r in L if r["hard"] > 0))
    return files


GREEK = re.compile("[\u0370-\u03ff\u1f00-\u1fff]")
LOOKALIKE = set("xXkKoOaAeEiIuUvVpPtTnNyYhHbBmMcC")


def greek_standins(site, text):
    """the user can't type Greek on the phone and types a Latin look-alike (x for the x-shaped ϰ, i.e. kappa) where
    the site already has a Greek letter: wherever the user's text differs from the site only by Latin look-alikes
    standing in Greek letters, the site's Greek letters are kept"""
    import difflib
    out = []
    for op, a0, a1, b0, b1 in difflib.SequenceMatcher(None, site, text, autojunk=False).get_opcodes():
        seg_s, seg_t = site[a0:a1], text[b0:b1]
        bare = re.sub("[\u2018\u2019'` ]", "", seg_t)      # a breathing typed as a quote before the letter: "\u2018 A" for "\u1f08"
        if (op == "replace" and all(GREEK.match(c) for c in seg_s) and all(c in LOOKALIKE for c in bare)
                and (len(seg_s) == len(seg_t) or len(seg_s) == len(bare))):
            out.append(seg_s)
        else:
            out.append(seg_t)
    return "".join(out)


CUT = re.compile(r"cut ?off|missing from (the )?scan", re.I)


def marks(rows, run, out):
    """the database rows (ArtifactData list output, a list of {id, data} or of bodies) as an export"""
    d = json.load(open(rows))
    if isinstance(d, dict): d = d.get("documents") or d.get("docs") or d.get("rows") or []
    lines = []
    for x in d:
        b = x.get("data", x)
        if b.get("deleted") or not b.get("status") or (run != "all" and b.get("run", run) != run): continue
        lines.append({"run": b.get("run", run), "page": b["page"], "rank": b["rank"], "kid": b.get("kid"), "xml": b.get("xml"), "eids": b.get("eids", []),
                      "status": b["status"], "site": b["site"], "text": greek_standins(b["site"], b.get("text", b["site"])), "note": b.get("note", ""),
                      "time": b.get("time")})
    for m in lines:          # an edit that only typed Greek letters as Latin look-alikes is the site's text: Right
        if m["status"] == "fixed" and m["text"] == m["site"]: m["status"] = "ok"
        # a line whose scan is cut off (the user's note, 9 Nov: "Beg cut off", "Star is missing from scan") has a right
        # text but an image without all of it: kept out of the training like a bad line
        if m["status"] in ("ok", "fixed") and CUT.search(m["note"] or ""): m["status"], m["was"] = "bad", m["status"]
    lines.sort(key=lambda m: (int(m["page"]), m["rank"]))
    runs = sorted({m["run"] for m in lines}) if run == "all" else [run]
    for rn in runs:
        part = [m for m in lines if run != "all" or m["run"] == rn]
        o = out if run != "all" else out.replace("RUN", rn)
        json.dump({"run": rn, "exported": max([m["time"] or "" for m in part] or [""]), "source": "phone artifact",
                   "lines": part}, open(o, "w"), ensure_ascii=False, indent=1)
        print("%s: %d marks -> %s" % (rn, len(part), o))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("run")
    ap.add_argument("rows", nargs="?")
    ap.add_argument("--run", dest="mrun")
    ap.add_argument("--out", required=True)
    ap.add_argument("--pages", help="build: only pages lo-hi")
    ap.add_argument("--data", help="all: the folder for the image files")
    a = ap.parse_args()
    if a.run == "marks": marks(a.rows, a.mrun, a.out)
    elif a.run == "all": build_all(a.out, a.data or os.path.join(os.path.dirname(os.path.abspath(a.out)), "phone-all"))
    else: build(a.run, a.out, a.pages)
