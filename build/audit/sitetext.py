"""The site's text of one book page, as a list of word tokens, read from data/c*.json and data/pages.json.

Each token knows its place: its offset in the page's plain text (the text the column break is counted in), the entry
it belongs to, and whether it is Hebrew, part of a headword (span.hw), a binyan form (span.bf), a sense number
(span.n), a superscript (folio side) or the letter heading (h2.letter)."""
import html as H
import json, os, re, unicodedata

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHUNK = 10

HEB_CH = "א-ת"
NIK = re.compile("[֑-ׇ]")
FIN = str.maketrans("ךםןףץ", "כמנפצ")
HEBWORD = re.compile("[%s][֑-ׇ%s'\"׳״’]*" % (HEB_CH, HEB_CH))
TAG = re.compile(r"<[^>]+>|[^<]+")
CLS = re.compile(r'class="([^"]*)"')
IDA = re.compile(r'id="([^"]*)"')


def key(s):
    """the form a Latin word is compared in: no accents, punctuation or case; a number (with or without its folio
    side, "26b", "26°") is '#26'"""
    s = s.replace("æ", "ae").replace("Æ", "Ae").replace("œ", "oe").replace("Œ", "Oe").replace("ß", "ss")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9]", "", s)
    m = re.fullmatch(r"(\d+)[a-d]?", s)
    if m: return "#" + m.group(1)
    return s


def heb_skel(s):
    """Hebrew letters only, no vowels, final letters as ordinary ones"""
    s = NIK.sub("", s).translate(FIN)
    return re.sub("[^%s]" % HEB_CH, "", s)


def is_heb(s):
    return bool(re.search("[%s]" % HEB_CH, s))


class Book:
    """the built site in data/: page list and page HTML"""

    def __init__(self, repo=REPO):
        self.repo = repo
        self.meta = json.load(open(os.path.join(repo, "data", "pages.json")))["pages"]
        self.index = {m[0]: i for i, m in enumerate(self.meta)}
        self._chunks = {}

    def html(self, pid):
        i = self.index[str(pid)]
        c = i // CHUNK
        if c not in self._chunks:
            self._chunks[c] = json.load(open(os.path.join(self.repo, "data", "c%03d.json" % c)))
        h = self._chunks[c][i % CHUNK]
        return "".join(h) if isinstance(h, list) else h

    def body_pages(self):
        return [m[0] for m in self.meta if m[1] == "b" and m[5] != "vtitle"]

    def page(self, pid):
        return Page(self, str(pid))


class Page:
    def __init__(self, book, pid):
        self.pid = pid
        m = book.meta[book.index[pid]]
        self.first, self.last, self.kind, self.known = m[2], m[3], m[5], m[6]
        self.below = m[7] if len(m) > 7 else None
        self.html = book.html(pid)
        self._parse()
        self._breaks()

    def _parse(self):
        """walk the HTML; build the plain text and one attribute record per character"""
        plain, attrs = [], []
        bounds = set()                   # offsets where a block (div, p, h2) opens or closes: a word ends there
        stack = []                       # (tag, classes, serial, right-to-left isolate?)
        serial = 0
        eid, cont, para, npara = None, False, None, -1
        for m in TAG.finditer(self.html):
            t = m.group(0)
            if t.startswith("<"):
                if t.startswith("</"):
                    name = t[2:-1].strip()
                    if name in ("div", "p", "h2"): bounds.add(len(plain))
                    for k in range(len(stack) - 1, -1, -1):
                        if stack[k][0] == name:
                            del stack[k:]; break
                    continue
                name = re.match(r"<(\w+)", t).group(1)
                cl = (CLS.search(t).group(1) if CLS.search(t) else "").split()
                if name == "div" and "e" in cl:
                    eid = IDA.search(t).group(1); cont = "cont" in cl
                if name == "p":
                    npara += 1; para = " ".join(cl)
                if name in ("div", "p", "h2", "br"): bounds.add(len(plain))
                if name in ("br", "img"): continue
                serial += 1
                dm = re.search(r'dir="(\w+)"', t)
                # an element the browser sets as its own right-to-left island: span.h (CSS: direction rtl,
                # unicode-bidi isolate) or anything with dir="rtl" (a headword, a form in a list of forms)
                rtl = ("h" in cl and name == "span") or (dm is not None and dm.group(1) == "rtl")
                stack.append((name, cl, serial, rtl))
                continue
            text = H.unescape(t)
            flags = set()
            unit = next((x[2] for x in reversed(stack) if x[3]), None)
            for name, cl, _, _ in stack:
                if name == "h2": flags.add("h2")
                if name == "sup": flags.add("sup")
                if name == "i": flags.add("i")
                for c in ("hw", "bf", "n", "h", "fm"):
                    if c in cl: flags.add(c)
                if name == "a" and "r" in cl: flags.add("ref")
            rec = (eid, cont, npara, para, frozenset(flags), unit)
            for ch in text:
                plain.append(ch); attrs.append(rec)
        self.plain = "".join(plain)
        self.attrs = attrs
        self.bounds = bounds
        # tokens: whitespace-separated chunks, split further into Hebrew and non-Hebrew runs
        toks = []
        chunks = []
        for m in re.finditer(r"\S+", self.plain):
            a, z = m.start(), m.end()
            cuts = [a] + sorted(b for b in bounds if a < b < z) + [z]
            chunks += [(self.plain[x:y], x) for x, y in zip(cuts, cuts[1:])]
        for s, a in chunks:
            pieces = []
            for r in re.finditer("(%s)|([^%s]+)" % (HEBWORD.pattern, HEB_CH), s):
                if r.group(1) is not None:
                    pieces.append((r.group(0), r.start(), True)); continue
                # "storage.—Pl." is two words: split before a dash that follows a word
                p0 = r.start()
                for q in re.split(r"(?<=[^\s\u2014])(?=\u2014)", r.group(0)):
                    if q: pieces.append((q, p0, False))
                    p0 += len(q)
            for txt, rs, isheb in pieces:
                off = a + rs
                eid_, cont_, np_, para_, fl, unit = attrs[off]
                heb = isheb
                t = {"i": len(toks), "text": txt, "off": off, "end": off + len(txt), "heb": heb,
                     "eid": eid_, "cont": cont_, "para": np_, "pcls": para_,
                     "hw": "hw" in fl, "bf": "bf" in fl, "n": "n" in fl, "sup": "sup" in fl, "h2": "h2" in fl,
                     "unit": unit if unit is not None else -1 - len(toks)}
                t["key"] = "" if heb else key(txt)
                t["skel"] = heb_skel(txt) if heb else ""
                toks.append(t)
        # the side letter of a folio ("26<sup>b</sup>") is part of the number token already, since there is no space
        for t in toks:
            m = re.match(r"(\d+)([a-d])\W*$", t["text"]) if not t["heb"] else None
            t["side"] = m.group(2) if m else ""
        self.tokens = toks
        # entries in page order: id -> first and last token index, and whether it began on an earlier page
        ent = {}
        for t in toks:
            if t["h2"] or not t["eid"]: continue
            e = ent.setdefault(t["eid"], {"eid": t["eid"], "cont": t["cont"], "a": t["i"], "b": t["i"]})
            e["b"] = t["i"]
        self.entries = list(ent.values())
        hw = {}
        for t in toks:
            if t["hw"] and t["eid"]: hw.setdefault(t["eid"], []).append(t)
        for e in self.entries:
            ts = hw.get(e["eid"], [])
            e["hw"] = self.text(ts[0]["off"], ts[-1]["end"]).strip() if ts else ""
        self.letter_text = "".join(ch for ch, a in zip(self.plain, attrs) if "h2" in a[4]).strip()

    def _breaks(self):
        """where the site breaks the columns, as offsets in the plain text, the way index.html does it:
        a letter page (heading at the top) splits at known - 1 (index.html subtracts the heading and one);
        a page with a letter part-way down splits above the heading at `known`, and below it before the
        words in pages.json's 8th field; any other page at `known`. -1: the browser balances the columns."""
        self.site_breaks = []            # one per segment of two columns: offset or None
        h2 = [i for i, a in enumerate(self.attrs) if "h2" in a[4]]
        if self.kind == "letter":
            self.site_breaks.append(self.known - 1 if self.known >= 0 else None)
        elif h2:
            hs, he = h2[0], h2[-1] + 1
            self.site_breaks.append(self.known if 0 < self.known < hs else None)
            if self.below:
                k = self.plain.find(self.below, he)
                self.site_breaks.append(k if k > 0 else None)
            else:
                self.site_breaks.append(None)
        else:
            self.site_breaks.append(self.known if self.known >= 0 else None)
        self.mid_letter = bool(h2) and self.kind != "letter"

    def words_at(self, off, n=6, before=False):
        """a few words of plain text after (or before) an offset, for showing a break"""
        if off is None: return ""
        w = [t["text"] for t in self.tokens if (t["end"] <= off if before else t["off"] >= off) and not t["h2"]]
        return " ".join(w[-n:] if before else w[:n])

    def text(self, a, b):
        """plain text from a to b, with a space where a block (paragraph, entry) begins or ends"""
        cuts = sorted(x for x in self.bounds if a < x < b)
        out, p = [], a
        for c in cuts:
            out.append(self.plain[p:c]); p = c
            if out[-1] and not out[-1][-1].isspace(): out.append(" ")
        out.append(self.plain[p:b])
        return "".join(out)

    def text_map(self, a, b):
        """like text(a, b), plus where each plain offset lands in the result, and for each character of the result
        whether it is a superscript and which right-to-left island (if any) it belongs to"""
        cuts = set(x for x in self.bounds if a < x < b)
        out, pos, sup, unit = [], {}, [], []
        for i in range(a, b):
            if i in cuts and out and not out[-1].isspace():
                out.append(" "); sup.append(False); unit.append(None)
            pos[i] = len(out)
            out.append(self.plain[i])
            fl = self.attrs[i][4]
            sup.append("sup" in fl); unit.append(self.attrs[i][5])
        pos[b] = len(out)
        return "".join(out), pos, sup, unit

    def entry_span(self, eid):
        """first and last plain offsets of an entry on this page"""
        a = [t for t in self.tokens if t["eid"] == eid and not t["h2"]]
        return (a[0]["off"], a[-1]["end"]) if a else None

    def entry_text(self, eid):
        a = [t for t in self.tokens if t["eid"] == eid and not t["h2"]]
        if not a: return ""
        return self.text(a[0]["off"], a[-1]["end"])


def visual_left_of(a, b):
    """True if the site shows Hebrew token a to the left of token b (both on one line): within one right-to-left
    island the later word is on the left; separate islands follow each other left to right"""
    if a["unit"] == b["unit"]: return a["i"] > b["i"]
    return a["i"] < b["i"]
