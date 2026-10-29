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
"""


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


def write(out, findings, pages, entries, book, run):
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

    # crops for findings
    for n, x in enumerate(findings):
        x["_id"] = n
        sc = pages.get(x["page"], {}).get("scan")
        im = page_img(x["page"]) if sc else None
        if im is None or not (x.get("lines") or x.get("boxes")): continue
        c = crop_lines(im, sc, x.get("lines") or [], x.get("boxes") or [])
        if c is None: continue
        name = "crops/f%05d.png" % n
        small(c).save(os.path.join(rd, name))
        x["_crop"] = name
    # entry images: parts from every page of the run
    by_eid = defaultdict(list)
    for pid, eid, parts in entries:
        by_eid[eid].append((pid, parts))
    ent_rows = []
    order = []
    for pid, eid, parts in entries:
        if eid not in order: order.append(eid)
    run_set = set(run)
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
        # does it continue past the run?
        last = pids[-1] if pids else None
        cont_note = ""
        if last is not None:
            order_pages = book.body_pages()
            k = order_pages.index(last)
            if k + 1 < len(order_pages):
                nx = book.page(order_pages[k + 1])
                if nx.entries and nx.entries[0]["eid"] == eid and nx.entries[0]["cont"] and nx.pid not in run_set:
                    cont_note = "continues on p. %s, which is not in this run" % nx.pid
            first_page = book.page(pids[0])
            fe = next((e for e in first_page.entries if e["eid"] == eid), None)
            if fe and fe["cont"]:
                k0 = order_pages.index(pids[0])
                if k0 > 0 and order_pages[k0 - 1] not in run_set:
                    cont_note = ("begins on p. %s, which is not in this run. " % order_pages[k0 - 1]) + cont_note
        text = " ".join(book.page(pid).entry_text(eid) for pid in pids)
        hw = next((e["hw"] for pid in pids for e in book.page(pid).entries if e["eid"] == eid and e["hw"]), "")
        ent_rows.append((eid, pids, hw, text, name, cont_note))
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
             "<th class=n>Book entry lines</th><th class=n>Findings</th><th>Layout</th></tr>")
    pf = Counter(x["page"] for x in findings)
    for pid in run:
        st = pages.get(pid, {}).get("stats", {})
        lay = "pages/p%04d/layout.png" % int(pid)
        h.append('<tr><td><a href="#p%s">%s</a></td><td class="n">%s</td><td class="n">%s</td><td class="n">%s</td>'
                 '<td class="n">%d</td><td><a href="../%s">layout</a></td></tr>' %
                 (pid, pid, ("%.0f%%" % (100 * st["match_rate"])) if "match_rate" in st else "–",
                  st.get("entries", "–"), st.get("book_entry_lines", "–"), pf[pid], lay))
    h.append("</table>")
    h.append('<div class="bar">Show: ' + "".join('<label><input type="checkbox" class="sv" value="%d" checked> %s</label>'
                                                   % (k, SEV[k]) for k in (1, 2, 3)) +
             ' <select id="ty"><option value="">all kinds</option>' +
             "".join('<option value="%s">%s (%d)</option>' % (k, esc(TYPES.get(k, k)), v) for k, v in sorted(cnt.items())) +
             "</select></div>")
    for pid in run:
        fs = [x for x in findings if x["page"] == pid]
        h.append('<h2 id="p%s">Page %s <span class="mut">· %d findings</span></h2>' % (pid, pid, len(fs)))
        for x in sorted(fs, key=lambda x: (x["sev"], x["type"])):
            kv = []
            if x.get("site"): kv.append(("site", x["site"]))
            if x.get("scan"): kv.append(("scan (OCR)", x["scan"]))
            for k in ("site_vis", "book_vis", "site_heb", "scan_heb", "reread", "quote", "found", "ref",
                      "book_words", "scan_line", "proposed_known", "proposed_below", "context"):
                if x.get(k) not in (None, "", []): kv.append((k.replace("_", " "), x[k] if not isinstance(x[k], list) else ", ".join(x[k])))
            h.append('<div class="f" data-sev="%d" data-ty="%s"><div class="t s%d">%s <span class="mut">· %s · %s%s</span></div>'
                     % (x["sev"], x["type"], x["sev"], esc(TYPES.get(x["type"], x["type"])), SEV[x["sev"]], x["type"],
                        (' · <a href="entries.html#%s">entry %s</a>' % (esc(x["eid"]), esc(x["eid"]))) if x.get("eid") else ""))
            if x.get("note"): h.append("<div>%s</div>" % esc(x["note"]))
            h.append('<div class="kv">' + "".join('<div>%s</div><div dir="%s">%s</div>' % (
                esc(k), "rtl" if k in ("site heb", "scan heb", "site vis", "book vis", "quote") else "ltr", sup(esc(v)))
                for k, v in kv) + "</div>")
            if x.get("_crop"): h.append('<img loading="lazy" src="%s" alt="scan">' % x["_crop"])
            h.append("</div>")
    h.append("""<script>
function upd(){const s=[...document.querySelectorAll('.sv')].filter(c=>c.checked).map(c=>c.value);const t=document.getElementById('ty').value;
document.querySelectorAll('.f').forEach(f=>{f.style.display=(s.includes(f.dataset.sev)&&(!t||f.dataset.ty===t))?'':'none'})}
document.querySelectorAll('.sv,#ty').forEach(e=>e.addEventListener('change',upd));</script></body></html>""")
    open(os.path.join(rd, "index.html"), "w").write("\n".join(h))
    # ---- entries.html
    h = ['<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,'
         'initial-scale=1"><title>Jastrow audit: entries</title><style>%s</style></head><body>' % CSS,
         '<h1>Every entry: the scan beside the site</h1><div class="mut"><a href="index.html">back to the findings</a> · '
         'an entry that runs over two columns or pages is shown in all its parts, in reading order · '
         '<label><input type="checkbox" id="only"> only entries with findings</label></div>']
    for eid, pids, hw, text, name, cont_note in ent_rows:
        nf = eid_has.get(eid, 0)
        h.append('<div class="e" id="%s" data-n="%d"><div><b lang="he" dir="rtl">%s</b> <span class="mut">%s · p. %s%s</span>'
                 '%s<div class="txt" dir="ltr">%s</div></div><div>%s%s</div></div>' %
                 (esc(eid), nf, esc(hw), esc(eid), esc(", ".join(pids)),
                  (' · <a href="index.html#p%s">%d finding%s</a>' % (pids[0], nf, "s" if nf > 1 else "")) if nf else "",
                  ('<div class="mut">%s</div>' % esc(cont_note)) if cont_note else "", sup(esc(text)),
                  ('<img loading="lazy" src="%s" alt="scan of the entry">' % name) if name else '<div class="mut">no scan</div>', ""))
    h.append("""<script>document.getElementById('only').addEventListener('change',e=>{document.querySelectorAll('.e').forEach(x=>{
x.style.display=(e.target.checked&&x.dataset.n==='0')?'none':''})})</script></body></html>""")
    open(os.path.join(rd, "entries.html"), "w").write("\n".join(h))
    # ---- summary.txt
    lines = ["Jastrow audit: pages %s" % (", ".join(run) if len(run) < 12 else "%s-%s (%d)" % (run[0], run[-1], len(run))),
             "findings: %d (%s)" % (len(findings), ", ".join("%d %s" % (sevc[k], SEV[k]) for k in sorted(sevc))),
             "by kind: " + ", ".join("%s %d" % (k, v) for k, v in sorted(cnt.items(), key=lambda kv: -kv[1])),
             "scan pages that look incomplete: " + (", ".join(pid for pid in run if pages.get(pid, {}).get("stats", {}).get("scan_problem")) or "none"),
             "per page (matched %, entries site/book, findings):"]
    for pid in run:
        st = pages.get(pid, {}).get("stats", {})
        lines.append("  p. %s: %s, %s/%s, %d" % (pid, ("%.0f%%" % (100 * st["match_rate"])) if "match_rate" in st else "no scan",
                                                  st.get("entries", "-"), st.get("book_entry_lines", "-"), pf[pid]))
    open(os.path.join(out, "summary.txt"), "w").write("\n".join(lines) + "\n")
    return os.path.join(rd, "index.html"), "\n".join(lines)
