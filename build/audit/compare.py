"""Compare one page of the site with the OCR of the 1903 scan.

The page's text is aligned word for word with the scan, in reading order (segment by segment, left column then right
column), after joining words hyphenated at the end of a line. The alignment runs over the whole page, so an entry that
runs from one column into the next is compared as one piece; its parts in each column are recorded for the report.

Each scan word is first given a script: Hebrew if the Hebrew OCR reads that spot with more confidence than the
English OCR does. Latin words are aligned directly; Hebrew is compared stretch by stretch, in the order the book
prints it (right to left within a phrase; left to right in a list of forms)."""
import difflib, os, re, subprocess
from collections import Counter

import sitetext as ST

CFG = {
    "heb_margin": 8,          # Hebrew OCR must beat the English OCR's confidence by this much for a word to be Hebrew
    "real_conf": 75,          # an English scan word this confident, and in the book's vocabulary, is real text
    "verify": True,           # re-read a differing word at double size before reporting it
    "heb_fuzzy": 0.75,        # two Hebrew words (letters only) this similar are the same word
    "heb_differs": 0.55,      # a Hebrew stretch less similar than this is reported
    "count_conf": 55,         # an English OCR word this confident counts in the word count check
    "count_left": 2,          # an entry with this many real words left over, and no finding, is reported (word_count)
    "heb_loose": 0.5,         # an unpaired site word this like an unpaired scan word is "read poorly", not "differs"
    "heb_order_sim": 0.85,    # Hebrew order is checked only on words read this close to the site's ...
    "heb_order_conf": 60,     # ... and at least this confidently
    "heb_short_conf": 85,     # a two-letter Hebrew scan word left over counts only if read this confidently
    "indent": 0.45,           # a line starting this many line pitches in from its column's edge is indented
    "entry_lines": "indent",  # how an entry's first line sits in the book: indented (Jastrow), or "flush"
}

HYPH = re.compile(r"^(.*[A-Za-zÀ-ž])[-‐‑¬~]$")


def area(b): return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


def overlap(a, b):
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    return area([x0, y0, x1, y1])


def union(boxes):
    boxes = [b for b in boxes if b]
    if not boxes: return None
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def ratio(a, b): return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def ocr_shape(k):
    """a key with the letters OCR confuses made the same (l/1/I/i, O/0, rn/m, vv/w, ae/ee/e)"""
    k = k.lstrip("#")
    k = re.sub(r"[1il|]", "l", k).replace("0", "o").replace("rn", "m").replace("vv", "w")
    k = k.replace("ae", "e").replace("ee", "e").replace("oe", "e")
    k = k.replace("c", "e").replace("y", "v")                # acc./ace., cmp./emp., Prov./Proy.
    return k


def plain_shape(x):
    """letters and digits only, with the OCR's usual confusions made the same: two readings that differ only in
    spacing or punctuation ("s. 19" / "s.19", "R. s." / "R.s.") come out equal"""
    return ocr_shape(re.sub(r"[^0-9a-z]", "", x.lower()))


ROMAN = re.compile(r"^[\[(—-]*[IVXLC]+[\]),.;:]*$")
ROMAN_OCR = re.compile(r"^[\[(—-]*[IVXLCUHTEKYlif1|!tJ]+[\]),.;:]*$")
HEB_CONF = str.maketrans("כפחתזירדןךמסםנצף", "בבההווווווטטטגעק")   # Hebrew letters the OCR confuses


def one_letter(a, b):
    """the same length, and one letter different"""
    return len(a) == len(b) >= 2 and sum(x != y for x, y in zip(a, b)) == 1


def heb_look(skel):
    """a Hebrew word as the OCR might read it either way: confusable letters made the same, and ו/י left out (a
    holam, shuruk or hiriq is often read as one)"""
    return re.sub("[וי]", "", skel).translate(HEB_CONF)


class PageCompare:
    def __init__(self, page, scan, vocab, workdir):
        self.p = page
        self.s = scan
        self.vocab = vocab
        self.wd = os.path.join(workdir, "pages", "p%04d" % int(page.pid))
        self.f = []                                 # findings
        lay = scan["layout"]
        # the line pitch (scan.py, layout version 2); for a page laid out before that, from the OCR's lines
        self.lineh = lay["lineh"] if lay.get("version", 1) >= 2 else self.pitch_from_lines(scan["ocr"]["lines"], lay.get("lineh", 30))
        self.lines = scan["ocr"]["lines"]
        self.heb = scan["ocr"]["heb"]
        self._scan_tokens()
        self._align()

    @staticmethod
    def pitch_from_lines(lines, default):
        """the median distance between the tops of consecutive lines in a column"""
        import statistics as stt
        d, by = [], {}
        for ln in lines: by.setdefault((ln["seg"], ln["col"]), []).append(ln["box"][1])
        for ys in by.values():
            ys = sorted(ys)
            d += [b - a for a, b in zip(ys, ys[1:]) if b - a > 5]
        if len(d) < 5: return default
        m = stt.median(d)
        d = [x for x in d if 0.6 * m < x < 1.6 * m]
        return float(stt.median(d)) if d else default

    # ---------- scan words ----------
    def _scan_tokens(self):
        # a printer's signature at the foot of a column (p. 1669: "210"): its last line, a short number only
        last, sig = {}, set()
        for ln in self.lines: last[(ln["seg"], ln["col"])] = max(last.get((ln["seg"], ln["col"]), -1), ln["i"])
        nseg = max([ln["seg"] for ln in self.lines] or [0])
        for (sg, col), li in last.items():
            ws = [t for t in self.s["ocr"]["tokens"] if t["line"] == li]
            if sg == nseg and ws and len(ws) <= 2 and all(re.fullmatch(r"[\d*]{1,4}[.,]?", t["text"]) for t in ws):
                sig.add(li)
        self.signature_lines = sig
        raw = []
        for t in self.s["ocr"]["tokens"]:
            if t["line"] in sig: continue
            # split "storage.—Pl." before the dash, as on the site side; the box is shared out by letters
            parts = [q for q in re.split(r"(?<=[^\s\u2014])(?=\u2014)", t["text"]) if q]
            if len(parts) == 1:
                raw.append(t); continue
            b = t["box"]; n = len(t["text"]); x = b[0]
            for q_i, q in enumerate(parts):
                w = (b[2] - b[0]) * len(q) / n
                u = dict(t); u["text"] = q; u["box"] = [int(x), b[1], int(x + w), b[3]]
                u["first"] = t["first"] and q_i == 0; u["last"] = t["last"] and q_i == len(parts) - 1
                raw.append(u); x += w
        toks = []
        i = 0
        while i < len(raw):
            t = dict(raw[i]); t["boxes"] = [t["box"]]; t["lines"] = [t["line"]]; t["hyph"] = False
            m = HYPH.match(t["text"])
            if m and t["last"]:
                if i + 1 < len(raw) and raw[i + 1]["first"] and re.match(r"[a-zà-ž]", raw[i + 1]["text"]):
                    n = raw[i + 1]
                    t["raw"] = t["text"] + " " + n["text"]
                    t["text"] = m.group(1) + n["text"]
                    t["boxes"].append(n["box"]); t["lines"].append(n["line"])
                    t["conf"] = min(t["conf"], n["conf"]); t["hyph"] = True
                    t["last"] = n["last"]
                    i += 1
                elif i + 1 == len(raw):
                    t["page_end_hyph"] = True
            toks.append(t)
            i += 1
        # script: compare with the Hebrew OCR at the same place
        for t in toks:
            hc, ht = -1, ""
            for w in self.heb:
                b = w["box"]
                if overlap(b, t["box"]) > 0.5 * min(area(b), area(t["box"])) and re.search("[א-ת]", w["text"]):
                    if w["conf"] > hc: hc, ht = w["conf"], w["text"]
            t["heb_conf"], t["heb_text"] = hc, ht
            t["script"] = "heb" if hc > t["conf"] + CFG["heb_margin"] else "lat"
            t["key"] = ST.key(t["text"]) if t["script"] == "lat" else ""
        for k, t in enumerate(toks): t["j"] = k
        self.k = toks

    def real(self, t):
        """a scan word that is surely English text: confident, in the book's vocabulary, and not a spot where the
        Hebrew OCR also reads Hebrew (short words like "an", "on" are what Hebrew often comes out as)"""
        if t["script"] != "lat" or t["conf"] < CFG["real_conf"] or len(t["key"]) < 2: return False
        if not (t["key"] in self.vocab or t["key"].startswith("#")): return False
        if t["heb_conf"] >= 50 and not (len(t["key"]) >= 4 and t["conf"] >= 90): return False
        return True

    # ---------- alignment ----------
    def _align(self):
        P = self.p
        self.S = [t for t in P.tokens if not t["h2"] and (t["heb"] or t["key"])]
        self.K = [t for t in self.k if t["key"]]                    # Latin scan words
        a = [t["key"] if not t["heb"] else "\x00" for t in self.S]
        b = [t["key"] for t in self.K]
        ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
        # a lone match of a one- or two-letter word inside a gap is chance; fold it into the gap
        cl = []
        for op in ops:
            tag, i1, i2, j1, j2 = op
            if tag == "equal" and i2 - i1 == 1 and len(a[i1]) <= 2 and not a[i1].startswith("#"):
                tag = "replace"
            if cl and tag != "equal" and cl[-1][0] != "equal":
                cl[-1] = ("replace", cl[-1][1], i2, cl[-1][3], j2)
            else:
                cl.append((tag, i1, i2, j1, j2))
        self.ops = cl
        self.s2k = {}                                              # site token "i" -> scan token "j"
        for tag, i1, i2, j1, j2 in cl:
            if tag == "equal":
                for d in range(i2 - i1): self.s2k[self.S[i1 + d]["i"]] = self.K[j1 + d]["j"]
        lat = [t for t in self.S if not t["heb"]]
        self.stats = {"site_words": len(lat), "matched": sum(1 for t in lat if t["i"] in self.s2k),
                      "scan_words": len(self.K), "scan_tokens": len(self.k)}
        self.stats["match_rate"] = round(self.stats["matched"] / max(1, len(lat)), 3)

    def scan_between(self, i1, i2, j1, j2):
        """all scan tokens (Latin and Hebrew) between the anchors of a gap"""
        lo = self.K[j1 - 1]["j"] + 1 if j1 > 0 else 0
        hi = self.K[j2]["j"] if j2 < len(self.K) else len(self.k)
        return self.k[lo:hi], (self.K[j1 - 1] if j1 > 0 else None), (self.K[j2] if j2 < len(self.K) else None)

    # ---------- findings ----------
    def add(self, typ, sev, site_toks, scan_toks, note="", **kw):
        st = [t for t in site_toks]
        eid = st[0]["eid"] if st else None
        lines = sorted({l for t in scan_toks for l in t.get("lines", [t.get("line")]) if l is not None})
        rec = {"page": self.p.pid, "type": typ, "sev": sev, "eid": eid,
               "site": " ".join(t["text"] for t in st), "scan": " ".join(t.get("raw", t["text"]) for t in scan_toks),
               "note": note, "lines": lines, "boxes": [b for t in scan_toks for b in t.get("boxes", [t.get("box")])],
               "off": st[0]["off"] if st else None, "end": st[-1]["end"] if st else None}
        rec.update(kw)
        if rec["eid"] is None and rec["off"] is not None:
            rec["eid"] = self.eid_at(rec["off"])
        if rec["eid"] is None and scan_toks:
            rec["eid"] = self.eid_for_scan(scan_toks[0].get("j", 0))
        if rec["off"] is None and scan_toks and "j" in scan_toks[-1]:
            # nothing on the site to point at (words the site lacks): mark the place where they would go, right
            # after the last word before them that the site and the scan share (else before the next one)
            prev = self.site_before_scan(scan_toks[0]["j"])
            at = self.site_after_scan(scan_toks[-1]["j"])
            if prev is not None:
                rec["off"] = rec["end"] = prev["end"]
                if rec["eid"] is None: rec["eid"] = prev["eid"]
            elif at is not None:
                rec["off"] = rec["end"] = at["off"]
                if rec["eid"] is None: rec["eid"] = at["eid"]
        self.f.append(rec)

    def site_before_scan(self, j):
        """the last site token matched before scan token j"""
        best = None
        for si, kj in self.s2k.items():
            if kj < j and (best is None or kj > best[1]): best = (si, kj)
        if best is None: return None
        return next(t for t in self.p.tokens if t["i"] == best[0])

    def site_after_scan(self, j):
        """the first site token matched after scan token j (where text missing from the site would go)"""
        best = None
        for si, kj in self.s2k.items():
            if kj > j and (best is None or kj < best[1]): best = (si, kj)
        if best is None: return None
        return next(t for t in self.p.tokens if t["i"] == best[0])

    def eid_for_scan(self, j):
        """the entry of the last site word matched at or before scan token j"""
        best = None
        for si, kj in self.s2k.items():
            if kj <= j and (best is None or kj > best[1]): best = (si, kj)
        if best is None: return None
        t = next(t for t in self.p.tokens if t["i"] == best[0])
        return t["eid"]

    def eid_at(self, off):
        e = None
        for t in self.p.tokens:
            if t["off"] > off: break
            e = t["eid"]
        return e

    def verify(self, t):
        """read one scan word again, at double size, as a single word"""
        if not CFG["verify"]: return None
        try:
            from PIL import Image
            img = Image.open(os.path.join(self.wd, "page.png"))
            reads = []
            for k, b in enumerate(t["boxes"]):
                pad = 4
                c = img.crop((b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad))
                c = c.resize((c.width * 2, c.height * 2), Image.LANCZOS)
                name = os.path.join(self.wd, "verify.png")
                c.save(name)
                r = subprocess.run(["tesseract", name, "stdout", "-l", "eng", "--psm", "8", "--dpi", "600"],
                                   capture_output=True, text=True)
                reads.append(r.stdout.strip())
            txt = "".join(re.sub(r"[-¬]$", "", x) if k < len(reads) - 1 else x for k, x in enumerate(reads))
            return txt
        except Exception as e:
            return None

    def run(self):
        self.check_gaps()
        self.check_pairs()
        self.check_breaks()
        self.check_header()
        self.check_scan()
        self.map_entries()
        self.check_structure()
        self.check_counts()
        return self.f

    # ---------- word counts ----------
    def check_counts(self):
        """each entry's English words, the site's against the book's. The word-by-word comparison accounts for every
        difference, but drops some as OCR noise without a finding (next to Hebrew, short words, unsure readings).
        Here those dropped differences are added up per entry: an entry where real words of the book are left over
        with nothing to explain them is reported, so that missing or extra words can't hide among the noise"""
        site_n, book_n = Counter(), Counter()
        for t in self.S:
            if not t["heb"] and t["eid"]: site_n[t["eid"]] += 1
        tok = {t["i"]: t for t in self.S}
        for si in self.s2k:
            if tok[si]["eid"]: book_n[tok[si]["eid"]] += 1
        def gap_eid(S, prev):
            return next((t["eid"] for t in S if t["eid"]), None) or (self.eid_for_scan(prev["j"]) if prev else None)
        for S, between, prev in self.gaps:
            e = gap_eid(S, prev)
            if e: book_n[e] += len([t for t in between if t["script"] == "lat" and t["key"]])
        left = {}                              # eid -> [book words left over], [site words left over], gaps
        for S, between, prev in self.silent:
            eid = gap_eid(S, prev)
            if not eid: continue
            # looser than real(): a word-shaped English reading the comparison was unsure of still counts
            K = [t for t in between if t["script"] == "lat" and len(t["key"]) >= 3 and not t["key"].startswith("#")
                 and t["conf"] >= CFG["count_conf"] and re.fullmatch(r"[\[(]*[A-Za-zÀ-žḤḥ’'.,;:)\]-]+", t["text"])
                 and t["heb_conf"] < max(50, t["conf"]) and self.vocab.get(t["key"], 0) >= 2]
            # Roman numerals and folio numbers are often misread or lost next to Hebrew: they are left to the
            # number checks
            Sl = [t for t in S if not t["heb"] and t["key"] and len(t["key"].lstrip("#")) >= 3
                  and not t["key"].startswith("#") and not ROMAN.match(t["text"].lstrip("—"))]
            # a pair the comparison let pass as one word read two ways is no count difference
            ks = [t for t in K if not any(ratio(ocr_shape(t["key"]), ocr_shape(x["key"])) >= 0.7 for x in Sl)]
            ss = [t for t in Sl if not any(ratio(ocr_shape(t["key"]), ocr_shape(x["key"])) >= 0.7 for x in K)
                  and not any(ocr_shape(t["key"]) in ocr_shape(x["key"]) for x in between if x["key"])]
            if not ks and not ss: continue
            d = left.setdefault(eid, [[], [], [], []])
            d[0] += ks; d[1] += ss; d[2].append(between); d[3].append(any(t["heb"] for t in S) or
                                                                    any(t["script"] == "heb" for t in between))
        self.stats["count_entries"] = len(site_n)
        self.stats["count_flagged"] = 0
        for eid, (ks, ss, gaps, heb) in left.items():
            if len(ks) + len(ss) < CFG["count_left"]: continue
            self.stats["count_flagged"] += 1
            causes = []
            if any(heb): causes.append("next to Hebrew (the OCR may have read Hebrew as English, or lost a short word)")
            if ks and not ss: causes.append("words in the book that the site lacks: missing on the site, or run "
                                            "together with a neighbour")
            if ss and not ks: causes.append("site words not in the book: extra or doubled on the site, or the OCR "
                                            "lost them")
            if ks and ss: causes.append("words differ: a misreading on either side")
            site_t = [t for t in self.S if t["eid"] == eid]
            sev = 2 if len(ks) + len(ss) >= 3 and not all(heb) else 3
            self.add("word_count", sev, site_t[:1], [t for g in gaps for t in g],
                     "the site has %d English words in this entry, the book about %d. Left over after the word-by-word "
                     "comparison, with no other finding: %s%s%s. Likely: %s" % (
                         site_n[eid], book_n[eid],
                         ("in the book only: " + " ".join(t["text"] for t in ks)) if ks else "",
                         "; " if ks and ss else "",
                         ("on the site only: " + " ".join(t["text"] for t in ss)) if ss else "",
                         "; ".join(causes)), eid=eid,
                     book_words=" ".join(t["text"] for t in ks), site_words=" ".join(t["text"] for t in ss))

    def check_pairs(self):
        for tag, i1, i2, j1, j2 in self.ops:
            if tag != "equal": continue
            for d in range(i2 - i1):
                s, k = self.S[i1 + d], self.K[j1 + d]
                # a folio side the OCR read clearly ("26b") that differs from the site's
                m = re.match(r"^(\d+)([a-d])\W*$", k["text"])
                if s["side"] and m and m.group(2) != s["side"] and k["conf"] >= 80:
                    v = self.verify(k)
                    if v and re.match(r"^\d+%s" % s["side"], v): continue
                    self.add("folio_side", 2, [s], [k], "the site has %s, the scan seems to read %s" % (s["text"], k["text"]),
                             reread=v)
                # rule 2.8: a word the book breaks at a line's end is one word; the site should not keep the hyphen
                if k["hyph"] and "-" in s["text"] and not re.search(r"-\s*$", k["raw"].split()[-1]):
                    self.add("hyphen_kept", 3, [s], [k], "line-end hyphen in the book; the site has '%s' (a compound, or a hyphen to drop?)" % s["text"])

    def check_gaps(self):
        n = len(self.ops)
        self.silent = []                      # gaps that differ but gave no finding: for the word count check
        self.gaps = []                        # every gap, for the book's word count per entry
        for oi, (tag, i1, i2, j1, j2) in enumerate(self.ops):
            if tag == "equal": continue
            S = self.S[i1:i2]
            between, prev, nxt = self.scan_between(i1, i2, j1, j2)
            n0 = len(self.f)
            self.gaps.append((S, between, prev))
            self._gap(oi, n, S, between, prev, nxt)
            new = self.f[n0:]
            # nothing reported, or only minor notes and "not checked": the stretch's English is still unaccounted for
            if all(x["sev"] == 3 or x["type"].endswith("_unread") for x in new):
                told = {w for x in new for w in (x.get("scan") or "").split()}
                told_s = {w for x in new for w in (x.get("site") or "").split()}
                self.silent.append(([t for t in S if t["text"] not in told_s],
                                    [t for t in between if t.get("raw", t["text"]) not in told], prev))

    def _gap(self, oi, n, S, between, prev, nxt):
        if True:
            if oi == 0 or oi == n - 1:
                if self.edge_gap(oi == 0, S, between): return
            Sh = [t for t in S if t["heb"]]
            if Sh or any(t["script"] == "heb" for t in between):
                self.hebrew(S, between, prev, nxt)
                Slat = [t for t in S if not t["heb"]]
                Klat = [t for t in between if t["script"] == "lat" and t["key"] and
                        (self.real(t) or (t["conf"] >= 60 and t["heb_conf"] < 50))]
                if Slat or Klat:
                    self.latin_sub(Slat, Klat)
            else:
                self.latin(S, [t for t in between if t["key"]])

    def latin_sub(self, S, K):
        """the Latin words of a gap that also has Hebrew: align them on their own"""
        ops = difflib.SequenceMatcher(None, [t["key"] for t in S], [t["key"] for t in K], autojunk=False).get_opcodes()
        for tag, i1, i2, j1, j2 in ops:
            if tag != "equal": self.latin(S[i1:i2], K[j1:j2], mixed=True)

    def latin(self, S, K, mixed=False):
        if not S and not K: return
        sj, kj = "".join(t["key"] for t in S), "".join(t["key"] for t in K)
        if S and K and sj == kj:
            # one piece of a letter or two is often the OCR's doing ("I m." read as "Im."): lower confidence
            short = min(len(t["key"]) for t in (S if len(S) > len(K) else K)) <= 2
            if len(S) < len(K):
                # the book's pieces on two lines: a word divided at a line's end, whatever the OCR made of the
                # hyphen ("sur: rounding", "wea- ‘vers"); rule 2.8, not a finding
                if any(K[i]["lines"][-1] != K[i + 1]["lines"][0] for i in range(len(K) - 1)): return
                # or the OCR put a space after a hyphen, or read a hyphen as ":" ("bed- cover", "meeting- -place",
                # "sur: rounding"): the book's word is the site's
                if all(re.search(r"[-‐‑¬~:‘’]$", K[i]["text"]) or re.match(r"^[-‐‑]", K[i + 1]["text"])
                       for i in range(len(K) - 1)): return
                # an abbreviation the site sets without its space ("i.e." for "i. e.")
                abbr = len(S) == 1 and re.search(r"[.’'][A-Za-z]", S[0]["text"])
                self.add("run_on", 3 if abbr else (2 if short else 1), S, K,
                         ("the site sets an abbreviation without the book's space" if abbr else
                          "the site runs together what the book prints as %d words" % len(K)) +
                         (" (check: a short piece)" if short and not abbr else ""))
            elif len(S) > len(K):
                hy = any(t["hyph"] for t in K)
                # the OCR often loses a space in a tight line ("thealphabet", "R.s.", "field.cannot"): a real
                # word the site split is one the book uses whole elsewhere
                joined_known = self.vocab.get(kj, 0) >= 2
                lost = not hy and (not joined_known or any(re.search(r"[.,;:’')\-][^\s]", t["text"]) for t in K))
                self.add("split_word", 3 if lost else (2 if short else 1), S, K,
                         "the site splits a word the book prints whole" +
                         (" (hyphenated at a line's end in the book)" if hy else "") +
                         (" (probably the OCR missing a space)" if lost else
                          " (check: the OCR may have run them together)" if short else ""))
            return
        if S and K and plain_shape(" ".join(t["text"] for t in S)) == plain_shape(" ".join(t["text"] for t in K)):
            return                                             # the same, but for the OCR's spacing and punctuation
        if mixed:
            # next to Hebrew, short words (m., v., I, II, f.) are often read as Hebrew or lost; report only longer
            # words, and numbers the scan does not have anywhere in the gap
            gapnums = set(re.findall(r"\d+", " ".join(t["text"] for t in K)))
            S = [t for t in S if len(t["key"]) >= 3 and not t["key"].startswith("#") or
                 (re.search(r"\d", t["text"]) and not set(re.findall(r"\d+", t["text"])) <= gapnums)]
            if not S and not [t for t in K if self.real(t) and len(t["key"]) >= 3]: return
        if not K:
            if len(S) == 1 and len(S[0]["key"]) <= 1: return
            prev = self.p.plain[max(0, S[0]["off"] - 400):S[0]["off"]]
            txt = self.p.plain[S[0]["off"]:S[-1]["end"]]
            doubled = len(txt) > 12 and txt in prev
            self.add("doubled" if doubled else "not_in_scan", 1 if doubled else (3 if mixed and len(S) <= 2 else 2), S, [],
                     "the same words come just before" if doubled else
                     ("site words the scan's OCR does not have here" + (" (next to Hebrew)" if mixed else "")))
            return
        if not S:
            real = [t for t in K if self.real(t)]
            if real:
                self.add("missing_in_site", 1 if len(real) >= 2 else (3 if len(real[0]["key"]) <= 3 else 2), [], K,
                         "words in the book that the site does not have here", off=None)
            return
        if len(S) == len(K):
            for s, k in zip(S, K):
                if s["key"] == k["key"]: continue
                num = s["key"].startswith("#") or k["key"].startswith("#") or re.search(r"\d", s["text"] + k["text"])
                if not num and (k["conf"] < 50 or len(k["key"]) < 2): continue
                # letters the OCR confuses, in a word the site uses often: the OCR's error, not the site's
                if ocr_shape(s["key"]) == ocr_shape(k["key"]) and self.vocab.get(s["key"], 0) >= 3 and \
                        not re.search(r"\d", s["text"]): continue
                v = self.verify(k)
                if v is not None and ST.key(v) == s["key"]: continue        # the second reading agrees with the site
                typ, sev, note = ("number_differs" if num else "word_differs"), (1 if num else 2), ""
                sd, kd = re.search(r"\d", s["text"]), re.search(r"\d", k["text"])
                if num and self.ocr_misread_number(s["text"], k["text"], v):
                    sev, note = 3, "most likely the OCR misreading the book (a raised folio letter or a stop read as a digit, or a digit as a letter)"
                elif num and v is not None and re.search(r"\d", s["text"]) and not re.search(r"\d", v):
                    # read again, the OCR finds no digit at all: it cannot read this spot
                    sev, note = 3, "the OCR cannot read this number (read again: %s)" % (v or "nothing")
                elif num and not (sd and kd):
                    # a number on one side only: mostly the alignment next to Hebrew, or a letter read as a digit
                    common = self.vocab.get(s["key"], 0) >= 20
                    sev = 3 if (mixed or common) else 2
                    if common and kd: note = "the site's %s is a common abbreviation (as in D. S.); the OCR read digits" % s["text"]
                elif ROMAN.match(s["text"]) and ROMAN_OCR.match(k["text"]) and not ROMAN.match(k["text"]):
                    sev, note = 3, "a Roman numeral the OCR misread"
                elif self.ib_named(s, k):
                    typ, sev = "ib_named", 1
                    note = "the book has “Ib.” here; the site names the work (%s): Sefaria's expansion?" % s["text"]
                elif self.abbr_spelling(s, k):
                    typ, sev = "abbreviation", 2
                    note = "the site writes “%s”, the book “%s”" % (s["text"].strip("—"), k["text"].strip("—"))
                self.add(typ, sev, [s], [k], note, reread=v, ratio=round(ratio(s["key"], k["key"]), 2))
            return
        real = [t for t in K if self.real(t)]
        if not real and len(S) <= 1: return
        if self.ib_named(S[0], K[0]):
            self.add("ib_named", 1, S, K, "the book has “Ib.” here; the site names the work (%s): Sefaria's expansion?"
                     % " ".join(t["text"] for t in S[:3]))
            return
        self.add("differs", 2, S, K, "the site and the scan differ here" + (" (next to Hebrew)" if mixed else ""))

    @staticmethod
    def ib_named(s, k):
        """the book prints "Ib." where the site names a work ("Gen.", "Snh.")"""
        return k["key"] == "ib" and s["key"] != "ib" and re.match(r"^[—\[(]*[A-Z][a-z]*\.", s["text"]) is not None

    @staticmethod
    def abbr_spelling(s, k):
        """the same abbreviation spelt with a letter more or less ("Kidd." / "Kid.", "Nidd." / "Nid.")"""
        a, b = s["key"], k["key"]
        if not (s["text"].rstrip(";,)").endswith(".") and k["text"].rstrip(";,)").endswith(".")): return False
        if abs(len(a) - len(b)) != 1 or min(len(a), len(b)) < 2: return False
        lo, hi = sorted((a, b), key=len)
        return hi.startswith(lo) and hi[-1] == lo[-1]

    @staticmethod
    def ocr_misread_number(site, scan, reread=None):
        """the site has a folio number with its side (39ᵇ) and the OCR one digit more, the rest the same but for at
        most one digit (895, 444): the small raised letter read as a digit"""
        # the OCR read a digit as a letter (S for 5 or 8, g for 9, O for 0, l for 1) where the site has the digits;
        # two different digits are never the same
        a0, b0 = re.sub(r"[^\w]", "", site), re.sub(r"[^\w]", "", scan)
        for conf in (str.maketrans("SsBgqOoIliZ", "55899001112"), str.maketrans("SsBgqOoIliZ", "88899001112")):
            # only when the site has the digits: a site letter where the book has a digit may be the site's error
            if a0.isdigit() and a0 != b0 and a0 == b0.translate(conf): return True
        for sc in [scan] + ([reread] if reread else []):
            # a stop after the number read as a digit: "5;" as 53 or 55
            m2 = re.match(r"^\D*?(\d+)[;,:]$", site)
            if m2 and re.fullmatch(re.escape(m2.group(1)) + r"[35]", sc.strip().rstrip(";,.")): return True
            # one of two like digits lost: 111ᵃ read as 11ᵃ
            sd, kd = re.sub(r"\D", "", site), re.sub(r"\D", "", sc)
            if kd and len(sd) == len(kd) + 1 and any(sd[i] == sd[i + 1] and sd[:i] + sd[i + 1:] == kd for i in range(len(sd) - 1)):
                return True
        m = re.match(r"^\D*?(\d+)\s*\^?([a-dᵃᵇᶜᵈ])", site)
        if not m: return False
        a = m.group(1)
        d = re.sub(r"\D", "", scan)
        raised = re.search(r"\d[°¢%®*'’\"”^>]+[;:,.)]*$", scan)   # the letter read as a symbol: 83°, 35¢, 89>
        if len(d) == len(a) + 1: b = d[:len(a)]
        elif len(d) == len(a) and raised: b = d
        else: return False
        return sum(x != y for x, y in zip(a, b)) <= (1 if len(a) >= 2 else 0)

    # ---------- Hebrew ----------
    def region(self, prev, nxt, between):
        """the parts of lines between two anchor words: [(line index, x0, x1)]"""
        out = []
        L = {ln["i"]: ln for ln in self.lines}
        if prev is not None and nxt is not None:
            l0, l1 = prev["lines"][-1], nxt["lines"][0]
            x_after = prev["boxes"][-1][2]; x_before = nxt["boxes"][0][0]
        else:
            ls = sorted({l for t in between for l in t["lines"]})
            if not ls: return out
            l0, l1 = ls[0], ls[-1]
            x_after, x_before = -1, 10 ** 9
            if prev is not None: l0, x_after = prev["lines"][-1], prev["boxes"][-1][2]
            if nxt is not None: l1, x_before = nxt["lines"][0], nxt["boxes"][0][0]
        for li in range(l0, l1 + 1):
            if li not in L: continue
            cb = L[li]["colbox"]
            a = x_after if li == l0 else cb[0] - 10
            b = x_before if li == l1 else cb[2] + 10
            if a < b: out.append((li, a, b))
        return out

    def scan_hebrew(self, reg, between):
        """the Hebrew OCR's words in a region, each with its line and position, leaving out any that sit on a
        confidently read Latin word"""
        L = {ln["i"]: ln for ln in self.lines}
        lat = [t for t in between if t["script"] == "lat" and self.real(t)]
        out = []
        for li, a, b in reg:
            lb = L[li]["box"]
            for w in self.heb:
                cx, cy = (w["box"][0] + w["box"][2]) / 2, (w["box"][1] + w["box"][3]) / 2
                if not (a <= cx <= b and lb[1] - 0.3 * self.lineh <= cy <= lb[3] + 0.3 * self.lineh): continue
                sk = ST.heb_skel(w["text"])
                if not sk: continue
                if any(overlap(w["box"], t["box"]) > 0.5 * area(w["box"]) for t in lat): continue
                out.append({"text": w["text"], "skel": sk, "conf": w["conf"], "line": li, "x": cx, "box": w["box"]})
        out.sort(key=lambda w: (w["line"], w["x"]))
        return out

    def hebrew(self, S, between, prev, nxt):
        """compare the Hebrew of a gap: the same words, and in the same left-to-right order on each line as the
        site shows them (each Hebrew span is a right-to-left island; islands follow each other left to right)"""
        from functools import cmp_to_key
        sh = [t for t in S if t["heb"] and t["skel"]]
        reg = self.region(prev, nxt, between)
        ks = self.scan_hebrew(reg, between)
        if not sh and not ks: return
        self.stats["heb_regions"] = self.stats.get("heb_regions", 0) + 1
        typ = "headword" if any(t["hw"] for t in sh) else "hebrew"
        rec = dict(boxes=[w["box"] for w in ks] or [b for t in between for b in t["boxes"]],
                   lines=sorted({li for li, a, b in reg}))
        # pair each site word with the most similar scan word, best pairs first
        cands = sorted(((ratio(t["skel"], w["skel"]), si, kj) for si, t in enumerate(sh) for kj, w in enumerate(ks)),
                       reverse=True)
        pair, used = {}, set()
        for r, si, kj in cands:
            if r < CFG["heb_fuzzy"]: break
            if si in pair or kj in used: continue
            pair[si] = kj; used.add(kj)
        # order: any two paired words on one scan line that the site shows the other way round. Only pairs the OCR
        # read well count: a misread word paired with its neighbour's reading would look like a swap
        bad = []
        sc, kc_ = Counter(t["skel"] for t in sh), Counter(w["skel"] for w in ks)
        dup = Counter({k: max(sc[k], kc_[k]) for k in set(sc) | set(kc_)})
        items = [(sh[si], ks[kj]) for si, kj in pair.items() if len(sh[si]["skel"]) >= 3
                 and ks[kj]["conf"] >= CFG["heb_order_conf"] and ratio(sh[si]["skel"], ks[kj]["skel"]) >= CFG["heb_order_sim"]]
        for x in range(len(items)):
            for y in range(x + 1, len(items)):
                (a, wa), (b, wb) = items[x], items[y]
                if wa["line"] != wb["line"] or a["skel"] == b["skel"]: continue
                if dup[a["skel"]] > 1 or dup[b["skel"]] > 1: continue
                # two spellings of one word (אֲבֵלָה / אֲבֵילָה) pair either way round with what the OCR read: the
                # order is only reported when the pairing is clear
                if ratio(a["skel"], wb["skel"]) + ratio(b["skel"], wa["skel"]) >= \
                        ratio(a["skel"], wa["skel"]) + ratio(b["skel"], wb["skel"]) - 0.3: continue
                # the OCR's boxes overlap or touch: their order on the line can't be told
                if min(wa["box"][2], wb["box"][2]) - max(wa["box"][0], wb["box"][0]) > -0.1 * self.lineh: continue
                if ST.visual_left_of(a, b) != (wa["x"] < wb["x"]):
                    bad.append((a, b, wa, wb))
        if bad:
            ln = bad[0][2]["line"]
            typ_o = "headword" if any(a["hw"] or b["hw"] for a, b, _, _ in bad) else "hebrew"
            on = [(t, w) for t, w in items if w["line"] == ln]
            site_vis = sorted([t for t, w in on], key=cmp_to_key(lambda a, b: -1 if ST.visual_left_of(a, b) else 1))
            book_vis = [t for t, w in sorted(on, key=lambda p: p[1]["x"])]
            # sure only when every word of the swap was read letter for letter and confidently
            exact = all(a["skel"] == wa["skel"] and b["skel"] == wb["skel"] and min(wa["conf"], wb["conf"]) >= 80
                        for a, b, wa, wb in bad)
            self.add(typ_o + "_order", 1 if exact else 2, sh, [], "the Hebrew words stand in a different order on the site"
                     + ("" if exact else " (the OCR's reading is not exact: check)"),
                     site_vis=" ".join(t["text"] for t in site_vis), book_vis=" ".join(t["text"] for t in book_vis),
                     ocr_conf=min(min(wa["conf"], wb["conf"]) for _, _, wa, wb in bad), **rec)
        us = [t for si, t in enumerate(sh) if si not in pair and len(t["skel"]) >= 2]
        # what the OCR read but nothing on the site pairs with. Vowel points, a dagesh or a Latin letter often come
        # out as a short "word" (דד, זז, תק): only words of three letters, or very confident two-letter ones, count
        uk = [w for kj, w in enumerate(ks) if kj not in used and w["conf"] >= 70 and
              (len(w["skel"]) >= 3 or (len(w["skel"]) == 2 and w["conf"] >= CFG["heb_short_conf"]))]
        loose = [w for kj, w in enumerate(ks) if kj not in used]
        sv = " ".join(t["text"] for t in sh)
        kv = " ".join(w["text"] for w in ks)
        # a headword paired with a scan word that differs in a letter: the pairing allows small differences, but a
        # headword must be exact. It is read again, by itself at double size, before it is reported
        for si, kj in pair.items():
            t, w = sh[si], ks[kj]
            if t["hw"] and t["skel"] != w["skel"] and w["conf"] >= 30 and len(t["skel"]) >= 2:
                rr = self.verify_heb(w["box"])
                if rr is not None and ST.heb_skel(rr) == t["skel"]: continue
                self.headword_letters(t, w, rr)
        # a site word left unpaired that is like a scan word nothing else took (the OCR dropped or added letters):
        # the reading is too poor to say the site is wrong. Read it again first
        rest = []
        for t in us:
            best = max(loose, key=lambda w: ratio(t["skel"], w["skel"]), default=None)
            if best is not None and (ratio(t["skel"], best["skel"]) >= CFG["heb_loose"] or
                                     (len(best["skel"]) >= 2 and best["skel"] in t["skel"])):
                loose.remove(best)
                uk = [w for w in uk if w is not best]
                if t["hw"]:
                    rr = self.verify_heb(best["box"])
                    if rr is not None and ST.heb_skel(rr) == t["skel"]: continue
                    # a short headword with one letter different is still the same word (אכה / אכח: ratio 0.67)
                    for cand in ([dict(best, text=rr, skel=ST.heb_skel(rr))] if rr else []) + [best]:
                        if ratio(cand["skel"], t["skel"]) >= CFG["heb_fuzzy"] or one_letter(cand["skel"], t["skel"]):
                            self.headword_letters(t, cand, rr); break
                    else:
                        cand = None
                    if cand is not None: continue
                self.add(("headword" if t["hw"] else "hebrew") + "_unread", 3, [t], [],
                         "the OCR's reading is too poor to compare", site_heb=t["text"], scan_heb=best["text"],
                         ocr_conf=best["conf"], boxes=[best["box"]], lines=[best["line"]])
                continue
            rest.append(t)
        us = rest
        uhw = [t for t in us if t["hw"]]
        if uhw and not uk:
            # the headword is there but the OCR's reading is too unclear to pair with it: not checked
            self.add("headword_unread", 3, sh, [], "the OCR's reading of the headword is too unclear to compare",
                     site_all=sv, scan_all=kv, **rec)
            return
        if us and not ks:
            self.add(typ + "_unread", 3, sh, [], "the OCR read no Hebrew here", **rec)
        elif uhw or (us and uk):
            typ = "headword" if uhw else "hebrew"
            us = uhw or us
            self.add(typ + "_differs", 2 if typ == "headword" else 3, sh, [],
                     "check the Hebrew (OCR of pointed Hebrew is not reliable)",
                     site_heb=" ".join(t["text"] for t in us), scan_heb=" ".join(w["text"] for w in uk),
                     site_all=sv, scan_all=kv, **rec)
        # what the book seems to have beyond the site: not a second reading of a word that is there (the OCR often
        # reads a word twice, from the line above or below: "רבתא רבתא"), nor one like a site word, nor a reading
        # with digits or Latin in it (the marks found all of these false)
        def extra(w):
            if re.search(r"[0-9A-Za-z]", w["text"]): return False
            return all(ratio(w["skel"], t["skel"]) < 0.6 and w["skel"] not in t["skel"] and t["skel"] not in w["skel"]
                       for t in sh) and all(w["skel"] != x["skel"] for x in ks if x is not w)
        uk = [w for w in uk if extra(w)]
        if len(uk) >= 2 and not us and sum(len(w["skel"]) for w in uk) >= 6:
            self.add("hebrew_extra_in_book", 2, sh, [], "the book seems to have Hebrew words here that the site lacks",
                     scan_heb=" ".join(w["text"] for w in uk), site_all=sv, scan_all=kv,
                     eid=sh[0]["eid"] if sh else (self.eid_for_scan(prev["j"]) if prev else None), **rec)

    def headword_letters(self, t, w, rr):
        """a headword the OCR read with a letter or more different. Letters the OCR often takes for each other
        (ט/מ/ס, ה/ח/ת, ו/י/ר/ד/ז, ב/כ/פ, ג/נ, ע/צ), and a ו or י more or less (a holam, shuruk or hiriq read as a
        letter), could be either's error: minor"""
        look = heb_look(t["skel"]) == heb_look(w["skel"])
        # the OCR read only part of the word (גינוס for אבגינוס, אב for אבן), or ran a letter of the next word
        # into it (מאבבא for אבב): the user's marks found these all false
        a_, b_ = t["skel"], w["skel"]
        part = a_ != b_ and (a_ in b_ or b_ in a_) or (rr and ST.heb_skel(rr) != b_ and
                                                        (a_ in ST.heb_skel(rr) or ST.heb_skel(rr) in a_))
        sure = w["conf"] >= 75 and not look and not part and (rr is None or ST.heb_skel(rr) == w["skel"])
        self.add("headword_letters", 2 if sure else 3, [t], [],
                 "a letter of the headword differs from the book's" + ("" if sure else
                 " (the OCR read only part of the word: check)" if part else
                 " (letters the OCR often confuses: check)" if look else " (the OCR is unsure: check)"),
                 site_heb=t["text"], scan_heb=w["text"], ocr_conf=w["conf"], reread=rr,
                 boxes=[w["box"]], lines=[w["line"]])

    def verify_heb(self, box):
        """read one Hebrew word of the scan again, by itself at double size (cached in the page's folder)"""
        if not CFG["verify"]: return None
        import json
        cache = os.path.join(self.wd, "reread_heb.json")
        if not hasattr(self, "_rh"):
            try: self._rh = json.load(open(cache))
            except Exception: self._rh = {}
        k = ",".join(map(str, box))
        if k in self._rh: return self._rh[k]
        try:
            from PIL import Image
            img = Image.open(os.path.join(self.wd, "page.png"))
            pad = 6
            c = img.crop((box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad))
            c = c.resize((c.width * 2, c.height * 2), Image.LANCZOS)
            name = os.path.join(self.wd, "verify_heb.png")
            c.save(name)
            r = subprocess.run(["tesseract", name, "stdout", "-l", "heb", "--psm", "8", "--dpi", "600"],
                               capture_output=True, text=True)
            txt = r.stdout.strip() if r.returncode == 0 else None
        except Exception:
            return None
        self._rh[k] = txt
        try: json.dump(self._rh, open(cache, "w"), ensure_ascii=False)
        except Exception: pass
        return txt

    # ---------- page edges ----------
    def edge_gap(self, start, S, between):
        """a gap at the very start or end of the page: words that slipped across a page break"""
        real = [t for t in between if self.real(t)]
        Sl = [t for t in S if t["key"]]
        if not real and not Sl: return False
        if not start and between and between[-1].get("page_end_hyph") and Sl and not real[:-1]:
            k = between[-1]["key"]
            if Sl[-1]["key"].startswith(k): return True          # "un-" at the page's foot, "unworthy" in the site
        if start and Sl and not real and len(Sl) == 1: return False
        if len(Sl) + len(real) <= 1: return False
        # what really differs: words of three letters or more on one side that the other side lacks. Short words
        # (v., pl., m.) and numbers the OCR read in part are no evidence; next to Hebrew the OCR reads Hebrew as
        # Latin garbage, which is not "real" text
        kk = {plain_shape(t["text"]) for t in between}
        sk = {plain_shape(t["text"]) for t in Sl}
        sdig = set(re.findall(r"\d", " ".join(t["text"] for t in between)))
        s_only = [t for t in Sl if plain_shape(t["text"]) not in kk and
                  (len(t["key"].lstrip("#")) >= 3 and not t["key"].startswith("#") or
                   (re.search(r"\d", t["text"]) and not set(re.findall(r"\d", t["text"])) & sdig))]
        k_only = [t for t in real if plain_shape(t["text"]) not in sk and len(t["key"]) >= 3]
        if not s_only and not k_only: return False         # compared word by word (and the Hebrew) as usual
        heb = any(t["heb"] for t in S) or any(t["script"] == "heb" for t in between)
        self.add("page_start" if start else "page_end", 2 if heb or len(s_only) + len(k_only) <= 1 else 1, S, between,
                 "the %s of the page differs: words may have slipped across the page break" % ("start" if start else "end"),
                 site_only=" ".join(t["text"] for t in s_only), book_only=" ".join(t["text"] for t in k_only))
        return True

    # ---------- column breaks ----------
    def check_breaks(self):
        P, lay = self.p, self.s["layout"]
        nseg = len(lay["segments"])
        want = 2 if P.mid_letter else 1
        if nseg != want:
            self.add("layout", 1, [], [], "the scan has %d segment(s) of columns, the site page %d (letter heading "
                     "missed or extra?)" % (nseg, want))
        k2s = {v: s for s, v in self.s2k.items()}
        byi = {t["i"]: t for t in P.tokens}
        self.book_breaks = []
        for si in range(nseg):
            L = [t for t in self.k if t["seg"] == si and t["col"] == "L"]
            R = [t for t in self.k if t["seg"] == si and t["col"] == "R"]
            if not L or not R:
                self.book_breaks.append(None); continue
            mL = [t for t in L if t["j"] in k2s]
            mR = [t for t in R if t["j"] in k2s]
            if not mL or not mR:
                self.book_breaks.append(None); continue
            iL, iR = k2s[mL[-1]["j"]], k2s[mR[0]["j"]]
            nL = sum(1 for t in L if t["j"] > mL[-1]["j"])
            nR = sum(1 for t in R if t["j"] < mR[0]["j"])
            gap = [t for t in self.S if iL < t["i"] < iR]
            approx = False
            if nL == 0 and gap: tok = gap[0]
            elif nL == 0: tok = byi[iR]
            elif nR == 0: tok = byi[iR]
            else:
                approx = True
                tok = gap[min(len(gap) - 1, round(len(gap) * nL / (nL + nR)))] if gap else byi[iR]
            if nL == 0 and not gap: tok = byi[iR]
            if approx and gap:
                # words the OCR could not place on both sides (Hebrew, mostly): if the right column begins with an
                # entry's (indented) first line and one entry starts in that stretch, the break is there
                cls = getattr(self, "cls", None) or self.line_class()
                if cls.get(R[0]["line"]) == "indent":
                    st = [t for t in gap if t["i"] > 0 and P.tokens[t["i"] - 1]["eid"] != t["eid"] and not t.get("cont")
                          and any(e["eid"] == t["eid"] and not e["cont"] for e in P.entries)]
                    # entries that begin on the left column's last lines, past its last matched word, are on the
                    # left: so many of these starts belong there (p. 6: a short entry at the foot of the left column)
                    tail = {t["line"] for t in L if t["j"] > mL[-1]["j"]} - {mL[-1]["line"]}
                    nleft = sum(1 for l in tail if cls.get(l) == "indent")
                    if nleft < len(st):
                        tok, approx = st[nleft], False
            off = tok["off"]
            self.book_breaks.append(off)
            site = P.site_breaks[si] if si < len(P.site_breaks) else None
            first_line = " ".join(t["text"] for t in self.k if t["line"] == R[0]["line"])
            info = {"book_off": off, "site_off": site, "approx": approx, "book_words": P.words_at(off),
                    "scan_line": first_line, "seg": si}
            if P.kind == "letter" and si == 0: info["proposed_known"] = off + 1
            elif P.mid_letter and si == 1: info["proposed_below"] = P.plain[off:off + 30].split("  ")[0]
            else: info["proposed_known"] = off
            if site is None:
                self.add("column_break_unset", 3, [], [], "the site has no fixed column break here; the book's right "
                         "column begins: %s" % P.words_at(off), boxes=[R[0]["box"]], lines=[R[0]["line"]], **info)
                continue
            lo, hi = sorted((site, off))
            between = [t for t in self.S if lo <= t["off"] < hi]
            if between:
                inside = any(t["off"] < site < t["end"] for t in P.tokens)
                self.add("column_break", 2 if approx else 1, [], [], "the site's right column begins: %s | the book's: %s (%d word%s %s)"
                         % (P.words_at(site), P.words_at(off), len(between), "s" if len(between) > 1 else "",
                            "earlier" if off < site else "later") + (" — the site's break falls inside a word" if inside else "")
                         + (" — the book's break is estimated: the OCR could not place the words around it" if approx else ""),
                         boxes=[R[0]["box"]], lines=[R[0]["line"]], words=len(between), **info)

    # ---------- is the scan page whole? ----------
    def scan_problem(self, note, sev=1, **kw):
        self.add("scan_incomplete", sev, [], [], note, **kw)
        if sev == 1: self.stats["scan_problem"] = True

    def check_scan(self):
        """the scan page itself: cut off at an edge, a column shorter than the other, a blank band in a column, or
        a stretch of the site's text that the scan does not have at all (a missing piece of the page)"""
        lay, P = self.s["layout"], self.p
        lh = self.lineh
        W, H = lay.get("size") or (None, None)
        if W is None:
            try:
                from PIL import Image
                W, H = Image.open(os.path.join(self.wd, "page.png")).size
            except Exception:
                W = H = None
        x0, y0, x1, y1 = lay["body"]
        # 1. text running to the edge of the image: the scan is cropped
        if W:
            edges = [n for n, near in (("left", x0 < 8), ("top", y0 < 8), ("right", x1 > W - 8), ("bottom", y1 > H - 8)) if near]
            if edges:
                self.scan_problem("the text runs to the %s edge of the scan: the page may be cut off there" %
                                  " and ".join(edges), boxes=[[x0, y0, x1, y1]])
        # 2. the two columns of a segment should start and end on the same line (except at the foot of a page whose
        #    text ends early, where the book still balances them)
        bylines = {}
        for ln in self.lines:
            bylines.setdefault((ln["seg"], ln["col"]), []).append(ln)
        for si, seg in enumerate(lay["segments"]):
            cols = {c["side"]: c for c in seg["cols"]}
            if len(cols) < 2:
                self.scan_problem("segment %d of the page has only its %s column" % (si + 1, "left" if "L" in cols else "right"),
                                  boxes=[c["box"] for c in seg["cols"]])
                continue
            L, R = cols["L"]["box"], cols["R"]["box"]
            for what, a, b in (("top", L[1], R[1]), ("foot", L[3], R[3])):
                if abs(a - b) > 2.5 * lh:
                    short = "left" if (a > b if what == "top" else a < b) else "right"
                    self.scan_problem("the %s column %s %d lines %s the other's (the book balances its columns): "
                                      "part of it may be missing from the scan"
                                      % (short, "starts" if what == "top" else "ends", round(abs(a - b) / (lh * 1.25)),
                                         "below" if what == "top" else "above"), sev=2,
                                      boxes=[L, R], lines=[(ls[0] if what == "top" else ls[-1])["i"]
                                                           for ls in (bylines.get((si, "L")), bylines.get((si, "R"))) if ls])
        # 3. a blank band inside a column (ink rows), taller than a few lines
        try:
            import numpy as np
            from PIL import Image
            a = np.asarray(Image.open(os.path.join(self.wd, "page.png"))) < lay.get("thr", 128)
            for si, seg in enumerate(lay["segments"]):
                for c in seg["cols"]:
                    bx = c["box"]
                    rows = a[bx[1]:bx[3], bx[0]:bx[2]].sum(1) > 2
                    k, start = 0, None
                    for yy, v in enumerate(list(rows) + [True]):
                        if not v and start is None: start = yy
                        if v and start is not None:
                            if yy - start > 3 * lh:
                                self.scan_problem("a blank stretch of about %d lines in the %s column: text missing "
                                                  "from the scan?" % (round((yy - start) / (lh * 1.25)),
                                                                      {"L": "left", "R": "right"}[c["side"]]),
                                                  boxes=[[bx[0], bx[1] + start, bx[2], bx[1] + yy]])
                            start = None
        except Exception:
            pass
        # 4. a long run of the site's text with nothing matched in the scan (Latin words of 3+ letters)
        run, runs = [], []
        for t in self.S:
            if t["heb"] or len(t["key"]) < 3: continue
            if t["i"] in self.s2k:
                if len(run) >= 15: runs.append(run)
                run = []
            else:
                run.append(t)
        if len(run) >= 15: runs.append(run)
        for r in runs:
            where = "at the top of the page" if r[0]["i"] <= self.S[0]["i"] + 3 else \
                    ("at the foot of the page" if r[-1]["i"] >= self.S[-1]["i"] - 3 else "in the middle of the page")
            self.scan_problem("%d words of the site's text, %s, are not in the scan at all: is part of the scan page "
                              "missing? (from “%s” to “%s”)" % (len(r), where, P.words_at(r[0]["off"], 5),
                                                                P.words_at(r[-1]["end"], 5, before=True)),
                              off=r[0]["off"], eid=r[0]["eid"])
        # 5. how much of the site's page the scan covers
        lat = [t for t in self.S if not t["heb"] and len(t["key"]) >= 3]
        if lat:
            cov = sum(1 for t in lat if t["i"] in self.s2k) / len(lat)
            self.stats["coverage"] = round(cov, 3)
            if cov < 0.75:
                self.scan_problem("only %d%% of the site's words were found in the scan: the scan page may be "
                                  "incomplete, or a different page" % round(100 * cov))

    # ---------- running head ----------
    def check_header(self):
        h = self.s["ocr"].get("header")
        if not h:
            self.add("running_head", 3, [], [], "no running head found on the scan"); return
        nums = re.findall(r"\d+", h["eng"])
        if self.p.pid.isdigit() and self.p.pid not in nums:
            # the whole running head is mostly Hebrew; read the number again from the head's middle, digits only
            n2 = self.read_page_number()
            if n2 and self.p.pid in n2:
                pass
            elif n2:
                self.add("page_number", 2, [], [], "the running head's page number reads %s; expected %s (is the PDF "
                         "page mapping right?)" % (n2[0], self.p.pid))
            else:
                self.add("page_number", 3, [], [], "the running head's page number could not be read (expected %s)"
                         % self.p.pid)
        heb = [ST.heb_skel(w) for w in h["heb"] if ST.heb_skel(w)]
        for which, word in (("first", self.p.first), ("last", self.p.last)):
            sk = ST.heb_skel(word)
            if sk and heb and max(ratio(sk, w) for w in heb) < 0.7:
                self.add("guide_word", 3, [], [], "the running head's guide words read %s; the site's %s headword "
                         "is %s" % (" ".join(h["heb"]), which, word))

    def read_page_number(self):
        """the numbers in the middle fifth of the running head, read with digits only"""
        hb = self.s["layout"].get("header")
        if not hb: return []
        try:
            from PIL import Image
            im = Image.open(os.path.join(self.wd, "page.png"))
            w = hb[2] - hb[0]
            name = os.path.join(self.wd, "pageno.png")
            im.crop((hb[0] + int(0.4 * w), hb[1] - 4, hb[0] + int(0.6 * w), hb[3] + 4)).save(name)
            r = subprocess.run(["tesseract", name, "stdout", "-l", "eng", "--psm", "7", "-c",
                                "tessedit_char_whitelist=0123456789"], capture_output=True, text=True)
            return re.findall(r"\d+", r.stdout)
        except Exception:
            return []

    # ---------- entries ----------
    def scan_pos(self, site_i, end=False):
        """the scan token a site token corresponds to (or, for its end, the last one)"""
        if site_i in self.s2k: return self.s2k[site_i]
        order = [t["i"] for t in self.S]
        if site_i not in order: return None
        k = order.index(site_i)
        if not end:
            for x in range(k - 1, -1, -1):
                if order[x] in self.s2k: return self.s2k[order[x]] + 1
            return 0
        for x in range(k + 1, len(order)):
            if order[x] in self.s2k: return self.s2k[order[x]] - 1
        return len(self.k) - 1

    def line_starts(self):
        """where each scan line's text begins: its first word's left edge, passing over a stray mark the OCR read
        before it (a lone dash, bar or quote standing apart: a speck, or the gutter's rule)"""
        by = {}
        for t in self.s["ocr"]["tokens"]:
            by.setdefault(t["line"], []).append(t)
        lh, out = self.lineh, {}
        for li, ws in by.items():
            ws = sorted(ws, key=lambda w: w["box"][0])
            while len(ws) > 1:
                w, n = ws[0], ws[1]
                stray = (not re.search(r"[0-9A-Za-zא-ת]", w["text"]) and w["box"][2] - w["box"][0] < 0.5 * lh
                         and n["box"][0] - w["box"][2] > 0.25 * lh)
                if not stray: break
                ws = ws[1:]
            out[li] = self.ink_start(ws[0]["box"])
        return out

    def ink_start(self, box):
        """the left edge of a word's ink, leaving out a speck in front of it that the OCR took into the word
        (p. 2: "—ND2N," for the headword אִבְּבָא, read 50 px too far left)"""
        if not hasattr(self, "_ink"):
            try:
                import numpy as np
                from PIL import Image
                self._ink = np.asarray(Image.open(os.path.join(self.wd, "page.png"))) < self.s["layout"].get("thr", 128)
            except Exception:
                self._ink = None
        a = self._ink
        if a is None: return box[0]
        x0, y0, x1, y1 = box
        mass = a[y0:y1, x0:x1].sum(0)
        import numpy as np
        rs = []
        on =np.concatenate([[0], (mass > 0).astype(np.int8), [0]])
        d = np.diff(on); starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
        for s_, e_ in zip(starts, ends):
            if rs and s_ - rs[-1][1] <= 3: rs[-1] = [rs[-1][0], e_, rs[-1][2] + int(mass[s_:e_].sum())]
            else: rs.append([s_, e_, int(mass[s_:e_].sum())])
        lh = self.lineh
        while len(rs) > 1 and rs[0][2] < 0.03 * lh * lh and rs[1][0] - rs[0][1] > 0.2 * lh:
            rs = rs[1:]
        return x0 + int(rs[0][0]) if rs else x0

    def line_class(self):
        """each scan line: 'indent' (it starts in from its column's edge: in this book an entry's first line, or a
        paragraph's, such as a binyan), 'flush', or 'part' (a piece of a line the OCR split off).

        A line is measured against the edge of its own column, found from the column's flush lines and allowed to
        drift down the column (a page not quite flat), not against the column's box: a box set a little into the
        gutter made every line of a column look indented (p. 2)."""
        import numpy as np
        lh = self.lineh
        starts = self.line_starts()
        cls, self.line_dx = {}, {}
        groups = {}
        for ln in self.lines:
            if ln["i"] in starts: groups.setdefault((ln["seg"], ln["col"]), []).append(ln)
        for key, ls in groups.items():
            ls = sorted(ls, key=lambda l: (l["box"][1] + l["box"][3]) / 2)
            # a "line" that lies mostly level with the one before it is a piece of the same line
            keep = []
            for ln in ls:
                if keep:
                    p = keep[-1]["box"]; b = ln["box"]
                    # level: the centres within a third of a line (a tall headword's box overlaps the line above,
                    # but its centre is a whole line below)
                    if abs((p[1] + p[3]) / 2 - (b[1] + b[3]) / 2) < 0.35 * lh:
                        # the piece further left is the line's start
                        if starts[ln["i"]] < starts[keep[-1]["i"]]:
                            cls[keep[-1]["i"]] = "part"; keep[-1] = ln
                        else:
                            cls[ln["i"]] = "part"
                        continue
                keep.append(ln)
            if not keep: continue
            ys = np.array([(l["box"][1] + l["box"][3]) / 2 for l in keep], float)
            xs = np.array([starts[l["i"]] for l in keep], float)
            # the flush lines: those near the left of the column; fit their edge, twice
            e = np.percentile(xs, 25)
            sel = np.abs(xs - e) < 0.35 * lh
            fit = lambda y: np.full_like(y, e)
            for _ in range(2):
                if sel.sum() >= 6 and np.ptp(ys[sel]) > 4 * lh:
                    a_, b_ = np.polyfit(ys[sel], xs[sel], 1)
                    fit = lambda y, a_=a_, b_=b_: a_ * y + b_
                elif sel.sum():
                    m = float(np.median(xs[sel])); fit = lambda y, m=m: np.full_like(y, m)
                sel = np.abs(xs - fit(ys)) < 0.35 * lh
            rel = xs - fit(ys)
            for l, d in zip(keep, rel):
                self.line_dx[l["i"]] = float(d)
                cls[l["i"]] = "indent" if d > CFG["indent"] * lh else "flush"
        for ln in self.lines:
            cls.setdefault(ln["i"], "flush")
        return cls

    def map_entries(self):
        """pair the site's entry starts with the book's entry lines, in order.

        An entry begins a new line in the book, indented by about an em; the lines after it are flush (CFG
        'entry_lines'; checked on pp. 2, 6 and 8). For each
        site entry, the scan words between the last matched word before it and the first matched word of the entry
        are where its first line must be; the book's entry lines are paired with the site's entries in order within
        those bounds. What is left over on either side is a finding: an entry the site has where the book does not
        start one (entry_start), or a line the book starts like an entry where the site has none (book_entry_start:
        a missing entry, or two entries run into one)."""
        cls = self.line_class()
        self.cls = cls
        ecls = CFG.get("entry_lines", "indent")
        first_tok = {}
        for t in self.k:
            if t["first"] and t["line"] not in first_tok: first_tok[t["line"]] = t["j"]
        book = sorted(first_tok[l] for l in first_tok if cls.get(l) == ecls)
        order = [t["i"] for t in self.S]
        pos = {i: n for n, i in enumerate(order)}

        def bounds(site_i):
            k = pos[site_i]
            lo = 0
            for x in range(k - 1, -1, -1):
                if order[x] in self.s2k: lo = self.s2k[order[x]] + 1; break
            hi = len(self.k) - 1
            for x in range(k, len(order)):
                if order[x] in self.s2k: hi = self.s2k[order[x]]; break
            return lo, hi
        starts = []
        for e in self.p.entries:
            idx = [t["i"] for t in self.S if t["eid"] == e["eid"]]
            if not idx: continue
            e["_idx"] = idx
            if e["cont"]: continue
            starts.append((e, bounds(idx[0])))
        # pair them in order, as many as possible (dynamic programming); among equal counts, prefer pairing an
        # entry with the line its first matched word stands on
        line_of = {t["j"]: t["line"] for t in self.k}
        n, m = len(starts), len(book)
        def score(x, y):
            e, (lo, hi) = starts[x]
            j = book[y]
            if not (lo <= j <= hi): return None
            return 1 + (0.1 if first_tok.get(line_of.get(hi)) == j else 0)
        D = [[0.0] * (m + 1) for _ in range(n + 1)]
        for x in range(n - 1, -1, -1):
            for y in range(m - 1, -1, -1):
                best = max(D[x + 1][y], D[x][y + 1])
                sc = score(x, y)
                if sc is not None: best = max(best, sc + D[x + 1][y + 1])
                D[x][y] = best
        self.entry_start, used = {}, set()
        x = y = 0
        while x < n:
            sc = score(x, y) if y < m else None
            if sc is not None and abs(D[x][y] - (sc + D[x + 1][y + 1])) < 1e-9:
                self.entry_start[starts[x][0]["eid"]] = book[y]; used.add(book[y]); x += 1; y += 1
            elif y < m and abs(D[x][y] - D[x][y + 1]) < 1e-9:
                y += 1
            else:
                self.entry_start[starts[x][0]["eid"]] = None; x += 1
        # paragraph starts on the site (a binyan, a sub-entry) may also begin a line in the book
        para = set()
        for t in self.S:
            prev = self.p.tokens[t["i"] - 1] if t["i"] > 0 else None
            if prev is not None and prev["para"] != t["para"] and prev["eid"] == t["eid"]:
                lo, hi = bounds(t["i"])
                para.update(range(lo, hi + 1))
        self.book_entry_lines = book
        self.unexplained = [j for j in book if j not in used and j not in para]
        # each entry's parts in the scan: from its first line to the line before the next entry's first line
        L = {ln["i"]: ln for ln in self.lines}
        self.entry_parts = {}
        ents = [e for e in self.p.entries if "_idx" in e]
        for n, e in enumerate(ents):
            a = self.entry_start.get(e["eid"]) if not e["cont"] else 0
            if a is None: a = bounds(e["_idx"][0])[0]
            nxt = next((self.entry_start.get(x["eid"]) for x in ents[n + 1:] if self.entry_start.get(x["eid"]) is not None), None)
            b = nxt - 1 if nxt is not None else len(self.k) - 1
            if n == len(ents) - 1: b = len(self.k) - 1
            parts = {}
            for t in self.k[max(0, a):b + 1]:
                for li in t["lines"]:
                    parts.setdefault((t["seg"], t["col"]), set()).add(li)
            out = []
            for (seg, col), ls in sorted(parts.items()):
                cb = L[min(ls)]["colbox"]
                y0 = min(L[l]["box"][1] for l in ls); y1 = max(L[l]["box"][3] for l in ls)
                out.append({"seg": seg, "col": col, "box": [cb[0] - 6, y0 - 4, cb[2] + 6, y1 + 6], "lines": sorted(ls)})
            self.entry_parts[e["eid"]] = out

    def check_structure(self):
        for e in self.p.entries:
            if e["cont"] or e["eid"] not in self.entry_start or self.entry_start[e["eid"]] is not None: continue
            st = [x for x in self.p.tokens if x["i"] == e["a"]]
            lo = self.scan_pos(e["_idx"][0])
            near = self.k[lo:lo + 4] if lo is not None else []
            self.add("entry_start", 2, st, near, "a new entry (%s) begins here on the site, but the book's line here "
                     "is not indented as an entry's first line is. Either the book runs these words on in the entry "
                     "before (the site split one entry in two), or the audit misjudged the indent (likeliest on the "
                     "lines by a letter heading): look at the indent in the scan" % e.get("hw", ""), eid=e["eid"])
        for j in self.unexplained:
            t = self.k[j]
            toks = [x for x in self.k if x["line"] == t["line"]]
            self.add("book_entry_start", 2, [], toks[:6], "the book begins an entry line here, where the site has no "
                     "entry: a missing entry, or one run into the entry before?", lines=[t["line"]],
                     boxes=[next(ln["box"] for ln in self.lines if ln["i"] == t["line"])])
        self.stats["entries"] = len([e for e in self.p.entries if not e["cont"]])
        self.stats["book_entry_lines"] = len(self.book_entry_lines)
