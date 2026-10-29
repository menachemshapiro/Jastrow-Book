"""Checks that need no scan: on the site's own text (brackets, sense numbers, leftover hyphens, stray characters,
headwords, alphabetical order), and on its Talmud references (Bavli: is the folio inside the tractate, and is the
quotation that goes with it found on that daf)."""
import os, re, sys
from collections import Counter

import sitetext as ST

BUILD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BUILD)


def finding(pid, typ, sev, eid, site, note, **kw):
    r = {"page": pid, "type": typ, "sev": sev, "eid": eid, "site": site, "scan": "", "note": note, "lines": [],
         "boxes": [], "off": None}
    r.update(kw)
    return r


def entry_full_text(book, pid, eid):
    """an entry's text, including its parts on the following pages"""
    out = [book.page(pid).entry_text(eid)]
    order = book.body_pages()
    k = order.index(pid) if pid in order else -1
    while 0 <= k < len(order) - 1:
        k += 1
        p = book.page(order[k])
        if p.entries and p.entries[0]["eid"] == eid and p.entries[0]["cont"]:
            out.append(p.entry_text(eid))
        else:
            break
    return " ".join(out)


def entry_tokens(book, pid, eid):
    """the site tokens of an entry, including its parts on the following pages"""
    order = book.body_pages()
    k = order.index(pid) if pid in order else -1
    out = [t for t in book.page(pid).tokens if t["eid"] == eid]
    while 0 <= k < len(order) - 1:
        k += 1
        p = book.page(order[k])
        if p.entries and p.entries[0]["eid"] == eid and p.entries[0]["cont"]:
            out += [t for t in p.tokens if t["eid"] == eid]
        else:
            break
    return out


STRAY = re.compile(r"[�¬¦|_\\~^`\x00-\x08\x0b-\x1f]|[A-Za-z][א-ת]|[א-ת][A-Za-z]|"
                   r"[א-ת]\d|\d[א-ת]")


def site_checks(book, pid):
    p = book.page(pid)
    out = []
    prev_hw = None
    for e in p.entries:
        eid = e["eid"]
        if e["cont"]: continue                       # checked with the page it starts on
        text = entry_full_text(book, pid, eid)
        # brackets (not counting the ")" of the sense numbers, span.n: "1)", "—2)")
        ntoks = [t for t in entry_tokens(book, pid, eid) if t["n"]]
        for o, c in ("()", "[]"):
            no, nc = text.count(o) - sum(t["text"].count(o) for t in ntoks), text.count(c) - sum(t["text"].count(c) for t in ntoks)
            if no != nc:
                out.append(finding(pid, "brackets", 3, eid, text[:120], "%d '%s' but %d '%s' in the entry" %
                                   (no, o, nc, c)))
        # sense numbers (span.n): 1), 2), 3) ... (they start again at 1 in a new section)
        nums = [int(re.sub(r"\D", "", t["text"])) for t in entry_tokens(book, pid, eid)
                if t["n"] and re.search(r"\d", t["text"])]
        seq_bad = [(a, b) for a, b in zip(nums, nums[1:]) if not (b == a + 1 or b == 1)]
        if seq_bad:
            out.append(finding(pid, "sense_numbers", 2, eid, " ".join("%d)" % n for n in nums),
                               "sense numbers out of sequence: " + ", ".join("%d) then %d)" % x for x in seq_bad)))
        # a line-break hyphen left in the text ("un- worthy") — rule 2.8
        for m in re.finditer(r"[A-Za-z]{2,}- [a-z]{2,}", text):
            out.append(finding(pid, "hyphen_space", 2, eid, m.group(0), "a hyphen followed by a space: a word broken "
                               "at a line's end in the book, kept apart?"))
        for m in STRAY.finditer(text):
            ctx = text[max(0, m.start() - 15):m.end() + 15]
            if re.match(r"[IVX][\u05D0-\u05EA]", m.group(0)):
                out.append(finding(pid, "headword_display", 2, eid, ctx, "a homonym number (span.hn) runs into the "
                                   "headword after it with no space, as the site shows it"))
            else:
                out.append(finding(pid, "stray_char", 2, eid, ctx, "unexpected character(s) %r" % m.group(0)))
        # a phrase repeated right after itself (", 1) a renowned Babyl., 1) a renowned Babyl.")
        for m in re.finditer(r"(?<!\w)(\S.{10,80}?)[\s,;]*\1(?!\w)", text):
            if len(m.group(1).split()) >= 2:
                out.append(finding(pid, "doubled_text", 1, eid, m.group(0), "the same words twice in a row"))
        for m in re.finditer(r"\b([A-Za-z]{3,}) \1\b", text):
            out.append(finding(pid, "doubled_word", 3, eid, m.group(0), "the same word twice"))
        # headword
        hw = e["hw"]
        if hw:
            if re.search(r"[A-Za-z0-9]", re.sub(r"\b[IVX]+\b|[IVX]+(?=[\u05D0-\u05EA])", "", hw)):
                out.append(finding(pid, "headword_text", 2, eid, hw, "Latin letters or digits in the headword"))
            if re.search(r",\s*,|\(\s*\)|^\s*,", hw) or hw.count("(") != hw.count(")"):
                out.append(finding(pid, "headword_text", 2, eid, hw, "odd punctuation in the headword"))
            forms = [ST.heb_skel(x) for x in re.split(r"[,()\[\]]", hw) if ST.heb_skel(x)]
            # Jastrow orders by the consonants; variants listed with a headword may sort elsewhere, so flag only
            # when every form sorts before every form of the entry before (first two letters)
            if forms and prev_hw and max(f[:2] for f in forms) < min(f[:2] for f in prev_hw) and \
                    forms[0][0] == prev_hw[0][0]:
                out.append(finding(pid, "alphabetical", 3, eid, hw, "out of alphabetical order after %s" %
                                   " ".join(prev_hw)))
            if forms and p.first and ST.heb_skel(p.first)[:1] and not p.mid_letter and \
                    all(f[0] != ST.heb_skel(p.first)[0] for f in forms):
                out.append(finding(pid, "alphabetical", 3, eid, hw, "first letter differs from the page's letter"))
            if forms: prev_hw = forms
    return out


# ---------------------------------------------------------------- Talmud

class Talmud:
    """Bavli citations of the audited entries: range check, and the quotation search when Sefaria's Talmud text
    is available (paths.TALMUD)."""

    def __init__(self, site_dir, with_quotes=True):
        import talmud_index as TI
        self.TI = TI
        TI.SITE = site_dir
        self.texts = {eid: t for eid, t, refs in TI.entry_texts()}
        self.search = None
        if with_quotes:
            try:
                import paths
                if os.path.isdir(paths.TALMUD):
                    sys.path.insert(0, os.path.join(BUILD, "talsearch"))
                    import search2 as S2   # reads Sefaria's Bavli and Yerushalmi once (takes a little while)
                    self.S2, self.CO, self.B = S2, S2.corpus, S2.B
                    self.search = True
            except Exception as e:
                self.search_error = str(e)

    HEB = r"[א-ת][֑-״א-ת'\"’]*"
    RUN = re.compile(r"(" + HEB + r"(?:(?:\s|,\s|\s?\.\.\.\s?|\s?…\s?|\s?\(\s?|\s?\)\s?)+" + HEB + r")*\)?)")
    # a short Latin remark between the citation and the quotation: "(prov.)", "[Var.]"
    SKIP = re.compile(r"\s*(?:\([^()א-ת]{1,25}\)|\[[^\[\]א-ת]{1,25}\])")

    def quote_near(self, t, a, b):
        """the Hebrew right after a citation, past a short Latin remark such as "(prov.)". Failing that, Hebrew right
        before it, but not across a full stop or semicolon, nor a cross-reference ("v. אֲבַק."): Jastrow's stop
        ends what the Hebrew belongs to"""
        while True:
            m = self.SKIP.match(t, b)
            if not m: break
            b = m.end()
        m = re.compile(r"\s*").match(t, b)
        m = self.RUN.match(t, m.end())
        if m and m.group(1): return m.group(1).strip()
        m = re.search("(" + self.HEB + r"(?:\s+" + self.HEB + r")*)\s*,?\s*$", t[max(0, a - 120):a])
        if not m: return ""
        if re.search(r"(?:\bv\.|\bcmp\.|\bs\.|=)\s*$", t[max(0, a - 120):a][:m.start()]): return ""
        return m.group(1)

    @staticmethod
    def variants(q, after):
        """the ways a quotation may stand in the Talmud's text: without Jastrow's bracketed variants ("ניזיל
        (ליזיל)"), with the brackets' letters kept ("(ו)בגבולין"), and with the readings he gives after it
        ("read אבקתא", "Ar. … (ed. אבין)") put in for a word"""
        out = []
        def add(x):
            x = re.sub(r"\s+", " ", x).strip()
            if x and x not in out: out.append(x)
        add(re.sub(r"\([^()]*\)", " ", q))
        add(re.sub(r"[()]", "", q))
        # readings named after the quotation, up to the next citation-like stop
        alts = []
        for mm in re.finditer(r"(?:\bread|\bed\.|\bMs\.(?: M\.)?|\bVar\.(?: lect\.)?|\bcorr\.(?: acc\.)?|\bAr\.)\s*"
                              r"((?:[א-ת][֑-״א-ת'’]*[\s,]*)+)", after[:160]):
            alts += [w.strip(" ,") for w in re.split(r",\s*", mm.group(1)) if w.strip(" ,")]
        base = out[0] if out else q
        words = base.split()
        for a_ in alts:
            add(a_)
            sa = re.sub("[^א-ת]", "", a_)
            for i, w in enumerate(words):
                sw = re.sub("[^א-ת]", "", w)
                if sw and sa and sw[0] == sa[0] and len(set(sw) & set(sa)) >= min(len(sw), len(sa)) - 1:
                    add(" ".join(words[:i] + [a_] + words[i + 1:]))
        return out

    def daf_list(self, key, daf):
        f, s = int(daf[:-1]), daf[-1]
        near = [(f, "b" if s == "a" else "a"), (f - 1 if s == "a" else f, "b" if s == "a" else "a"),
                (f + 1 if s == "b" else f, "a" if s == "b" else "b")]
        return ["%d%s" % x for x in near]

    def check(self, pid, eids):
        TI = self.TI
        out, stats = [], Counter()
        for eid in eids:
            t = self.texts.get(eid)
            if not t: continue
            for m, hit in TI.citations(t):
                corp, key, ch, daf = hit
                if corp != "b": continue
                stats["bavli"] += 1
                f = int(daf[:-1])
                cite = m.group(0).strip("() ")
                if not (TI.BMIN.get(key, 2) <= f <= TI.BMAX[key]):
                    out.append(finding(pid, "talmud_range", 1, eid, cite, "%s %s is outside the tractate (%d–%d)" %
                                       (key, daf, TI.BMIN.get(key, 2), TI.BMAX[key]), ref="%s %s" % (key, daf),
                                       context=t[max(0, m.start() - 60):m.end() + 100]))
                    stats["out_of_range"] += 1
                    continue
                if not self.search: continue
                q = self.quote_near(t, m.start(), m.end())
                if not q:
                    stats["no_quote"] += 1; continue
                after = t[m.end():m.end() + 200]
                Rs = []
                for v in self.variants(q, after):
                    rx, nw, n = self.S2.pattern(v)
                    if n < 2 and nw < 1: continue
                    Rs.append(re.compile(r"(?:^| )" + rx.replace(r"\S* ", r"\S*(?: |$)") + r"(?= |$)"))
                if not Rs:
                    stats["quote_too_short"] += 1; continue
                def found(k, d):
                    txt = self.B.get((k, d))
                    if not txt: return False
                    txt = txt.translate(self.CO.FIN) + " "
                    return any(R.search(txt) for R in Rs)
                if found(key, daf):
                    stats["found_at"] += 1; continue
                # every word of the quotation on the cited daf, but not as one phrase: Jastrow follows a manuscript
                # or Ar., or quotes the words in another order. All words but one for a quotation of three or more
                words = [w for w in self.variants(q, "")[0].split() if re.sub("[^א-ת]", "", w)]
                if len(words) >= 2 and (key, daf) in self.B:
                    txt = self.B[(key, daf)].translate(self.CO.FIN) + " "
                    hit = 0
                    for w in words:
                        rx, _, _ = self.S2.pattern(w)
                        if rx and re.search(r"(?:^| )" + rx.replace(r"\S* ", r"\S*(?: |$)") + r"(?= |$)", txt): hit += 1
                    if hit >= (len(words) if len(words) == 2 else len(words) - 1):
                        stats["found_words_at"] += 1; continue
                variant = bool(re.match(r"\s*(?:\S+\s+){0,12}?(?:Ar\.|Ms\.|ed\.|Var\.|read\b)", after))
                near = [d for d in self.daf_list(key, daf) if found(key, d)]
                where = None
                if near:
                    kind, sev, where = "talmud_near", 2, near
                else:
                    same = sorted(d for (k, d) in self.B if k == key and found(k, d))
                    if same: kind, sev, where = "talmud_elsewhere", 1, same[:5]
                    else:
                        other = [h for h in self.S2.find(q) if h[0] == "b"][:5]
                        if other: kind, sev, where = "talmud_other_tractate", 1, ["%s %s" % (h[1], h[2]) for h in other]
                        else: kind, sev = "talmud_not_found", 3
                if variant and sev == 1: sev = 2                 # Jastrow quotes a variant reading here
                stats[kind] += 1
                out.append(finding(pid, kind, sev, eid, cite, {
                    "talmud_near": "the quotation is on a neighbouring amud",
                    "talmud_elsewhere": "the quotation is elsewhere in the tractate",
                    "talmud_other_tractate": "the quotation is in another tractate",
                    "talmud_not_found": "the quotation was not found (abbreviated or paraphrased?)"}[kind],
                    quote=q, found=where, ref="%s %s" % (key, daf), context=t[max(0, m.start() - 60):m.end() + 100]))
        return out, stats
