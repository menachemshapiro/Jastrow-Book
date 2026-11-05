"""Line-by-line review of the scan against the site's text: the checked lines train OCR engines (kraken, and
worked examples for LLM readers) and measure them (the gold lines). KRAKEN_PLAN.md, "Line review".

For each page, kraken's lines (PAGE XML made by kraken's own segmenter, so that the training lines are cut the
way kraken will cut them when it reads), and for each line:
  - the scan crop;
  - the site's text for that line, split into lines by the audit's alignment (each English word the audit matched
    and each Hebrew word it paired puts the site's text on a scan line; the words between are shared out by the
    room left on each line, or at the starts of entries, which always begin a line). A word the book divides at
    a line's end is divided here too, with its hyphen, since that is what the line shows; "=" is set without spaces,
    as the book prints it ("meadow=to"; the site's text has " = ");
  - what the other readers read there, with the words that differ from the site's marked: Tesseract (the
    audit's OCR), the PDF's own OCR layer (HebrewBooks), and kraken (the stock McCATMuS model reads no Hebrew,
    so only its English counts for now).
Vowel points are Sefaria's, unchecked: the readers are compared on letters only.

Before running, make each page's PAGE XML with kraken (in its own environment; about a minute a page):
  source ~/jastrow/kraken-venv/bin/activate
  M=~/.local/share/htrmopo/78d7d26e-50b3-55f8-b839-c7a882ea2053/McCATMuS_nfd_nofix_V1.mlmodel
  kraken --threads 3 -x -i work/audit/pages/p0013/page.png work/audit/pages/p0013/kraken_mccatmus.xml \\
      segment -bl ocr -m $M
Then (in the audit's environment):
  python3 build/audit/linereview.py --pages 13,151,155,1627 --site ~/jastrow/jb-site

Writes DIR/lines/<name>/index.html (open it in a browser), img/ and lines.json. On the page, each line is marked
Right / Fixed (edit the text) / Bad line (leave it out) / Skip, kept in the browser; Export saves
jastrow-lines-<name>-<time>.json, which the training export reads."""
import argparse, glob, html as H, json, math, os, re, subprocess, sys, time, unicodedata
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import paths  # noqa: E402
import sitetext as ST  # noqa: E402

HEB_LETTER = re.compile("[א-ת]")
FINALS = str.maketrans("ךםןףץ", "כמנפצ")
MIRROR = str.maketrans("()[]{}<>", ")(][}{><")
RAISED = {"a": "ᵃ", "b": "ᵇ", "c": "ᶜ", "d": "ᵈ"}                    # a folio's side, raised in the book


# ---------- comparing words ----------
def norm_word(w):
    """a word as compared: letters and digits only, no vowel points, final letters as plain, lower case"""
    w = unicodedata.normalize("NFKD", w)                              # also ᵃ -> a, ﬁ -> fi
    w = "".join(c for c in w if not ("֑" <= c <= "ׇ"))     # points and accents (letters are 05d0-05ea)
    w = w.translate(FINALS).replace("ﬁ", "fi").replace("ﬂ", "fl").lower()
    m = FOLIO.match(w.strip())
    if m: return m.group(1)                                          # 38a, 38°, 38% are all folio 38
    return "".join(c for c in w if c.isalnum())


FOLIO = re.compile("^(\\d+)[a-dᵃᵇᶜᵈ°?*%\"'’”“]?[.,;:)]*$")


def word_spans(s):
    """a line's words as compared, with where each stands in the line: a folio's raised side letter, which the
    readers read every way (38°, 38%, "38 a"), is left out, and so is a lone a-d after a number"""
    out = []
    for mt in re.finditer(r"[^\s\u2014]+", s):
        w = mt.group(0)
        if not norm_word(w): continue
        m = FOLIO.match(w)
        if m: w = m.group(1)
        elif re.fullmatch(r"[a-d][.,;]?", w) and out and out[-1][2].isdigit(): continue
        out.append((mt.start(), mt.end(), w))
    return out


def words(s):
    return [w for _, _, w in word_spans(s)]


CM = [None]                                       # the audit's count of the OCR's Latin misreadings (ocrmodel)


def familiar(a, b):
    """an English word read in a way the OCR often misreads it (S. as 8., l. as 1., cc as ce): not a difference
    worth showing. Hebrew is never let off this way: a ב read as כ is just what is being looked for"""
    if CM[0] is None or HEB_LETTER.search(a) or HEB_LETTER.search(b): return False
    n, _ = CM[0].seen(a, b, own=False)
    return n is not None and n >= 3


def diff_marks(site, other, latin_only=False):
    """which of `other`'s words, and which of the site's, the two do not share (word lists, by norm_word)"""
    a = [norm_word(w) for w in site]
    b = [norm_word(w) for w in other]
    if latin_only:
        keep_a = [i for i, w in enumerate(site) if not HEB_LETTER.search(w)]
        keep_b = [j for j, w in enumerate(other) if not HEB_LETTER.search(w)]
    else:
        keep_a, keep_b = list(range(len(a))), list(range(len(b)))
    # Hebrew: a bag of words within the line (the readers' order of Hebrew is unreliable); English: in order
    heb_a = [i for i in keep_a if HEB_LETTER.search(site[i])]
    heb_b = [j for j in keep_b if HEB_LETTER.search(other[j])]
    bad_a, bad_b = set(keep_a), set(keep_b)
    free = {}
    for j in heb_b: free.setdefault(b[j], []).append(j)
    for i in heb_a:
        if free.get(a[i]):
            bad_a.discard(i); bad_b.discard(free[a[i]].pop(0))
    keep_a = [i for i in keep_a if i not in heb_a]
    keep_b = [j for j in keep_b if j not in heb_b]
    sa, sb = [a[i] for i in keep_a], [b[j] for j in keep_b]
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, sa, sb, autojunk=False).get_opcodes():
        if tag == "equal":
            bad_a -= {keep_a[i] for i in range(i1, i2)}
            bad_b -= {keep_b[j] for j in range(j1, j2)}
        elif tag == "replace" and i2 - i1 == j2 - j1:
            for i, j in zip(range(i1, i2), range(j1, j2)):
                if familiar(site[keep_a[i]], other[keep_b[j]]):
                    bad_a.discard(keep_a[i]); bad_b.discard(keep_b[j])
    return bad_a, bad_b


def logical(items):
    """words in left-to-right order on the line -> reading order: each run of Hebrew words is read right to left"""
    out, run = [], []
    for w in items:
        if HEB_LETTER.search(w):
            run.append(w)
        else:
            out += run[::-1] + [w]; run = []
    return out + run[::-1]


# ---------- kraken's lines ----------
def kraken_lines(xml_path):
    """the TextLines of a PAGE XML: id, outline, baseline, bounding box, text"""
    root = ET.parse(xml_path).getroot()
    ns = {"p": root.tag.split("}")[0][1:]} if root.tag.startswith("{") else {}
    q = (lambda t: "p:" + t) if ns else (lambda t: t)
    out = []
    for ln in root.iter(("{%s}TextLine" % ns["p"]) if ns else "TextLine"):
        def pts(el):
            return [[int(float(v)) for v in p.split(",")] for p in el.get("points").split()] if el is not None else []
        poly = pts(ln.find(q("Coords"), ns))
        base = pts(ln.find(q("Baseline"), ns))
        te = ln.find(q("TextEquiv") + "/" + q("Unicode"), ns)
        if not poly: continue
        xs, ys = [p[0] for p in poly], [p[1] for p in poly]
        out.append({"id": ln.get("id"), "poly": poly, "base": base, "box": [min(xs), min(ys), max(xs), max(ys)],
                    "kraken": (te.text or "") if te is not None else ""})
    return out


# ---------- the PDF's OCR layer ----------
def pdf_words(scan, img_size):
    """the PDF's text layer for the page, each word's box moved onto the audit's straightened page image"""
    pdf = os.path.join(paths.SCANS, scan["pdf"])
    if scan.get("gif") or not os.path.exists(pdf) or not scan.get("pdf_page"): return []
    r = subprocess.run(["pdftotext", "-bbox", "-f", str(scan["pdf_page"]), "-l", str(scan["pdf_page"]), pdf, "-"],
                       capture_output=True, text=True)
    if r.returncode: return []
    s = scan.get("dpi", 400) / 72
    ang = math.radians(scan["layout"].get("angle", 0))
    cx, cy = img_size[0] / 2, img_size[1] / 2

    def m(x, y):
        # PIL's rotate(angle) turns the picture counter-clockwise about its centre (scan.deskew)
        dx, dy = x * s - cx, y * s - cy
        return cx + dx * math.cos(ang) + dy * math.sin(ang), cy - dx * math.sin(ang) + dy * math.cos(ang)
    out = []
    for a, b, c, d, t in re.findall(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>',
                                    r.stdout):
        t = H.unescape(t)
        x0, y0 = m(float(a), float(b)); x1, y1 = m(float(c), float(d))
        # the layer keeps Hebrew in visual order: reverse the Hebrew parts only ("Ib.שא" is "Ib." and "אש")
        parts = re.findall(r"[\u0590-\u05ff\"'׳״]+|[^\u0590-\u05ff]+", t) if HEB_LETTER.search(t) else [t]
        n = len(t)
        for q in parts:
            if HEB_LETTER.search(q): q = q[::-1].translate(MIRROR)
            out.append({"text": q, "box": [x0, y0, x1, y1]})
    # a headword in large type comes out letter by letter ("ב ר ך ם י ף"): join each such run into one word
    joined = []
    for w in out:
        if joined and len(w["text"]) == 1 and HEB_LETTER.match(w["text"]) and joined[-1].get("spelt"):
            p = joined[-1]
            if abs(w["box"][1] - p["box"][1]) < 20 and 0 <= w["box"][0] - p["box"][2] < 60:
                p["text"] = w["text"] + p["text"]; p["box"][2] = w["box"][2]; continue
        if len(w["text"]) == 1 and HEB_LETTER.match(w["text"]): w = dict(w, spelt=True)
        joined.append(w)
    return joined


# ---------- the site's text, line by line ----------
def lis_keep(anchors):
    """keep the heaviest run of anchors whose lines never go back (an anchor out of order is a chance match). An
    English word matched exactly weighs more than a Hebrew word paired by likeness"""
    n = len(anchors)
    best, prev = [0.0] * n, [-1] * n
    for k in range(n):
        w = 3.0 if anchors[k].get("lat") else 1.0
        best[k] = w
        for i in range(k - 1, max(-1, k - 400), -1):
            if anchors[i]["rank"] <= anchors[k]["rank"] and best[i] + w > best[k]:
                best[k], prev[k] = best[i] + w, i
    out, k = [], max(range(n), key=lambda i: best[i]) if n else -1
    while k >= 0:
        out.append(anchors[k]); k = prev[k]
    return out[::-1]


def near_line(order, box):
    """the scan line whose middle is nearest a word's middle, in the word's column"""
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    cand = [ln for ln in order if ln["box"][0] - 30 <= cx <= ln["box"][2] + 30] or order
    return min(cand, key=lambda ln: abs((ln["box"][1] + ln["box"][3]) / 2 - cy))


def in_bag(bag, w):
    """the site's word w is among a reader's words of a line (letters only; a near match for longer words)"""
    k = norm_word(w)
    if not k or not bag: return 0
    if k in bag: return 2                                            # a sure sighting counts double
    # Hebrew words the readers garble more (משיבחלו read as משרבחלף, מטכבחלו: 0.71)
    cut = 0.7 if HEB_LETTER.search(k) else 0.8
    return int(len(k) >= 4 and any(len(x) >= 3 and SequenceMatcher(None, k, x).ratio() >= cut for x in bag))


def site_lines(pc, CO, bags=None, where_out=None):
    """the site's text of each scan line (Tesseract's lines), as {line i: {"spans": [(off, end, suffix)], flags}}"""
    P = pc.p
    lines = [ln for ln in pc.lines if ln["i"] not in pc.signature_lines]
    order = sorted(lines, key=lambda l: (l["seg"], 0 if l["col"] == "L" else 1, (l["box"][1] + l["box"][3]) / 2))
    rank = {ln["i"]: r for r, ln in enumerate(order)}
    L = {ln["i"]: ln for ln in lines}
    toks = [t for t in P.tokens if not t["h2"]]
    pos = {t["i"]: n for n, t in enumerate(toks)}
    anchors = []
    for si, kj in pc.s2k.items():
        k = pc.k[kj]
        if si not in pos or k["lines"][0] not in rank: continue
        an = {"n": pos[si], "rank": rank[k["lines"][0]], "box": k["boxes"][0], "lat": True}
        if k.get("hyph") and len(k["lines"]) == 2 and k["lines"][1] in rank:
            an["hyph"] = (rank[k["lines"][1]], k.get("raw", ""), k["boxes"][1])
        anchors.append(an)
    # a scan word the audit paired with two of the site's words (the same phrase twice, "אקרא דא׳" on p. 13) places neither
    used = {}
    for st, w in pc.heb_pair_toks: used[tuple(w["box"])] = used.get(tuple(w["box"]), 0) + 1
    for st, w in pc.heb_pair_toks:
        if used[tuple(w["box"])] > 1: continue
        # the audit finds a Hebrew word in every line whose band it falls in (the bands overlap), so its "line"
        # may be the next one: take the line nearest the word itself
        if st["i"] not in pos: continue
        n = pos[st["i"]]
        # a word whose letters stand again a few words off (בית ... בית, בּוּתָא / בָּוְתָא) may be paired with the
        # other's place: it places nothing
        k = norm_word(st["text"])
        if any(norm_word(toks[j]["text"]) == k for j in range(max(0, n - 15), min(len(toks), n + 16)) if j != n): continue
        anchors.append({"n": n, "rank": rank[near_line(order, w["box"])["i"]], "box": w["box"],
                        "exact": k == norm_word(w.get("text", ""))})
    anchors.sort(key=lambda a: a["n"])
    # one anchor per site word (a Hebrew word can be paired twice in overlapping gaps)
    seen, uniq = set(), []
    for a in anchors:
        if a["n"] in seen: continue
        seen.add(a["n"]); uniq.append(a)
    anchors = lis_keep(uniq)
    # every entry begins a line: between two anchors there must be at least as many lines as entry starts; where
    # not, a Hebrew pair is wrong (p. 151 בַּז paired with the בזי of the next line): drop a Hebrew anchor, one whose
    # scan word has other letters first, else the earlier
    def starts(a, b): return sum(1 for n in range(a + 1, b + 1) if n > 0 and toks[n]["eid"] != toks[n - 1]["eid"])
    while True:
        bad = next(((A, B) for A, B in zip(anchors, anchors[1:])
                    if B["rank"] - A["rank"] < starts(A["n"], B["n"]) and not (A.get("lat") and B.get("lat"))), None)
        if not bad: break
        A, B = bad
        heb = [x for x in (A, B) if not x.get("lat")]
        drop = next((x for x in heb if not x.get("exact")), heb[0])
        anchors.remove(drop)
    if os.environ.get("LRDEBUG"):
        for a in uniq:
            print("ANCHOR", a["n"], toks[a["n"]]["text"], "rank", a["rank"], "lat" if a.get("lat") else "heb",
                  "kept" if a in anchors else "dropped", file=sys.stderr)
    nl = len(order)
    where = [None] * len(toks)                     # token n -> line rank
    split = {}                                     # token n -> (letters on the first line, rank of the second line)
    flags = {r: set() for r in range(nl)}
    for a in anchors:
        where[a["n"]] = a["rank"]
        if "hyph" in a:
            r2, raw, _ = a["hyph"]
            first = CO.HYPH.match(raw.split(" ")[0]) if raw else None
            t = toks[a["n"]]["text"]
            n = None
            if first:
                f = first.group(1)
                if t[:len(f)].lower() == f.lower(): n = len(f)
                else:
                    # the OCR misread a letter: count its letters
                    lt = [i for i, c in enumerate(t) if c.isalpha()]
                    nf = sum(1 for c in f if c.isalpha())
                    if 0 < nf < len(lt): n = lt[nf - 1] + 1; flags[a["rank"]].add("hyphen_guess")
            if n:
                split[a["n"]] = (n, r2)
            else:
                flags[a["rank"]].add("divided_word")
    # the words between two anchors
    bounds = [{"n": -1, "rank": 0, "box": None, "start": True}] + anchors + \
             [{"n": len(toks), "rank": nl - 1, "box": None, "end": True}]
    for A, B in zip(bounds, bounds[1:]):
        gap = list(range(A["n"] + 1, B["n"]))
        la = split[A["n"]][1] if A["n"] in split else A["rank"]
        lb = B["rank"]
        if not gap: continue
        if la >= lb:
            for n in gap: where[n] = la
            continue
        # entries begin on a new line: if the gap holds exactly as many entry starts as line ends, they are the ends
        starts = [n for n in gap + ([B["n"]] if B["n"] < len(toks) else [])
                  if n > 0 and toks[n]["eid"] != toks[n - 1]["eid"]]
        if len(starts) == lb - la:
            r = la
            for n in gap:
                if n in starts: r += 1
                where[n] = r
            continue
        # else share the words out by the room left on each line
        def width(r):
            b = L[order[r]["i"]]["box"]
            x0, x1 = b[0], b[2]
            if r == la and A.get("box"): x0 = A["box"][2] if A["n"] not in split else split_box_end(A, anchors)
            if r == lb and B.get("box"): x1 = B["box"][0]
            return max(1, x1 - x0)
        room = [width(r) for r in range(la, lb + 1)]
        need = [len(toks[n]["text"]) + 1 for n in gap]
        tot_room, tot_need = sum(room), sum(need)
        c, cum = 0, [0]
        for w in room: cum.append(cum[-1] + w)
        for n, w in zip(gap, need):
            mid = (c + w / 2) / tot_need * tot_room
            r = next(i for i in range(len(room)) if cum[i + 1] >= mid)
            where[n] = la + r
            c += w
        # then move each line end to where the readers saw the words: the split between lines r and r+1 that puts
        # most of the gap's words on a line whose readers have them (ties keep the share by length)
        if bags:
            for r in range(la, lb):
                zone = [n for n in gap if where[n] in (r, r + 1)]
                if not zone: continue
                b1, b2 = bags.get(order[r]["i"]), bags.get(order[r + 1]["i"])
                cur = sum(1 for n in zone if where[n] == r)
                def score(k): return sum(in_bag(b1, toks[n]["text"]) for n in zone[:k]) + \
                    sum(in_bag(b2, toks[n]["text"]) for n in zone[k:])
                best = max(range(len(zone) + 1), key=lambda k: (score(k), -abs(k - cur)))
                if os.environ.get("LRDEBUG"):
                    print("ZONE", r, [toks[n]["text"] for n in zone], "cur", cur, "best", best, sorted(b1 or []), sorted(b2 or []), file=sys.stderr)
                if score(best) > score(cur):
                    for k, n in enumerate(zone): where[n] = r if k < best else r + 1
        for r in range(la, lb + 1): flags[r].add("estimated")
    # punctuation standing alone (Sefaria's "X , v. Y") goes with the word before it; an opening bracket with the next
    for n, t in enumerate(toks):
        if any(c.isalnum() for c in t["text"]) or n in split: continue
        # an opening bracket, and the asterisk that marks an entry (it stands before the headword), go with the next word
        if (t["text"].strip()[:1] in "([" or t["text"].strip() == "*") and n + 1 < len(toks) and where[n + 1] is not None:
            where[n] = where[n + 1]
        elif n > 0 and where[n - 1] is not None and (n - 1) not in split: where[n] = where[n - 1]
    # spans of the plain text, per line
    spans = {r: [] for r in range(nl)}
    for n, t in enumerate(toks):
        if where[n] is None: continue
        if n in split:
            k, r2 = split[n]
            spans[where[n]].append((t["off"], t["off"] + k, "-"))
            spans[r2].append((t["off"] + k, t["end"], ""))
            flags[where[n]].add("hyphen")
        else:
            spans[where[n]].append((t["off"], t["end"], ""))
    if where_out is not None: where_out.update(where=where, toks=toks, order=order)
    out = {}
    for r in range(nl):
        sp = sorted(spans[r])
        text = ""
        for k, (a, b, suf) in enumerate(sp):
            if k:
                pa, pb, psuf = sp[k - 1]
                between = P.plain[pb:a]
                text += "" if P.plain[pa:pb].strip() == "*" else \
                    " " if (re.search(r"\s", between) or pb in P.bounds or psuf) else between
            text += "".join(RAISED.get(c, c) if "sup" in P.attrs[o][4] else c
                            for o, c in zip(range(a, b), P.plain[a:b])) + suf
        eids = []
        for n in range(len(toks)):
            if where[n] == r and toks[n]["eid"] and toks[n]["eid"] not in eids: eids.append(toks[n]["eid"])
        # the book divides a word at this line's end that the audit did not match: the site's text runs on
        last = [t for t in pc.k if t["lines"][0] == order[r]["i"]]
        if last and last[-1].get("hyph") and "hyphen" not in flags[r]: flags[r].add("divided_word")
        out[order[r]["i"]] = {"rank": r, "text": re.sub(r"\s*=\s*", "=", re.sub(r"\s+", " ", text)).strip(), "eids": eids,
                              "flags": sorted(flags[r]), "box": order[r]["box"], "col": order[r]["col"],
                              "seg": order[r]["seg"]}
    return out


DASH = re.compile("^[\u2014\u2013-]")


def move_dashes(sl, scan, PW, CO):
    """a dash at a line break ("7.—" / "—2) (cmp.") stands at the end of one line or the start of the next: put it
    where the readers (Tesseract, the PDF layer) see it"""
    seq = sorted(sl, key=lambda li: sl[li]["rank"])
    def ends(li):
        b = sl[li]["box"]
        pw = [w["text"] for w in sorted((w for w in PW if in_box(w, b)), key=lambda w: w["box"][0])]
        rd = [tess_text(scan, li, CO), " ".join(pw)]
        return (sum(1 for t in rd if t.strip() and t.strip()[-1] in "\u2014\u2013-"),
                sum(1 for t in rd if t.strip() and DASH.match(t.strip())))
    for a, b in zip(seq, seq[1:]):
        ta, tb = sl[a]["text"], sl[b]["text"]
        if not ta or not tb or sl[a]["col"] != sl[b]["col"] or sl[a]["seg"] != sl[b]["seg"]: continue
        if tb.startswith("\u2014") and not ta.endswith("\u2014"):
            ea, _ = ends(a); _, sb = ends(b)
            if ea > sb: sl[a]["text"], sl[b]["text"] = ta + "\u2014", tb[1:].lstrip()
        elif ta.endswith("\u2014") and not tb.startswith("\u2014"):
            ea, _ = ends(a); _, sb = ends(b)
            if sb > ea: sl[a]["text"], sl[b]["text"] = ta[:-1].rstrip(), "\u2014" + tb


def split_box_end(A, anchors):
    return A["hyph"][2][2]


# ---------- Tesseract's reading, line by line ----------
def tess_text(scan, li, CO):
    toks = sorted((t for t in scan["ocr"]["tokens"] if t["line"] == li), key=lambda t: t["box"][0])
    out = []
    for t in toks:
        hc, ht = -1, ""
        for w in scan["ocr"]["heb"]:
            b = w["box"]
            ov = max(0, min(b[2], t["box"][2]) - max(b[0], t["box"][0])) * max(0, min(b[3], t["box"][3]) - max(b[1], t["box"][1]))
            ar = min((b[2] - b[0]) * (b[3] - b[1]), (t["box"][2] - t["box"][0]) * (t["box"][3] - t["box"][1]))
            if ar > 0 and ov > 0.5 * ar and HEB_LETTER.search(w["text"]) and w["conf"] > hc: hc, ht = w["conf"], w["text"]
        out.append(ht if hc > t["conf"] + CO.CFG["heb_margin"] else t["text"])
    return " ".join(logical(out))


def in_box(w, b, pad=0):
    cx, cy = (w["box"][0] + w["box"][2]) / 2, (w["box"][1] + w["box"][3]) / 2
    return b[0] - pad <= cx <= b[2] + pad and b[1] <= cy <= b[3]


# ---------- one page ----------
def page_lines(pid, book, V, CO, out, img_dir, xml_name):
    import focus as FO
    from PIL import Image
    wd = os.path.join(out, "pages", "p%04d" % int(pid))
    scan = json.load(open(os.path.join(wd, "scan.json")))
    xml = os.path.join(wd, xml_name)
    if not os.path.exists(xml):
        print("  p. %s: no %s (run kraken first, see --help)" % (pid, xml_name)); return []
    pc = CO.PageCompare(book.page(str(pid)), scan, V, out)
    FO.run_page(pc, CO, headwords=False)
    img = Image.open(os.path.join(wd, "page.png")).convert("L")
    K = kraken_lines(xml)
    PW = pdf_words(scan, img.size)
    # each line's words as the readers saw them (a PDF word goes to the one line nearest it: the lines' boxes overlap)
    bags = {ln["i"]: {norm_word(w) for w in words(tess_text(scan, ln["i"], CO)) if norm_word(w)} for ln in pc.lines}
    for w in PW:
        k = norm_word(w["text"])
        if k and pc.lines: bags[near_line(pc.lines, w["box"])["i"]].add(FOLIO.match(k).group(1) if FOLIO.match(k) else k)
    sl = site_lines(pc, CO, bags)
    move_dashes(sl, scan, PW, CO)
    gut = scan["layout"].get("gutter") or [img.size[0] // 2, img.size[0] // 2]
    # each Tesseract line to the kraken line it overlaps most
    for k in K:
        k["tess"] = []
        k["crosses"] = k["box"][0] < gut[0] - 20 and k["box"][2] > gut[1] + 20
    for li, s in sl.items():
        b, best, bo = s["box"], None, 0
        for k in K:
            kb = k["box"]
            ov = max(0, min(b[2], kb[2]) - max(b[0], kb[0])) * max(0, min(b[3], kb[3]) - max(b[1], kb[1]))
            if ov > bo: best, bo = k, ov
        if best is not None and bo > 0.3 * (b[2] - b[0]) * (b[3] - b[1]): best["tess"].append(li)
        else: s["lost"] = True
    lost = [li for li, s in sl.items() if s.get("lost")]
    recs = []
    for k in K:
        if not k["tess"]: continue                               # running head, page number, letter heading
        tl = sorted(k["tess"], key=lambda li: sl[li]["rank"])
        flags = set(f for li in tl for f in sl[li]["flags"])
        if len(tl) > 1: flags.add("two_lines")
        if k["crosses"]: flags.add("crosses_gutter")
        site = " ".join(sl[li]["text"] for li in tl).strip()
        if not site: flags.add("no_site_text")
        tess = " ".join(tess_text(scan, li, CO) for li in tl)
        kb = k["box"]
        pdfw = sorted((w for w in PW if in_box(w, kb)), key=lambda w: w["box"][0])
        pdf = " ".join(logical([w["text"] for w in pdfw]))
        x0, y0 = max(0, kb[0] - 12), max(0, kb[1] - 6)
        x1, y1 = min(img.size[0], kb[2] + 12), min(img.size[1], kb[3] + 6)
        name = "p%04d_%03d.jpg" % (int(pid), sl[tl[0]]["rank"])
        crop = img.crop((x0, y0, x1, y1))
        crop = crop.resize((max(1, int(crop.width * 0.6)), max(1, int(crop.height * 0.6))), Image.LANCZOS)
        crop.save(os.path.join(img_dir, name), quality=85)
        rec = {"page": str(pid), "rank": sl[tl[0]]["rank"], "kid": k["id"], "xml": os.path.relpath(xml, out),
               "img": "img/" + name, "box": kb, "col": sl[tl[0]]["col"], "eids": [e for li in tl for e in sl[li]["eids"]],
               "flags": sorted(flags), "site": site,
               "readers": {"tesseract": tess, "pdf": pdf, "kraken": k["kraken"]}}
        sw = words(site)
        if "estimated" in flags and sw:
            def near(a, b): return SequenceMatcher(None, norm_word(a), norm_word(b)).ratio() >= 0.75
            ends = [words(t) for rd, t in rec["readers"].items() if rd != "kraken"]
            first = any(any(near(sw[0], w) for w in ow[:2]) for ow in ends)
            last = any(any(near(sw[-1], w) for w in ow[-2:]) for ow in ends)
            if first and last: flags.discard("estimated"); rec["flags"] = sorted(flags)
        rec["marks"] = {}
        for rd, txt in rec["readers"].items():
            ow = words(txt)
            ba, bb = diff_marks(sw, ow, latin_only=(rd == "kraken"))
            rec["marks"][rd] = {"site": sorted(ba), "reader": sorted(bb),
                                "rspans": [[a, b] for k_, (a, b, _) in enumerate(word_spans(txt)) if k_ in bb]}
        # for the page: each of the site's words that a reader read otherwise, with how many readers did
        cnt = {}
        for m in rec["marks"].values():
            for i in m["site"]: cnt[i] = cnt.get(i, 0) + 1
        rec["sitew"] = [[a, b, cnt[k_]] for k_, (a, b, _) in enumerate(word_spans(site)) if k_ in cnt]
        # words two readers or more see that our text lacks (folio numbers count; one-letter scraps do not)
        ex = {}
        for rd, m in rec["marks"].items():
            ow = words(rec["readers"][rd])
            for k in {norm_word(ow[j]) for j in m["reader"]}:
                if len(k) >= 2 and not (rd == "kraken" and HEB_LETTER.search(k)): ex[k] = ex.get(k, 0) + 1
        sk = {norm_word(w) for w in sw}
        rec["extra"] = sorted(k for k, n in ex.items() if n >= 2 and k not in sk)
        recs.append(rec)
    recs.sort(key=lambda r: r["rank"])
    print("  p. %-5s %3d lines; kraken lines with no text %d; Tesseract lines kraken missed %d; estimated %d" % (
        pid, len(recs), sum(1 for k in K if not k["tess"]), len(lost), sum(1 for r in recs if "estimated" in r["flags"])))
    return recs


# ---------- the page ----------
FLAG_TEXT = {
    "estimated": "line end estimated: the site's words at this line's ends were placed by length, check them",
    "hyphen": "the book divides a word at the line's end: hyphen added as printed",
    "hyphen_guess": "divided word: where it divides was guessed, check it",
    "divided_word": "the book divides a word here that the site's text joins: check the line's end",
    "two_lines": "kraken took two of the audit's lines as one",
    "crosses_gutter": "kraken's line crosses the gutter: mark it Bad",
    "no_site_text": "no site text found for this line",
}

PAGE = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Line review %(name)s</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Frank+Ruhl+Libre:wght@400;700&family=Noto+Serif+Hebrew:wght@400;700&family=Noto+Serif:ital,wght@0,400;0,700;1,400&display=swap">
<style>
body{font-family:system-ui,sans-serif;margin:0;background:#f4f1ea;color:#222}
header{position:sticky;top:0;background:#fff;border-bottom:1px solid #ccc;padding:8px 16px;z-index:2;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
header .count{font-size:14px;color:#555}
main{max-width:1100px;margin:0 auto;padding:12px 16px 80px}
.intro{font-size:14px;line-height:1.45;background:#fff;border:1px solid #ddd;padding:10px 14px;border-radius:6px}
.card{background:#fff;border:1px solid #ddd;border-radius:6px;margin:14px 0;padding:10px 14px;border-left:6px solid #ddd}
.card.ok{border-left-color:#3a8d3a}.card.fixed{border-left-color:#2f6fd0}.card.bad{border-left-color:#b33}.card.skip{border-left-color:#999}
.meta{font-size:12px;color:#666;display:flex;gap:10px;flex-wrap:wrap}
.meta a{color:#666}
.scan{display:block;max-width:100%%;margin:6px 0;border:1px solid #eee}
.txt{font-family:'Noto Serif','Frank Ruhl Libre','Noto Serif Hebrew',serif;font-size:21px;line-height:1.6;padding:2px 4px;direction:ltr;text-align:left}
.txt [lang=he]{font-family:'Frank Ruhl Libre','Noto Serif Hebrew',serif;font-size:23px}
.hi{unicode-bidi:isolate}
.prev{font-family:'Noto Serif','Frank Ruhl Libre','Noto Serif Hebrew',serif;font-size:21px;padding:2px 4px;background:#f3f8ff;direction:ltr;text-align:left}
.prev b{font:600 11px sans-serif;color:#789;text-transform:uppercase;margin-right:6px}
.d1{background:#ffe89a}.d2{background:#ffb8a8}
.edit{width:100%%;box-sizing:border-box;font-family:'Noto Serif','Frank Ruhl Libre',serif;font-size:20px;padding:4px;direction:ltr}
.rd{font-size:14px;color:#444;margin:2px 0 2px 4px;direction:ltr}
.rd b{display:inline-block;width:86px;font-weight:600;color:#777}
.rd .x{background:#ffd6cc}
.agree{font-size:13px;color:#3a8d3a}
.miss{font-size:13px;color:#a33;margin:2px 0}.flag.chg{background:#ffe0e0;border-color:#e99}
.flag{font-size:12px;background:#fff4d6;border:1px solid #ecd58a;border-radius:4px;padding:1px 6px;margin:2px 4px 2px 0;display:inline-block}
.btns{margin-top:6px;display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.btns button{font-size:14px;padding:4px 12px;border:1px solid #aaa;background:#f7f7f7;border-radius:4px;cursor:pointer}
.btns button.on{color:#fff}.b-ok.on{background:#3a8d3a}.b-fixed.on{background:#2f6fd0}.b-bad.on{background:#b33}.b-skip.on{background:#777}
.note{font-size:13px;width:240px}
nav{display:flex;gap:8px;align-items:center}
</style></head><body>
<header><b>Line review</b><span class="count" id="count"></span>
<nav><button id="prev">&larr; 20</button><span id="where"></span><button id="next">20 &rarr;</button>
<select id="filter"><option value="all">all lines</option><option value="open">not yet marked</option><option value="disagree">readers disagree</option><option value="flag">flagged</option><option value="again">check again</option></select></nav>
<button id="export">Export</button><label style="font-size:13px">Import <input type="file" id="import" accept=".json"></label></header>
<main><div class="intro">
<p><b>Each card is one line of the scan</b>, with the site's text for that line under it. Vowel points are Sefaria's and are not being checked: look at the letters, the English, the punctuation and where the line begins and ends. A word the book divides at the line's end should end with its hyphen, as printed.</p>
<p><span class="d1">Yellow</span>: one reader read this word differently; <span class="d2">red</span>: two or more did. Below are the readers' own readings, their differing words marked: <b>Tesseract</b> (the audit's OCR), <b>PDF</b> (the OCR layer in the HebrewBooks PDF), <b>kraken</b> (stock model, no Hebrew yet: only its English is compared). Readers are often wrong; the scan decides.</p>
<p><b>Right</b>: the text matches the line. <b>Edit</b>: correct it (marks the line Fixed). <b>Bad line</b>: leave it out of training (bad crop, two lines in one, a heading). <b>Skip</b>: not sure. Marks are kept in this browser; <b>Export</b> saves them to a file (send it, or keep it for the training export). Keys: on a card, <b>r</b> Right, <b>e</b> Edit, <b>b</b> Bad, <b>s</b> Skip; <b>j</b>/<b>k</b> next/previous card.</p>
</div><div id="cards"></div></main>
<script>
const RUN=%(run)s, L=%(lines)s, FLAGS=%(flags)s, PRIOR=%(prior)s, RECHECK=%(recheck)s, MADE=%(made)s;
const KEY="jastrow-lines-"+RUN;
const id=r=>r.page+":"+r.rank;
const nz0=s=>(s||"").normalize("NFKD").replace(/[\u0591-\u05c7\u2066-\u2069\u200e\u200f]/g,"").replace(/\s+/g," ").replace(/ ([,.;:)])/g,"$1").trim();
let M=JSON.parse(localStorage.getItem(KEY)||"{}");
// marks exported before (linereview.py --marks): taken in where the browser has none, with the text they were made on
for(const x of PRIOR){const cid=x.page+":"+x.rank; if(!M[cid]){M[cid]={status:x.status, note:x.note, time:x.time, site:x.site}; if(x.text!=x.site) M[cid].text=x.text}
  else if(M[cid].site==null) M[cid].site=x.site}
// an edit that the new text now matches is no longer an edit
for(const r of L){const m=M[id(r)]; if(m&&m.text!=null&&nz0(m.text)==nz0(r.site)){delete m.text; m.status="ok"; m.site=r.site}}
let start=0, cur=0;
const esc=s=>s.replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const HEB=/[א-ת]/;
function wordsOf(s){return s.split(/\s+/).filter(w=>w.normalize("NFD").replace(/[֑-ׇ]/g,"").replace(/[^\p{L}\p{N}]/gu,""))}
function wspan(w,cls){return '<span'+(HEB.test(w)?' lang="he"':'')+(cls?' class="'+cls+'"':'')+'>'+esc(w)+'</span>'}
function marked(s,spans){  // the text with the given [start, end, class] stretches marked, the rest as it is
  let out="", at=0;
  for(const [a,b,c] of spans){out+=esc(s.slice(at,a))+wspan(s.slice(a,b),c); at=b}
  return out+esc(s.slice(at));
}
// Hebrew laid out as the site sets it (make_site2.py): each Hebrew phrase is one right-to-left island in the
// left-to-right line; a bracket is part of a phrase only when more Hebrew follows it; a comma list of single words
// runs left to right, the first word on the left. Plain text in the browser reversed both (the user, 5 Nov).
const HW="[\u05D0-\u05EA][\u0591-\u05C7\u05D0-\u05EA\u05F3\u05F4'\"\u2019*\u05BE-]*";
const HSEP="(?: +|, ?| *\\( *"+HW+"(?: +"+HW+")* *\\) *)";
const HPH=new RegExp(HW+"(?:"+HSEP+HW+")*","g");
function hebCls(s,spans){const c=new Array(s.length).fill(""); for(const [a,b,k] of spans) for(let i=a;i<b;i++) c[i]=k; return c}
function hebRun(s,c,a,b){let out="",i=a; while(i<b){let j=i; while(j<b&&c[j]==c[i]) j++; const t=esc(s.slice(i,j));
  out+=c[i]?'<span class="'+c[i]+'">'+t+'</span>':t; i=j} return out}
function heb(s,spans){const c=hebCls(s,spans); let out="",at=0; HPH.lastIndex=0; let m;
  while((m=HPH.exec(s))){const a=m.index,b=a+m[0].length; out+=hebRun(s,c,at,a);
    const parts=m[0].split(/(, ?)/);
    if(parts.length>1&&parts.every((p,k)=>k%%2||!/[ ()]/.test(p))){out+='<span class="hi" dir="ltr">'; let o=a;
      parts.forEach((p,k)=>{out+=k%%2?hebRun(s,c,o,o+p.length):'<span class="hi" dir="rtl" lang="he">'+hebRun(s,c,o,o+p.length)+'</span>'; o+=p.length}); out+='</span>'}
    else out+='<span class="hi" dir="rtl" lang="he">'+hebRun(s,c,a,b)+'</span>';
    at=b}
  return out+hebRun(s,c,at,s.length)}
// the edit box is plain text, which would set a comma list of Hebrew words right to left (the user typed
// several reversed, 5 Nov): a left-to-right mark after each comma of such a list keeps it as the book prints it;
// the marks are taken out again when the edit is kept
function lrmText(s){HPH.lastIndex=0; return s.replace(HPH,m=>{const parts=m.split(/(, ?)/);
  return parts.length>1&&parts.every((p,k)=>k%%2||!/[ ()]/.test(p))?parts.map((p,k)=>k%%2?p+"\u200E":p).join(""):m})}
function noMarks(s){return s.replace(/[\u200E\u200F\u2066-\u2069]/g,"")}
function siteHTML(r){return heb(r.site, r.sitew.map(([a,b,n])=>[a,b,n>=2?"d2":"d1"]))}
function showPrev(el){const p=el.querySelector(".prev"); p.innerHTML='<b>shown as</b> '+heb(noMarks(el.querySelector(".edit").value),[])}
function readerHTML(r,rd){
  const t=r.readers[rd]; if(!t.trim()) return "";
  return '<div class="rd"><b>'+rd+'</b><span>'+marked(t, r.marks[rd].rspans.map(([a,b])=>[a,b,"x"]))+'</span></div>';
}
function disagree(r){return r.sitew.length>0||r.extra.length>0}
const nz=s=>(s||"").normalize("NFKD").replace(/[\u0591-\u05c7\u2066-\u2069\u200e\u200f]/g,"").replace(/\s+/g," ").replace(/ ([,.;:)])/g,"$1").trim();
// "check again": a mark made on text that has changed since, or a line Claude asked to redo (--recheck) not marked since this build
function again(r){const m=M[id(r)]; return changed(r)||(RECHECK.includes(id(r))&&!(m&&m.time&&m.time>MADE))}
function changed(r){const m=M[id(r)]; return !!(m&&m.status&&m.site!=null&&nz(m.site)!=nz(r.site))}
function visible(){const f=document.getElementById("filter").value;
  return L.filter(r=>f=="all"||(f=="open"&&!M[id(r)])||(f=="disagree"&&disagree(r))||(f=="flag"&&(r.flags.length||changed(r)))||(f=="again"&&again(r)))}
function card(r){
  const m=M[id(r)]||{}, st=m.status||"";
  const flags=r.flags.map(f=>'<span class="flag">'+esc(FLAGS[f]||f)+'</span>').join("");
  const shown=m.text!=null?m.text:r.site;
  const agree=!disagree(r)?'<div class="agree">all readers agree with the site</div>':"";
  return `<div class="card ${st}" data-id="${id(r)}" tabindex="0">
   <div class="meta"><span>p. ${r.page}, ${r.col=="L"?"left":"right"} column, line ${r.rank+1}</span><span>${r.eids.join(", ")}</span>
   <a href="https://menachemshapiro.github.io/Jastrow-Book/#p${r.page}" target="_blank">site page</a></div>
   <img class="scan" src="${r.img}" loading="lazy">
   <div class="txt">${m.text!=null?wordsOf(shown).length?heb(shown,[]):"":siteHTML(r)}</div>
   <input class="edit" dir="ltr" style="display:none" value="${esc(lrmText(shown))}"><div class="prev" style="display:none"></div>
   ${flags?"<div>"+flags+"</div>":""}${changed(r)?'<span class="flag chg">our text for this line changed since you marked it: check again</span>':""}
   ${r.extra.length?'<div class="miss">two readers or more also see, not in our text: <b>'+r.extra.map(w=>wspan(w,"")).join(", ")+'</b></div>':""}${agree}
   ${["tesseract","pdf","kraken"].map(rd=>readerHTML(r,rd)).join("")}
   <div class="btns"><button class="b-ok ${st=="ok"?"on":""}" data-s="ok">Right</button>
   <button class="b-fixed ${st=="fixed"?"on":""}" data-s="edit">Edit</button>
   <button class="b-bad ${st=="bad"?"on":""}" data-s="bad">Bad line</button>
   <button class="b-skip ${st=="skip"?"on":""}" data-s="skip">Skip</button>
   ${m.text!=null?'<button data-s="reset">Undo edit</button>':""}
   <input class="note" placeholder="note" value="${esc(m.note||"")}"></div></div>`;
}
function save(){localStorage.setItem(KEY,JSON.stringify(M)); count()}
function count(){const n=Object.values(M).filter(m=>m.status).length; document.getElementById("count").textContent=n+" of "+L.length+" lines marked"}
function render(){const V=visible(); if(start>=V.length) start=Math.max(0,V.length-20);
  document.getElementById("cards").innerHTML=V.slice(start,start+20).map(card).join("");
  document.getElementById("where").textContent=V.length?(start+1)+"–"+Math.min(V.length,start+20)+" of "+V.length:"none";
  count(); cur=0}
function rec(cid){return L.find(r=>id(r)==cid)}
function set(cid,st){const m=M[cid]||(M[cid]={}); m.status=st; m.site=rec(cid).site; m.time=new Date().toISOString(); save(); rerender(cid)}
function rerender(cid){const el=document.querySelector('.card[data-id="'+cid+'"]'); const r=rec(cid); const t=document.createElement("div"); t.innerHTML=card(r); el.replaceWith(t.firstElementChild)}
function startEdit(el){const inp=el.querySelector(".edit"); inp.style.display="block"; el.querySelector(".txt").style.display="none"; const p=el.querySelector(".prev"); p.style.display="block"; showPrev(el); inp.focus()}
document.addEventListener("input",e=>{if(e.target.classList.contains("edit")) showPrev(e.target.closest(".card"))});
document.addEventListener("click",e=>{const b=e.target.closest("button[data-s]"); if(!b) return; const el=b.closest(".card"), cid=el.dataset.id, s=b.dataset.s;
  if(s=="edit") return startEdit(el);
  if(s=="reset"){const m=M[cid]; delete m.text; if(m.status=="fixed") delete m.status; save(); return rerender(cid)}
  set(cid,s)});
document.addEventListener("change",e=>{const el=e.target.closest(".card"); if(!el) return; const cid=el.dataset.id, m=M[cid]||(M[cid]={});
  if(e.target.classList.contains("note")){m.note=e.target.value; save()}
  if(e.target.classList.contains("edit")){const v=noMarks(e.target.value).trim(); if(v!=rec(cid).site){m.text=v; m.status="fixed"} else {delete m.text}; m.time=new Date().toISOString(); save(); rerender(cid)}});
document.addEventListener("keydown",e=>{
  if(e.target.classList&&e.target.classList.contains("edit")&&e.key=="Enter"){e.target.blur(); return}
  if(e.target.tagName=="INPUT"||e.target.tagName=="SELECT") return;
  const cs=[...document.querySelectorAll(".card")]; if(!cs.length) return;
  const focus=i=>{cur=Math.max(0,Math.min(cs.length-1,i)); cs[cur].focus(); cs[cur].scrollIntoView({block:"center"})};
  const a=document.activeElement.closest&&document.activeElement.closest(".card"); if(a) cur=cs.indexOf(a);
  const cid=cs[cur].dataset.id;
  if(e.key=="j") focus(cur+1); else if(e.key=="k") focus(cur-1);
  else if(e.key=="r"){set(cid,"ok"); focusNext(cur)} else if(e.key=="b"){set(cid,"bad"); focusNext(cur)} else if(e.key=="s"){set(cid,"skip"); focusNext(cur)}
  else if(e.key=="e"){e.preventDefault(); startEdit(document.querySelectorAll(".card")[cur])}});
function focusNext(i){const cs=[...document.querySelectorAll(".card")]; const n=Math.min(cs.length-1,i+1); cur=n; cs[n].focus(); cs[n].scrollIntoView({block:"center"})}
document.getElementById("prev").onclick=()=>{start=Math.max(0,start-20); render(); scrollTo(0,0)};
document.getElementById("next").onclick=()=>{if(start+20<visible().length){start+=20; render(); scrollTo(0,0)}};
document.getElementById("filter").onchange=()=>{start=0; render()};
document.getElementById("export").onclick=()=>{
  const out={run:RUN, exported:new Date().toISOString(), lines:L.filter(r=>M[id(r)]&&M[id(r)].status).map(r=>{const m=M[id(r)];
    return {page:r.page, rank:r.rank, kid:r.kid, xml:r.xml, eids:r.eids, status:m.status, site:r.site, text:m.text!=null?m.text:r.site, note:m.note||"", time:m.time}})};
  const a=document.createElement("a"); a.href=URL.createObjectURL(new Blob([JSON.stringify(out,null,1)],{type:"application/json"}));
  a.download="jastrow-lines-"+RUN+"-"+new Date().toISOString().slice(0,16).replace(/[:T]/g,"")+".json"; a.click()};
document.getElementById("import").onchange=e=>{const f=e.target.files[0]; if(!f) return; f.text().then(t=>{const d=JSON.parse(t);
  for(const x of d.lines){const cid=x.page+":"+x.rank; M[cid]={status:x.status, note:x.note, time:x.time}; if(x.text!=x.site) M[cid].text=x.text}
  save(); render()})};
render();
</script></body></html>"""


def main():
    import audit as AU
    import compare as CO
    import ocrmodel as OM
    import report as RP
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], epilog=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pages", required=True)
    ap.add_argument("--site", default=os.environ.get("JASTROW_SITE") or ST.REPO)
    ap.add_argument("--out", default=os.path.join(paths.WORK, "audit"))
    ap.add_argument("--xml", default="kraken_mccatmus.xml", help="the PAGE XML's name in each page's folder")
    ap.add_argument("--name", help="the review's name (default: the pages)")
    ap.add_argument("--marks", nargs="*", default=[], help="exported marks (jastrow-lines-*.json) to carry over")
    ap.add_argument("--recheck", default="", help="lines to show under \"check again\", as page:rank,page:rank")
    args = ap.parse_args()
    site = os.path.abspath(os.path.expanduser(args.site))
    book = ST.Book(site)
    run = AU.parse_pages(args.pages, book)
    if not run: sys.exit("no pages")
    V = AU.vocab(site)
    mf = [os.path.join(args.out, "marks.json")] + sorted(glob.glob(os.path.expanduser("~/Downloads/jastrow-audit-marks*.json")))
    CO.CM, CO.HCM = OM.build(os.path.join(args.out, "pages"), RP.load_marks(mf))
    CO.CFG.update(reread3=False, stage4=False)
    CM[0] = CO.CM
    name = args.name or re.sub(r"[^\w-]+", "_", args.pages)
    od = os.path.join(args.out, "lines", name)
    img = os.path.join(od, "img")
    os.makedirs(img, exist_ok=True)
    recs = []
    for pid in run:
        recs += page_lines(pid, book, V, CO, args.out, img, args.xml)
    json.dump({"run": name, "made": time.strftime("%Y-%m-%d %H:%M"), "site": site, "lines": recs},
              open(os.path.join(od, "lines.json"), "w"), ensure_ascii=False, indent=0)
    prior = {}
    for f in args.marks:
        for x in json.load(open(os.path.expanduser(f)))["lines"]:
            prior[(x["page"], x["rank"])] = x                     # a later file wins
    prior = list(prior.values())
    page = PAGE % {"name": H.escape(name), "run": json.dumps(name), "lines": json.dumps(recs, ensure_ascii=False),
                   "flags": json.dumps(FLAG_TEXT), "prior": json.dumps(prior, ensure_ascii=False),
                   "recheck": json.dumps([x for x in args.recheck.split(",") if x]),
                   "made": json.dumps(time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()))}
    open(os.path.join(od, "index.html"), "w").write(page)
    dis = sum(1 for r in recs if any(m["site"] for m in r["marks"].values()))
    print("%d lines; %d where a reader differs from the site; %d flagged.\n%s" % (
        len(recs), dis, sum(1 for r in recs if r["flags"]), os.path.join(od, "index.html")))


if __name__ == "__main__":
    main()
