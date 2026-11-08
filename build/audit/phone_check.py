"""A line-review check page (linereview / kraken_prep review: work/audit/lines/<run>/check.html) made into one
self-contained claude.ai Artifact page for the phone: the line images built in (data: URIs, only the lines on the
page), marks saved online in the artifact's database (collection "marks", one document per line, id "<page>-<rank>")
as well as in the browser, and a debug log (the user, 8 Nov: artifacts have been hard to open on the phone).

  python3 build/audit/phone_check.py b2 --out <file.html>
  python3 build/audit/phone_check.py marks <rows.json> --run b2 --out <export.json>   # database rows -> an export
                                                                                     # kraken_prep.py --marks reads
"""
import argparse, base64, json, os, re, sys

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
.core{display:flex;flex-direction:column;gap:6px}
.core .scan{margin:0}
.sstop{display:flex;gap:8px;align-items:center;font-size:13px;color:#555}
.sstop .pos{margin-right:auto}
.syncmini{font-size:12px;padding:1px 7px;border-radius:9px;background:#eee;color:#444}
.syncmini.ok{background:#e2f2e2;color:#245c24}.syncmini.wait{background:#fff4d6;color:#7a5a00}.syncmini.err{background:#ffe0e0;color:#8a1f1f}
.ssnav{display:flex;gap:6px;flex-wrap:wrap}
.ssnav button{font-size:14px;padding:7px 12px;border:1px solid #bbb;background:#fbfbfb;border-radius:6px;color:#333}
.ssnav button:disabled{opacity:.4}
.ssnav [data-ss=next]{margin-left:auto}
.more{margin-top:12px;border-top:1px dashed #ddd;padding-top:8px}
.more .note{width:100%;box-sizing:border-box;margin:6px 0}
#slidetip{font-size:13px;color:#666;line-height:1.4;margin-top:10px}
#railtab{display:none}
@media (orientation:landscape) and (max-height:600px){
 header{position:fixed;top:0;bottom:0;left:0;width:240px;box-sizing:border-box;flex-direction:column;align-items:stretch;flex-wrap:nowrap;gap:12px;overflow:auto;
  padding-top:max(12px,env(safe-area-inset-top,0px));padding-bottom:max(12px,env(safe-area-inset-bottom,0px));padding-left:max(14px,env(safe-area-inset-left,0px));padding-right:14px;
  border-bottom:0;border-right:1px solid #ccc;box-shadow:2px 0 12px rgba(0,0,0,.18);transform:translateX(-110%);transition:transform .2s;z-index:5}
 body.railopen header{transform:none}
 header nav{flex-wrap:wrap}
 header button,header select{font-size:15px;padding:7px 10px}
 #railtab{display:block;position:fixed;left:env(safe-area-inset-left,0px);top:50%;transform:translateY(-50%);z-index:4;width:30px;height:70px;padding:0;
  border:1px solid #bbb;border-left:0;border-radius:0 9px 9px 0;background:rgba(255,255,255,.92);font-size:18px;color:#444}
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
by themselves; so does an edit once you press Enter or tap outside the box. <b>Next</b> moves on without marking; <b>Undo</b> takes back the
last mark and returns to that line. The readers, flags and the note box are below each card. In landscape the menu is behind the tab
on the left edge.</div></div>"""

RAILTAB = '<button id="railtab" type="button" aria-label="Menu">&#9776;</button>'

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
const NAV='<div class="ssnav"><button type="button" data-ss="back">&lsaquo; Back</button><button type="button" data-ss="undo">Undo</button>'+
  '<button type="button" data-ss="next">Next &rsaquo;</button></div>';
const TOP='<div class="sstop"><span class="pos"></span><span class="syncmini"></span></div>';
function structure(){const c=el("slidecard").querySelector(".card[data-id]"); if(!c) return;
  const pick=q=>c.querySelector(":scope > "+q);
  const parts=[pick(".scan"),pick(".txt"),pick(".edit"),pick(".prev"),pick(".btns")].filter(Boolean);
  const note=c.querySelector(".btns .note"), rest=[...c.children].filter(x=>!parts.includes(x));
  const core=document.createElement("div"); core.className="core"; core.innerHTML=TOP;
  core.append(...parts); core.insertAdjacentHTML("beforeend",NAV);
  const more=document.createElement("div"); more.className="more"; if(note) more.append(note); more.append(...rest);
  c.append(core,more); const im=core.querySelector("img"); if(im) im.loading="eager"; fill()}
function fill(){const n=SS.list.length, marked=SS.list.filter(c=>M[c]&&M[c].status).length;
  document.querySelectorAll("#slidecard .pos").forEach(p=>p.textContent=(SS.i<n?"Line "+(SS.i+1)+" of "+n:"End")+" · "+marked+" marked");
  document.querySelectorAll("#slidecard [data-ss=back]").forEach(b=>b.disabled=SS.i==0);
  document.querySelectorAll("#slidecard [data-ss=undo]").forEach(b=>b.disabled=!UNDO.length);
  document.querySelectorAll("#slidecard [data-ss=next]").forEach(b=>b.disabled=SS.i>=n);
  mirror()}
function mirror(){const s=el("sync"); document.querySelectorAll(".syncmini").forEach(m=>{m.className="syncmini "+s.className; m.textContent=s.textContent})}
new MutationObserver(mirror).observe(el("sync"),{childList:true,characterData:true,subtree:true,attributes:true});
function hdrH(){return LAND.matches?0:document.querySelector("header").getBoundingClientRect().height}
function center(tag){const core=document.querySelector("#slidecard .core"); if(!core) return;
  const im=core.querySelector("img"), go=()=>{const h=hdrH(), r=core.getBoundingClientRect(), avail=innerHeight-h;
    scrollTo(0,Math.max(0,scrollY+r.top-h-Math.max(0,(avail-r.height)/2)));
    requestAnimationFrame(()=>report(tag,false))};
  (im&&!im.complete&&im.decode?im.decode().catch(()=>{}):Promise.resolve()).then(go)}
function report(tag,force){const core=document.querySelector("#slidecard .core");
  if(!core){if(force) dlog("w","layout "+tag+": no card on screen"+(SS.on?"":" (one at a time is off)")); return}
  const r=core.getBoundingClientRect(), b=(core.querySelector(".btns")||core).getBoundingClientRect(), h=hdrH(), vv=window.visualViewport;
  const fit=r.top>=h-1&&r.bottom<=innerHeight+1;
  if(!force&&fit&&reports>=3) return; reports++;
  dlog(fit?"":"w","layout "+tag+": "+(LAND.matches?"landscape, side menu":"portrait or tall, top bar")+"; view "+innerWidth+"x"+innerHeight+
    (vv?" (visible "+Math.round(vv.width)+"x"+Math.round(vv.height)+")":"")+"; screen "+screen.width+"x"+screen.height+" "+(screen.orientation?screen.orientation.type:"")+
    "; top bar "+Math.round(h)+"px; card core "+Math.round(r.top)+" to "+Math.round(r.bottom)+" ("+Math.round(r.height)+"px), mark buttons end at "+Math.round(b.bottom)+
    "; scrolled "+Math.round(scrollY)+" of "+Math.round(document.documentElement.scrollHeight-innerHeight)+"; "+(fit?"fits on screen":"DOES NOT FIT ON SCREEN"))}
function show(tag){const n=SS.list.length;
  if(!n||SS.i>=n){const left=SS.list.some(c=>!(M[c]&&M[c].status));
    el("slidecard").innerHTML='<div class="card"><div class="core">'+TOP+'<p>'+(!n?'No lines in this view. Choose another in the menu.':'<b>End of the list.</b> '+
      (left?'Some lines are still unmarked. <button id="ssfirst" type="button">Go to the first unmarked line</button>':'Every line here is marked.'))+'</p>'+NAV+'</div></div>';
    const b=el("ssfirst"); if(b) b.onclick=()=>{rebuild(); show("first unmarked")}}
  else{const cid=SS.list[SS.i]; slideCid=cid; slidePrev=clone(M[cid]); el("slidecard").innerHTML=card(rec(cid)); structure()}
  fill(); el("where").textContent=""; count(); keep(); center(tag||"card")}
function go(i,tag){SS.i=Math.max(0,Math.min(SS.list.length,i)); show(tag)}
function mode(on){SS.on=on; el("ssbtn").textContent=on?"Show the list":"One at a time";
  document.querySelector(".intro").hidden=on; el("cards").hidden=on; el("slide").hidden=!on;
  el("prev").hidden=on; el("next").hidden=on; document.body.classList.remove("railopen");
  if(on){rebuild(SS.at); show("start")} else {_render(); keep(); scrollTo(0,0)}
  dlog("","one at a time: "+(on?"on":"off"))}
const _render=render; render=function(){if(SS.on){rebuild(SS.list[SS.i]); show("redraw")} else _render()};
const _rerender=rerender; rerender=function(cid){if(SS.on&&cid==slideCid){el("slidecard").innerHTML=card(rec(cid)); structure()} else _rerender(cid)};
const _set=set; set=function(cid,st){const prev=clone(M[cid]); _set(cid,st);
  if(SS.on&&cid==slideCid){UNDO.push({cid,prev}); go(SS.i+1,"next")}};
document.addEventListener("change",e=>{if(!SS.on||!e.target.classList.contains("edit")) return;
  const c=e.target.closest(".card"), cid=c&&c.dataset.id; if(cid!=slideCid) return;
  const m=M[cid]; if(m&&m.status=="fixed"&&JSON.stringify(m)!=JSON.stringify(slidePrev)){UNDO.push({cid,prev:slidePrev}); go(SS.i+1,"next")}});
document.addEventListener("click",e=>{const b=e.target.closest("[data-ss]");
  if(b){const a=b.dataset.ss;
    if(a=="back") go(SS.i-1,"back"); else if(a=="next") go(SS.i+1,"next");
    else if(a=="undo"){const u=UNDO.pop(); if(!u) return; if(u.prev) M[u.cid]=u.prev; else delete M[u.cid];
      save(u.cid); const i=SS.list.indexOf(u.cid); if(i<0) rebuild(u.cid); else SS.i=i; show("undo")}
    return}
  if(e.target.id=="railtab"){document.body.classList.toggle("railopen"); return}
  if(document.body.classList.contains("railopen")&&!e.target.closest("header")) document.body.classList.remove("railopen")});
el("ssbtn").onclick=()=>mode(!SS.on);
el("dbglayout").onclick=()=>report("check",true);
let rt; addEventListener("resize",()=>{clearTimeout(rt); rt=setTimeout(()=>{
  if(!LAND.matches) document.body.classList.remove("railopen");
  const a=document.activeElement; if(!SS.on) return; if(a&&(a.tagName=="INPUT"||a.tagName=="SELECT")) return report("after resize (typing, not moved)",true);
  center("after resize"); setTimeout(()=>report("after resize",true),400)},300)});
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
  if(kind=="e"){const w=document.getElementById("dbgwrap"); if(w) w.hidden=false}}
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
      const body=m?Object.assign({},m,{page:r.page,rank:r.rank,kid:r.kid,xml:r.xml,eids:r.eids,site:r.site,run:RUN}):{deleted:true,page:r.page,rank:r.rank,run:RUN};
      for(const k of Object.keys(body)) if(body[k]===undefined) delete body[k];
      try{await DB.collection("marks").doc(docId(cid)).set(body); DIRTY.delete(cid); keepDirty(); lastErr=""}
      catch(e){lastErr=(e&&(e.code||e.message))||String(e); dlog("e","save "+cid+" failed: "+lastErr+(e&&e.message?" ("+e.message+")":"")); break}
      status()}}
  finally{busy=false; status()}}
window.flushOnline=flush;
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
    LS.set(KEY,JSON.stringify(M)); DB=db; render(); status(); flush()}
  catch(e){clearTimeout(timer); lastErr=(e&&(e.code||e.message))||String(e); dlog("e","reading saved marks failed: "+lastErr+" "+(e&&e.message||"")); DB=db; status(); flush()}
},e=>{clearTimeout(timer); lastErr=String(e); dlog("e","claude.use(\"db\") rejected: "+e); status()});
})();
</script>"""


def build(run, out):
    src = open(os.path.join(LINES, run, "check.html"), encoding="utf-8").read()
    pages = sorted({int(p) for p in re.findall(r'"page": "(\d+)"', src)})
    title = "Line Check pp. %d–%d" % (pages[0], pages[-1]) if pages else "Line Check " + run
    # the publish wraps the page in its own skeleton
    src = re.sub(r'^<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>[^<]*</title>',
                 '<title>%s</title>\n<meta name="claude:viewport-fit-sides" content="cover">' % title, src)
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
    src = src.replace("render();\n</script>", 'render(); dlog("","first page drawn: "+L.length+" lines");\n</script>' + POST_JS + SS_JS, 1)
    open(out, "w", encoding="utf-8").write(src)
    print("%s: %d lines, %d images (%.1f MB), page %.1f MB -> %s" % (
        run, src.count('"rank":'), n[0], n[1] / 1e6, len(src.encode()) / 1e6, out))


def marks(rows, run, out):
    """the database rows (ArtifactData list output, a list of {id, data} or of bodies) as an export"""
    d = json.load(open(rows))
    if isinstance(d, dict): d = d.get("documents") or d.get("docs") or d.get("rows") or []
    lines = []
    for x in d:
        b = x.get("data", x)
        if b.get("deleted") or not b.get("status") or b.get("run", run) != run: continue
        lines.append({"page": b["page"], "rank": b["rank"], "kid": b.get("kid"), "xml": b.get("xml"), "eids": b.get("eids", []),
                      "status": b["status"], "site": b["site"], "text": b.get("text", b["site"]), "note": b.get("note", ""),
                      "time": b.get("time")})
    lines.sort(key=lambda m: (int(m["page"]), m["rank"]))
    json.dump({"run": run, "exported": max([m["time"] or "" for m in lines] or [""]), "source": "phone artifact",
               "lines": lines}, open(out, "w"), ensure_ascii=False, indent=1)
    print("%d marks -> %s" % (len(lines), out))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("run")
    ap.add_argument("rows", nargs="?")
    ap.add_argument("--run", dest="mrun")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.run == "marks": marks(a.rows, a.mrun, a.out)
    else: build(a.run, a.out)
