#!/usr/bin/env python3
"""Index every citation of Midrash Rabbah in the dictionary, for the site's finder.

Jastrow cites the Rabbah on the Torah by section ("Gen. R. s. 19", "Lev. R. s. 1, end") and the Rabbah on
the five Megillot by the verse commented on ("Cant. R. to III, 4", "Lam. R. to I, 5"), or its introduction
("Lam. R. introd."). Follow-ons are resolved to the citation just before them: "; s. 78" and "Ib. s. 33"
(another section), "Ib. to V, 1" and "; IX, 10" (another verse), "ib. introd.". "l. c." (the place cited
above) is not counted again. Sefaria's own links are used only to report how often the two agree.

usage: python3 build/midrash_index.py <site dir>      (reads data/c*.json, writes data/midrash/)"""
import sys, os, re, json, glob
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
SITE = sys.argv[1] if len(sys.argv) > 1 else "."
sys.argv = [sys.argv[0], SITE]
import talmud_index as T            # entry_texts(), roman()

# book: (Jastrow's abbreviation, Hebrew name, kind: s = by section, v = by verse, sections or chapters)
BOOKS = {
    "Bereishit_Rabbah": ("Gen", "בראשית רבה", "s", 100), "Shemot_Rabbah": ("Ex", "שמות רבה", "s", 52),
    "Vayikra_Rabbah": ("Lev", "ויקרא רבה", "s", 37), "Bamidbar_Rabbah": ("Num", "במדבר רבה", "s", 23),
    "Devarim_Rabbah": ("Deut", "דברים רבה", "s", 11),
    "Shir_HaShirim_Rabbah": ("Cant", "שיר השירים רבה", "v", 8), "Ruth_Rabbah": ("Ruth", "רות רבה", "v", 4),
    "Eichah_Rabbah": ("Lam", "איכה רבה", "v", 5), "Kohelet_Rabbah": ("Koh", "קהלת רבה", "v", 12),
    "Esther_Rabbah": ("Esth", "אסתר רבה", "v", 10),
}
AB = {v[0]: b for b, v in BOOKS.items()}
ROM = r"(?=[IVXLC])C?(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})"
BK = "|".join(AB)
MODS = r"(?:,?\s*(?:beg|end|bot|top)\.?)?"

P = re.compile(
    r"(?P<rs>(?<![\w.])(?P<rsb>" + BK + r")\.? R\.,?\s+s\.\s*(?P<rsn>\d+))"
    r"|(?P<rv>(?<![\w.])(?P<rvb>" + BK + r")\.? R\.,?\s+to\s+(?P<rvc>" + ROM + r")\b,?\s*(?P<rvv>\d+))"
    r"|(?P<ri>(?<![\w.])(?P<rib>" + BK + r")\.? R\.,?\s+introd\.)"
    r"|(?P<rlc>(?<![\w.])(?:" + BK + r")\.? R\.,?\s+l\.\s*c\.)"
    r"|(?P<is>\b[Ii]b\.,?\s+s\.\s*(?P<isn>\d+))"
    r"|(?P<cs>(?<=[;,] )s\.\s*(?P<csn>\d+))"
    r"|(?P<iv>\b[Ii]b\.,?\s+to\s+(?P<ivc>" + ROM + r")\b,?\s*(?P<ivv>\d+))"
    r"|(?P<ii>\b[Ii]b\.,?\s+introd\.)"
    r"|(?P<cv>(?<=[;,] )(?:to\s+)?(?P<cvc>" + ROM + r")\b,\s*(?P<cvv>\d+)\b(?!\^))"
    # anything else that starts a citation ends the run
    r"|(?P<other>(?<![\w.])(?:[A-Z][\wḤḥ’'é]*\.,? ){1,3}(?:" + ROM + r"\b,? \d|\d+\^|s\. \d|p\. \d|\d|to " + ROM + r"\b))"
)


def snippet(t, a, e):
    rest = t[e:e + 160]
    m = re.search(r";|\.—|\.\s+[A-Z]|(?<=[.,)] )(?:[A-Z][a-zḥ]*\. ){1,3}(?:[IVXL]+\b|\d|s\. \d)|\b[Ii]b\. (?:[IVXL]+\b|\d|s\.)|\bTarg\.", rest)
    if m: rest = rest[:m.start()]
    s = t[a:e] + rest
    if s.count("(") > s.count(")"):
        k = t.find(")", a + len(s))
        s = t[a:k + 1] if 0 <= k - (a + len(s)) < 100 else s[:s.rfind("(")]
    s = s.strip().rstrip(",")
    if len(s) > 140: s = s[:140].rsplit(" ", 1)[0] + " …"
    return s


def main():
    out = defaultdict(lambda: defaultdict(list))        # book -> unit (section, or chapter; 0 = introduction) -> rows
    agree = Counter(); unlinked = 0
    for eid, t, refs in T.entry_texts():
        ctx = None              # [book, chapter] being continued
        for m in P.finditer(t):
            g = m.group
            hit = None
            if g("rs"):
                book = AB[g("rsb")]
                if BOOKS[book][2] != "s": ctx = None; continue
                ctx = [book, None]; hit = (book, int(g("rsn")), 0)
            elif g("rv"):
                book = AB[g("rvb")]
                if BOOKS[book][2] != "v": ctx = None; continue
                ctx = [book, T.roman(g("rvc"))]; hit = (book, ctx[1], int(g("rvv")))
            elif g("ri"):
                book = AB[g("rib")]
                if BOOKS[book][2] != "v": ctx = None; continue
                ctx = [book, 0]; hit = (book, 0, 0)
            elif g("rlc") or g("other"):
                ctx = None; continue
            elif not ctx:
                continue
            elif g("is") or g("cs"):
                if BOOKS[ctx[0]][2] != "s": continue
                hit = (ctx[0], int(g("isn") or g("csn")), 0)
            elif g("iv") or g("cv"):
                if BOOKS[ctx[0]][2] != "v": continue
                c, v = (g("ivc"), g("ivv")) if g("iv") else (g("cvc"), g("cvv"))
                ctx = [ctx[0], T.roman(c)]; hit = (ctx[0], ctx[1], int(v))
            elif g("ii"):
                if BOOKS[ctx[0]][2] != "v": continue
                hit = (ctx[0], 0, 0)
            if not hit: continue
            book, unit, v = hit
            if not (0 <= unit <= BOOKS[book][3]) or (BOOKS[book][2] == "s" and unit == 0): continue
            lst = out[book][unit]
            cite = m.group(0).strip("() ")
            if not (lst and lst[-1][0] == eid and lst[-1][1] == v):
                lst.append([eid, v, snippet(t, m.start(), m.end()), [cite]])
            elif cite not in lst[-1][3]:
                lst[-1][3].append(cite)
            r = refs.get(m.start())
            if r:
                rm = re.match(r"([A-Za-z_]+_Rabbah)\.(\d+)(?:\.(\d+))?", r)
                if rm and BOOKS[book][2] == "s":
                    agree[(rm.group(1), int(rm.group(2))) == (book, unit)] += 1
                elif rm and book in ("Shir_HaShirim_Rabbah", "Kohelet_Rabbah") and unit and rm.group(3):
                    agree[(rm.group(1), int(rm.group(2)), int(rm.group(3))) == (book, unit, v)] += 1
            else:
                unlinked += 1
    os.makedirs(os.path.join(SITE, "data/midrash"), exist_ok=True)
    for f in glob.glob(os.path.join(SITE, "data/midrash/*.json")): os.remove(f)
    idx = []
    for book in BOOKS:
        units = out.get(book)
        if not units: continue
        data = {str(u): sorted(units[u], key=lambda r: (r[1], r[0])) for u in sorted(units)}
        json.dump(data, open(os.path.join(SITE, "data/midrash/r_%s.json" % book), "w"), ensure_ascii=False, separators=(",", ":"))
        idx.append([book, BOOKS[book][1], [[int(u), len(v)] for u, v in data.items()], BOOKS[book][2]])
    json.dump({"r": idx}, open(os.path.join(SITE, "data/midrash/index.json"), "w"), ensure_ascii=False, separators=(",", ":"))
    n = sum(len(v) for b in out.values() for v in b.values())
    print("Midrash Rabbah citations", n, "; agreement with Sefaria's links:", dict(agree), "; not linked by Sefaria:", unlinked)
    for book in BOOKS: print("  ", book, sum(len(v) for v in out[book].values()))


if __name__ == "__main__":
    main()
