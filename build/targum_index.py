#!/usr/bin/env python3
"""Index every Targum citation in the dictionary by Targum, book, chapter and verse, for the site's finder.

Jastrow's forms (see his list of abbreviations):
  Targ. Gen. XVII, 4  /  Targ. O. Gen. XVII, 4     Onkelos (a Targum to the Torah without a qualifier)
  Targ. Y. Gen. ...   /  Targ. Y. I Gen. ...       Targum Yerushalmi I = "Yonatan" (Pseudo-Jonathan)
  Targ. Y. II, Gen. ...                            Targum Yerushalmi II (the Fragment Targum)
  Targ. Is. XXX, 2, Targ. I Sam. ...               Targum Yonatan to the Prophets
  Targ. Ps. ..., Targ. Job ..., Targ. II Esth. ... the Targumim to the Writings (II Esth. = Targum Sheni)
Follow-on references are resolved to the Targum citation just before them: "Targ. O. ib. XLI, 43" (same
book), "Targ. Y. ib." (same verse, another Targum), "; XXI, 3" or "ib. XXI, 3" (same book), "; 6" or
"ib. 6" (same chapter). Sefaria's own links are used only to report how often the two agree.

usage: python3 build/targum_index.py <site dir>      (reads data/c*.json, writes data/targum/)"""
import sys, os, re, json, glob
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
SITE = sys.argv[1] if len(sys.argv) > 1 else "."
sys.argv = [sys.argv[0], SITE]
import talmud_index as T            # entry_texts(), roman()

# book: (Jastrow's abbreviations, Hebrew name, chapters, section: t = Torah, n = Prophets, k = Writings, Sefaria name)
BOOKS = {
    "Genesis": (["Gen."], "בראשית", 50, "t"), "Exodus": (["Ex.", "Exod."], "שמות", 40, "t"),
    "Leviticus": (["Lev."], "ויקרא", 27, "t"), "Numbers": (["Num."], "במדבר", 36, "t"),
    "Deuteronomy": (["Deut."], "דברים", 34, "t"),
    "Joshua": (["Josh."], "יהושע", 24, "n"), "Judges": (["Jud.", "Judg."], "שופטים", 21, "n"),
    "I_Samuel": (["I Sam."], "שמואל א", 31, "n"), "II_Samuel": (["II Sam."], "שמואל ב", 24, "n"),
    "I_Kings": (["I Kings", "I Kings,"], "מלכים א", 22, "n"), "II_Kings": (["II Kings", "II Kings,"], "מלכים ב", 25, "n"),
    "Isaiah": (["Is."], "ישעיה", 66, "n"), "Jeremiah": (["Jer."], "ירמיה", 52, "n"), "Ezekiel": (["Ez.", "Ezek."], "יחזקאל", 48, "n"),
    "Hosea": (["Hos."], "הושע", 14, "n"), "Joel": (["Joel"], "יואל", 4, "n"), "Amos": (["Am.", "Amos"], "עמוס", 9, "n"),
    "Obadiah": (["Ob."], "עובדיה", 1, "n"), "Jonah": (["Jon."], "יונה", 4, "n"), "Micah": (["Mic."], "מיכה", 7, "n"),
    "Nahum": (["Nah."], "נחום", 3, "n"), "Habakkuk": (["Hab."], "חבקוק", 3, "n"), "Zephaniah": (["Zeph."], "צפניה", 3, "n"),
    "Haggai": (["Hag."], "חגי", 2, "n"), "Zechariah": (["Zech.", "Zach."], "זכריה", 14, "n"), "Malachi": (["Mal."], "מלאכי", 3, "n"),
    "Psalms": (["Ps."], "תהלים", 150, "k"), "Proverbs": (["Prov."], "משלי", 31, "k"), "Job": (["Job", "Job."], "איוב", 42, "k"),
    "Song_of_Songs": (["Cant."], "שיר השירים", 8, "k"), "Ruth": (["Ruth", "Ruth."], "רות", 4, "k"),
    "Lamentations": (["Lam."], "איכה", 5, "k"), "Ecclesiastes": (["Koh."], "קהלת", 12, "k"),
    "Esther": (["Esth."], "אסתר", 10, "k"), "Esther_II": (["II Esth."], "אסתר (תרגום שני)", 10, "k"),
    "I_Chronicles": (["I Chr.", "I Chron."], "דברי הימים א", 29, "k"), "II_Chronicles": (["II Chr.", "II Chron."], "דברי הימים ב", 36, "k"),
}
ORDER = list(BOOKS)
AB = {a: b for b, v in BOOKS.items() for a in v[0]}
BK = "|".join(sorted((re.escape(a) for a in AB), key=len, reverse=True))
# the Targumim, in the order the site lists them
CORPORA = [("o", "תרגום אונקלוס", "t"), ("yj", "תרגום יונתן על התורה", "t"), ("yr", "תרגום ירושלמי", "t"),
           ("n", "תרגום יונתן על הנביאים", "n"), ("k", "תרגום כתובים", "k")]
# Sefaria's titles, for the agreement check
def sefaria_title(corp, book):
    if corp == "o": return "Onkelos_" + book
    if corp == "yj": return "Targum_Jonathan_on_" + book
    if corp == "yr": return "Targum_Jerusalem,_" + book
    if corp == "n": return "Targum_Jonathan_on_" + book
    if book in ("I_Chronicles", "II_Chronicles"): return "Targum_of_" + book
    return "Aramaic_Targum_to_" + book
ROM = r"(?=[IVXLC])C?(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})"     # I to CL (Psalms has 150)
QUAL = r"(?P<q>O\.,?\s+|Y\.\s+II,?\s+|Y\.\s+I\s+|Y\.\s+)?"

P = re.compile(
    # a Targum citation: "Targ. Gen. XVII, 4", "Targ. Y. II, Deut. XXXII, 2", "Targ. O. ib. XLI, 43", "Targ. Y. ib. 16", "Targ. Y. ib."
    r"(?P<tg>(?<![A-HJ-Z])Targ\.\s+" + QUAL + r"(?P<b>" + BK + r"|ib\.)\s*(?:(?P<c>" + ROM + r")\b\.?,?\s*(?P<v>\d+)\b(?!\^)|(?P<v2>\d+)\b(?!\^))?)"
    # any other Targ. citation (a book of the Bible without a Targum, or a form not read) ends the run
    r"|(?P<tother>(?<![A-HJ-Z])Targ\.)"
    # a Bible reference: remembered for a following "Targ. ib."
    r"|(?P<bib>(?<![\w.])(?P<bb>" + BK + r")\s*(?P<bc>" + ROM + r")\b,? (?P<bv>\d+))"
    # follow-ons: "ib. XXI, 3", "ib. 6", "; XXI, 3", "; 6", "4-6"
    r"|(?P<ibc>\b[Ii]b\.,?\s+(?P<ic>" + ROM + r")\b,? (?P<iv>\d+))"
    r"|(?P<ibv>\b[Ii]b\.,? (?P<iv2>\d+)\b(?!\^))"
    r"|(?P<cc>(?<=[;,] )(?P<cc_c>" + ROM + r")\b,? (?P<cc_v>\d+)\b(?!\^))"
    r"|(?P<cv>(?<=[;,] )(?P<cv_v>\d+)\b(?![\^\d]))"
    r"|(?P<cv2>(?<=\d)[-–](?P<cv2_v>\d+)\b)"
    # anything else that starts a citation ends the run
    r"|(?P<other>(?<![\w.])(?:(?![A-Z]?Targ\.)[A-Z][\wḤḥ’'é]*\.,? ){1,3}(?:" + ROM + r"\b,? \d|\d+\^|s\. \d|p\. \d|\d))"
)


def corpus_of(q, book):
    sec = BOOKS[book][3]
    q = (q or "").replace(",", "").split()
    if sec != "t":
        return None if q else sec          # "Targ. Y. Is." does not exist; anything else is the Prophets or Writings
    if not q: return "o"
    if q == ["O."]: return "o"
    if q == ["Y.", "II"]: return "yr"
    return "yj"                            # "Y." and "Y. I"


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
    out = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))      # corpus -> book -> chapter -> rows
    agree = Counter(); disagree = []; unlinked = Counter()
    for eid, t, refs in T.entry_texts():
        ctx = None              # [corpus, book, chapter, verse] of the Targum citation being continued
        lastbib = None          # [book, chapter, verse] of the last Bible reference, for "Targ. ib."
        for m in P.finditer(t):
            g = m.group
            hit = None
            if g("tg"):
                b = g("b")
                src = ctx[1:] if ctx else lastbib
                if b == "ib.":
                    if not src: ctx = None; continue
                    book = src[0]
                else:
                    book = AB[b]
                corp = corpus_of(g("q"), book)
                if not corp: ctx = None; continue
                if g("c"): ch, v = T.roman(g("c")), int(g("v"))
                elif g("v2") and b == "ib." and src: ch, v = src[1], int(g("v2"))
                elif b == "ib." and src and src[2]: ch, v = src[1], src[2]          # "Targ. Y. ib.": the same verse
                else: ctx = None; continue
                ctx = [corp, book, ch, v]
                hit = (corp, book, ch, v)
            elif g("tother"):
                ctx = None; continue
            elif g("bib"):
                lastbib = [AB[g("bb")], T.roman(g("bc")), int(g("bv"))]; ctx = None; continue
            elif g("other"):
                ctx = None; continue
            elif not ctx:
                continue
            elif g("ibc") or g("cc"):
                c, v = (g("ic"), g("iv")) if g("ibc") else (g("cc_c"), g("cc_v"))
                ctx = [ctx[0], ctx[1], T.roman(c), int(v)]
                hit = tuple(ctx)
            elif g("ibv") or g("cv") or g("cv2"):
                v = int(g("iv2") or g("cv_v") or g("cv2_v"))
                ctx = [ctx[0], ctx[1], ctx[2], v]
                hit = tuple(ctx)
            if not hit: continue
            corp, book, ch, v = hit
            if not (1 <= ch <= BOOKS[book][2]) or not (1 <= v <= 180):
                continue
            lst = out[corp][book][ch]
            cite = m.group(0).strip("() ")
            if not (lst and lst[-1][0] == eid and lst[-1][1] == v):     # one row per entry and verse, with every citation of it
                lst.append([eid, v, snippet(t, m.start(), m.end()), [cite]])
            elif cite not in lst[-1][3]:
                lst[-1][3].append(cite)
            r = refs.get(m.start())
            if r:
                rm = re.match(r"(.+?)\.(\d+)\.(\d+)", r)
                if rm and re.match(r"(Onkelos|Targum|Aramaic_Targum)", r):
                    ok = (rm.group(1), int(rm.group(2)), int(rm.group(3))) == (sefaria_title(corp, book), ch, v)
                    agree[corp, ok] += 1
                    if not ok: disagree.append((eid, t[m.start():m.start() + 40], r, corp, book, ch, v))
            else:
                unlinked[corp] += 1
    os.makedirs(os.path.join(SITE, "data/targum"), exist_ok=True)
    for f in glob.glob(os.path.join(SITE, "data/targum/*.json")): os.remove(f)
    idx = {}
    for corp, heb_c, sec in CORPORA:
        idx[corp] = []
        for book in ORDER:
            chs = out[corp].get(book)
            if not chs: continue
            data = {str(ch): sorted(chs[ch], key=lambda r: (r[1], r[0])) for ch in sorted(chs)}
            json.dump(data, open(os.path.join(SITE, "data/targum/%s_%s.json" % (corp, book)), "w"), ensure_ascii=False, separators=(",", ":"))
            idx[corp].append([book, BOOKS[book][1], [[int(c), len(v)] for c, v in data.items()]])
    json.dump(idx, open(os.path.join(SITE, "data/targum/index.json"), "w"), ensure_ascii=False, separators=(",", ":"))
    for corp, heb_c, _ in CORPORA:
        n = sum(len(v) for b in out[corp].values() for v in b.values())
        print("%-3s %6d citations in %2d books; agree with Sefaria %d, disagree %d; not linked by Sefaria %d" % (
            corp, n, len(out[corp]), agree[corp, True], agree[corp, False], unlinked[corp]))
    json.dump(disagree, open("/tmp/claude-0/targum_disagree.json", "w"), ensure_ascii=False, indent=0)


if __name__ == "__main__":
    main()
