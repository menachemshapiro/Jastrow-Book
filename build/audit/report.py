"""Write the audit's report: findings.jsonl (one finding per line, for tools), summary.txt (short, to paste to
Claude), and report/index.html + report/entries.html (to read: every finding with its piece of the scan, and every
entry's scan, from all the columns and pages it runs over, beside the site's text)."""
import hashlib, html, json, os, time
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

SEV = {1: "likely error", 2: "check", 3: "minor / uncertain", 4: "decide as a group"}
# kinds that are one systematic question each, decided together, not finding by finding
GROUP = {"ib_named", "abbreviation"}
SEV_ORDER = (1, 2, 4, 3)
SEV_TITLE = {1: "Likely errors", 2: "Worth a check", 3: "Minor or uncertain", 4: "Decide as a group"}
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
    "ib_named": "Book has “Ib.”, site names the work", "word_count": "Word count differs", "etc_first": "Hebrew begins with “etc.”", "homonym_number": "Homonym number out of sequence", "abbreviation": "Abbreviation spelt differently",
}

# what the OCR could not read is not a finding about the site: counted per page, not listed
NOT_CHECKED = {"hebrew_unread", "headword_unread"}
# checks of the site's text alone
SITE_ONLY = {"brackets", "sense_numbers", "stray_char", "headword_text", "headword_display", "alphabetical",
             "doubled_text", "doubled_word", "hyphen_space", "etc_first", "homonym_number"}
SEV_HELP = {1: "What the audit thinks is most likely a real difference between the site and the book.",
            2: "A difference that may be real, or may come from the OCR or the page layout. Compare the two sides.",
            3: "Small or doubtful: mostly OCR noise. Look here after the others.",
            4: "Systematic differences, one question each: the book's “Ib.” where Sefaria's text names the work, and "
               "abbreviations spelt with a letter more or less. Decide each kind once (restore the book, or keep the "
               "site), rather than finding by finding."}
LABEL = {"site_words": "site only", "scan": "OCR reads", "reread": "read again", "book_vis": "Hebrew in the book", "scan_heb": "Hebrew OCR",
         "book_words": "book's words", "scan_line": "the book's line", "site_vis": "as the site shows it",
         "site_heb": "site's Hebrew", "ref": "reference", "quote": "the quotation", "found": "found at",
         "proposed_known": "proposed", "proposed_below": "proposed below", "context": "context"}
CSS2 = """
main{max-width:1180px;margin:0 auto}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:16px 0}
.tile{display:flex;flex-direction:column;background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:10px 14px;cursor:pointer;position:relative}.tile input{position:absolute;top:10px;right:10px}
.tile b{font-size:28px;line-height:1.1;font-variant-numeric:tabular-nums}.tile small{color:var(--mut)}
.tile.t1 b{color:var(--s1)}.tile.t2 b{color:var(--s2)}.tile.t3 b{color:var(--s3)}.tile.t4 b{color:var(--s4)}.tile.t0{cursor:default}.tile.t0 b{color:var(--mut)}
.tile:has(input:not(:checked)){opacity:.55}
.warn{border:1px solid var(--s1);border-radius:8px;padding:8px 12px;margin:8px 0}
.pill{font-size:12px;font-weight:600;border-radius:99px;padding:1px 8px;color:#fff;white-space:nowrap}
.pill.p1{background:var(--s1)}.pill.p2{background:var(--s2)}.pill.p3{background:var(--s3)}.pill.p4{background:var(--s4)}
article.f{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:12px 0}
article.f header{display:flex;flex-wrap:wrap;gap:6px 8px;align-items:baseline}
.note{margin:6px 0 8px}
.cmp{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px}
@media (max-width:820px){.cmp{grid-template-columns:1fr}}
.side{border:1px solid var(--line);border-radius:8px;padding:8px 10px;background:var(--bg)}
.side .ctx{border:0;padding:0;margin:0;background:none}.side img{margin-top:0;display:block}
.lab{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut);margin-bottom:4px}
.sub{font-size:13px;color:var(--mut);margin-top:6px}.sub span:first-child{font-weight:600}
.grp h2 .mut{font-weight:400}
.mark{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-top:10px;padding-top:8px;border-top:1px dashed var(--line)}
.mark button{font:inherit;font-size:13px;border:1px solid var(--line);background:var(--bg);color:var(--fg);border-radius:99px;
padding:2px 10px;cursor:pointer}.mark button:hover{border-color:var(--mut)}
.mark button.on[data-v=error]{background:var(--s1);border-color:var(--s1);color:#fff}
.mark button.on[data-v=false]{background:#12805c;border-color:#12805c;color:#fff}
.mark button.on[data-v=unsure]{background:var(--s3);border-color:var(--s3);color:#fff}
.mark textarea{flex:1 1 260px;min-width:0;font:inherit;font-size:13px;border:1px solid var(--line);border-radius:6px;
background:var(--bg);color:var(--fg);padding:3px 8px;resize:vertical;min-height:28px;height:28px}
.mark .when{font-size:12px;color:var(--mut)}
article.f.done{border-left:4px solid var(--line)}article.f.v-error{border-left-color:var(--s1)}
article.f.v-false{border-left-color:#12805c}article.f.v-unsure{border-left-color:var(--s3)}
.mbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:6px}
.mbar button,.mbar label.btn{font:inherit;font-size:13px;border:1px solid var(--line);background:var(--card);color:var(--fg);
border-radius:6px;padding:2px 10px;cursor:pointer}.mbar .dirty{color:var(--s2);font-weight:600}
"""
CSS = """
:root{--bg:#fbfaf7;--fg:#1d1b18;--mut:#6b665e;--line:#e3dfd6;--s1:#b42318;--s2:#b54708;--s3:#667085;--s4:#6941c6;--card:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#161513;--fg:#ece8e1;--mut:#a29c92;--line:#36332e;--card:#1f1e1b;
--s1:#f97066;--s2:#fdb022;--s3:#98a2b3;--s4:#b692f6}}
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
.mk.cur.s1{background:color-mix(in srgb,var(--s1) 42%,transparent);text-decoration:underline 2px var(--s1);text-underline-offset:4px}
.mk.cur.s2{background:color-mix(in srgb,var(--s2) 42%,transparent);text-decoration:underline 2px var(--s2);text-underline-offset:4px}
.mk.cur.s3{background:color-mix(in srgb,var(--s3) 38%,transparent);text-decoration:underline 2px var(--s3);text-underline-offset:4px}
.ins.cur{box-shadow:0 0 0 2px color-mix(in srgb,var(--fg) 25%,transparent)}
.ctx{background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:6px 9px;margin-top:6px}
.links{font-size:13px;margin-top:4px}.links a{margin-right:10px}
details{margin-top:6px}summary{cursor:pointer;color:var(--mut)}
.pgl{font-size:12px;color:var(--mut);border:1px solid var(--line);border-radius:4px;padding:0 4px;margin:0 3px}
.elev{font-size:13px;margin:4px 0}
.we{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px}.we img{margin-top:0}
@media (max-width:800px){.we{grid-template-columns:1fr}}
"""
LIVE = "https://menachemshapiro.github.io/Jastrow-Book/"


def esc(s): return html.escape(str(s or ""))


# what a mark keeps of its finding, so that marks.json alone says what was judged
MARK_FIELDS = ("page", "type", "sev", "eid", "site", "scan", "note", "reread", "site_heb", "scan_heb", "site_vis",
               "book_vis", "site_all", "scan_all", "ocr_conf", "ref", "quote", "found")


def fkey(x):
    """a finding's key, the same from run to run as long as the site's text and the OCR's reading are: the page, the
    kind, the entry and the two texts (not the severity or the note, which tuning changes)"""
    s = "|".join(str(x.get(k) or "") for k in ("page", "type", "eid", "site", "scan", "site_heb", "scan_heb", "book_vis"))
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]


def marks_line(shown):
    """your verdicts on this run's findings, and the false alarms by kind (what tuning should look at)"""
    v = Counter((x.get("mark") or {}).get("verdict") for x in shown if (x.get("mark") or {}).get("verdict"))
    if not v: return "your marks: none yet (mark findings in the report, then Export marks)"
    fa = Counter(x["type"] for x in shown if (x.get("mark") or {}).get("verdict") == "false")
    er = Counter(x["type"] for x in shown if (x.get("mark") or {}).get("verdict") == "error")
    return "your marks: %d (site is wrong %d, false alarm %d, not sure %d); false alarms by kind: %s; errors by kind: %s" % (
        sum(v.values()), v["error"], v["false"], v["unsure"],
        ", ".join("%s %d" % kv for kv in fa.most_common()) or "none", ", ".join("%s %d" % kv for kv in er.most_common()) or "none")


def load_marks(paths_):
    """the verdicts given in the report, from marks.json files (exported from the report): {key: mark}; where a key
    is in more than one file, the latest verdict wins"""
    out = {}
    for p in paths_:
        try: d = json.load(open(p))
        except Exception: continue
        for m in d.get("marks", []):
            k = m.get("key")
            if k and (k not in out or (m.get("time") or "") >= (out[k].get("time") or "")): out[k] = m
    return out


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
            if state is not None and i < n and unit[i] is not None and unit[i] == state[0] and i > 0 and unit[i - 1] == unit[i]:
                close((None,) + state[1:]); state = (state[0], (), False); out.append("")
            else:
                close(state); state = None
            for m in ins[i]:
                c = " cur" if cur is not None and m[3] == cur else ""
                out.append('<a class="ins s%d%s" href="index.html#f%d" data-f="%d" title="%s">‸</a>' %
                           (m[2], c, m[3], m[3], esc(m[4])))
        if i == n: break
        st = (unit[i], tuple(cover[i]), sup[i])
        if st != state:
            # a mark starting or ending inside a right-to-left island must not split the island: two islands are set
            # left to right, so the Hebrew would come out in the wrong order. Close and reopen only what is inside it
            if state is not None and st[0] is not None and st[0] == state[0]:
                close((None,) + state[1:]); opn((None,) + st[1:])
            else:
                close(state); opn(st)
            state = st
        out.append(esc(text[i]))
    close(state)
    return "".join(out)


def write(out, findings, pages, entries, book, run, scans=None, site_url="http://localhost:8000/", pages_root=None,
          marks=None, label=""):
    """out: this run's folder; pages_root: the folder whose pages/ holds each page's scan and OCR (shared by all
    runs); pages: {pid: {"stats":…, "scan":…}}; entries: [(pid, eid, parts)]"""
    pages_root = pages_root or out
    rd = os.path.join(out, "report")
    prel = os.path.relpath(os.path.join(pages_root, "pages"), rd)
    os.makedirs(os.path.join(rd, "crops"), exist_ok=True)
    os.makedirs(os.path.join(rd, "entries"), exist_ok=True)
    saved = marks or {}
    for x in findings:
        x["key"] = fkey(x)
        if x["key"] in saved: x["mark"] = {k: saved[x["key"]].get(k) for k in ("verdict", "note", "time")}
    with open(os.path.join(out, "findings.jsonl"), "w") as f:
        for x in findings:
            f.write(json.dumps({k: v for k, v in x.items() if k not in ("boxes",)}, ensure_ascii=False) + "\n")
    imgs = {}

    def page_img(pid):
        if pid not in imgs:
            p = os.path.join(pages_root, "pages", "p%04d" % int(pid), "page.png")
            imgs[pid] = Image.open(p) if os.path.exists(p) else None
        return imgs[pid]

    def page_links(pid, eid=None):
        """open the whole page: the scan (PDF at that page, and the straightened image) and the site"""
        L = []
        if page_img(pid) is not None:
            L.append('<a href="%s/p%04d/page.png" target="_blank">whole scan page</a>' % (prel, int(pid)))
            L.append('<a href="%s/p%04d/layout.png" target="_blank">layout</a>' % (prel, int(pid)))
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
    # ---- index.html: likely errors first; each finding as the site's text beside the book's scan
    eimg = {r[0]: r[3] for r in ent_rows}
    for x in findings:
        if x["type"] in GROUP: x["sev"] = 4
    shown = [x for x in findings if x["type"] not in NOT_CHECKED]
    unread = [x for x in findings if x["type"] in NOT_CHECKED]
    cnt = Counter(x["type"] for x in shown)
    sevc = Counter(x["sev"] for x in shown)
    eid_has = Counter(x.get("eid") for x in findings)
    pf = Counter(x["page"] for x in shown)
    pu = Counter(x["page"] for x in unread)
    hw_of = {r[0]: r[2] for r in ent_rows}
    bad = [pid for pid in run if pages.get(pid, {}).get("stats", {}).get("scan_problem")]
    runs_txt = esc(", ".join(run) if len(run) < 12 else "%s–%s (%d pages)" % (run[0], run[-1], len(run)))
    h = ['<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,'
         'initial-scale=1"><title>Jastrow audit</title><style>%s</style></head><body><main>' % (CSS + CSS2)]
    h.append('<h1>Jastrow audit</h1><div class="mut">The site against the 1903 scan · pages %s · '
             '<a href="entries.html">every entry, scan beside text</a></div>' % runs_txt)
    # the counts, as tiles that also switch the list
    h.append('<div class="tiles">')
    for k, lab, sub in ((1, "Likely errors", "start here"), (2, "Worth a check", "often OCR or layout"),
                        (4, "Decide as a group", "Ib., abbreviations"), (3, "Minor or uncertain", "hidden at first")):
        h.append('<label class="tile t%d"><input type="checkbox" class="sv" value="%d"%s><b>%d</b><span>%s</span>'
                 '<small>%s</small></label>' % (k, k, "" if k == 3 else " checked", sevc[k], lab, sub))
    h.append('<div class="tile t0"><b>%d</b><span>Hebrew not checked</span><small>the OCR could not read it; '
             'not a finding</small></div></div>' % len(unread))
    if bad:
        h.append('<div class="warn"><b>Scan pages that look incomplete: %s.</b> Look at these scans first: findings '
                 'on them may come from the scan, not the site.</div>' % ", ".join(
                     '<a href="#p%s">p. %s</a>' % (p, p) for p in bad))
    # filters
    h.append('<div class="bar"><select id="ty"><option value="">every kind</option>%s</select> '
             '<select id="pg"><option value="">every page</option>%s</select> '
             '<select id="mk"><option value="">marked or not</option><option value="none">not yet marked</option>'
             '<option value="error">marked: site is wrong</option><option value="false">marked: false alarm</option>'
             '<option value="unsure">marked: not sure</option><option value="any">marked</option></select> '
             '<span class="mut" id="nshow"></span>'
             '<div class="mbar"><span id="mcount" class="mut"></span>'
             '<button id="mexp" title="save your verdicts and notes as a file">Export marks</button>'
             '<label class="btn" title="load a marks file exported before">Import marks<input type="file" id="mimp" '
             'accept=".json,application/json" hidden></label>'
             '<button id="mauto" hidden title="keep a copy of your marks on disk, saved after every change">Autosave to a file…</button>'
             '<span id="mautost" class="mut"></span><span id="mdirty" class="dirty"></span></div></div>' % (
                 "".join('<option value="%s">%s (%d)</option>' % (k, esc(TYPES.get(k, k)), v)
                         for k, v in sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))),
                 "".join('<option value="%s">p. %s (%d)</option>' % (p, p, pf[p]) for p in run)))
    used_eids = set()

    def site_side(x):
        if x["_id"] in ctx_html:
            body = '<div class="ctx" dir="ltr">%s</div>' % ctx_html[x["_id"]]
        elif x.get("site"):
            body = '<div class="ctx" dir="auto">%s</div>' % sup(esc(x["site"]))
        else:
            body = '<div class="mut">—</div>'
        extra = [(k, x[k]) for k in ("site_vis", "site_heb", "site_words") if x.get(k)]
        body += "".join('<div class="sub"><span>%s</span> <span dir="rtl" lang="he">%s</span></div>'
                        % (LABEL.get(k, k), esc(v)) for k, v in extra)
        return '<div class="side"><div class="lab">Site</div>%s</div>' % body

    def book_side(x):
        if x["type"] in SITE_ONLY:
            im_ = eimg.get(x.get("eid"))
            return '<div class="side"><div class="lab">Book (1903 scan: the whole entry)</div>%s<div class="sub">A check ' \
                   'of the site\'s own text, not compared with the scan word by word.</div></div>' % (
                       ('<img loading="lazy" src="%s" alt="scan of the entry">' % im_) if im_ else
                       '<div class="mut">no scan of this entry: open the scan page</div>')
        if x["type"].startswith("talmud_"):
            body = "".join('<div class="sub"><span>%s</span> <span dir="auto">%s</span></div>' % (
                LABEL.get(k, k), esc(", ".join(x[k]) if isinstance(x[k], list) else x[k]))
                for k in ("ref", "quote", "found") if x.get(k))
            return '<div class="side"><div class="lab">Talmud (Sefaria)</div>%s</div>' % (body or '<div class="mut">—</div>')
        body = ('<img loading="lazy" src="%s" alt="the scan here">' % x["_crop"]) if x.get("_crop") else \
            '<div class="mut">no crop of the scan for this one: open the scan page</div>'
        reads = [(k, x[k]) for k in ("scan", "reread", "book_vis", "scan_heb", "book_words", "scan_line") if x.get(k)]
        body += "".join('<div class="sub"><span>%s</span> <span dir="%s">%s</span></div>' % (
            LABEL.get(k, k), "rtl" if k in ("book_vis", "scan_heb") else "auto",
            sup(esc(", ".join(v) if isinstance(v, list) else v))) for k, v in reads)
        return '<div class="side"><div class="lab">Book (1903 scan)</div>%s</div>' % body

    def card(x):
        eid = x.get("eid")
        where = "p. %s" % x["page"]
        if eid:
            where += ' · <a href="entries.html#%s"><span lang="he" dir="rtl">%s</span> %s</a>' % (
                esc(eid), esc(hw_of.get(eid, "")), esc(eid))
        o = ['<article class="f" id="f%d" data-sev="%d" data-ty="%s" data-pg="%s" data-k="%s">' % (
                 x["_id"], x["sev"], x["type"], x["page"], x["key"]),
             '<header><span class="pill p%d">%s</span> <b>%s</b> <span class="mut">%s</span></header>' % (
                 x["sev"], SEV[x["sev"]], esc(TYPES.get(x["type"], x["type"])), where)]
        if x.get("note"): o.append('<p class="note">%s</p>' % sup(esc(x["note"])))
        o.append('<div class="cmp">%s%s</div>' % (site_side(x), book_side(x)))
        more = [(k, x[k]) for k in ("proposed_known", "proposed_below", "context") if x.get(k) not in (None, "", [])]
        if more:
            o.append('<div class="sub">' + " · ".join("%s: %s" % (esc(LABEL.get(k, k)), esc(v if not isinstance(v, list)
                     else ", ".join(map(str, v)))) for k, v in more) + "</div>")
        if eid and eid in ent_html:
            used_eids.add(eid)
            o.append('<details data-e="%s" data-f="%d"><summary>the whole entry, text and scan</summary><div class="ctx">'
                     '</div></details>' % (esc(eid), x["_id"]))
        o.append(page_links(x["page"], eid))
        o.append('<div class="mark" data-k="%s"><button data-v="error" title="the site differs from the book: a real '
                 'error to correct">Site is wrong</button><button data-v="false" title="the site is right: the OCR, the '
                 'layout or the audit is at fault">False alarm</button><button data-v="unsure">Not sure</button>'
                 '<textarea rows="1" placeholder="note: what the book really has, why it is right or wrong…"></textarea>'
                 '<span class="when"></span></div>' % x["key"])
        o.append("</article>")
        return "".join(o)

    for sev in SEV_ORDER:
        fs = sorted((x for x in shown if x["sev"] == sev),
                    key=lambda x: (run.index(x["page"]) if x["page"] in run else 1e9, x.get("off") if x.get("off") is not None else 1e9))
        h.append('<section class="grp" data-sev="%d"><h2>%s <span class="mut">%d</span></h2>%s%s</section>' % (
            sev, SEV_TITLE[sev], len(fs),
            '<p class="mut">%s</p>' % SEV_HELP[sev], "".join(card(x) for x in fs) or '<p class="mut">None.</p>'))
    # pages, at the foot: how well each page was read
    h.append('<section><h2 id="pages">Pages</h2><table><tr><th>Page</th><th class=n>Site words found</th>'
             '<th class=n>Entries: site / book</th><th class=n>Findings</th><th class=n>Hebrew not checked</th>'
             '<th></th></tr>')
    for pid in run:
        st = pages.get(pid, {}).get("stats", {})
        e_, b_ = st.get("entries"), st.get("book_entry_lines")
        off = e_ is not None and b_ is not None and abs(e_ - b_) > 1
        h.append('<tr id="p%s"><td>%s%s</td><td class="n">%s</td><td class="n%s">%s / %s</td><td class="n">%d</td>'
                 '<td class="n mut">%d</td><td>%s</td></tr>' % (
                     pid, pid, ' <span class="pill p1">scan?</span>' if pid in bad else "",
                     ("%.0f%%" % (100 * st["match_rate"])) if "match_rate" in st else "–", " s2" if off else "",
                     e_ if e_ is not None else "–", b_ if b_ is not None else "–", pf[pid], pu[pid], page_links(pid)))
    h.append('</table><p class="mut">"Entries: book" counts the lines the book indents as an entry\'s first line, '
             'plus paragraphs such as a binyan. A page whose two numbers differ by more than one is marked.</p></section>')
    for eid in used_eids:
        im_ = ('<img loading="lazy" src="%s" alt="scan of the entry">' % eimg[eid]) if eimg.get(eid) else \
            '<div class="mut">no scan</div>'
        h.append('<template id="t-%s"><div class="we"><div dir="ltr">%s</div><div>%s</div></div></template>' %
                 (esc(eid), ent_html[eid], im_))
    fdata = {x["key"]: {k: x[k] for k in MARK_FIELDS if x.get(k) not in (None, "", [])} for x in shown}
    h.append('<script>const RUN=%s, FD=%s, SAVED=%s;</script>' % tuple(
        json.dumps(v, ensure_ascii=False).replace("</", "<\\/") for v in (label, fdata, list(saved.values()))))
    h.append("""</main><script>
// ---- your verdicts: kept in the browser as you go, and in marks.json when you export them
const LS='jastrow-audit-marks-v1';
let M={}; SAVED.forEach(m=>{M[m.key]=m});
let dirty=false;
function lsRead(){try{return JSON.parse(localStorage.getItem(LS)||'{}')}catch(e){return {}}}
function lsWrite(){try{localStorage.setItem(LS,JSON.stringify(M))}catch(e){}}
Object.values(lsRead()).forEach(m=>{if(m&&m.key&&(!M[m.key]||(m.time||'')>=(M[m.key].time||''))) M[m.key]=m});
function setDirty(v){dirty=v;document.getElementById('mdirty').textContent=v?'not exported yet':''}
function show(box){const k=box.dataset.k, m=M[k]||{}, art=box.closest('article');
 box.querySelectorAll('button').forEach(b=>b.classList.toggle('on',b.dataset.v===m.verdict));
 const ta=box.querySelector('textarea'); if(document.activeElement!==ta) ta.value=m.note||'';
 box.querySelector('.when').textContent=m.time?('marked '+m.time.slice(0,10)):'';
 art.classList.remove('done','v-error','v-false','v-unsure'); if(m.verdict) art.classList.add('done','v-'+m.verdict);}
function count(){const v={error:0,false:0,unsure:0}; let n=0;
 document.querySelectorAll('article.f').forEach(a=>{const m=M[a.dataset.k]; if(m&&m.verdict){v[m.verdict]++;n++}});
 document.getElementById('mcount').textContent='marked '+n+' of '+document.querySelectorAll('article.f').length+
  ': site is wrong '+v.error+', false alarm '+v.false+', not sure '+v.unsure;}
function put(k,ch){const m=Object.assign({key:k},M[k]||{},ch,{time:new Date().toISOString(),run:RUN});
 if(!m.verdict&&!m.note) delete M[k]; else M[k]=m; lsWrite(); setDirty(true); autoSoon();
 const box=document.querySelector('.mark[data-k="'+k+'"]'); if(box) show(box); count();}
document.querySelectorAll('.mark').forEach(box=>{const k=box.dataset.k; show(box);
 box.querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>put(k,{verdict:(M[k]||{}).verdict===b.dataset.v?'':b.dataset.v})));
 const ta=box.querySelector('textarea'); let tm;
 ta.addEventListener('input',()=>{clearTimeout(tm); tm=setTimeout(()=>put(k,{note:ta.value.trim()}),400)});
 ta.addEventListener('focus',()=>{ta.style.height='70px'}); ta.addEventListener('blur',()=>{if(!ta.value) ta.style.height=''});});
count();
function payload(){const marks=Object.values(M).filter(m=>m.verdict||m.note).map(m=>Object.assign({},m,{finding:FD[m.key]||m.finding||null}));
 return JSON.stringify({version:1,exported:new Date().toISOString(),run:RUN,marks:marks},null,1);}
// ---- autosave: a file on disk (Chrome and Edge), written a moment after every change and once a minute
let FH=null, tmA=null, pend=false;
const st=t=>{document.getElementById('mautost').textContent=t};
function idb(){return new Promise((ok,no)=>{const r=indexedDB.open('jastrow-audit',1);
 r.onupgradeneeded=()=>r.result.createObjectStore('kv'); r.onsuccess=()=>ok(r.result); r.onerror=()=>no(r.error)})}
async function idbSet(k,v){try{const db=await idb(); db.transaction('kv','readwrite').objectStore('kv').put(v,k)}catch(e){}}
async function idbGet(k){try{const db=await idb(); return await new Promise(ok=>{const q=db.transaction('kv').objectStore('kv').get(k);
 q.onsuccess=()=>ok(q.result); q.onerror=()=>ok(null)})}catch(e){return null}}
async function autoWrite(){if(!FH||!pend) return; pend=false;
 try{const w=await FH.createWritable(); await w.write(payload()); await w.close(); setDirty(false);
  st('autosaved to '+FH.name+' at '+new Date().toTimeString().slice(0,5));}
 catch(e){pend=true; st('autosave failed ('+e.name+'): use Export marks');}}
function autoSoon(){pend=true; if(!FH) return; clearTimeout(tmA); tmA=setTimeout(autoWrite,2000);}
setInterval(autoWrite,60000);
const ab=document.getElementById('mauto');
async function startAuto(h){FH=h; ab.hidden=true; idbSet('fh',h); pend=true; await autoWrite();}
if(window.showSaveFilePicker){ab.hidden=false;
 ab.addEventListener('click',async()=>{try{
  if(ab.dataset.resume){const h=await idbGet('fh'); if(h&&await h.requestPermission({mode:'readwrite'})==='granted') return startAuto(h);}
  startAuto(await showSaveFilePicker({suggestedName:'jastrow-audit-marks.json',startIn:'downloads',
   types:[{description:'marks',accept:{'application/json':['.json']}}]}));}catch(e){}});
 idbGet('fh').then(async h=>{if(!h) return;
  try{if(await h.queryPermission({mode:'readwrite'})==='granted') return startAuto(h);}catch(e){}
  ab.dataset.resume='1'; ab.textContent='Resume autosave to '+h.name; ab.hidden=false;});
}else st('marks are kept in this browser as you go; for a file, use Export marks (autosave to a file needs Chrome or Edge)');
document.getElementById('mexp').addEventListener('click',()=>{
 const blob=new Blob([payload()],{type:'application/json'});
 const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download='jastrow-audit-marks-'+new Date().toISOString().slice(0,16).replace(/[-:]/g,'').replace('T','-')+'.json';
 document.body.appendChild(a); a.click(); a.remove(); setDirty(false);});
document.getElementById('mimp').addEventListener('change',e=>{const f=e.target.files[0]; if(!f) return;
 f.text().then(t=>{let n=0; (JSON.parse(t).marks||[]).forEach(m=>{if(m.key&&(!M[m.key]||(m.time||'')>=(M[m.key].time||''))){M[m.key]=m;n++}});
  lsWrite(); autoSoon(); document.querySelectorAll('.mark').forEach(show); count(); alert(n+' marks loaded');}).catch(()=>alert('not a marks file'));});
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault(); e.returnValue='';}});
function upd(){const s=[...document.querySelectorAll('.sv')].filter(c=>c.checked).map(c=>c.value);
const t=document.getElementById('ty').value, p=document.getElementById('pg').value, mk=document.getElementById('mk').value; let n=0;
document.querySelectorAll('.f').forEach(f=>{const v=(M[f.dataset.k]||{}).verdict||'';
 const okm=!mk||(mk==='none'?!v:mk==='any'?!!v:v===mk);
 const on=s.includes(f.dataset.sev)&&(!t||f.dataset.ty===t)&&(!p||f.dataset.pg===p)&&okm;
 f.style.display=on?'':'none'; if(on) n++});
document.querySelectorAll('.grp').forEach(g=>{g.style.display=s.includes(g.dataset.sev)?'':'none'});
document.getElementById('nshow').textContent=n+' shown';}
document.querySelectorAll('.sv,#ty,#pg,#mk').forEach(e=>e.addEventListener('change',upd));
if(location.hash.startsWith('#f')){const f=document.querySelector(location.hash); if(f){const c=document.querySelector('.sv[value="'+f.dataset.sev+'"]'); c.checked=true;}}
upd(); if(location.hash){const f=document.querySelector(location.hash); if(f) f.scrollIntoView();}
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
             "findings: %d (%s); Hebrew the OCR could not read, not checked: %d" % (
                 len(shown), ", ".join("%d %s" % (sevc[k], SEV[k]) for k in sorted(sevc)), len(unread)),
             "by kind: " + ", ".join("%s %d" % (k, v) for k, v in sorted(cnt.items(), key=lambda kv: -kv[1])),
             "scan pages that look incomplete: " + (", ".join(bad) or "none"),
             marks_line(shown),
             "per page (matched %, entries site/book, findings, Hebrew not checked):"]
    for pid in run:
        st = pages.get(pid, {}).get("stats", {})
        lines.append("  p. %s: %s, %s/%s, %d, %d" % (pid, ("%.0f%%" % (100 * st["match_rate"])) if "match_rate" in st else "no scan",
                                                      st.get("entries", "-"), st.get("book_entry_lines", "-"), pf[pid], pu[pid]))
    open(os.path.join(out, "summary.txt"), "w").write("\n".join(lines) + "\n")
    return os.path.join(rd, "index.html"), "\n".join(lines)
