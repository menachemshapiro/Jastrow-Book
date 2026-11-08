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

HEADER_TOOLS = ('<span id="sync">loading…</span><button id="dbgbtn" type="button">Debug</button>')

DEBUG_HTML = """<div id="dbgwrap" hidden><div id="dbg"></div><div id="dbgbar">
<button id="dbgcopy" type="button">Copy log</button><button id="dbgping" type="button">Test online save</button>
<button id="dbgretry" type="button">Retry saving</button></div></div>"""

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
    src = src.replace("</div></main>", "</div>" + DEBUG_HTML + "</main>", 1)
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
    src = src.replace("render();\n</script>", 'render(); dlog("","first page drawn: "+L.length+" lines");\n</script>' + POST_JS, 1)
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
