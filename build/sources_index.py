#!/usr/bin/env python3
"""Index the dictionary's citations of the Mishnah, the Tosefta, Yalkut Shimoni, Midrash Tehillim and
Pesikta Rabbati, for the site's finder.

Jastrow's forms:
  Mishnah           Ber. VII, 1   Kel. XXVI, 4   Ab. I, 5 (Aboth)          tractate, chapter, mishnah
  Tosefta           Tosef. Sabb. XVI (XVII), 3   Tosef. Kel. B. Mets. VIII, 6   Tosef. ib. II, 7
  Yalkut Shimoni    Yalk. Gen. 61   Yalk. Ps. 863   Yalk. ib. 874              book, remez
  Midrash Tehillim  Midr. Till. to Ps. XXII, 4                                 psalm, verse
  Pesikta Rabbati   Pesik. R. s. 18                                            section (piska)
A chapter in parentheses ("XVI (XVII)") is the other numbering; the first is the one indexed. Follow-ons
are resolved to the citation just before them ("Ib. II, 2", "ib. 5", "; III, 4", "; s. 20"), and
"Tosef. ib." to the tractate cited just before. Sefaria's own links are used only to report agreement.

usage: python3 build/sources_index.py <site dir>      (reads data/c*.json, writes data/sources/)"""
import sys, os, re, json, glob
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
SITE = sys.argv[1] if len(sys.argv) > 1 else "."
sys.argv = [sys.argv[0], SITE]
import talmud_index as T            # entry_texts(), roman()
import paths

# tractate: (Jastrow's abbreviations, Hebrew name, Sefaria's Mishnah title, Sefaria's Tosefta title)
TR = [
    ("Berakhot", ["Ber."], "ברכות", "Berakhot"), ("Peah", ["Peah", "Peah."], "פאה", "Peah"), ("Demai", ["Dem."], "דמאי", "Demai"),
    ("Kilayim", ["Kil."], "כלאים", "Kilaim"), ("Sheviit", ["Shebi.", "Sheb."], "שביעית", "Shevi'it"), ("Terumot", ["Ter."], "תרומות", "Terumot"),
    ("Maasrot", ["Maasr.", "Maas."], "מעשרות", "Ma'asrot"), ("Maaser_Sheni", ["Maas. Sh."], "מעשר שני", "Ma'aser_Sheni"),
    ("Challah", ["Ḥall."], "חלה", "Challah"), ("Orlah", ["Orl."], "ערלה", "Orlah"), ("Bikkurim", ["Bicc."], "ביכורים", "Bikkurim"),
    ("Shabbat", ["Sabb.", "Sab."], "שבת", "Shabbat"), ("Eruvin", ["Erub."], "עירובין", "Eiruvin"), ("Pesachim", ["Pes."], "פסחים", "Pesachim"),
    ("Shekalim", ["Shek."], "שקלים", "Shekalim"), ("Yoma", ["Yoma"], "יומא", "Yoma"), ("Sukkah", ["Succ."], "סוכה", "Sukkah"),
    ("Beitzah", ["Bets."], "ביצה", "Beitsah"), ("Rosh_Hashanah", ["R. Hash."], "ראש השנה", "Rosh_Hashanah"),
    ("Taanit", ["Taan."], "תענית", "Ta'anit"), ("Megillah", ["Meg."], "מגילה", "Megillah"), ("Moed_Katan", ["M. Kat."], "מועד קטן", "Moed_Kattan"),
    ("Chagigah", ["Ḥag."], "חגיגה", "Chagigah"), ("Yevamot", ["Yeb."], "יבמות", "Yevamot"), ("Ketubot", ["Keth."], "כתובות", "Ketubot"),
    ("Nedarim", ["Ned."], "נדרים", "Nedarim"), ("Nazir", ["Naz."], "נזיר", "Nazir"), ("Sotah", ["Sot.", "Sotah"], "סוטה", "Sotah"),
    ("Gittin", ["Gitt.", "Git."], "גיטין", "Gittin"), ("Kiddushin", ["Kidd.", "Kid."], "קידושין", "Kiddushin"),
    ("Bava_Kamma", ["B. Kam."], "בבא קמא", "Bava_Kamma"), ("Bava_Metzia", ["B. Mets."], "בבא מציעא", "Bava_Metzia"),
    ("Bava_Batra", ["B. Bath."], "בבא בתרא", "Bava_Batra"), ("Sanhedrin", ["Snh."], "סנהדרין", "Sanhedrin"), ("Makkot", ["Macc."], "מכות", "Makkot"),
    ("Shevuot", ["Shebu."], "שבועות", "Shevuot"), ("Eduyot", ["Eduy."], "עדיות", "Eduyot"), ("Avodah_Zarah", ["Ab. Zar."], "עבודה זרה", "Avodah_Zarah"),
    ("Avot", ["Ab.", "Aboth"], "אבות", None), ("Horayot", ["Hor."], "הוריות", "Horayot"),
    ("Zevachim", ["Zeb."], "זבחים", "Zevahim"), ("Menachot", ["Men."], "מנחות", "Menahot"), ("Chullin", ["Ḥull."], "חולין", "Chullin"),
    ("Bekhorot", ["Bekh."], "בכורות", "Bekhorot"), ("Arakhin", ["Arakh."], "ערכין", "Arakhin"), ("Temurah", ["Tem."], "תמורה", "Temurah"),
    ("Keritot", ["Kerith.", "Ker."], "כריתות", "Keritot"), ("Meilah", ["Meïl.", "Meil."], "מעילה", "Meilah"), ("Tamid", ["Tam."], "תמיד", None),
    ("Middot", ["Midd."], "מדות", None), ("Kinnim", ["Kinn."], "קנים", None),
    ("Kelim", ["Kel."], "כלים", None), ("Kelim_Kamma", ["Kel. B. Kam."], "כלים בבא קמא", "Kelim_Kamma"),
    ("Kelim_Metsia", ["Kel. B. Mets."], "כלים בבא מציעא", "Keilim_Metsia"), ("Kelim_Batra", ["Kel. B. Bath."], "כלים בבא בתרא", "Keilim_Batra"),
    ("Oholot", ["Ohol."], "אהלות", "Ohalot"), ("Negaim", ["Neg."], "נגעים", "Negaim"), ("Parah", ["Par.", "Parah"], "פרה", "Parah"),
    ("Tahorot", ["Toh."], "טהרות", "Tahorot"), ("Mikvaot", ["Mikv."], "מקואות", "Mikvaot"), ("Niddah", ["Nidd."], "נדה", "Niddah"),
    ("Makhshirin", ["Makhsh."], "מכשירין", "Makhshirin"), ("Zavim", ["Zab."], "זבים", "Zavim"), ("Tevul_Yom", ["T’bul Yom"], "טבול יום", "Tevul_Yom"),
    ("Yadayim", ["Yad."], "ידים", "Yadayim"), ("Oktzin", ["Ukts."], "עוקצין", "Uktsin"),
]
TKEYS = [t[0] for t in TR]
TAB = {a: t[0] for t in TR for a in t[1]}
THEB = {t[0]: t[2] for t in TR}
TOSTITLE = {t[0]: t[3] for t in TR}
MISHNAH_ONLY_PARTS = {"Kelim_Kamma", "Kelim_Metsia", "Kelim_Batra"}      # the Tosefta divides Kelim in three; the Mishnah does not
MTITLE = lambda k: "Pirkei_Avot" if k == "Avot" else "Mishnah_" + k
TRX = "|".join(sorted((re.escape(a) for a in TAB), key=len, reverse=True))

# Yalkut Shimoni: Jastrow's book -> (Hebrew, part of the Yalkut)
YB = [("Gen.", "בראשית", "Torah"), ("Ex.", "שמות", "Torah"), ("Lev.", "ויקרא", "Torah"), ("Num.", "במדבר", "Torah"), ("Deut.", "דברים", "Torah"),
      ("Josh.", "יהושע", "Nach"), ("Jud.", "שופטים", "Nach"), ("Sam.", "שמואל", "Nach"), ("Kings", "מלכים", "Nach"), ("Is.", "ישעיה", "Nach"),
      ("Jer.", "ירמיה", "Nach"), ("Ez.", "יחזקאל", "Nach"), ("Hos.", "הושע", "Nach"), ("Joel", "יואל", "Nach"), ("Am.", "עמוס", "Nach"),
      ("Ob.", "עובדיה", "Nach"), ("Jon.", "יונה", "Nach"), ("Mic.", "מיכה", "Nach"), ("Nah.", "נחום", "Nach"), ("Hab.", "חבקוק", "Nach"),
      ("Zeph.", "צפניה", "Nach"), ("Hag.", "חגי", "Nach"), ("Zech.", "זכריה", "Nach"), ("Mal.", "מלאכי", "Nach"), ("Ps.", "תהלים", "Nach"),
      ("Prov.", "משלי", "Nach"), ("Job", "איוב", "Nach"), ("Cant.", "שיר השירים", "Nach"), ("Ruth", "רות", "Nach"), ("Lam.", "איכה", "Nach"),
      ("Koh.", "קהלת", "Nach"), ("Esth.", "אסתר", "Nach"), ("Dan.", "דניאל", "Nach"), ("Ezra", "עזרא", "Nach"), ("Neh.", "נחמיה", "Nach"),
      ("Chr.", "דברי הימים", "Nach")]
YALIAS = {"Ezek.": "Ez.", "Job.": "Job", "Amos": "Am.", "Zach.": "Zech.", "Judg.": "Jud.", "I Sam.": "Sam.", "II Sam.": "Sam.",
          "I Kings": "Kings", "II Kings": "Kings", "I Chr.": "Chr.", "II Chr.": "Chr.", "Exod.": "Ex.", "Ruth.": "Ruth"}
YKEY = {b[0]: b[0].rstrip(".").replace(" ", "_") for b in YB}
YHEB = {YKEY[b[0]]: b[1] for b in YB}
YPART = {YKEY[b[0]]: b[2] for b in YB}
YBX = "|".join(sorted([re.escape(b[0]) for b in YB] + [re.escape(a) for a in YALIAS], key=len, reverse=True))

ROM = r"(?=[IVXLC])C?(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})"
ALT = r"(?:\s*\(" + ROM + r"\))?"           # the other chapter numbering, in parentheses
MOD = r"(?:,?\s*(?:beg|end)\.?)?"

P = re.compile(
    # Tosefta
    r"(?P<tos>\bTosef\.\s+(?P<tt>" + TRX + r"|ib\.)\s*(?P<tc>" + ROM + r")\b" + ALT + r",?\s*(?:(?:beg|end)\.?,?\s*)?(?P<th>\d+)?\b(?!\^))"
    # Yalkut Shimoni, Midrash Tehillim, Pesikta Rabbati
    r"|(?P<yal>\bYalk\.\s+(?P<yb>" + YBX + r"|ib\.)\s*(?P<yr>\d+)\b(?!\^))"
    r"|(?P<mt>\bMidr\.\s+Till\.,?\s+to\s+Ps\.\s*(?P<mtp>" + ROM + r")\b(?:,\s*(?P<mtv>\d+)\b)?)"
    r"|(?P<pr>\bPesik\.\s+R\.,?\s+(?:addit\.\s+)?s\.\s*(?P<prs>\d+))"
    # the Mishnah: a tractate, a chapter, a mishnah (with no folio side after it, which would make it the Jerusalem Talmud)
    r"|(?P<mi>(?<![\w.’])(?<!Y\. )(?<!Bab\. )(?P<mt_>" + TRX + r")\s+(?P<mc>" + ROM + r")\b" + ALT + r",\s*" + MOD + r"\s*(?P<mn>\d+)\b(?![\^\d]))"
    # a tractate named without a chapter: remembered, for a following "Tosef. ib."
    r"|(?P<tn>(?<![\w.’])(?:Y\.\s+|Bab\.\s+)?(?P<tnt>" + TRX + r")\s+(?:\d|l\.\s*c\.|" + ROM + r"\b))"
    # a book of the Bible (in a Bible reference, "Sifré Deut.", "Deut. R." ...): remembered for "Yalk. ib."; ends a run
    r"|(?P<bk>(?<![\w.])(?P<bkb>" + YBX + r")(?=\s))"
    # follow-ons
    r"|(?P<ibc>\b[Ii]b\.,?\s+(?P<ic>" + ROM + r")\b" + ALT + r",\s*(?P<iv>\d+)\b(?![\^\d]))"
    r"|(?P<ibv>\b[Ii]b\.,?\s+(?P<iv2>\d+)\b(?![\^\d]))"
    r"|(?P<ibs>\b[Ii]b\.,?\s+s\.\s*(?P<isn>\d+))"
    r"|(?P<ibp>\b[Ii]b\.,?\s+to\s+Ps\.\s*(?P<ibpp>" + ROM + r")\b(?:,\s*(?P<ibpv>\d+)\b)?)"
    r"|(?P<cs>(?<=[;,] )s\.\s*(?P<csn>\d+)\b)"
    r"|(?P<cc>(?<=[;,] )(?P<cc_c>" + ROM + r")\b" + ALT + r",\s*(?P<cc_v>\d+)\b(?![\^\d]))"
    r"|(?P<cv>(?<=[;,] )(?P<cv_v>\d+)\b(?![\^\d]))"
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
    out = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))     # corpus -> book -> unit -> rows
    agree = Counter(); unlinked = Counter(); dis = []
    for eid, t, refs in T.entry_texts():
        ctx = None              # [corpus, book, unit]
        lasttr = None           # the last tractate named, for "Tosef. ib."
        lastyb = None           # the last Yalkut book
        for m in P.finditer(t):
            g = m.group
            hit = None
            if g("tos"):
                tt = g("tt")
                key = lasttr if tt == "ib." else TAB[tt]
                if key == "Kelim" and tt != "ib.": key = "Kelim"
                if not key or not TOSTITLE.get(key):
                    ctx = None; continue
                ch = T.roman(g("tc"))
                lasttr = key
                if g("th"):
                    ctx = ["t", key, ch]; hit = ("t", key, ch, int(g("th")))
                else:
                    ctx = ["t", key, ch]; hit = ("t", key, ch, 0)
            elif g("yal"):
                b = g("yb")
                if b == "ib.":
                    if not lastyb: ctx = None; continue
                    key = lastyb
                else:
                    key = YKEY[YALIAS.get(b, b)]
                lastyb = key
                ctx = ["ys", key, None]; hit = ("ys", key, int(g("yr")), 0)
            elif g("mt"):
                ctx = ["mt", "Psalms", T.roman(g("mtp"))]; hit = ("mt", "Psalms", ctx[2], int(g("mtv") or 0))
            elif g("pr"):
                ctx = ["pr", "Pesikta_Rabbati", None]; hit = ("pr", "Pesikta_Rabbati", int(g("prs")), 0)
            elif g("mi"):
                key = TAB[g("mt_")]
                lasttr = key
                if key in MISHNAH_ONLY_PARTS: ctx = None; continue
                ch = T.roman(g("mc"))
                ctx = ["m", key, ch]; hit = ("m", key, ch, int(g("mn")))
            elif g("bk"):
                b = g("bkb"); lastyb = YKEY[YALIAS.get(b, b)]; ctx = None; continue
            elif g("tn"):
                lasttr = TAB[g("tnt")]; ctx = None; continue
            elif g("other"):
                ctx = None; continue
            elif not ctx:
                continue
            elif g("ibc") or g("cc"):
                if ctx[0] not in ("m", "t"): continue
                c, v = (g("ic"), g("iv")) if g("ibc") else (g("cc_c"), g("cc_v"))
                ctx = [ctx[0], ctx[1], T.roman(c)]; hit = (ctx[0], ctx[1], ctx[2], int(v))
            elif g("ibv") or g("cv"):
                v = int(g("iv2") or g("cv_v"))
                if ctx[0] in ("m", "t", "mt"): hit = (ctx[0], ctx[1], ctx[2], v)
                elif ctx[0] == "ys": hit = ("ys", ctx[1], v, 0)
            elif g("ibs") or g("cs"):
                if ctx[0] == "pr": hit = ("pr", ctx[1], int(g("isn") or g("csn")), 0)
            elif g("ibp"):
                if ctx[0] == "mt":
                    ctx = ["mt", "Psalms", T.roman(g("ibpp"))]; hit = ("mt", "Psalms", ctx[2], int(g("ibpv") or 0))
            if not hit: continue
            corp, book, unit, v = hit
            if not (1 <= unit <= 1100) or v > 200: continue
            if corp in ("m", "t") and unit > 30: continue
            if corp == "mt" and unit > 150: continue
            if corp == "pr" and unit > 60: continue
            lst = out[corp][book][unit]
            cite = m.group(0).strip("() ")
            if not (lst and lst[-1][0] == eid and lst[-1][1] == v):
                lst.append([eid, v, snippet(t, m.start(), m.end()), [cite]])
            elif cite not in lst[-1][3]:
                lst[-1][3].append(cite)
            r = refs.get(m.start())
            if r:
                rm = re.match(r"(.+?)\.(\d+)(?:\.(\d+))?", r)
                if rm:
                    want = {"m": (MTITLE(book), unit, v), "t": ("Tosefta_" + (TOSTITLE.get(book) or ""), unit, v),
                            "ys": ("Yalkut_Shimoni_on_" + YPART.get(book, ""), unit, None), "mt": ("Midrash_Tehillim", unit, None),
                            "pr": ("Pesikta_Rabbati", unit, None)}[corp]
                    got = (rm.group(1), int(rm.group(2)), int(rm.group(3)) if rm.group(3) else None)
                    # the Tosefta's halakhot are numbered differently in Zuckermandel's edition and Sefaria's, so only its
                    # chapters are compared; elsewhere a level only one side gives is not compared
                    deep = want[2] is not None and got[2] is not None and v and corp != "t"
                    ok = got[:2] == want[:2] and (not deep or got[2] == want[2])
                    agree[corp, ok] += 1
                    if not ok and len(dis) < 3000: dis.append((corp, eid, t[m.start():m.start() + 45], r, book, unit, v))
            else:
                unlinked[corp] += 1
    D = os.path.join(SITE, "data/sources")
    os.makedirs(D, exist_ok=True)
    for f in glob.glob(os.path.join(D, "*.json")): os.remove(f)
    idx = {}
    order = {"m": TKEYS, "t": TKEYS, "ys": [YKEY[b[0]] for b in YB], "mt": ["Psalms"], "pr": ["Pesikta_Rabbati"]}
    heb = {"m": THEB, "t": THEB, "ys": YHEB, "mt": {"Psalms": "מדרש תהלים"}, "pr": {"Pesikta_Rabbati": "פסיקתא רבתי"}}
    for corp in ("m", "t", "ys", "mt", "pr"):
        idx[corp] = []
        for book in order[corp]:
            units = out[corp].get(book)
            if not units: continue
            data = {str(u): sorted(units[u], key=lambda r: (r[1], r[0])) for u in sorted(units)}
            json.dump(data, open(os.path.join(D, "%s_%s.json" % (corp, book)), "w"), ensure_ascii=False, separators=(",", ":"))
            sef = {"m": MTITLE(book), "t": "Tosefta_" + (TOSTITLE.get(book) or ""), "ys": "Yalkut_Shimoni_on_" + YPART.get(book, ""),
                   "mt": "Midrash_Tehillim", "pr": "Pesikta_Rabbati"}[corp]
            idx[corp].append([book, heb[corp][book], [[int(u), len(v)] for u, v in data.items()], "", sef])
    json.dump(idx, open(os.path.join(D, "index.json"), "w"), ensure_ascii=False, separators=(",", ":"))
    for corp in ("m", "t", "ys", "mt", "pr"):
        n = sum(len(v) for b in out[corp].values() for v in b.values())
        print("%-3s %6d citations; agree with Sefaria %d, disagree %d; not linked %d" % (corp, n, agree[corp, True], agree[corp, False], unlinked[corp]))
    json.dump(dis, open(paths.report("sources_disagree.json"), "w"), ensure_ascii=False, indent=0)


if __name__ == "__main__":
    main()
