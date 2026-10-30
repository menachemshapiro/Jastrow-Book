"""Stage 3 of the audit (AUDIT_PLAN.md): test both readings against the image.

For each disagreement the word-by-word comparison leaves, the scan's word is read again with Tesseract's character
alternatives switched on (`-c lstm_choice_mode=2`, hOCR output): for every character it reads, the other characters
it considered, each with its confidence. It is read four ways: at the page's size and at double size, each in grey
(the contrast stretched) and in black and white (a threshold a little above the page's own, which thickens faint
type). Then two hypotheses are scored against those alternatives, letter by letter:
  - Sefaria's reading (the site's word), and
  - the OCR's own best reading.
A hypothesis fits when each of its letters is among the alternatives at its place, with a good confidence; a letter
of Sefaria's that never appears among the alternatives at its place is evidence of a real difference. The score of a
hypothesis is the best of the four reads: the geometric mean, per letter, of the confidence of the path that best
lines the hypothesis up with the alternatives (a letter missing, or one too many, costs as much as a poor letter).

The word is also read once more with Sefaria's word as the only word in the dictionary (`--user-words`, the system
dictionaries off): if even then the OCR reads something else, the difference is blatant.

Verdicts (CFG in compare.py: re_ok, re_err, re_good, re_weak). "delta" is how much less likely Sefaria's letters
are than the OCR's agreed reading, on the read most in Sefaria's favour, for the whole word (in nats: 0.7 is about
half as likely, 3 about a twentieth):
  ocr_misread     Sefaria's reading fits: each of its letters is among the alternatives, and the word is nearly as
                  likely as the OCR's (delta <= re_ok); or read with Sefaria's word as the only dictionary word, the
                  OCR finds it. The OCR misread the book: not a finding (kept as minor, with the scores).
  likely_error    only the OCR's reading fits: the four reads agree on it, it fits well (re_good, re_weak), it is
                  much likelier than Sefaria's (delta >= re_err), and the two are one word read two ways. Likely
                  an error in Sefaria's text.
  unclear         anything between: both fit, or neither does. For the user.
Then the words themselves are asked (AUDIT_PLAN 11, "which side"): where the OCR's reading is no word of the book
(seen once or never on the whole site) and Sefaria's is a common one, the OCR misread worn type: ocr_misread; and a
"likely error" whose OCR reading is no word of the book is only unclear.
Everything read is cached per page, in pages/pNNNN/reread3.json (keyed by the crop, the way it was read and the
model), so a second run reads nothing again.

Models: the reads use scan.lang_args(), so `audit.py --trained` (or JASTROW_OCR_MODELS) swaps in the models trained on
the book without any change here; the cache key carries the model's name."""
import html as H
import json, math, os, re, subprocess, tempfile, unicodedata

import numpy as np
from PIL import Image, ImageOps

import scan as SC

NIK = re.compile("[֑-ׇ]")
FIN = str.maketrans("ךםןףץ", "כמנפצ")
P_MIN = 0.01            # an alternative the OCR listed with confidence 0 still counts this much
C_SUB = -math.log(0.002)    # a letter with no alternative like it at its place
C_INS = -math.log(0.005)    # a letter of the hypothesis with no place at all in the reading
SKIP_FLOOR = 0.002
VARIANTS = (("1x", "grey"), ("1x", "bw"), ("2x", "grey"), ("2x", "bw"))


def norm_lat(s):
    """a Latin reading as scored: letters and digits only, lower case, no accents (ligatures opened)"""
    s = s.replace("æ", "ae").replace("œ", "oe").replace("ﬁ", "fi").replace("ﬂ", "fl").replace("ß", "ss")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]", "", s)


def norm_heb(s):
    """a Hebrew reading as scored: its letters only, final letters as ordinary ones"""
    return re.sub("[^א-ת]", "", NIK.sub("", s).translate(FIN))


def norm(s, script):
    return norm_heb(s) if script == "heb" else norm_lat(s)


# ---------- reading ----------
def parse_hocr(txt, script):
    """an hOCR file of one or more images: for each image, (text, word confidence, positions), where a position is
    [(character, confidence 0..1), ...] in reading order (Hebrew comes out left to right, and is turned round)"""
    pages = re.split(r"<div class='ocr_page'", txt)[1:]
    out = []
    for pg in pages:
        words = []
        for piece in pg.split("<span class='ocrx_word'")[1:]:
            tm = re.match(r"[^>]*title='bbox (\d+) \d+ \d+ \d+; x_wconf (\d+)'>([^<]*)", piece)
            if not tm: continue
            x0, wc, text = int(tm.group(1)), int(tm.group(2)), H.unescape(tm.group(3)).strip()
            pos = []
            for grp in re.split(r"<span class='ocrx_cinfo' id='lstm_choices", piece)[1:]:
                ch = [(H.unescape(c), float(x) / 100) for x, c in re.findall(r"x_confs ([\d.]+)'>([^<]*)<", grp)]
                if ch: pos.append(ch)
            if not pos and text:
                # no alternatives given (an old Tesseract, or a legacy model): the reading alone, at its confidence
                pos = [[(c, wc / 100)] for c in text]
            words.append((x0, text, wc, pos))
        if script == "heb":
            words.sort(key=lambda w: -w[0])
            seq = [list(reversed(w[3])) for w in words]
        else:
            words.sort(key=lambda w: w[0])
            seq = [w[3] for w in words]
        text = " ".join(w[1] for w in words)
        # a word's positions; a word of its own begins with a ["\x00", 0] marker (passed over at no cost)
        pos = [q for n, ps in enumerate(seq) for q in ([[["\x00", 0.0]]] if n else []) + ps]
        conf = min((w[2] for w in words), default=0)
        out.append({"text": text, "conf": conf, "pos": pos})
    return out


class Reader:
    """re-reads of one page's crops, batched (one Tesseract run per way of reading) and cached"""

    def __init__(self, wd, dpi=400, lineh=50):
        self.wd = wd
        self.dpi = dpi
        self.lineh = lineh
        self.cache_path = os.path.join(wd, "reread3.json")
        try: self.cache = json.load(open(self.cache_path))
        except Exception: self.cache = {}
        self._img = None
        self._thr = None
        self.ran = 0

    def img(self):
        if self._img is None:
            self._img = Image.open(os.path.join(self.wd, "page.png")).convert("L")
            try:
                sc = json.load(open(os.path.join(self.wd, "scan.json")))
                self._thr = sc["layout"].get("thr")
            except Exception:
                self._thr = None
            if self._thr is None: self._thr = SC.otsu(np.asarray(self._img))
        return self._img

    def crop(self, box, size, contrast):
        im = self.img()
        # the boxes are already the whole space between the word's neighbours (compare.py): no room is added
        # sideways, so that no piece of a neighbour comes in; a little above and below, for accents and points
        px, py = 1, max(4, int(0.2 * self.lineh))
        c = im.crop((max(0, box[0] - px), max(0, box[1] - py), box[2] + px, box[3] + py))
        if contrast == "grey":
            c = ImageOps.autocontrast(c, cutoff=1)
        else:
            t = min(250, int(self._thr) + 20)
            c = c.point(lambda v: 0 if v < t else 255)
        if size == "2x":
            c = c.resize((c.width * 2, c.height * 2), Image.LANCZOS)
        # a white margin: Tesseract reads a word poorly when its ink touches the image's edge
        m = 10 if size == "1x" else 20
        return ImageOps.expand(c, border=m, fill=255)

    @staticmethod
    def bkey(boxes):
        return ";".join(",".join(map(str, b)) for b in boxes)

    def key(self, boxes, lang, size, contrast, psm):
        return "%s|%s|%s|%s|%s|%d" % (self.bkey(boxes), SC.models_tag()[lang], lang, size, contrast, psm)

    def read_all(self, reqs):
        """reqs: [(boxes, lang)]: read each crop the four ways (cached). Boxes on more than one line are read one by
        one and joined"""
        todo = {}
        for boxes, lang in reqs:
            psm = 8
            for size, contrast in VARIANTS:
                for b in boxes:
                    k = self.key([b], lang, size, contrast, psm)
                    if k not in self.cache: todo.setdefault((lang, size, contrast, psm), {})[k] = b
        for (lang, size, contrast, psm), items in todo.items():
            self._run(lang, size, contrast, psm, items)
        if todo: self.save()

    def _run(self, lang, size, contrast, psm, items):
        keys = list(items)
        with tempfile.TemporaryDirectory() as td:
            names = []
            for n, k in enumerate(keys):
                p = os.path.join(td, "c%04d.png" % n)
                self.crop(items[k], size, contrast).save(p)
                names.append(p)
            lst = os.path.join(td, "list.txt")
            open(lst, "w").write("\n".join(names) + "\n")
            dpi = self.dpi * (2 if size == "2x" else 1)
            r = subprocess.run(["tesseract", lst, os.path.join(td, "out")] + SC.lang_args(lang) +
                               ["--psm", str(psm), "--dpi", str(dpi), "-c", "lstm_choice_mode=2", "hocr"],
                               capture_output=True, text=True)
            self.ran += 1
            try: txt = open(os.path.join(td, "out.hocr"), encoding="utf-8").read()
            except OSError: txt = ""
            res = parse_hocr(txt, lang)
            for n, k in enumerate(keys):
                self.cache[k] = res[n] if n < len(res) else {"text": "", "conf": 0, "pos": []}

    def reads(self, boxes, lang):
        """the four reads of a crop: [(variant, text, conf, positions)]"""
        out = []
        for size, contrast in VARIANTS:
            parts = [self.cache.get(self.key([b], lang, size, contrast, 8)) for b in boxes]
            parts = [p for p in parts if p]
            if not parts: continue
            out.append(("%s %s" % (size, contrast), " ".join(p["text"] for p in parts),
                        min(p["conf"] for p in parts), [q for p in parts for q in p["pos"]]))
        return out

    def forced(self, boxes, lang, word):
        """the crop read with `word` as the only word in the dictionary (system dictionaries off), at double size"""
        k = "%s|%s|%s|forced|%s" % (self.bkey(boxes), SC.models_tag()[lang], lang, word)
        if k in self.cache: return self.cache[k]
        texts = []
        with tempfile.TemporaryDirectory() as td:
            uw = os.path.join(td, "words.txt")
            open(uw, "w").write(word + "\n")
            for b in boxes:
                p = os.path.join(td, "c.png")
                self.crop(b, "2x", "grey").save(p)
                r = subprocess.run(["tesseract", p, "stdout"] + SC.lang_args(lang) +
                                   ["--psm", "8", "--dpi", str(2 * self.dpi), "--user-words", uw,
                                    "-c", "load_system_dawg=0", "-c", "load_freq_dawg=0"],
                                   capture_output=True, text=True)
                self.ran += 1
                texts.append(r.stdout.strip())
        self.cache[k] = " ".join(texts)
        self.save()
        return self.cache[k]

    def save(self):
        try: json.dump(self.cache, open(self.cache_path, "w"), ensure_ascii=False)
        except OSError: pass


# ---------- scoring ----------
def position_options(pos, script):
    """a position's alternatives as scored: [(normalised characters, confidence)], and the confidence that it is a
    letter at all (a position read as punctuation, a vowel point or a space costs little to pass over)"""
    opts, best = [], 0.0
    for c, p in pos:
        n = norm(c, script)
        if n:
            opts.append((n, max(p, P_MIN)))
            best = max(best, p)
    # the OCR's first choice here is no letter (a bracket, a stop, a point): passing over it costs little, whatever
    # letters it also considered
    top = max(pos, key=lambda cp: cp[1]) if pos else None
    if top is not None and not norm(top[0], script) and top[1] >= best: best = min(best, 0.5)
    return opts, best


C_EDGE = -math.log(0.5)  # a whole word at either edge of a read passed over: a piece of a neighbour in the crop


def score(hyp, pos, script):
    """the best of: the whole read, or the read with its first and/or last word left out (when it has more than one
    word: a piece of a neighbour that came into the crop), at a small cost each"""
    words = [[]]
    for p in pos:
        if p and p[0][0] == "\x00": words.append([])
        else: words[-1].append(p)
    words = [w for w in words if w]
    if len(words) <= 1: return _score(hyp, [p for w in words for p in w], script)
    best = None
    for a in (0, 1):
        for b in (0, 1):
            ws = words[a:len(words) - b]
            if not ws: continue
            f, u, w, c = _score(hyp, [p for x in ws for p in x], script)
            m = max(1, len(norm(hyp, script)))
            f *= math.exp(-(a + b) * C_EDGE / m); c += (a + b) * C_EDGE
            if best is None or (-u, f) > (-best[1], best[0]): best = (f, u, w, c)
    return best


def _score(hyp, pos, script):
    """how well a hypothesis fits a read's alternatives: (fit 0..1, letters unsupported). The best path lines the
    hypothesis's letters up with the positions: a letter among a position's alternatives costs -log(its confidence);
    a letter not among them, a letter with no position, or a position passed over that was surely a letter, cost
    as much as a very poor letter and count as unsupported"""
    h = norm(hyp, script)
    P = [position_options(p, script) for p in pos]
    n, m = len(P), len(h)
    if m == 0:
        c = sum(-math.log(max(SKIP_FLOOR, 1 - b)) for _, b in P)
        return (1.0, 0, 1.0, c) if all(b < 0.5 for _, b in P) else (0.0, sum(b >= 0.5 for _, b in P), 0.0, c)
    INF = float("inf")
    # D[i][j]: best (cost, unsupported, weakest letter) having used i positions and j letters
    D = [[(INF, 0, 1.0)] * (m + 1) for _ in range(n + 1)]
    D[0][0] = (0.0, 0, 1.0)
    for i in range(n + 1):
        for j in range(m + 1):
            c0, u0, w0 = D[i][j]
            if c0 == INF: continue
            def go(i2, j2, c, u, w=1.0):
                if c0 + c < D[i2][j2][0]: D[i2][j2] = (c0 + c, u0 + u, min(w0, w))
            if i < n:
                opts, best = P[i]
                # the position passed over
                go(i + 1, j, -math.log(max(SKIP_FLOOR, 1 - best)), 1 if best >= 0.5 else 0, 1 - best)
                if j < m:
                    hit = False
                    for s, p in opts:
                        if h.startswith(s, j):
                            go(i + 1, j + len(s), -math.log(p), 0, p); hit = True
                    if not hit: go(i + 1, j + 1, C_SUB, 1, 0.0)
            if j < m:
                go(i, j + 1, C_INS, 1, 0.0)
    c, u, w = D[n][m]
    return math.exp(-c / m), u, w, c


def near(a, b, script):
    """two readings close enough to be one word read or typed two ways (not a different word, nor a piece of one)"""
    import difflib
    x, y = norm(a, script), norm(b, script)
    r = difflib.SequenceMatcher(None, x, y, autojunk=False).ratio()
    if len(a.split()) > 1 or len(b.split()) > 1 or not x:
        # a stretch of words: words missing on one side (Sefaria's text empty here), or the stretches alike
        return len(y) >= 3 if not x else (r >= 0.6 and abs(len(x) - len(y)) <= 3)
    if not y: return False
    return abs(len(x) - len(y)) <= 2 and r >= 0.5


def judge(site, ocr, reads, script, cfg, forced=None):
    """score both hypotheses against every read; the verdict. Returns a dict for the finding.

    The OCR's best reading is the one its re-reads agree on (three of the four ways give the same letters); if they
    don't agree, the read that fits its own reading best. Sefaria is called wrong only when its reading does not fit, the OCR's agreed
    reading does, clearly better, and the two are one word read two ways (near()): a reading that is a piece of the
    word, or another word, says more about the crop than about the site."""
    if not reads:
        return {"verdict": "unread", "site_fit": None, "ocr_fit": None}
    from collections import Counter
    texts = [r[1] for r in reads]
    nt = Counter(norm(t, script) for t in texts if norm(t, script))
    agreed = None
    if nt:
        top, cnt = nt.most_common(1)[0]
        if cnt >= 3: agreed = next(t for t in texts if norm(t, script) == top)
    S_ = [score(site, r[3], script) for r in reads]
    if agreed is not None:
        best = agreed
    else:
        # no agreement: the read that fits its own reading best stands for the OCR (not the first OCR's reading,
        # which next to noise may be no reading at all)
        own = [score(r[1], r[3], script) if norm(r[1], script) else (0.0, 9, 0.0, 99.0) for r in reads]
        k = max(range(len(reads)), key=lambda i: (-own[i][1], own[i][0]))
        best = reads[k][1] if (norm(reads[k][1], script) and cfg.get("best_own", False)) else ocr
    K_ = [score(best, r[3], script) for r in reads]
    kf, ku, kw, _ = max(K_, key=lambda x: (-x[1], x[0]))
    # Sefaria's reading is weighed on the reads that make sense of the OCR's (all its letters among the
    # alternatives), on the one most in Sefaria's favour: fewest unsupported letters, then the smallest delta, how
    # much less likely Sefaria's letters are than the OCR's (nats, for the whole word: one letter of a long word is
    # not diluted)
    good_r = [i for i in range(len(reads)) if K_[i][1] == 0 or not cfg.get("good_reads", True)] or \
        list(range(len(reads)))
    i_ = min(good_r, key=lambda i: (S_[i][1], S_[i][3] - K_[i][3]))
    su, delta = S_[i_][1], S_[i_][3] - K_[i_][3]
    sf, _, sw, _ = max(S_, key=lambda x: (-x[1], x[0]))
    good, weak = cfg["re_good"], cfg["re_weak"]
    k_ok = kf >= good and ku == 0 and kw >= weak
    f_site = forced is not None and norm(forced, script) == norm(site, script)
    same = norm(site, script) == norm(best, script)
    if same or norm(site, script) == norm(ocr, script):
        v = "ocr_misread"            # the same letters: only spacing or punctuation differed
    elif su == 0 and delta <= cfg["re_ok"]:
        v = "ocr_misread"            # every letter of Sefaria's among the alternatives, and nearly as likely
    elif f_site and not (k_ok and agreed is not None):
        v = "ocr_misread"            # read with Sefaria's word as the only word, the OCR finds it, and nothing surer
    elif k_ok and agreed is not None and near(site, best, script) and (delta >= cfg["re_err"] or (
            # read with Sefaria's word as the only dictionary word, the OCR still reads its own: less is needed
            forced is not None and norm(forced, script) == norm(best, script) and delta >= cfg["re_err_forced"])):
        v = "likely_error"           # the reads agree on another word, much likelier than Sefaria's
    else:
        v = "unclear"
    # the image alone can't always tell; the words can (AUDIT_PLAN 11, "which side"). Sefaria's text was made by OCR
    # too, so its typos are rarely words of the book; the OCR's misreadings of worn type rarely are either
    cnt = cfg.get("count")
    sc_, kc_ = (cnt(site, script), cnt(best, script)) if cnt else (None, None)
    word_note = ""
    if sc_ is not None and kc_ is not None and v in ("likely_error", "unclear") and near(site, best, script):
        if sc_ >= cfg["common"] and kc_ <= 1:
            v, word_note = "ocr_misread", "Sefaria's word is common in the book (%d×), the OCR's reading is no word of it" % sc_
        elif v == "likely_error" and kc_ <= 1 and sc_ > cfg["rare"]:
            v, word_note = "unclear", "the OCR's reading is no word of the book, and Sefaria's is (%d×)" % sc_
    return {"verdict": v, "ocr_best": best, "agreed": agreed is not None, "delta": round(delta, 2),
            "site_fit": round(sf, 3), "site_unsupported": su, "site_weakest": round(sw, 3),
            "ocr_fit": round(kf, 3), "ocr_unsupported": ku, "ocr_weakest": round(kw, 3),
            "reads": texts, "forced": forced, "site_count": sc_, "ocr_count": kc_, "word_note": word_note,
            "blatant": bool(v == "likely_error" and forced is not None and not f_site)}


def judge_number(site, reads):
    """a number (a folio, a chapter): its digits only. The reads agree on the digits (three of four; a raised side
    letter read as one more digit, "39b" as 395, is cut off): the same as Sefaria's: the OCR misread the rest; others:
    likely an error; no agreement: unclear"""
    from collections import Counter
    m = re.search(r"\d+", site)
    if not m or not reads: return {"verdict": "unread"}
    sd = m.group(0)
    cut = []
    for r in reads:
        d = re.search(r"\d+", r[1] or "")
        d = d.group(0) if d else ""
        cut.append(d[:len(sd)] if len(d) in (len(sd), len(sd) + 1) else None)
    c = Counter(x for x in cut if x)
    top, n = c.most_common(1)[0] if c else (None, 0)
    v = "ocr_misread" if top == sd and n >= 2 else "likely_error" if top and n >= 3 and top != sd else "unclear"
    return {"verdict": v, "ocr_best": top or "", "site_fit": None, "reads": [r[1] for r in reads], "digits": True}
