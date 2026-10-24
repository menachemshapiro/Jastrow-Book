#!/usr/bin/env python3
"""Index every citation of Targum Onkelos in the dictionary by book, chapter and verse, for the site's finder.

Jastrow cites Onkelos as "Targ. O. Gen. XVII, 4", or simply "Targ. Gen. XVII, 4" (a Targum to the Torah
without a qualifier is Onkelos; Targum Yerushalmi and Pseudo-Jonathan are "Targ. Y.", "Targ. Y. I",
"Targ. Y. II"). Follow-on references are resolved to the Onkelos citation just before them:
"Targ. O. ib. XLI, 43" (same book), "; XXI, 3" or "ib. XXI, 3" (same book), "; 6" or "ib. 6" (same chapter).
Sefaria's own links are used only to report how often the two agree.

usage: python3 build/targum_index.py <site dir>      (reads data/c*.json, writes data/targum/)"""
import sys, os, re, json, glob
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
SITE = sys.argv[1] if len(sys.argv) > 1 else "."
sys.argv = [sys.argv[0], SITE]
import talmud_index as T            # entry_texts(), roman(), ROM

BOOKS = [("Gen", "Genesis", "בראשית", 50), ("Ex", "Exodus", "שמות", 40), ("Lev", "Leviticus", "ויקרא", 27),
         ("Num", "Numbers", "במדבר", 36), ("Deut", "Deuteronomy", "דברים", 34)]
AB = {b[0]: b[1] for b in BOOKS}
HEB = {b[1]: b[2] for b in BOOKS}
NCH = {b[1]: b[3] for b in BOOKS}
BK = r"(?:Gen|Ex|Exod|Lev|Num|Deut)"
ROM = r"(?:XL|L?X{0,3})(?:IX|IV|V?I{0,3})"        # I to L (Genesis has fifty chapters)

P = re.compile(
    # Targum Onkelos: "Targ. Gen. XVII, 4", "Targ. O. Gen. XVII, 4", "Targ. O. ib. XLI, 43"
    r"(?P<o>(?<![A-HJ-Z])Targ\.\s+(?:O\.,?\s+)?(?P<ob>" + BK + r"\.|ib\.)\s*(?P<oc>" + ROM + r")\b\.?,? (?P<ov>\d+))"
    # "Targ. O. ib. 16": the same chapter
    r"|(?P<oib>(?<![A-Z])Targ\.\s+(?:O\.,?\s+)?ib\.,? (?P<oibv>\d+)\b(?!\^))"
    # another Targum (Yerushalmi, Pseudo-Jonathan, the Prophets and Writings) or any other Targ. citation
    r"|(?P<tother>(?<![A-Z])Targ\.)"
    # a Bible reference: remembered for a following "Targ. ib.", ends an Onkelos run
    r"|(?P<bib>(?<![\w.])(?P<bb>" + BK + r")\.\s*(?P<bc>" + ROM + r")\b,? \d+)"
    # follow-ons: "ib. XXI, 3", "ib. 6", "; XXI, 3", "; 6"
    r"|(?P<ibc>\b[Ii]b\.,?\s+(?P<ic>" + ROM + r")\b,? (?P<iv>\d+))"
    r"|(?P<ibv>\b[Ii]b\.,? (?P<iv2>\d+)\b(?!\^))"
    r"|(?P<cc>(?<=[;,] )(?P<cc_c>" + ROM + r")\b,? (?P<cc_v>\d+)\b(?!\^))"
    r"|(?P<cv>(?<=[;,] )(?P<cv_v>\d+)\b(?![\^\d]))"
    r"|(?P<cv2>(?<=\d)[-–](?P<cv2_v>\d+)\b)"
    # anything else that starts a citation ends the run
    r"|(?P<other>(?<![\w.])(?:(?![A-Z]?Targ\.)[A-Z][\wḤḥ’'é]*\.,? ){1,3}(?:" + ROM + r"\b,? \d|\d+\^|s\. \d|p\. \d|\d))"
)


def snippet(t, a, e):
    """the citation as Jastrow gives it, then what follows it up to the next citation"""
    rest = t[e:e + 160]
    m = re.search(r";|\.—|\.\s+[A-Z]|(?<=[.,)] )(?:[A-Z][a-zḥ]*\. ){1,3}(?:[IVXL]+\b|\d)|\b[Ii]b\. (?:[IVXL]+\b|\d)|\bTarg\.", rest)
    if m: rest = rest[:m.start()]
    s = (t[a:e] + rest)
    if s.count("(") > s.count(")"):              # don't stop inside a parenthesis: finish it, or leave it out
        k = t.find(")", a + len(s))
        s = t[a:k + 1] if 0 <= k - (a + len(s)) < 100 else s[:s.rfind("(")]
    s = s.strip().rstrip(",")
    if len(s) > 140: s = s[:140].rsplit(" ", 1)[0] + " …"
    return s


def main():
    out = defaultdict(lambda: defaultdict(list))
    agree = Counter(); disagree = []; unlinked = 0
    for eid, t, refs in T.entry_texts():
        ctx = None              # [book, chapter] of the Onkelos citation being continued
        lastbib = None          # the last Torah book named, for "Targ. ib."
        for m in P.finditer(t):
            g = m.group
            hit = None
            if g("o"):
                b = g("ob")
                if b == "ib.":
                    book = ctx[0] if ctx else (lastbib[0] if lastbib else None)
                    if not book: ctx = None; continue
                else:
                    book = AB[b.rstrip(".").replace("Exod", "Ex")]
                ctx = [book, T.roman(g("oc"))]
                hit = (book, ctx[1], int(g("ov")))
            elif g("oib"):
                src = ctx or lastbib
                if not src: continue
                ctx = list(src)
                hit = (ctx[0], ctx[1], int(g("oibv")))
            elif g("tother"):
                ctx = None; continue
            elif g("bib"):
                lastbib = [AB[g("bb").replace("Exod", "Ex")], T.roman(g("bc"))]; ctx = None; continue
            elif g("other"):
                ctx = None; continue
            elif not ctx:
                continue
            elif g("ibc") or g("cc"):
                c, v = (g("ic"), g("iv")) if g("ibc") else (g("cc_c"), g("cc_v"))
                ctx = [ctx[0], T.roman(c)]
                hit = (ctx[0], ctx[1], int(v))
            elif g("ibv") or g("cv") or g("cv2"):
                v = g("iv2") or g("cv_v") or g("cv2_v")
                hit = (ctx[0], ctx[1], int(v))
            if not hit: continue
            book, ch, v = hit
            if not (1 <= ch <= NCH[book]) or not (1 <= v <= 90):
                continue
            lst = out[book][ch]
            cite = m.group(0).strip("() ")
            if not (lst and lst[-1][0] == eid and lst[-1][1] == v):     # one row per entry and verse, with every citation of it
                lst.append([eid, v, snippet(t, m.start(), m.end()), [cite]])
            elif cite not in lst[-1][3]:
                lst[-1][3].append(cite)
            r = refs.get(m.start())
            if r:
                rm = re.match(r"Onkelos_([A-Za-z]+)\.(\d+)\.(\d+)", r)
                if rm:
                    ok = (rm.group(1), int(rm.group(2)), int(rm.group(3))) == (book, ch, v)
                    agree[ok] += 1
                    if not ok: disagree.append((eid, t[m.start():m.start() + 40], r, book, ch, v))
            else:
                unlinked += 1
    os.makedirs(os.path.join(SITE, "data/targum"), exist_ok=True)
    for f in glob.glob(os.path.join(SITE, "data/targum/*.json")): os.remove(f)
    idx = []
    for _, book, heb, _ in BOOKS:
        chs = out.get(book, {})
        data = {}
        for ch in sorted(chs):
            data[str(ch)] = sorted(chs[ch], key=lambda r: (r[1], r[0]))
        json.dump(data, open(os.path.join(SITE, "data/targum/o_%s.json" % book), "w"), ensure_ascii=False, separators=(",", ":"))
        idx.append([book, heb, [[int(c), len(v)] for c, v in data.items()]])
    json.dump({"o": idx}, open(os.path.join(SITE, "data/targum/index.json"), "w"), ensure_ascii=False, separators=(",", ":"))
    n = sum(len(v) for b in out.values() for v in b.values())
    print("Onkelos citations", n, "; agreement with Sefaria's links:", dict(agree), "; not linked by Sefaria:", unlinked)
    json.dump(disagree, open("/tmp/claude-0/targum_disagree.json", "w"), ensure_ascii=False, indent=0)


if __name__ == "__main__":
    main()
