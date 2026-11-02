#!/usr/bin/env python3
"""Two focused checks against the 1903 scans, each with its own report: where every column starts and ends, and
every entry's headword.

usage:
  python3 build/audit/focus.py --pages 1-20                 both checks
  python3 build/audit/focus.py columns --pages 1-20         only the columns
  python3 build/audit/focus.py headwords --pages 1-20       only the headwords
options:
  --out DIR    the audit's folder (default work/audit): the OCR is read from DIR/pages, and is made there first
               for any page not yet OCR'd (as audit.py does)
  --jobs N, --dpi N   as for audit.py, for pages not yet OCR'd

1. Columns. For each column of the page (two, or four on a page with a letter heading part-way down): the scan's
   first and last lines beside the site's first and last words of that column. A column's end is flagged when the
   site's column break or the page's first or last words differ from the book's (the audit's `column_break`,
   `page_start` and `page_end`), when words lie on the wrong side of a letter heading, or when the scan page looks
   incomplete there.

2. Headwords. For each entry: the scan's first line, with the headword found by its size (the book sets headwords
   in larger type than the rest), beside the site's headword. Flagged:
   - the headword does not begin with the letter of its section (a symbol before it, such as *, is allowed);
   - punctuation that looks wrong: doubled, a space before a comma, a stray point, a full stop, brackets that don't
     pair, a comma at the start. These are struck through as proposed removals; click any character to strike it
     or bring it back;
   - English in the headword other than the usual few words (constr., also, a., or, pl., ch., I, II ...), or a
     headword that runs into the entry's text, or a second headword inside one entry (two entries run together?);
   - the book prints a different number of forms in large type than the site marks as the headword;
   - a letter differs from the book's (the audit's headword comparison, re-read at double size).

Results, in DIR/focus/<pages>_<date>_<time>/: columns.html, headwords.html, summary.txt. In each report, mark
every item OK / Wrong / Not sure (kept in the browser) and Export: the file holds your marks and, for headwords,
the proposed removals as text_fixes records (page, entry, old, new, why) to check and append with
build/apply/commit_round.py."""
import argparse, glob, html as H, json, os, re, sys, time
from collections import Counter
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import paths  # noqa: E402
import sitetext as ST  # noqa: E402

# the book's headwords are set larger: their letters' body at least this many line pitches high (pp. 1-20: headword
# letters 0.77-1.1; 0.5% of them below 0.75)
BIG = 0.75
# English the book prints among a headword's forms
HW_WORDS = {"constr", "also", "a", "or", "and", "pl", "ch", "sing", "f", "m", "fem", "masc", "cmp", "same", "v",
            "i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii", "abs", "emph", "contr", "w",
            "pr", "n", "adj", "adv", "prep", "conj", "interj", "part", "pi", "pa", "hif", "nif", "af", "ithpa"}


# what may stand between two forms of a headword in the book (not grammar labels such as m., f., ch.: the
# headword ends before them)
JOIN_WORDS = {"constr", "also", "a", "or", "and", "i", "ii", "iii", "iv", "v", "vi"}
# grammar labels that end a headword
STOP_WORDS = {"ch", "m", "f", "pr", "n", "pl", "v", "b", "h", "adj", "adv", "prep", "conj", "interj", "part", "pa",
              "pi", "hif", "nif", "af", "same", "cmp", "fem", "masc", "sing"}
# a letter confusion the OCR makes this often on this book (ג/נ, ט/מ) is one the re-reading can't settle
CONFUSION_CAP = 100


# ---------- the site's headword ----------
def hw_html(page_html, eid):
    """the entry's first span.hw, as raw HTML, with where it starts in the page's HTML; None if it has none"""
    m = re.search(r'<div class="e[^"]*" id="%s">' % re.escape(eid), page_html)
    if not m: return None
    end_div = page_html.find('<div class="e', m.end())
    stop = end_div if end_div > 0 else len(page_html)
    a = page_html.find('<span class="hw"', m.end(), stop)
    if a < 0: return None

    def span_end(x):
        depth = 0
        for t in re.finditer(r"<(/?)span\b[^>]*>", page_html[x:]):
            depth += -1 if t.group(1) else 1
            if depth == 0: return x + t.end()
        return len(page_html)
    p, hn_inside = span_end(a), False
    # a second span.hw after only a homonym number (span.hn) and punctuation is the same headword's next form
    # (A00017: "אַבָּא, I אָב"); after real text, it is another headword inside the entry
    while True:
        b = page_html.find('<span class="hw"', p, stop)
        if b < 0: return {"html": page_html[a:p], "at": a, "second": False, "hn_inside": hn_inside}
        gap = page_html[p:b]
        if re.fullmatch(r"[\s,;=]*(?:[IVX]+[\s,;=]*)?", re.sub(r"<[^>]+>", "", gap)):
            hn_inside = hn_inside or 'class="hn"' in gap
            p = span_end(b); continue
        return {"html": page_html[a:p], "at": a, "second": True, "hn_inside": hn_inside}


def entry_html(page_html, eid):
    """the entry's whole div, as raw HTML (as the site has it on this page)"""
    m = re.search(r'<div class="e[^"]*" id="%s">' % re.escape(eid), page_html)
    if not m: return ""
    depth = 0
    for t in re.finditer(r"<(/?)div\b[^>]*>", page_html[m.start():]):
        depth += -1 if t.group(1) else 1
        if depth == 0: return page_html[m.start():m.start() + t.end()]
    return page_html[m.start():]


# the site's own stylesheet and fonts, for showing an entry as the site sets it
SITE_FONTS = ("https://fonts.googleapis.com/css2?family=Old+Standard+TT:ital,wght@0,400;0,700;1,400&family=Frank+Ruhl+Libre:"
              "wght@400;500;700&family=GFS+Didot&family=Noto+Serif+Hebrew:wght@400;700&family=Noto+Serif:ital,wght@0,400;"
              "0,700;1,400&display=swap")


SITE = [ST.REPO]      # the site checked: this repository, or --site


def site_css():
    try:
        m = re.search(r"<style>(.*?)</style>", open(os.path.join(SITE[0], "index.html"), encoding="utf-8").read(), re.S)
        return m.group(1) if m else ""
    except OSError:
        return ""


def text_units(raw):
    """the headword's characters, each with where it stands in its HTML: [char, start, end]"""
    out = []
    for m in ST.TAG.finditer(raw):
        if m.group(0).startswith("<"): continue
        for u in re.finditer(r"&#?\w+;|.", m.group(0), re.S):
            out.append([H.unescape(u.group(0)), m.start() + u.start(), m.start() + u.end()])
    return out


def punct_suggestions(units):
    """indices of characters that look like stray punctuation, each with why"""
    s = "".join(u[0] for u in units)
    out = {}
    def mark(i, why):
        if 0 <= i < len(units): out.setdefault(i, why)
    for m in re.finditer(r"([,.;])(\s*)([,.;])", s):
        mark(m.start(3), "doubled punctuation")
        for k in range(m.start(2), m.end(2)): mark(k, "doubled punctuation")
    for m in re.finditer(r"(\s+)(?=,)", s):
        for k in range(m.start(1), m.end(1)): mark(k, "a space before a comma")
    for m in re.finditer(r"(?:^|(?<=[\s,]))([֑-ׇ̀-ͯ˙¨.])(?=[\s,]|$)", s):
        mark(m.start(1), "a stray point standing alone")
    for m in re.finditer(r"^\s*([,.;])", s):
        mark(m.start(1), "punctuation before the headword")
    for m in re.finditer(r"(?<![.…])\.(?![.…])", s):
        if not re.search(r"[A-Za-z]$", s[:m.start()]):        # "constr." and other English abbreviations keep theirs
            mark(m.start(), "a full stop in the headword")
    for o, c in ("()", "[]"):
        st = []
        for i, ch in enumerate(s):
            if ch == o: st.append(i)
            elif ch == c:
                if st: st.pop()
                else: mark(i, "a closing bracket with no opening one")
        for i in st: mark(i, "an opening bracket with no closing one")
    for m in re.finditer(r"\(\s*\)", s):
        mark(m.start(), "empty brackets"); mark(m.end() - 1, "empty brackets")
    return out


# ---------- the scan ----------
class Ink:
    def __init__(self, wd, thr):
        import numpy as np
        from PIL import Image
        self.np = np
        self.img = Image.open(os.path.join(wd, "page.png")).convert("L")
        self.a = np.asarray(self.img) < thr

    def body(self, box):
        """the height of a word's letters: the rows where its ink is dense, leaving out points and thin strokes"""
        x0, y0, x1, y1 = [int(v) for v in box]
        r = self.a[max(0, y0):y1, max(0, x0):x1].sum(1)
        if not len(r) or r.max() == 0: return 0
        rows = self.np.where(r > 0.25 * r.max())[0]
        return int(rows[-1] - rows[0] + 1)

    def letters(self, box, lh):
        """the height of a stretch of ink's letters: the rows with a letter's worth of ink in them (specks from the
        line above, and the points below, have too little)"""
        x0, y0, x1, y1 = [int(v) for v in box]
        r = self.a[max(0, y0):y1, max(0, x0):x1].sum(1)
        rows = self.np.where(r >= max(3, 0.12 * lh))[0]
        return int(rows[-1] - rows[0] + 1) if len(rows) else 0

    def crop(self, box, path, scale=0.5, marks=(), pad=6):
        from PIL import ImageDraw
        W, Hh = self.img.size
        x0, y0, x1, y1 = max(0, box[0] - pad), max(0, box[1] - pad), min(W, box[2] + pad), min(Hh, box[3] + pad)
        im = self.img.crop((x0, y0, x1, y1)).convert("RGB")
        d = ImageDraw.Draw(im)
        for b in marks:
            d.rectangle([b[0] - x0 - 3, b[1] - y0 - 3, b[2] - x0 + 3, b[3] - y0 + 3], outline=(220, 30, 30), width=3)
        im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))))
        im.save(path, quality=80)


def col_lines(pc):
    by = {}
    for ln in pc.lines: by.setdefault((ln["seg"], ln["col"]), []).append(ln)
    for k in by: by[k].sort(key=lambda l: (l["box"][1] + l["box"][3]) / 2)
    return by


def line_words(scan, li):
    return " ".join(t["text"] for t in sorted((t for t in scan["ocr"]["tokens"] if t["line"] == li),
                                              key=lambda t: t["box"][0]))


def union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


# ---------- 1. columns ----------
def heb_edge(pc, R, cands, words):
    """where the image has each of the site's Hebrew words, among candidate places {side: [Hebrew OCR words]}:
    found loosely by the OCR's letters, else by re-reading each place with the OCR's alternatives (stage 3) and
    scoring the site's word against them. Returns [(word, side or None)]"""
    import reread as RR
    import compare as CO
    out = []
    for w in words:
        hits = {sd: max([loose(w, c["text"]) for c in cs] or [0]) for sd, cs in cands.items()}
        good = [sd for sd, v in hits.items() if v >= 0.75]
        if len(good) == 1:
            out.append((w, good[0])); continue
        fit = set()
        for sd, cs in cands.items():
            for c in cs:
                if loose(w, c["text"]) < 0.3: continue
                b = pc.heb_region(c["box"])
                R.read_all([(b, "heb")])
                for rd in R.reads(b, "heb"):
                    a_ = RR.score(w, rd[3], "heb"); k_ = RR.score(rd[1], rd[3], "heb") if RR.norm_heb(rd[1]) else None
                    if a_[1] == 0 and (k_ is None or a_[3] - k_[3] <= CO.CFG["re_ok"]):
                        fit.add(sd); break
        out.append((w, fit.pop() if len(fit) == 1 else None))
    return out


def edge_cands(pc, lines):
    out = []
    for ln in lines:
        lb = ln["box"]
        out += [w for w in pc.heb if w["seg"] == ln["seg"] and w["col"] == ln["col"] and
                len(re.findall("[א-ת]", w["text"])) >= 2 and lb[1] <= (w["box"][1] + w["box"][3]) / 2 <= lb[3]]
    return out


def site_heb_near(P, off, before, n=6):
    """the site's Hebrew words among the n words before (or after) an offset"""
    ts = [t for t in P.tokens if not t["h2"] and (t["end"] <= off if before else t["off"] >= off)]
    ts = ts[-n:] if before else ts[:n]
    return [t["text"] for t in ts if t["heb"] and len(t["skel"]) >= 2]


def check_columns(pid, pc, F, ink, img_dir):
    import reread as RR
    P, scan = pc.p, pc.s
    R = RR.Reader(pc.wd, scan.get("dpi", 400), pc.lineh)
    lay = scan["layout"]
    by = col_lines(pc)
    h2 = [i for i, a in enumerate(P.attrs) if "h2" in a[4]]
    toks = [t for t in P.tokens if not t["h2"]]
    if not toks: return []
    page_a, page_b = toks[0]["off"], toks[-1]["end"]
    nseg = len(lay["segments"])
    page_notes = [(x["sev"], x["note"]) for x in F if x["type"] in ("scan_incomplete", "layout")]
    # words on the wrong side of a letter heading part-way down: matched to the scan's other segment
    slipped = []
    if P.mid_letter and nseg == 2 and h2:
        for t in toks:
            j = pc.s2k.get(t["i"])
            if j is None: continue
            want = 0 if t["off"] < h2[0] else 1
            if pc.k[j]["seg"] != want: slipped.append(t["text"])
    rows = []
    for si in range(max(nseg, 1)):
        # the site's text of this segment
        if P.mid_letter and h2:
            a, b = (page_a, h2[0]) if si == 0 else (h2[-1] + 1, page_b)
        else:
            a, b = page_a, page_b
        brk = P.site_breaks[si] if si < len(P.site_breaks) else None
        bbrk = pc.book_breaks[si] if si < len(getattr(pc, "book_breaks", [])) else None
        seg_find = [x for x in F if x["type"] in ("column_break", "column_break_unset") and x.get("seg") == si]
        edge = None
        if brk is not None and by.get((si, "L")) and by.get((si, "R")):
            # the site's Hebrew words on either side of its break, looked for in the image at the foot of the left
            # column and the top of the right, with the site's word (Sefaria's text checks the scan too)
            cands = {"L": edge_cands(pc, by[(si, "L")][-3:]), "R": edge_cands(pc, by[(si, "R")][:3])}
            res = [(w, "L", sd) for w, sd in heb_edge(pc, R, cands, site_heb_near(P, brk, True))] + \
                  [(w, "R", sd) for w, sd in heb_edge(pc, R, cands, site_heb_near(P, brk, False))]
            edge = {"wrong": [(w, st, sd) for w, st, sd in res if sd is not None and sd != st],
                    "right": [w for w, st, sd in res if sd == st], "lost": [w for w, st, sd in res if sd is None]}
        for side in ("L", "R"):
            ls = by.get((si, side), [])
            for end in ("top", "foot"):
                r = {"page": pid, "seg": si, "col": side, "end": end, "flags": [], "img": None, "scan": ""}
                if ls:
                    pick = ls[:2] if end == "top" else ls[-2:]
                    box = union([l["colbox"][:1] + l["box"][1:2] + l["colbox"][2:3] + l["box"][3:] for l in pick])
                    name = "p%s_s%d%s_%s.jpg" % (pid, si, side, end)
                    ink.crop(box, os.path.join(img_dir, name), 0.45)
                    r["img"] = "img/" + name
                    r["scan"] = " / ".join(line_words(scan, l["i"]) for l in pick)
                else:
                    r["flags"].append([1, "the scan has no %s column here" % ("left" if side == "L" else "right")])
                # the site's words at this end of the column
                if side == "L" and end == "top": off, before = a, False
                elif side == "R" and end == "foot": off, before = b, True
                else:
                    off = brk if brk is not None else bbrk
                    before = end == "foot"
                r["site"] = P.words_at(off, 8, before) if off is not None else "(the site sets no break here)"
                if before: r["site"] = "… " + r["site"]
                else: r["site"] += " …"
                if (side, end) in (("L", "foot"), ("R", "top")):
                    if brk is None:
                        r["flags"].append([3, "the site has no fixed column break here (the browser balances the "
                                              "columns); the book's right column begins: %s" % P.words_at(bbrk) if bbrk
                                           is not None else "the site has no fixed break and the book's could not be found"])
                    for x in seg_find:
                        if x["type"] != "column_break": continue
                        sev, note = x["sev"], x["note"]
                        # an estimated break (the OCR could not place the words around it) the Hebrew settles
                        if edge and sev == 2 and edge["right"] and not edge["wrong"]:
                            sev, note = 3, note + " — but the image has the site's Hebrew at the edge where the site " \
                                                  "puts it: " + ", ".join(edge["right"])
                        elif edge and edge["wrong"]:
                            sev = 1
                        r["flags"].append([sev, note])
                    if edge and edge["wrong"]:
                        # on its own (no word shift found), the OCR's Hebrew at the edge was a false alarm in all the
                        # user's marks of pp. 1-100
                        alone = not any(x["type"] == "column_break" for x in seg_find)
                        r["flags"].append([3 if alone else 1, "the image has " + "; ".join(
                            "%s at the %s" % (w, "foot of the left column" if sd == "L" else "top of the right column")
                            for w, st, sd in edge["wrong"]) + ", where the site puts it in the other column"
                                           + (" (the OCR's Hebrew only: no shift of the words found)" if alone else "")])
                    elif edge and edge["right"] and not any(f[0] <= 2 for f in r["flags"]):
                        r["flags"].append([9, "the Hebrew at the edge is where the site puts it: " + ", ".join(edge["right"])])
                    if bbrk is None and brk is not None:
                        r["flags"].append([2, "the audit could not find the book's break (too few words matched)"])
                if si == 0 and side == "L" and end == "top":
                    r["flags"] += [[edge_sev(x), x["note"] + _only(x)] for x in F if x["type"] == "page_start"]
                if si == nseg - 1 and side == "R" and end == "foot":
                    r["flags"] += [[edge_sev(x), x["note"] + _only(x)] for x in F if x["type"] == "page_end"]
                if slipped and ((si == 0 and side == "R" and end == "foot") or (si == 1 and side == "L" and end == "top")):
                    r["flags"].append([1, "words on the wrong side of the letter heading: %s" % " ".join(slipped[:8])])
                rows.append(r)
    for r in rows: r["page_notes"] = page_notes
    return rows


def edge_sev(x):
    """a page's first or last words differing: in the user's marks mostly a word the book hyphenates across the page,
    or a page number or signature read as text; one differing word (or numbers only) is minor"""
    w = (x.get("site_only") or "").split() + (x.get("book_only") or "").split()
    if len(w) <= 1 or all(re.fullmatch(r"[\d.,;:()]+", t) for t in w): return 3
    return x["sev"]


def _only(x):
    s = []
    if x.get("site_only"): s.append("site only: " + x["site_only"])
    if x.get("book_only"): s.append("book only: " + x["book_only"])
    return (" (" + "; ".join(s) + ")") if s else ""


# ---------- 2. headwords ----------
def section_letters(P):
    """the letter each entry's headword should begin with: the commonest first letter of the headwords on the
    page, before and after a letter heading part-way down"""
    h2 = [i for i, a in enumerate(P.attrs) if "h2" in a[4]]
    cut = h2[0] if h2 and P.mid_letter else None
    groups = {0: Counter(), 1: Counter()}
    first = {}
    for e in P.entries:
        if e["cont"]: continue
        sk = ST.heb_skel(e.get("hw1", ""))
        if not sk: continue
        g = 1 if cut is not None and P.tokens[e["a"]]["off"] > cut else 0
        groups[g][sk[0]] += 1; first[e["eid"]] = g
    want = {g: (c.most_common(1)[0][0] if c else None) for g, c in groups.items()}
    if cut is not None:
        hl = ST.heb_skel(P.letter_text)
        if hl: want[1] = hl[0]
    return {eid: want[g] for eid, g in first.items()}


def ink_headword(pc, ink, j):
    """the headword in the image, found by the ink, not by the OCR's words (which split and join the large type
    unpredictably): on the entry's first line, from its start, the stretches of ink set apart by a word space,
    each with its letters' height. The headword is the large ones from the line's start, with only marks (commas,
    brackets), a homonym number or a joining word (constr., also, a.) between; it may go on to the next line.
    Returns {"words": [{box, ocr, conf, before, after}], "lead": [marks], "lines": [boxes]}; a mark is "point"
    (comma, full stop, a stray point: low and small) or "bracket" (tall and thin)"""
    np = ink.np
    lh = pc.lineh
    L = {ln["i"]: ln for ln in pc.lines}
    by = col_lines(pc)
    li = pc.k[j]["line"]
    res = {"words": [], "lead": [], "lines": []}
    for step in range(3):
        ln = L[li]
        lb, cb = ln["box"], ln["colbox"]
        en = [t for t in pc.k if li in t["lines"]]
        eng_line = [t for t in en if pc.real(t) and t["key"] not in JOIN_WORDS]
        conn = [t for t in en if t["key"] in JOIN_WORDS or re.fullmatch(r"[IVX1l]+[.,]?", t["text"])]
        # a grammar label (ch., m., pr. n.) the English OCR read ends the headword, however tall its letters
        labels = [t for t in en if t["script"] == "lat" and t["key"] in STOP_WORDS and t["conf"] >= 60]
        hebw = [w for w in pc.heb if w["seg"] == ln["seg"] and w["col"] == ln["col"] and re.search("[א-ת]", w["text"])
                and lb[1] - 0.3 * lh <= (w["box"][1] + w["box"][3]) / 2 <= lb[3] + 0.3 * lh]
        start = min([t["box"][0] for t in en] or [lb[0]])
        y0, y1 = int(lb[1]), int(lb[3])
        x0, x1 = int(max(cb[0] - 4, start - lh)), int(cb[2] + 4)
        a = ink.a[y0:y1, x0:x1]
        # word spaces are measured in the band where this line's letters stand: vowel points below the line, and
        # the lines above and below where the line's box reaches into them, can bridge them
        rp = a.sum(1)
        c0 = int(min(max((pc.k[j]["box"][1] + pc.k[j]["box"][3]) / 2 - y0, 0), len(rp) - 1)) if step == 0 else len(rp) // 2
        thr = 0.3 * rp.max() if rp.max() else 1
        lo = hi = c0
        while lo > 0 and rp[lo - 1] >= thr: lo -= 1
        while hi < len(rp) - 1 and rp[hi + 1] >= thr: hi += 1
        if rp[c0] < thr: lo, hi = 0, len(rp) - 1
        on = np.concatenate([[0], (a[lo:hi + 1].sum(0) > 0).astype(np.int8), [0]])
        d = np.diff(on)
        parts = list(zip(np.where(d == 1)[0], np.where(d == -1)[0]))
        blobs = []
        for s, e in parts:
            if blobs and s - blobs[-1][-1][1] < 0.25 * lh: blobs[-1].append((s, e))
            else: blobs.append([(s, e)])

        def pbox(ps):
            sub = a[:, ps[0][0]:ps[-1][1]]
            rows = np.where(sub.sum(1) >= 2)[0]
            if not len(rows): rows = np.where(sub.sum(1) > 0)[0]
            return [x0 + int(ps[0][0]), y0 + int(rows[0]), x0 + int(ps[-1][1]), y0 + int(rows[-1]) + 1]

        def mark_kind(b, ref):
            h = b[3] - b[1]
            if h >= 0.6 * lh and b[2] - b[0] < 0.35 * lh: return "bracket"
            if h < 0.45 * lh and b[2] - b[0] < 0.35 * lh and (b[1] + b[3]) / 2 > (ref[1] + ref[3]) / 2: return "point"
            return None
        stopped, words = False, []
        for bl in blobs:
            bx = pbox(bl)
            w = bx[2] - bx[0]
            heb_here = [h for h in hebw if overlap_frac(bx, h["box"]) > 0.3]
            big = min(ink.letters(bx, lh), ink.body(bx)) >= BIG * lh and w >= 0.5 * lh and heb_here
            if not res["words"] and not words:
                if bx[0] - start > (1.5 if step == 0 else 0.6) * lh: stopped = True; break
                if not big:
                    k = mark_kind(bx, bx) if w < 0.6 * lh else None
                    if k or w < 0.6 * lh: res["lead"].append(k or "mark"); continue
                    stopped = True; break
            if big:
                if any(overlap_frac(bx, t["box"]) > 0.3 for t in eng_line + labels): stopped = True; break
                prev = (words or res["words"] or [None])[-1]
                if prev is not None and step == 0 and words and bx[0] - prev["box"][2] > 4 * lh: stopped = True; break
                # marks at either end of the word's ink (a comma close after it, a bracket around it)
                core = list(bl)
                before, after = [], []
                while len(core) > 1:
                    k = mark_kind(pbox([core[-1]]), pbox(core[:-1]))
                    if not k: break
                    after.insert(0, k); core.pop()
                while len(core) > 1:
                    k = mark_kind(pbox([core[0]]), pbox(core[1:]))
                    if not k: break
                    before.append(k); core.pop(0)
                cbx = pbox(core)
                ocr = " ".join(h["text"] for h in sorted(heb_here, key=lambda h: -h["box"][0]))
                conf = min(h["conf"] for h in heb_here)
                ids = {id(h) for h in heb_here}
                if prev is not None and ids & prev["ids"] and cbx[0] - prev["box"][2] < 0.8 * lh:
                    # one word whose letters stand apart (the OCR read it as one): one word
                    prev.update(box=union([prev["box"], cbx]), after=after, ids=prev["ids"] | ids,
                                ocr=" ".join(h["text"] for h in sorted({id(h): h for h in heb_here + prev["toks"]}.values(),
                                                                       key=lambda h: -h["box"][0])),
                                toks=prev["toks"] + heb_here)
                    continue
                if prev is not None: prev["after"] += before
                elif before: res["lead"] += before
                words.append({"box": cbx, "ocr": ocr, "conf": conf, "after": after, "ids": ids, "toks": heb_here})
                continue
            # small: a mark, a homonym number, a joining word; anything else ends the headword
            k = mark_kind(bx, (words or res["words"] or [{"box": bx}])[-1]["box"]) if w < 0.6 * lh else None
            if k or w < 0.6 * lh:
                (words or res["words"])[-1]["after"].append(k or "mark") if (words or res["words"]) else None
                continue
            if any(overlap_frac(bx, t["box"]) > 0.3 for t in conn): continue
            stopped = True; break
        if not words: break
        res["words"] += words; res["lines"].append(lb)
        if stopped or cb[2] - words[-1]["box"][2] > 2.5 * lh: break
        seq = by.get((ln["seg"], ln["col"]), [])
        nx = next((x for n_, x in enumerate(seq) if n_ > 0 and seq[n_ - 1]["i"] == li), None)
        if nx is None: break
        li = nx["i"]
    return res


def overlap_frac(a, b):
    """the overlap of two boxes, as a share of the smaller"""
    w = min(a[2], b[2]) - max(a[0], b[0]); h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0: return 0.0
    return w * h / max(1, min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])))


def loose(a, b):
    """how alike two Hebrew words are, by their letters only (the OCR's reading of large pointed type is rough)"""
    import difflib
    a, b = ST.heb_skel(a), ST.heb_skel(b)
    if not a or not b: return 0.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def site_words(hw):
    """the site's headword as Hebrew words, each with where it stands in the headword's characters"""
    return [(m.group(0), m.start(), m.end()) for m in ST.HEBWORD.finditer(hw) if ST.heb_skel(m.group(0))]


def compare_forms(sw, bw):
    """the site's headword words against the large words in the image, both left to right (GUIDELINES 2.9).
    Returns (pairs [(site index, book index)], extra book words, site words not found). A site word is found in a
    book word whose letters match loosely; two site words in one book word, or one site word over two, are the OCR's
    or the spacing's doing, not a difference"""
    S, B = [w for w, _, _ in sw], [w["ocr"] for w in bw]
    joined = "".join(ST.heb_skel(b) for b in B)
    pairs, used, missing = [], set(), []
    k = 0
    for i, s in enumerate(S):
        best, bj = 0.0, None
        for jx in range(k, len(B)):
            r = max(loose(s, B[jx]), partial(ST.heb_skel(s), ST.heb_skel(B[jx])))
            if r > best: best, bj = r, jx
        if bj is not None and best >= 0.5:
            pairs.append((i, bj)); used.add(bj); k = bj
        elif partial(ST.heb_skel(s), joined) >= 0.6:
            pass                                          # in the large words, split or joined otherwise
        else:
            missing.append(i)
    extra = [jx for jx in range(len(B)) if jx not in used and B[jx] not in {B[u] for u in used} and
             not any(partial(ST.heb_skel(B[jx]), ST.heb_skel(S[i])) >= 0.6 for i in range(len(S)))]
    return pairs, extra, missing


def partial(a, b):
    """how well the shorter of two letter strings fits somewhere inside the longer"""
    import difflib
    if not a or not b: return 0.0
    if len(a) > len(b): a, b = b, a
    best = 0.0
    for i in range(0, len(b) - len(a) + 1):
        best = max(best, difflib.SequenceMatcher(None, a, b[i:i + len(a)], autojunk=False).ratio())
    return best


def gap_of(sw, i):
    """which gap of the headword a character stands in: 0 before the first word, n after the n-th"""
    return sum(1 for _, _, e in sw if e <= i)


PUNCT_POINT = set(",.;:˙¨") | {chr(c) for c in range(0x300, 0x370)}


def judge_punct(r, sw, bw, lead):
    """each proposed removal against the image: the marks the image has in that gap between the headword's words,
    against the marks the site has there"""
    units, hw = r["units"], r["hw"]
    n = len(sw)
    mappable = len(bw) == n and n > 0
    def site_marks(g, kind):
        a = sw[g - 1][2] if g > 0 else 0
        b = sw[g][1] if g < n else len(hw)
        chars = hw[a:b]
        return sum(1 for c in chars if (c in "()[]") == (kind == "bracket") and (c in "()[]" or c in PUNCT_POINT))
    def scan_marks(g, kind):
        ms = lead if g == 0 else bw[g - 1]["after"]
        return sum(1 for m in ms if m == kind or (m == "mark" and kind == "point"))
    out = {}
    for i, why in list(r["sugg"].items()):
        i = int(i)
        c = units[i][0]
        if c.isspace():
            out[str(i)] = (why, None); continue
        kind = "bracket" if c in "()[]" else "point"
        if not mappable:
            out[str(i)] = (why + " (the scan can't tell: its large words could not be paired with the site's)", None)
            continue
        g = gap_of(sw, i)
        sm, km = site_marks(g, kind), scan_marks(g, kind)
        if km < sm:
            out[str(i)] = (why + "; scan confirms: %s here" % ("no mark" if km == 0 else "%d mark%s, the site %d" %
                                                                (km, "s" if km > 1 else "", sm)), True)
        else:
            out[str(i)] = (why + "; scan shows a mark here: keep", False)
    return out


def run_page(pc, CO, headwords=True):
    """the comparison as audit.py runs it, with stages 3 and 4 off, then stage 3 for the headword findings only"""
    pc.check_gaps(); pc.check_pairs(); pc.check_breaks(); pc.check_header(); pc.check_scan()
    pc.map_entries(); pc.check_structure()
    allf = pc.f
    hwf = [x for x in allf if x["type"] in ("headword_letters", "headword_differs", "headword_order")] if headwords else []
    if hwf:
        pc.f = hwf
        CO.CFG["reread3"] = True
        try: pc.stage3()
        finally: CO.CFG["reread3"] = False; pc.f = allf
    return allf


def check_headwords(pid, pc, F, ink, img_dir):
    P = pc.p
    rows = []
    for e in P.entries:
        info = hw_html(P.html, e["eid"])
        e["hw1"] = "".join(u[0] for u in text_units(info["html"])) if info else ""
    lead = section_letters(P)
    byeid = {}
    for x in F:
        if x.get("eid"): byeid.setdefault(x["eid"], []).append(x)
    for e in P.entries:
        if e["cont"]: continue
        eid = e["eid"]
        r = {"page": pid, "eid": eid, "flags": [], "img": None, "book": [], "verdicts": {},
             "ent": entry_html(P.html, eid), "parts": [x["box"] for x in getattr(pc, "entry_parts", {}).get(eid, [])],
             "pdir": pc.wd, "isz": list(ink.img.size)}
        info = hw_html(P.html, eid)
        if not info:
            r.update(hw="", units=[], sugg={}, old="", prefix="", sev=1)
            r["flags"].append([1, "the entry has no headword on the site"])
            rows.append(r); continue
        units = text_units(info["html"])
        hw = "".join(u[0] for u in units)
        sugg = punct_suggestions(units)
        # the record's "old" must occur once on the page
        old = info["html"]
        if P.html.count(old) != 1:
            pre = P.html.rfind('<div class="e', 0, info["at"])
            old = P.html[pre:info["at"]] + old
        r.update(hw=hw, units=units, sugg={str(k): v for k, v in sugg.items()}, old=old,
                 prefix=old[:len(old) - len(info["html"])])
        # English in the headword
        eng = [w for w in re.findall(r"[A-Za-z]+", hw) if w.lower() not in HW_WORDS]
        if re.search(r"\d", hw) or len(hw) > 90:
            r["flags"].append([1, "the headword runs into the entry's text (the site's span.hw is too long)"])
        elif eng:
            r["flags"].append([2, "English in the headword: %s" % ", ".join(eng[:6])])
        if info["second"]:
            r["flags"].append([2, "a second headword inside this entry: two entries run together, or a second "
                                  "form the book also sets large?"])
        if info["hn_inside"]:
            r["flags"].append([2, "a homonym number (I, II …) stands between the headword's forms on the site: "
                                  "check where the book has it"])
        sw = site_words(hw)
        sk = ST.heb_skel(hw)
        lead_c = re.match(r"\s*([^\s֑-ׇא-ת]*)", hw).group(1)
        if lead_c and lead_c not in ("*",):
            r["flags"].append([3, "begins with %r before its letters" % lead_c])
        if sk and lead.get(eid) and sk[0] != lead[eid]:
            r["flags"].append([1, "begins with %s, not %s like the other headwords of this section" % (sk[0], lead[eid])])
        # the audit's headword findings, each tested against the image (stage 3): a letter is flagged only when the
        # image fits the OCR's reading clearly better than Sefaria's
        for x in byeid.get(eid, []):
            if x["type"] in ("headword_letters", "headword_differs", "headword_order"):
                v = x.get("verdict")
                if v == "ocr_misread":
                    r["flags"].append([9, "letters: the OCR misread the book; Sefaria's reading fits the image"])
                elif v == "likely_error" and max([int(n) for n in re.findall(r"\((\d+)×\)", x["note"])] or [0]) >= CONFUSION_CAP:
                    r["flags"].append([3, "letters: the image seems to fit the OCR's reading, but the letters differ by "
                                          "a confusion this OCR makes hundreds of times on this book: %s" % x["note"]])
                elif v == "likely_error":
                    r["flags"].append([1, "letters: the image fits the OCR's reading clearly better than Sefaria's: %s"
                                       % x["note"]])
                else:
                    r["flags"].append([3, "letters: the image can't tell (%s): %s" % (v or "not re-read", x["note"])])
            elif x["type"] == "entry_start":
                r["flags"].append([2, "the book's line here is not indented as an entry's first line"])
        # the book's headword, from the ink
        j = getattr(pc, "entry_start", {}).get(eid)
        bw, lead_marks = [], []
        if j is None:
            r["flags"].append([3, "the entry's first line was not found in the scan"])
        else:
            ih = ink_headword(pc, ink, j)
            bw, lead_marks = ih["words"], ih["lead"]
            L = {ln["i"]: ln for ln in pc.lines}
            ln = L[pc.k[j]["line"]]
            lbs = ih["lines"] or [ln["box"]]
            box = [ln["colbox"][0], min(b[1] for b in lbs), ln["colbox"][2], max(b[3] for b in lbs)]
            name = "p%s_%s.jpg" % (pid, eid)
            ink.crop(box, os.path.join(img_dir, name), 0.5, marks=[w["box"] for w in bw])
            r["img"] = "img/" + name
            r["book"] = [w["ocr"] for w in bw]
            if not bw:
                r["flags"].append([3, "no large word was found at the start of the entry's line"])
            else:
                pairs, extra, missing = compare_forms(sw, bw)
                sure = [jx for jx in extra if bw[jx]["conf"] >= 60 and len(ST.heb_skel(bw[jx]["ocr"])) >= 2]
                if sure:
                    r["flags"].append([2, "the image has another large word the site's headword lacks: %s"
                                       % ", ".join(bw[jx]["ocr"] for jx in sure)])
                elif extra:
                    r["flags"].append([3, "maybe another large word in the image (read unsurely): %s"
                                       % ", ".join(bw[jx]["ocr"] for jx in extra)])
                if missing and len(bw) < len(sw):
                    r["flags"].append([2, "the image lacks a large word for the site's %s (%d large word%s in the "
                                       "image, %d in the site's headword)" % (", ".join(sw[i][0] for i in missing),
                                                                             len(bw), "" if len(bw) == 1 else "s", len(sw))])
                elif missing:
                    r["flags"].append([3, "not matched among the large words (the OCR's reading is rough): %s"
                                       % ", ".join(sw[i][0] for i in missing)])
        # each proposed removal against the image
        if sugg:
            v = judge_punct(r, sw, bw, lead_marks)
            for i, (why, conf) in v.items():
                r["sugg"][i] = why
                if conf is False: r["sugg"].pop(i)               # the scan has the mark: not proposed
            whys = {}
            for i, (why, conf) in v.items():
                if not r["units"][int(i)][0].isspace(): whys.setdefault(why, conf)
            for why, conf in whys.items():
                r["flags"].append([1 if conf else 3 if conf is False else 2, why])
        r["sev"] = min([f[0] for f in r["flags"]] or [9])
        rows.append(r)
    return rows


# ---------- reports ----------
CSS = """
:root{--bg:#fbfaf7;--fg:#1d1d1b;--mut:#6b6a66;--line:#dedbd3;--card:#fff;--s1:#b42318;--s2:#b54708;--s3:#667085;
--ok:#067647;--hl:#fff4d6}
@media (prefers-color-scheme:dark){:root{--bg:#161614;--fg:#ecebe6;--mut:#a3a19a;--line:#3a3935;--card:#1f1f1c;
--s1:#f97066;--s2:#fdb022;--s3:#98a2b3;--ok:#47cd89;--hl:#3b3420}}
body{margin:0;padding:16px 20px 60px;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif}
h1{font-size:20px;margin:0 0 4px} .mut{color:var(--mut)} a{color:inherit}
.bar{position:sticky;top:0;background:var(--bg);padding:8px 0;border-bottom:1px solid var(--line);z-index:2;
display:flex;gap:10px;flex-wrap:wrap;align-items:center}
button,select{font:inherit;padding:3px 10px;border:1px solid var(--line);background:var(--card);color:var(--fg);
border-radius:6px;cursor:pointer} button.on{border-color:currentColor;font-weight:600}
.pg{margin:22px 0 6px;font-size:16px;font-weight:600} .note{font-size:13px;color:var(--s2);margin:2px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px;min-width:0}
.card.s1{border-left:4px solid var(--s1)} .card.s2{border-left:4px solid var(--s2)} .card.s3{border-left:4px solid var(--s3)}
.card img{max-width:100%;display:block;margin:6px 0;background:#fff;border-radius:3px}
.lab{font-size:12px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em}
.f1{color:var(--s1)} .f2{color:var(--s2)} .f3{color:var(--s3)} .okv{color:var(--ok)}
.he{font-size:22px;font-family:"SBL Hebrew","Ezra SIL","Taamey Frank CLM","Noto Serif Hebrew",serif}
.u{cursor:pointer;border-radius:2px;padding:0 1px} .u:hover{background:var(--hl)}
.u.del{text-decoration:line-through;text-decoration-thickness:2px;color:var(--s1);background:var(--hl)}
.marks{display:flex;gap:6px;margin-top:8px;flex-wrap:wrap;align-items:center}
.marks input{flex:1;min-width:120px;font:inherit;padding:3px 6px;border:1px solid var(--line);border-radius:6px;
background:var(--card);color:var(--fg)}
.m-ok .b-ok,.m-wrong .b-wrong,.m-unsure .b-unsure{border-color:currentColor;font-weight:600;background:var(--hl)}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:10px} @media (max-width:700px){.cols{grid-template-columns:1fr}}
.hidden{display:none}
.card.wide{grid-column:1/-1} .sbs{display:none;grid-template-columns:1fr 1fr;gap:12px;margin-top:8px;align-items:start}
.card.wide .sbs{display:grid} @media (max-width:800px){.sbs{grid-template-columns:1fr}}
.sbs iframe{width:100%;border:1px solid var(--line);border-radius:4px;height:300px;background:#fdfdfa}
.bookv .part{width:100%;background-repeat:no-repeat;border:1px solid var(--line);border-radius:4px;margin-bottom:6px;
background-color:#fff} .m-sbs .b-sbs{font-weight:600;border-color:currentColor}
.psbs{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:6px 0 12px;align-items:start}
@media (max-width:800px){.psbs{grid-template-columns:1fr}}
.psbs iframe{width:100%;height:85vh;border:1px solid var(--line);border-radius:4px;background:#fff}
.psbs .scanv{height:85vh;overflow:auto;border:1px solid var(--line);border-radius:4px;background:#fff}
.psbs .scanv img{width:100%;margin:0} .pg button{font-size:13px;font-weight:400;margin-left:8px} .pg button.on{font-weight:600}
"""

JS = r"""
const KEY='jastrow-focus-'+KIND;
let M={}; try{M=JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){}
function save(){try{localStorage.setItem(KEY,JSON.stringify(M))}catch(e){} count()}
function count(){const n=Object.values(M).filter(m=>m.v).length;document.getElementById('nm').textContent=n+' marked'}
function mark(id,v){M[id]=M[id]||{};M[id].v=(M[id].v===v?'':v);paint(id);save()}
function note(id,t){M[id]=M[id]||{};M[id].note=t;save()}
function paint(id){const c=document.getElementById(id);if(!c)return;c.classList.remove('m-ok','m-wrong','m-unsure');
 const m=M[id];if(m&&m.v)c.classList.add('m-'+m.v);const i=c.querySelector('.marks input');if(i&&m&&m.note)i.value=m.note;
 if(KIND==='headwords'){const d=dels(id);c.querySelectorAll('.u').forEach(s=>s.classList.toggle('del',d.has(+s.dataset.i)));
  const nw=c.querySelector('.new');if(nw)nw.textContent=d.size?'after removal: '+newText(id):''}}
function dels(id){const m=M[id];if(m&&m.del)return new Set(m.del);return new Set(Object.keys(DATA[id].sugg||{}).map(Number))}
function tog(id,i){M[id]=M[id]||{};const d=dels(id);d.has(i)?d.delete(i):d.add(i);M[id].del=[...d];paint(id);save()}
function newText(id){const d=dels(id);return DATA[id].units.filter((u,i)=>!d.has(i)).map(u=>u[0]).join('')}
function newHtml(id){const r=DATA[id];const d=[...dels(id)].sort((a,b)=>b-a);let h=r.old.slice(r.prefix.length);
 for(const i of d){const u=r.units[i];h=h.slice(0,u[1])+h.slice(u[2])}return r.prefix+h}
function exportMarks(){const out={kind:KIND,run:RUN,exported:new Date().toISOString(),marks:{},records:[]};
 for(const [id,m] of Object.entries(M)){if(!m.v&&!m.note&&!m.del)continue;const r=DATA[id];if(!r)continue;
  out.marks[id]={page:r.page,eid:r.eid,where:r.where,verdict:m.v||'',note:m.note||'',flags:r.flags.map(f=>f[1])};
  if(m.del)out.marks[id].del=m.del;
  if(KIND==='headwords'&&m.v==='wrong'&&dels(id).size){out.marks[id].remove=[...dels(id)].sort((a,b)=>a-b).map(i=>r.units[i][0]);
   out.records.push({page:+r.page,entry:r.hw.trim(),old:r.old,new:newHtml(id),
    why:(m.note||'Stray punctuation in the headword, not in the 1903 book: a typo in the digital text.')})}}
 const b=new Blob([JSON.stringify(out,null,1)],{type:'application/json'});const a=document.createElement('a');
 a.href=URL.createObjectURL(b);a.download='jastrow-focus-'+KIND+'-'+new Date().toISOString().slice(0,16).replace(/[:T]/g,'')+'.json';
 a.click()}
function importMarks(f){const rd=new FileReader();rd.onload=()=>{const o=JSON.parse(rd.result);
 for(const [id,m] of Object.entries(o.marks||{})){M[id]={v:m.verdict,note:m.note};if(m.del)M[id].del=m.del}
 save();Object.keys(DATA).forEach(paint);filt()};rd.readAsText(f)}
function filt(){const s=document.getElementById('sev').value,mm=document.getElementById('mk').value;
 document.querySelectorAll('.card').forEach(c=>{const r=DATA[c.id];const m=(M[c.id]||{}).v||'';
  let show=(s==='all'||r.sev<=+s)&&(mm==='all'||(mm==='none'?!m:m===mm));c.classList.toggle('hidden',!show)});
 document.querySelectorAll('.pgbox').forEach(p=>p.classList.toggle('hidden',!p.querySelector('.card:not(.hidden)')))}
function sbs(id,force){const c=document.getElementById(id);if(!c)return;const on=force!==undefined?force:!c.classList.contains('wide');
 c.classList.toggle('wide',on);c.classList.toggle('m-sbs',on);if(!on||c.querySelector('.sbs'))return;
 const r=DATA[id],b=document.createElement('div');b.className='sbs';
 const L=document.createElement('div');L.innerHTML='<div class=lab>Site, as on the website</div>';
 const fr=document.createElement('iframe');fr.title='the site\'s entry';
 fr.srcdoc='<!doctype html><meta charset=utf-8><link rel=stylesheet href="'+FONTS+'"><style>'+SITECSS+
  'html,body{height:auto;overflow:hidden;margin:0;background:var(--paper)}#w{position:static;transform-origin:0 0;'+
  'width:633px;height:auto;padding:10px 20px}#w .cols{height:auto;column-count:1;overflow:visible}</style>'+
  '<div class="page" id=w><div class="cols"><div class="col">'+(r.ent||'<p>(no entry on the site)</p>')+'</div></div></div>';
 const fit=()=>{try{const d=fr.contentDocument,w=d.getElementById('w');const z=fr.clientWidth/633;
  w.style.transform='scale('+z+')';fr.style.height=Math.ceil(w.offsetHeight*z)+4+'px'}catch(e){}};
 fr.onload=()=>{fit();try{fr.contentDocument.fonts.ready.then(fit)}catch(e){}};
 new ResizeObserver(fit).observe(fr);L.appendChild(fr);
 if(r.more){const n=document.createElement('div');n.className='mut';n.textContent='The entry continues on p. '+r.more+' (not shown).';L.appendChild(n)}
 const R=document.createElement('div');R.className='bookv';R.innerHTML='<div class=lab>Book (1903 scan: the entry on this page)</div>';
 if(!r.parts||!r.parts.length||!r.pimg){R.innerHTML+='<div class=mut>the entry was not found in the scan</div>'}
 for(const [x0,y0,x1,y1] of r.parts||[]){const W=r.isz[0],H=r.isz[1],a=Math.max(0,x0),t=Math.max(0,y0),w=Math.min(W,x1)-a,h=Math.min(H,y1)-t;
  const d=document.createElement('div');d.className='part';d.style.aspectRatio=w+'/'+h;
  d.style.backgroundImage='url("'+encodeURI(r.pimg)+'")';d.style.backgroundSize=(W/w*100)+'% auto';
  d.style.backgroundPosition=(W>w?a/(W-w)*100:0)+'% '+(H>h?t/(H-h)*100:0)+'%';R.appendChild(d)}
 b.appendChild(L);b.appendChild(R);c.appendChild(b)}
let SITEURL=SITE0;try{SITEURL=localStorage.getItem('jastrow-focus-site')||SITE0}catch(e){}
function setSite(u){SITEURL=(u||SITE0).trim();if(!/\/$/.test(SITEURL))SITEURL+='/';try{localStorage.setItem('jastrow-focus-site',SITEURL)}catch(e){}
 document.querySelectorAll('.psbs iframe').forEach(f=>{f.src=SITEURL+'#p'+f.dataset.p})}
function psbs(pid){const bx=document.querySelector('.pgbox[data-p="'+pid+'"]');if(!bx)return;const btn=bx.querySelector('.b-psbs');
 let v=bx.querySelector('.psbs');if(v){v.hidden=!v.hidden;btn.classList.toggle('on',!v.hidden);return}
 v=document.createElement('div');v.className='psbs';
 v.innerHTML='<div><div class=lab>Site, the page on the website</div><iframe data-p="'+pid+'" title="the website"></iframe></div>'+
  '<div><div class=lab>Book (1903 scan: the whole page)</div><div class=scanv><img loading=lazy alt="scan of the page"></div></div>';
 v.querySelector('iframe').src=SITEURL+'#p'+pid;v.querySelector('img').src=bx.dataset.img;
 bx.querySelector('.pg').after(v);btn.classList.add('on')}
let SBSALL=false,IO=null;
function sbsAll(on){SBSALL=on;document.getElementById('sbsall').classList.toggle('on',on);
 if(IO){IO.disconnect();IO=null}
 if(!on){document.querySelectorAll('.card.wide').forEach(c=>sbs(c.id,false));return}
 IO=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting&&!e.target.classList.contains('hidden')){sbs(e.target.id,true);IO.unobserve(e.target)}}),{rootMargin:'600px'});
 document.querySelectorAll('.card').forEach(c=>IO.observe(c))}
window.addEventListener('load',()=>{Object.keys(DATA).forEach(paint);count();filt();
 const si=document.getElementById('siteurl');if(si)si.value=SITEURL});
"""


def esc(s): return H.escape(str(s))


VERDICT_HELP = ("<b>OK</b>: the site is right (a false alarm). <b>Wrong</b>: the site is wrong here and needs fixing. "
                "<b>Not sure</b>: can't tell.")
SITE_URL = "https://menachemshapiro.github.io/Jastrow-Book/"
SITE_INPUT = ('<label title="the website shown beside the scan: the live site, or http://localhost:8000/ for your local '
              'copy">site <input id=siteurl size=34 onchange="setSite(this.value)"></label>')


def flags_html(fl):
    if not [f for f in fl if f[0] < 9]: fl = fl + [[9, "agrees with the book"]]
    return "".join('<div class="%s">%s %s</div>' % ("okv" if s == 9 else "f%d" % s,
                   "✓" if s == 9 else "●" if s == 1 else "◆" if s == 2 else "○", esc(t))
                   for s, t in sorted(fl, key=lambda f: f[0]))


VERDICTS = ('<button class="b-ok" title="the site is right here: a false alarm" onclick="mark(\'%s\',\'ok\')">OK</button>'
            '<button class="b-wrong" title="the site is wrong here: it needs fixing" onclick="mark(\'%s\',\'wrong\')">'
            'Wrong</button><button class="b-unsure" title="can\'t tell" onclick="mark(\'%s\',\'unsure\')">Not sure</button>')


def marks_html(cid, sbs=False):
    return ('<div class="marks">' + VERDICTS +
            '<input placeholder="note" onchange="note(\'%s\',this.value)">%s</div>') % (
        cid, cid, cid, cid, ('<button class="b-sbs" onclick="sbs(\'%s\')" title="the whole entry: the site as it looks '
                             'on the website, beside the scan">Side by side</button>' % cid) if sbs else "")


def page_shell(kind, title, run, intro, body, data):
    return ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'><title>%s</title>"
            "<style>%s</style><h1>%s</h1><div class=mut>%s</div>"
            "<div class=bar><label>show <select id=sev onchange=filt()><option value=1>likely wrong</option>"
            "<option value=2 selected>likely wrong and worth a check</option><option value=3>everything flagged</option>"
            "<option value=all>all, flagged or not</option></select></label>"
            "<label>marks <select id=mk onchange=filt()><option value=all>any</option><option value=none>not yet marked"
            "</option><option value=ok>OK</option><option value=wrong>Wrong</option><option value=unsure>Not sure"
            "</option></select></label><button onclick=exportMarks()>Export</button>"
            "<label><button onclick=\"this.nextElementSibling.click()\">Import…</button><input type=file hidden "
            "accept=.json onchange=importMarks(this.files[0])></label>%s<span id=nm class=mut></span></div>%s"
            "<script>const KIND=%s,RUN=%s,DATA=%s,FONTS=%s,SITECSS=%s,SITE0=%s;%s</script>") % (
        esc(title), CSS, esc(title), intro,
        '<button id=sbsall onclick="sbsAll(!SBSALL)" title="open every card shown as the whole entry, the site beside '
        'the scan">Side by side: all</button>' if kind == "headwords" else SITE_INPUT,
        body, json.dumps(kind), json.dumps(run), json.dumps(data, ensure_ascii=False).replace("</", "<\\/"),
        json.dumps(SITE_FONTS), json.dumps(site_css() if kind == "headwords" else "").replace("</", "<\\/"),
        json.dumps(SITE_URL), JS)


def page_box(pid, out):
    """a page's heading in the columns report, with its button for the website's page beside the scan"""
    img = os.path.relpath(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(out))), "pages",
                                       "p%04d" % int(pid), "page.png"), out)
    return ('<div class=pgbox data-p="%s" data-img="%s"><div class=pg>p. %s <button class=b-psbs onclick="psbs(\'%s\')" '
            'title="the page on the website beside the whole scan page">Side by side</button></div>'
            % (esc(pid), esc(img), esc(pid), esc(pid)))


def report_columns(rows, out, run):
    data, body, pages = {}, [], {}
    for r in rows: pages.setdefault(r["page"], []).append(r)
    for pid, rs in pages.items():
        notes = "".join('<div class="note">%s</div>' % esc(n) for _, n in rs[0]["page_notes"])
        segs = []
        for si in sorted({r["seg"] for r in rs}):
            cells = []
            for end in ("top", "foot"):
                for side in ("L", "R"):
                    r = next((x for x in rs if x["seg"] == si and x["col"] == side and x["end"] == end), None)
                    if not r: cells.append("<div></div>"); continue
                    cid = "p%s-%d%s-%s" % (pid, si, side, end)
                    r["sev"] = min([f[0] for f in r["flags"]] or [9])
                    r["where"] = "%s column, %s%s" % ("left" if side == "L" else "right", end,
                                                      " (below the letter heading)" if si == 1 else "")
                    data[cid] = {k: r[k] for k in ("page", "seg", "col", "end", "flags", "sev", "where")}
                    data[cid]["eid"] = ""
                    cells.append('<div class="card s%s" id="%s"><div class=lab>%s</div>%s<div><b>Book:</b> '
                                 '<span class=mut>%s</span></div><div><b>Site:</b> %s</div>%s%s</div>' % (
                                     r["sev"] if r["sev"] < 9 else "", cid, esc(r["where"]),
                                     '<img loading=lazy src="%s">' % r["img"] if r["img"] else "",
                                     esc(r["scan"][:200]), esc(r["site"]), flags_html(r["flags"]), marks_html(cid)))
            segs.append('<div class=cols>%s</div>' % "".join(cells))
        body.append(page_box(pid, out) + '%s%s</div>' % (notes, "".join(segs)))
    nflag = sum(1 for d in data.values() if d["sev"] <= 2)
    intro = ("Run %s. Each page is shown as the book has it: the tops of its two columns, then their feet. Each "
             "box is the scan's first or last two lines beside the site's words at that end of the column. %d of %d "
             "column ends flagged. " % (esc(run), nflag, len(data)) + VERDICT_HELP)
    path = os.path.join(out, "columns.html")
    open(path, "w").write(page_shell("columns", "Columns: start and end", run, intro, "".join(body), data))
    return path, nflag, len(data)


def report_headwords(rows, out, run):
    data, body, pages = {}, [], {}
    for r in rows: pages.setdefault(r["page"], []).append(r)
    for pid, rs in pages.items():
        cards = []
        for r in rs:
            cid = "p%s-%s" % (pid, r["eid"])
            r["where"] = r["hw"]
            data[cid] = {k: r.get(k) for k in ("page", "eid", "hw", "units", "sugg", "old", "prefix", "flags", "sev", "where",
                                               "ent", "parts", "isz", "more")}
            data[cid]["pimg"] = os.path.relpath(os.path.join(r["pdir"], "page.png"), out) if r.get("pdir") else ""
            spans = "".join('<span class="u" data-i="%d" title="%s" onclick="tog(\'%s\',%d)">%s</span>' % (
                i, esc(r["sugg"].get(str(i), "click to strike")), cid, i, esc(u[0]) if u[0] != " " else "&nbsp;")
                for i, u in enumerate(r["units"]))
            book = " · ".join(r["book"]) if r["book"] else "—"
            cards.append('<div class="card s%s" id="%s"><div class=lab>%s</div>%s'
                         '<div><b>Site:</b> <span class=he dir=ltr>%s</span></div><div class="mut new"></div>'
                         '<div class=mut><b>Book, as the OCR read the large words:</b> <span dir=rtl>%s</span></div>%s%s</div>'
                         % (r["sev"] if r["sev"] < 9 else "", cid, esc(r["eid"]),
                            '<img loading=lazy src="%s">' % r["img"] if r["img"] else "", spans or "(none)",
                            esc(book), flags_html(r["flags"]), marks_html(cid, sbs=True)))
        body.append('<div class=pgbox><div class=pg>p. %s</div><div class=grid>%s</div></div>' % (pid, "".join(cards)))
    nflag = sum(1 for d in data.values() if d["sev"] <= 2)
    intro = (VERDICT_HELP + " Run %s. Each entry: the scan's first line, the headword boxed in red where the audit found it by its "
             "larger type, beside the site's headword. Characters struck through are proposed for removal: click "
             "any character to strike it or bring it back, then mark the entry <b>Wrong</b> to put the removal in "
             "the export as a text_fixes record. %d of %d headwords flagged." % (esc(run), nflag, len(data)))
    path = os.path.join(out, "headwords.html")
    open(path, "w").write(page_shell("headwords", "Headwords", run, intro, "".join(body), data))
    return path, nflag, len(data)


# ---------- main ----------
_W = {}


def _init(site, out, what, img, cm, hcm):
    import audit as AU, compare as CO
    SITE[0] = site
    CO.CM, CO.HCM = cm, hcm
    CO.CFG.update(reread3=False, stage4=False)
    _W.update(CO=CO, book=ST.Book(site), V=AU.vocab(site), out=out, what=what, img=img)


def _page(pid):
    """one page's column ends and headwords (in a worker)"""
    CO, book, out, what, img = _W["CO"], _W["book"], _W["out"], _W["what"], _W["img"]
    sp = os.path.join(out, "pages", "p%04d" % int(pid), "scan.json")
    if not os.path.exists(sp): return pid, [], [], "no OCR"
    scan = json.load(open(sp))
    if "ocr" not in scan: return pid, [], [], "no OCR"
    cols, hws = [], []
    try:
        pc = CO.PageCompare(book.page(pid), scan, _W["V"], out)
        F = run_page(pc, CO, headwords=what in ("both", "headwords"))
        ink = Ink(pc.wd, scan["layout"].get("thr", 128))
        if what in ("both", "columns"): cols = check_columns(pid, pc, F, ink, img)
        if what in ("both", "headwords"):
            hws = check_headwords(pid, pc, F, ink, img)
            try:
                nx = book.page(str(int(pid) + 1)).entries
            except Exception:
                nx = []
            if hws and nx and nx[0]["cont"] and nx[0]["eid"] == hws[-1]["eid"]:
                hws[-1]["more"] = str(int(pid) + 1)
    except Exception as e:
        return pid, [], [], "%s: %s" % (type(e).__name__, e)
    return pid, cols, hws, None


def main():
    import audit as AU
    import compare as CO
    import ocrmodel as OM
    import report as RP
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("what", nargs="?", default="both", choices=("both", "columns", "headwords"))
    ap.add_argument("--pages", required=True)
    ap.add_argument("--out", default=os.path.join(paths.WORK, "audit"))
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--dpi", type=int, default=400)
    ap.add_argument("--site", default=os.environ.get("JASTROW_SITE") or ST.REPO,
                    help="the site to check (a checkout of the live branch; default: this repository)")
    args = ap.parse_args()
    # the pages run in parallel: one thread each for Tesseract's re-reads and numpy (else they compete for the cores)
    for v in ("OMP_THREAD_LIMIT", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS"): os.environ.setdefault(v, "1")
    SITE[0] = os.path.abspath(os.path.expanduser(args.site))
    book = ST.Book(SITE[0])
    run = AU.parse_pages(args.pages, book)
    if not run: sys.exit("no pages")
    # OCR any page not done yet
    import scan as SC
    def need(p):
        sp = os.path.join(args.out, "pages", "p%04d" % int(p), "scan.json")
        if not os.path.exists(sp): return True
        # a damaged PDF page (scan.REPLACE) read from the PDF before its GIF was there
        return int(p) in SC.REPLACE and SC.gif_for(p) and not json.load(open(sp)).get("gif")
    todo = [(p, paths.SCANS, args.out, args.dpi, False) for p in run if need(p)]
    if todo:
        print("OCR of %d page(s) not done before (a minute or two each)..." % len(todo), flush=True)
        with Pool(max(1, min(args.jobs, len(todo)))) as pool:
            for pid, secs, err in pool.imap_unordered(AU.scan_one, todo):
                print("  p. %-5s %5.1f s%s" % (pid, secs, ("  ERROR " + err) if err else ""), flush=True)
    V = AU.vocab(SITE[0])
    mf = [os.path.join(args.out, "marks.json")] + sorted(glob.glob(os.path.expanduser("~/Downloads/jastrow-audit-marks*.json")))
    CO.CM, CO.HCM = OM.build(os.path.join(args.out, "pages"), RP.load_marks(mf))
    # the comparison, without stage 3 and 4 (not needed for these two checks; much faster)
    CO.CFG.update(reread3=False, stage4=False)
    stamp = time.strftime("%Y-%m-%d_%H%M%S")
    name = re.sub(r"[^\w-]+", "_", args.pages) + "_" + stamp
    out = os.path.join(args.out, "focus", name)
    img = os.path.join(out, "img")
    os.makedirs(img, exist_ok=True)
    cols, hws, skipped = [], [], []
    t0 = time.time()
    with Pool(max(1, min(args.jobs, len(run))), initializer=_init,
              initargs=(SITE[0], args.out, args.what, img, CO.CM, CO.HCM)) as pool:
        for n, (pid, c, h, err) in enumerate(pool.imap(_page, run)):
            if (n + 1) % 50 == 0: print("  %d of %d pages  (%.0f s)" % (n + 1, len(run), time.time() - t0), flush=True)
            if err:
                if err != "no OCR": print("  p. %s: %s" % (pid, err))
                skipped.append(pid); continue
            cols += c; hws += h
    lines = ["focus.py %s --pages %s  (%s)" % (args.what, args.pages, name)]
    if args.what in ("both", "columns"):
        p, nf, nt = report_columns(cols, out, name)
        by = Counter(min([f[0] for f in r["flags"]] or [9]) for r in cols)
        lines.append("columns: %d column ends, %d likely wrong, %d worth a check, %d minor  ->  %s"
                     % (nt, by[1], by[2], by[3], p))
    if args.what in ("both", "headwords"):
        p, nf, nt = report_headwords(hws, out, name)
        by = Counter(r["sev"] for r in hws)
        kinds = Counter(re.sub(r":.*|\d+", "", f[1]).strip() for r in hws for f in r["flags"] if f[0] <= 2)
        lines.append("headwords: %d entries, %d likely wrong, %d worth a check, %d minor  ->  %s"
                     % (nt, by[1], by[2], by[3], p))
        lines += ["  %4d  %s" % (c, k) for k, c in kinds.most_common(12)]
    if skipped: lines.append("pages not checked (no OCR): %s" % ", ".join(skipped))
    open(os.path.join(out, "summary.txt"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
