"""Write the audit's report: findings.jsonl (one finding per line, for tools), summary.txt (short, to paste to
Claude), and report/index.html + report/entries.html (to read: every finding with its piece of the scan, and every
entry's scan, from all the columns and pages it runs over, beside the site's text)."""
import html, json, os
from collections import Counter, defaultdict

from PIL import Image, ImageDraw, ImageFont
import re


def label_font():
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans.ttf"):
        if os.path.exists(p): return ImageFont.truetype(p, 15)
    try: return ImageFont.load_default(size=15)
    except TypeError: return ImageFont.load_default()


def sup(s):
    """'26^b' as 26<sup>b</sup>, after escaping"""
    return re.sub(r"\^([a-d])", r"<sup>\1</sup>", s)

SEV = {1: "likely error", 2: "check", 3: "minor / uncertain"}
TYPES = {
    "run_on": "Words run together", "split_word": "Word split apart", "hyphen_kept": "Line-end hyphen kept",
    "hyphen_space": "Hyphen followed by a space", "word_differs": "Word differs", "number_differs": "Number differs",
    "folio_side": "Folio side differs", "differs": "Text differs", "missing_in_site": "Missing on the site",
    "not_in_scan": "Not found in the scan", "doubled": "Doubled text", "doubled_text": "Phrase repeated",
    "doubled_word": "Word repeated", "page_start": "Page start differs", "page_end": "Page end differs",
    "column_break": "Column break differs", "column_break_unset": "No fixed column break",
    "layout": "Page layout differs", "running_head": "Running head", "page_number": "Page number",
    "guide_word": "Guide word", "entry_start": "Entry the book does not start",
    "book_entry_start": "Entry line with no site entry", "hebrew_order": "Hebrew out of order",
    "headword_order": "Headword forms out of order", "hebrew_differs": "Hebrew differs",
    "headword_differs": "Headword differs", "headword_letters": "Headword letter differs",
    "hebrew_unread": "Hebrew not read", "headword_unread": "Headword not read",
    "hebrew_extra_in_book": "Hebrew missing on the site", "hebrew_missing_in_site": "Hebrew missing on the site",
    "brackets": "Unbalanced brackets", "sense_numbers": "Sense numbers out of sequence",
    "stray_char": "Stray character", "headword_text": "Headword text", "headword_display": "Headword display",
    "alphabetical": "Alphabetical order", "scan_incomplete": "Scan page incomplete", "talmud_range": "Bavli folio out of range",
    "talmud_near": "Bavli quote on next amud", "talmud_elsewhere": "Bavli quote elsewhere in tractate",
    "talmud_other_tractate": "Bavli quote in another tractate", "talmud_not_found": "Bavli quote not found",
}

CSS = """
:root{--bg:#fbfaf7;--fg:#1d1b18;--mut:#6b665e;--line:#e3dfd6;--s1:#b42318;--s2:#b54708;--s3:#667085;--card:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#161513;--fg:#ece8e1;--mut:#a29c92;--line:#36332e;--card:#1f1e1b;
--s1:#f97066;--s2:#fdb022;--s3:#98a2b3}}
body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0;padding:16px 24px 60px}
h1{font-size:22px;margin:4px 0 2px}h2{font-size:18px;margin:28px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}
.mut{color:var(--mut)}table{border-collapse:collapse;margin:8px 0}td,th{border-bottom:1px solid var(--line);padding:3px 10px;text-align:left}
td.n{text-align:right;font-variant-numeric:tabular-nums}
.f{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin:10px 0}
.f .t{font-weight:600}.s1{color:var(--s1)}.s2{color:var(--s2)}.s3{color:var(--s3)}
.f img,.e img{max-width:100%;border:1px solid var(--line);margin-top:6px;background:#fff}
.kv{display:grid;grid-template-columns:110px 1fr;gap:2px 10px;margin-top:4px}.kv div:nth-child(odd){color:var(--mut)}
.h,[lang=he]{font-family:"Frank Ruhl Libre","Noto Serif Hebrew","SBL Hebrew",serif;font-size:1.12em}
.bar{position:sticky;top:0;background:var(--bg);padding:8px 0;border-bottom:1px solid var(--line);z-index:2}
.bar label{margin-right:12px;white-space:nowrap}
.e{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px;border-bottom:1px solid var(--line);padding:14px 0}
.e .txt{white-space:pre-wrap}.kv div[dir=rtl]{text-align:left}@media (max-width:800px){.e{grid-template-columns:1fr}}
a{color:inherit}
.isl{direction:rtl;unicode-bidi:isolate}
.mk{border-radius:3px;text-decoration:none;padding:0 1px}
.mk.s1{background:color-mix(in srgb,var(--s1) 26%,transparent)}.mk.s2{background:color-mix(in srgb,var(--s2) 26%,transparent)}
.mk.s3{background:color-mix(in srgb,var(--s3) 22%,transparent)}
.ins{font-weight:700;text-decoration:none;padding:0 2px;border-radius:3px}
.ins.s1{background:var(--s1);color:#fff}.ins.s2{background:var(--s2);color:#fff}.ins.s3{background:var(--s3);color:#fff}
.mk.cur,.ins.cur{outline:2px solid var(--fg);outline-offset:1px}
.ctx{background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:6px 9px;margin-top:6px}
.links{font-size:13px;margin-top:4px}.links a{margin-right:10px}
details{margin-top:6px}summary{cursor:pointer;color:var(--mut)}
.pgl{font-size:12px;color:var(--mut);border:1px solid var(--line);border-radius:4px;padding:0 4px;margin:0 3px}
.elev{font-size:13px;margin:4px 0}
"""
LIVE = "https://menachemshapiro.github.io/Jastrow-Book/"


def esc(s): return html.escape(str(s or ""))


def crop_lines(img, scan, lines, boxes, pad_lines=1):
    """the column width of the lines involved, with a line above and below"""
    L = {ln["i"]: ln for ln in scan["ocr"]["lines"]} if scan and scan.get("ocr") else {}
    ls = [l for l in lines if l in L]
    if not ls and boxes:
        b = [min(x[0] for x in boxes), min(x[1] for x in boxes), max(x[2] for x in boxes), max(x[3] for x in boxes)]
        return img.crop((b[0] - 40, b[1] - 30, b[2] + 40, b[3] + 30))
    if not ls: return None
    # context lines from the same column
    col = (L[ls[0]]["seg"], L[ls[0]]["col"])
    same = [l for l in L if (L[l]["seg"], L[l]["col"]) == col]
    lo = max(min(same), min(ls) - pad_lines); hi = min(max(same), max(ls) + pad_lines)
    use = [l for l in range(lo, hi + 1) if l in L] + [l for l in ls if l not in range(lo, hi + 1)]
    cb = L[ls[0]]["colbox"]
    y0 = min(L[l]["box"][1] for l in use) - 6; y1 = max(L[l]["box"][3] for l in use) + 6
    x0 = min(cb[0], min(L[l]["box"][0] for l in use)) - 8; x1 = max(cb[2], max(L[l]["box"][2] for l in use)) + 8
    im = img.crop((x0, y0, x1, y1)).convert("RGB")
    d = ImageDraw.Draw(im)
    for b in boxes or []:
        d.rectangle((b[0] - x0 - 2, b[1] - y0 - 2, b[2] - x0 + 2, b[3] - y0 + 2), outline=(220, 40, 40), width=2)
    return im


def stack(parts, label_h=22):
    """pieces of an entry from several columns/pages, one under the other"""
    if not parts: return None
    w = max(p.width for _, p in parts)
    h = sum(p.height + label_h for _, p in parts)
    out = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(out)
    y = 0
    for lab, p in parts:
        d.rectangle((0, y, w, y + label_h - 2), fill=(236, 233, 226))
        d.text((6, y + 2), lab, fill=(60, 60, 60), font=label_font())
        out.paste(p, (0, y + label_h))
        y += p.height + label_h
    return out


def small(im, width=900):
    if im.width > width:
        im = im.resize((width, int(im.height * width / im.width)), Image.LANCZOS)
    return im


def render_marked(text, sup, unit, marks, cur=None):
    """the text as HTML, set like the site (each Hebrew island right to left, folio sides raised), with findings
    highlighted. marks: (start, end, sev, fid, title); start == end marks a place where words are missing."""
    n = len(text)
    cover = [[] for _ in range(n)]
    ins = defaultdict(list)
    for m in marks:
        s_, e_ = max(0, m[0]), min(n, m[1])
        if e_ <= s_: ins[min(max(0, m[0]), n)].append(m)
        else:
            for i in range(s_, e_): cover[i].append(m)
    out, state = [], None

    def close(st):
        if st is None: return
        u, mk, sp = st
        if sp: out.append("</sup>")
        if mk: out.append("</a>")
        if u is not None: out.append("</span>")

    def opn(st):
        u, mk, sp = st
        if u is not None: out.append('<span class="isl">')
        if mk:
            ms = [m for m in mk]
            sev = min(m[2] for m in ms)
            c = " cur" if cur is not None and any(m[3] == cur for m in ms) else ""
            out.append('<a class="mk s%d%s" href="index.html#f%d" data-f="%s" title="%s">' % (
                sev, c, ms[0][3], " ".join(str(m[3]) for m in ms), esc(" | ".join(m[4] for m in ms))))
        if sp: out.append("<sup>")
    for i in range(n + 1):
        if ins.get(i):
            close(state); state = None
            for m in ins[i]:
                c = " cur" if cur is not None and m[3] == cur else ""
                out.append('<a class="ins s%d%s" href="index.html#f%d" data-f="%d" title="%s">‸</a>' %
                           (m[2], c, m[3], m[3], esc(m[4])))
        if i == n: break
        st = (unit[i], tuple(cover[i]), sup[i])
        if st != state:
            close(state); opn(st); state = st
        out.append(esc(text[i]))
    close(state)
    return "".join(out)


def write(out, findings, pages, entries, book, run, scans=None, site_url="http://localhost:8000/"):
    """out: the audit folder; pages: {pid: {"stats":…, "scan":…}}; entries: [(pid, eid, parts)]"""
    rd = os.path.join(out, "report")
    os.makedirs(os.path.join(rd, "crops"), exist_ok=True)
    os.makedirs(os.path.join(rd, "entries"), exist_ok=True)
    with open(os.path.join(out, "findings.jsonl"), "w") as f:
        for x in findings:
            f.write(json.dumps({k: v for k, v in x.items() if k not in ("boxes",)}, ensure_ascii=False) + "\n")
    imgs = {}

    def page_img(pid):
        if pid not in imgs:
            p = os.path.join(out, "pages", "p%04d" % int(pid), "page.png")
            imgs[pid] = Image.open(p) if os.path.exists(p) else None
        return imgs[pid]

    def page_links(pid, eid=None):
        """open the whole page: the scan (PDF at that page, and the straightened image) and the site"""
        L = []
        sc = pages.get(pid, {}).get("scan")
        if sc and scans and sc.get("pdf"):
            L.append('<a href="%s#page=%d" target="_blank">scan PDF p. %d</a>' % (
                esc(os.path.relpath(os.path.join(scans, sc["pdf"]), rd)), sc["pdf_page"], sc["pdf_page"]))
        if page_img(pid) is not None:
            L.append('<a href="../pages/p%04d/page.png" target="_blank">scan image</a>' % int(pid))
            L.append('<a href="../pages/p%04d/layout.png" target="_blank">layout</a>' % int(pid))
        L.append('<a href="%s#p%s" target="_blank">site page (local)</a>' % (esc(site_url), pid))
        L.append('<a href="%s#p%s" target="_blank">site page (live)</a>' % (LIVE, pid))
        if eid:
            L.append('<a href="%s#%s" target="_blank">entry on site (local)</a>' % (esc(site_url), esc(eid)))
        return '<div class="links">%s</div>' % " ".join(L)

    for n, x in enumerate(findings):
        x["_id"] = n
    # ---- each entry's text, as the site has it, with its findings marked (one piece per page)
    by_eid = defaultdict(list)
    for pid, eid, parts in entries:
        by_eid[eid].append((pid, parts))
    order = []
    for pid, eid, parts in entries:
        if eid not in order: order.append(eid)
    for x in findings:                                  # entries with findings but no scan (site-only checks)
        if x.get("eid") and x["eid"] not in by_eid and x["page"] in run:
            by_eid[x["eid"]].append((x["page"], [])); order.append(x["eid"])
    fby = defaultdict(list)
    for x in findings:
        if x.get("eid"): fby[x["eid"]].append(x)
    ent_html, ent_level, ctx_html = {}, defaultdict(list), {}
    for eid in order:
        pieces = []
        for pid, _ in by_eid[eid]:
            p = book.page(pid)
            sp = p.entry_span(eid)
            if not sp: continue
            text, pos, sup_, unit = p.text_map(*sp)
            marks = []
            for x in fby[eid]:
                if x["page"] != pid: continue
                title = "%s: %s" % (TYPES.get(x["type"], x["type"]), x.get("note") or "")
                m = None
                if x.get("off") is not None and sp[0] <= x["off"] <= sp[1]:
                    e_ = x.get("end") if x.get("end") is not None else x["off"]
                    m = (pos[x["off"]], pos[max(x["off"], min(e_, sp[1]))], x["sev"], x["_id"], title)
                elif x.get("site") and len(x["site"]) >= 4:
                    k = text.find(x["site"][:80])
                    if k >= 0: m = (k, k + len(x["site"][:80]), x["sev"], x["_id"], title)
                if m: marks.append(m); x["_mark"] = (pid, m)
                else: ent_level[eid].append(x)
            pieces.append((pid, text, sup_, unit, marks))
            # each finding's context: about 90 characters either side of its mark
            for m in marks:
                a0 = max(0, m[0] - 90); b0 = min(len(text), m[1] + 90)
                while a0 > 0 and not text[a0 - 1].isspace(): a0 -= 1
                while b0 < len(text) and not text[b0].isspace(): b0 += 1
                sub = [(mm[0] - a0, mm[1] - a0, mm[2], mm[3], mm[4]) for mm in marks if mm[3] == m[3]]
                ctx_html[m[3]] = ("… " if a0 > 0 else "") + render_marked(text[a0:b0], sup_[a0:b0], unit[a0:b0], sub, cur=m[3]) + \
                    (" …" if b0 < len(text) else "")
        multi = len(pieces) > 1
        ent_html[eid] = " ".join(('<span class="pgl">p. %s</span>' % pid if multi else "") +
                                 render_marked(t, su, un, mk) for pid, t, su, un, mk in pieces)
    # crops for findings
    for x in findings:
        n = x["_id"]
        sc = pages.get(x["page"], {}).get("scan")
        im = page_img(x["page"]) if sc else None
        if im is None or not (x.get("lines") or x.get("boxes")): continue
        c = crop_lines(im, sc, x.get("lines") or [], x.get("boxes") or [])
        if c is None: continue
        name = "crops/f%05d.png" % n
        small(c).save(os.path.join(rd, name))
        x["_crop"] = name
    # entry images: parts from every page of the run
    ent_rows = []
    run_set = set(run)
    order_pages = book.body_pages()
    for eid in order:
        pieces, pids = [], []
        for pid, parts in by_eid[eid]:
            pids.append(pid)
            im = page_img(pid)
            if im is None: continue
            for pt in parts:
                b = pt["box"]
                pieces.append(("p. %s, %s column%s" % (pid, {"L": "left", "R": "right"}[pt["col"]],
                                                      ", below the letter heading" if pt["seg"] > 0 else ""),
                               im.crop((max(0, b[0]), max(0, b[1]), b[2], b[3])).convert("RGB")))
        st = stack(pieces)
        name = None
        if st is not None:
            name = "entries/%s.png" % eid
            small(st, 760).save(os.path.join(rd, name))
        cont_note = ""
        if pids:
            k = order_pages.index(pids[-1])
            if k + 1 < len(order_pages):
                nx = book.page(order_pages[k + 1])
                if nx.entries and nx.entries[0]["eid"] == eid and nx.entries[0]["cont"] and nx.pid not in run_set:
                    cont_note = "continues on p. %s, which is not in this run" % nx.pid
            fe = next((e for e in book.page(pids[0]).entries if e["eid"] == eid), None)
            if fe and fe["cont"]:
                k0 = order_pages.index(pids[0])
                if k0 > 0 and order_pages[k0 - 1] not in run_set:
                    cont_note = ("begins on p. %s, which is not in this run. " % order_pages[k0 - 1]) + cont_note
        hw = next((e["hw"] for pid in pids for e in book.page(pid).entries if e["eid"] == eid and e["hw"]), "")
        ent_rows.append((eid, pids, hw, name, cont_note))
    # ---- index.html
    cnt = Counter(x["type"] for x in findings)
    sevc = Counter(x["sev"] for x in findings)
    eid_has = Counter(x.get("eid") for x in findings)
    h = ['<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,'
         'initial-scale=1"><title>Jastrow audit</title><style>%s</style></head><body>' % CSS]
    h.append("<h1>Jastrow audit: the site against the 1903 scan</h1>")
    h.append('<div class="mut">Pages %s · %d findings (%s) · <a href="entries.html">every entry, scan beside text</a></div>' %
             (esc(", ".join(run) if len(run) < 12 else "%s–%s (%d pages)" % (run[0], run[-1], len(run))), len(findings),
              ", ".join("%d %s" % (sevc[k], SEV[k]) for k in sorted(sevc))))
    bad = [pid for pid in run if pages.get(pid, {}).get("stats", {}).get("scan_problem")]
    if bad:
        h.append('<h2 class="s1">Scan pages that look incomplete</h2><div>%s. Check these scans first: findings on '
                 'them may come from the scan, not the site. Pages: %s</div>' % (len(bad), ", ".join(
                     '<a href="#p%s">%s</a>' % (p, p) for p in bad)))
    h.append("<h2>By kind</h2><table><tr><th>Kind</th><th>Code</th><th class=n>Count</th></tr>")
    for k, v in sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0])):
        h.append('<tr><td>%s</td><td class="mut">%s</td><td class="n">%d</td></tr>' % (esc(TYPES.get(k, k)), k, v))
    h.append("</table><h2>Pages</h2><table><tr><th>Page</th><th class=n>Site words matched</th><th class=n>Entries</th>"
             "<th class=n>Book entry lines</th><th class=n>Findings</th></tr>")
    pf = Counter(x["page"] for x in findings)
    for pid in run:
        st = pages.get(pid, {}).get("stats", {})
        h.append('<tr><td><a href="#p%s">%s</a></td><td class="n">%s</td><td class="n">%s</td><td class="n">%s</td>'
                 '<td class="n">%d</td></tr>' %
                 (pid, pid, ("%.0f%%" % (100 * st["match_rate"])) if "match_rate" in st else "–",
                  st.get("entries", "–"), st.get("book_entry_lines", "–"), pf[pid]))
    h.append("</table>")
    h.append('<div class="bar">Show: ' + "".join('<label><input type="checkbox" class="sv" value="%d" checked> %s</label>'
                                                   % (k, SEV[k]) for k in (1, 2, 3)) +
             ' <select id="ty"><option value="">all kinds</option>' +
             "".join('<option value="%s">%s (%d)</option>' % (k, esc(TYPES.get(k, k)), v) for k, v in sorted(cnt.items())) +
             "</select></div>")
    used_eids = set()
    for pid in run:
        fs = [x for x in findings if x["page"] == pid]
        h.append('<h2 id="p%s">Page %s <span class="mut">· %d findings</span></h2>%s' % (pid, pid, len(fs), page_links(pid)))
        for x in sorted(fs, key=lambda x: (x["sev"], x["type"])):
            kv = []
            if x.get("site") and x["_id"] not in ctx_html: kv.append(("site", x["site"]))
            if x.get("scan"): kv.append(("scan (OCR)", x["scan"]))
            for k in ("site_vis", "book_vis", "site_heb", "scan_heb", "reread", "quote", "found", "ref",
                      "book_words", "scan_line", "proposed_known", "proposed_below", "context"):
                if x.get(k) not in (None, "", []): kv.append((k.replace("_", " "), x[k] if not isinstance(x[k], list) else ", ".join(x[k])))
            eid = x.get("eid")
            h.append('<div class="f" id="f%d" data-sev="%d" data-ty="%s"><div class="t s%d">%s <span class="mut">· %s · %s%s</span></div>'
                     % (x["_id"], x["sev"], x["type"], x["sev"], esc(TYPES.get(x["type"], x["type"])), SEV[x["sev"]], x["type"],
                        (' · <a href="entries.html#%s">entry %s</a>' % (esc(eid), esc(eid))) if eid else ""))
            if x.get("note"): h.append("<div>%s</div>" % esc(x["note"]))
            if x["_id"] in ctx_html:
                h.append('<div class="ctx" dir="ltr">%s</div>' % ctx_html[x["_id"]])
            h.append('<div class="kv">' + "".join('<div>%s</div><div dir="%s">%s</div>' % (
                esc(k), "rtl" if k in ("site heb", "scan heb", "site vis", "book vis", "quote") else "ltr", sup(esc(v)))
                for k, v in kv) + "</div>")
            if eid and eid in ent_html:
                used_eids.add(eid)
                h.append('<details data-e="%s" data-f="%d"><summary>show the whole entry</summary><div class="ctx" dir="ltr">'
                         '</div></details>' % (esc(eid), x["_id"]))
            if x.get("_crop"): h.append('<img loading="lazy" src="%s" alt="scan">' % x["_crop"])
            h.append(page_links(pid, eid))
            h.append("</div>")
    # each entry's marked text once; "show the whole entry" copies it in and outlines the finding
    for eid in used_eids:
        h.append('<template id="t-%s">%s</template>' % (esc(eid), ent_html[eid]))
    h.append("""<script>
function upd(){const s=[...document.querySelectorAll('.sv')].filter(c=>c.checked).map(c=>c.value);const t=document.getElementById('ty').value;
document.querySelectorAll('.f').forEach(f=>{f.style.display=(s.includes(f.dataset.sev)&&(!t||f.dataset.ty===t))?'':'none'})}
document.querySelectorAll('.sv,#ty').forEach(e=>e.addEventListener('change',upd));
document.querySelectorAll('details[data-e]').forEach(d=>d.addEventListener('toggle',()=>{
 const box=d.querySelector('.ctx'); if(!d.open||box.childNodes.length) return;
 box.appendChild(document.getElementById('t-'+d.dataset.e).content.cloneNode(true));
 box.querySelectorAll('[data-f]').forEach(m=>{if(m.dataset.f.split(' ').includes(d.dataset.f)) m.classList.add('cur')});
}));</script></body></html>""")
    open(os.path.join(rd, "index.html"), "w").write("\n".join(h))
    # ---- entries.html
    h = ['<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,'
         'initial-scale=1"><title>Jastrow audit: entries</title><style>%s</style></head><body>' % CSS,
         '<h1>Every entry: the scan beside the site</h1><div class="mut"><a href="index.html">back to the findings</a> · '
         'an entry that runs over two columns or pages is shown in all its parts, in reading order · findings are '
         'highlighted in the text (hover for what, click to go to the finding) · '
         '<label><input type="checkbox" id="only"> only entries with findings</label></div>']
    for eid, pids, hw, name, cont_note in ent_rows:
        nf = eid_has.get(eid, 0)
        lev = "".join('<div class="elev"><a class="mk s%d" href="index.html#f%d">%s</a> %s</div>' % (
            x["sev"], x["_id"], esc(TYPES.get(x["type"], x["type"])), esc(x.get("note") or "")) for x in ent_level.get(eid, []))
        h.append('<div class="e" id="%s" data-n="%d"><div><b lang="he" dir="rtl">%s</b> <span class="mut">%s · p. %s%s</span>'
                 '%s%s<div class="txt" dir="ltr">%s</div>%s</div><div>%s</div></div>' %
                 (esc(eid), nf, esc(hw), esc(eid), esc(", ".join(pids)),
                  (' · %d finding%s' % (nf, "s" if nf > 1 else "")) if nf else "",
                  ('<div class="mut">%s</div>' % esc(cont_note)) if cont_note else "", lev, ent_html.get(eid, ""),
                  page_links(pids[0], eid) if pids else "",
                  ('<img loading="lazy" src="%s" alt="scan of the entry">' % name) if name else '<div class="mut">no scan</div>'))
    h.append("""<script>document.getElementById('only').addEventListener('change',e=>{document.querySelectorAll('.e').forEach(x=>{
x.style.display=(e.target.checked&&x.dataset.n==='0')?'none':''})})</script></body></html>""")
    open(os.path.join(rd, "entries.html"), "w").write("\n".join(h))
    # ---- summary.txt
    lines = ["Jastrow audit: pages %s" % (", ".join(run) if len(run) < 12 else "%s-%s (%d)" % (run[0], run[-1], len(run))),
             "findings: %d (%s)" % (len(findings), ", ".join("%d %s" % (sevc[k], SEV[k]) for k in sorted(sevc))),
             "by kind: " + ", ".join("%s %d" % (k, v) for k, v in sorted(cnt.items(), key=lambda kv: -kv[1])),
             "scan pages that look incomplete: " + (", ".join(bad) or "none"),
             "per page (matched %, entries site/book, findings):"]
    for pid in run:
        st = pages.get(pid, {}).get("stats", {})
        lines.append("  p. %s: %s, %s/%s, %d" % (pid, ("%.0f%%" % (100 * st["match_rate"])) if "match_rate" in st else "no scan",
                                                  st.get("entries", "-"), st.get("book_entry_lines", "-"), pf[pid]))
    open(os.path.join(out, "summary.txt"), "w").write("\n".join(lines) + "\n")
    return os.path.join(rd, "index.html"), "\n".join(lines)
