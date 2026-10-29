#!/usr/bin/env python3
"""Index every Talmud citation in the dictionary by tractate and daf, for the site's Talmud finder.

Jastrow cites the Babylonian Talmud by folio and side ("Ber. 26^b") and the Jerusalem Talmud by
chapter and the folio and column of the Krotoshin edition ("Y. Ber. VIII, 12^c"). Citations are read
from the entry text itself, using Jastrow's abbreviations; "Ib." and bare folio numbers ("; 33^b") are
resolved to the tractate cited just before them. Sefaria's own links are used only to report how
often the two agree.

usage: python3 build/talmud_index.py <site dir>      (reads data/c*.json, writes data/talmud/)"""
import sys, os, re, json, glob, html
from collections import defaultdict, Counter

SITE = sys.argv[1] if len(sys.argv) > 1 else "."

# Jastrow's abbreviation -> (Sefaria-style key, Hebrew name); "b" = has Babylonian Gemara, "y" = has Jerusalem Gemara
TRACT = [
    (["Ber."], "Berakhot", "ברכות", "by"), (["Peah", "Peah."], "Peah", "פאה", "y"), (["Dem."], "Demai", "דמאי", "y"),
    (["Kil."], "Kilayim", "כלאים", "y"), (["Shebi.", "Sheb.", "Shebi"], "Sheviit", "שביעית", "y"), (["Ter."], "Terumot", "תרומות", "y"),
    (["Maasr.", "Maas."], "Maasrot", "מעשרות", "y"), (["Maas. Sh.", "Maas Sh.", "Mass. Sh.", "Maass Sh."], "Maaser_Sheni", "מעשר שני", "y"),
    (["Ḥall."], "Challah", "חלה", "y"), (["Orl."], "Orlah", "ערלה", "y"), (["Bicc."], "Bikkurim", "ביכורים", "y"),
    (["Sabb.", "Sab."], "Shabbat", "שבת", "by"), (["Erub."], "Eruvin", "עירובין", "by"), (["Pes."], "Pesachim", "פסחים", "by"),
    (["Shek."], "Shekalim", "שקלים", "y"), (["Yoma"], "Yoma", "יומא", "by"), (["Succ."], "Sukkah", "סוכה", "by"),
    (["Bets."], "Beitzah", "ביצה", "by"), (["R. Hash.", "R. Hash", "R. Hasḥ.", "B. Hash."], "Rosh_Hashanah", "ראש השנה", "by"),
    (["Taan."], "Taanit", "תענית", "by"), (["Meg."], "Megillah", "מגילה", "by"), (["M. Kat.", "M Kat.", "M. K."], "Moed_Katan", "מועד קטן", "by"),
    (["Ḥag."], "Chagigah", "חגיגה", "by"), (["Yeb."], "Yevamot", "יבמות", "by"), (["Keth."], "Ketubot", "כתובות", "by"),
    (["Ned."], "Nedarim", "נדרים", "by"), (["Naz.", "Nâz."], "Nazir", "נזיר", "by"), (["Sot.", "Sotah"], "Sotah", "סוטה", "by"),
    (["Gitt.", "Git."], "Gittin", "גיטין", "by"), (["Kidd.", "Kid."], "Kiddushin", "קידושין", "by"),
    (["B. Kam."], "Bava_Kamma", "בבא קמא", "by"), (["B. Mets."], "Bava_Metzia", "בבא מציעא", "by"),
    (["B. Bath."], "Bava_Batra", "בבא בתרא", "by"), (["Snh."], "Sanhedrin", "סנהדרין", "by"), (["Macc."], "Makkot", "מכות", "by"),
    (["Shebu.", "Sebu."], "Shevuot", "שבועות", "by"), (["Ab. Zar."], "Avodah_Zarah", "עבודה זרה", "by"), (["Hor."], "Horayot", "הוריות", "by"),
    (["Zeb."], "Zevachim", "זבחים", "b"), (["Men."], "Menachot", "מנחות", "b"), (["Ḥull."], "Chullin", "חולין", "b"),
    (["Bekh."], "Bekhorot", "בכורות", "b"), (["Arakh."], "Arakhin", "ערכין", "b"), (["Tem."], "Temurah", "תמורה", "b"),
    (["Kerith.", "Ker.", "Kerith"], "Keritot", "כריתות", "b"), (["Meïl.", "Meil."], "Meilah", "מעילה", "b"), (["Tam."], "Tamid", "תמיד", "b"),
    (["Nidd."], "Niddah", "נדה", "by"),
]
ORDER = [t[1] for t in TRACT]
# last folio of each tractate of the Babylonian Talmud (Vilna); a citation beyond it is a misprint or a misreading
BMAX = {"Berakhot": 64, "Shabbat": 157, "Eruvin": 105, "Pesachim": 121, "Yoma": 88, "Sukkah": 56, "Beitzah": 40,
        "Rosh_Hashanah": 35, "Taanit": 31, "Megillah": 32, "Moed_Katan": 29, "Chagigah": 27, "Yevamot": 122, "Ketubot": 112,
        "Nedarim": 91, "Nazir": 66, "Sotah": 49, "Gittin": 90, "Kiddushin": 82, "Bava_Kamma": 119, "Bava_Metzia": 119,
        "Bava_Batra": 176, "Sanhedrin": 113, "Makkot": 24, "Shevuot": 49, "Avodah_Zarah": 76, "Horayot": 14, "Zevachim": 120,
        "Menachot": 110, "Chullin": 142, "Bekhorot": 61, "Arakhin": 34, "Temurah": 34, "Keritot": 28, "Meilah": 22,
        "Tamid": 33, "Niddah": 73}
BMIN = {"Tamid": 25}
ABBR = {}
for abbrs, key, heb, has in TRACT:
    for a in abbrs: ABBR[a] = key
HEB = {t[1]: t[2] for t in TRACT}
HAS = {t[1]: t[3] for t in TRACT}
TR = "|".join(sorted((re.escape(a) for a in ABBR), key=len, reverse=True))
ROM = r"(?:X{0,3}(?:IX|IV|V?I{0,3}))"
ROMV = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
def roman(s):
    n, prev = 0, 0
    for ch in reversed(s):
        v = ROMV[ch]; n = n - v if v < prev else n + v; prev = max(prev, v)
    return n

# a citation, in the order the text gives them
MODS = r"(?:(?:beg|end|bot|top|middle)\.?,? ?)*"
P = re.compile(
    r"(?P<y>\bY\. (?P<yt>" + TR + r") ?(?P<yc>" + ROM + r")\b,? " + MODS + r"(?P<yf>\d+)\^(?P<ys>[a-d]))"
    r"|(?P<y2>(?<!\w)(?P<y2t>" + TR + r") (?P<y2c>" + ROM + r")\b,? " + MODS + r"(?P<y2f>\d+)\^(?P<y2s>[a-d]))"
    r"|(?P<lc>(?<!\w)(?P<lct>" + TR + r") l\. c\.)"
    r"|(?P<bablc>\bBab\. ib\. l\. c\.)"
    r"|(?P<b>(?<!\w)(?:Bab\. )?(?P<bt>" + TR + r") +(?P<bf>\d+)\^(?P<bs>[ab]))"
    r"|(?P<m>(?<!\w)(?P<mt>" + TR + r") (?P<mc>" + ROM + r"),)"
    r"|(?P<bc>(?<!\w)(?P<bct>" + TR + r") (?P<bcf>\d+)(?![\d^]))"
    r"|(?P<yib>\bY\. ib\.,? (?:(?P<yic>" + ROM + r")\b,? " + MODS + r")?(?P<yif>\d+)\^(?P<yis>[a-d]))"
    r"|(?P<bib>\bBabl?\. (?:ib\.|ibid\.|ed\.),? (?P<bif>\d+)\^(?P<bis>[ab]))"
    r"|(?P<tos>\bTosef\. (?P<tt>" + TR + r") ?(?P<tc>" + ROM + r")?)"
    r"|(?P<side>\b[Ii]b\.\^(?P<ss>[a-d]))"
    r"|(?P<par>\((?P<pf>\d+)\^(?P<ps>[ab])\))"
    r"|(?P<ib>\b[Ii]b(?:id)?\.,? (?:(?P<ic>" + ROM + r"),? " + MODS + r")?(?P<if>\d+)\^(?P<is>[a-d]))"
    r"|(?P<cont>(?<=[;,] )(?:(?P<cc>" + ROM + r"),? " + MODS + r")?(?P<cf>\d+)\^(?P<cs>[a-d]))"
    r"|(?P<other>\b(?:Gen|Ex|Lev|Num|Deut|Cant|Lam|Koh|Esth|Ruth|Esther|Prov)\.? R\.|\bY\. (?!ib\.)[A-Z]\w*\.|\b(?:Dict|Compl|Ant|Levy|Fr|Fl|Sm|Del|Ar)\.|M’bo|\bp\. \d|\b(?:Pesik|Tanḥ|Tanh|Yalk|Midr|Sifra|Sifré|Sifre|Mekh|Tosef|Targ|Pirké|Pirke|Aboth|Ab\. d’R|Tanna|Zohar|Mass|Sefer|Lekah|Yelamd|Seder|Sem|Kall|Der\. Er|Ab\. R)\b)"
)
# words that make the citation before them part of something else (e.g. "Targ. Y. Gen.", "Tosef. Sabb.")
PRE_BAD = re.compile(r"(?:Tosef|Targ|Pesik|Sifra|Sifré|Mekh|Midr|Yalk|Tanḥ|Mass|Yelamd|Seder)\.? (?:\w+\. ){0,2}$")


WS, WS2 = re.compile(r"\s+"), re.compile(r"\s\s+")


def entry_texts():
    """(entry id, plain text with ^a..^d for superscript folio sides, Sefaria refs by text offset), in book order"""
    meta = json.load(open(os.path.join(SITE, "data/pages.json")))["pages"]
    order, parts = [], defaultdict(list)
    for f in sorted(glob.glob(os.path.join(SITE, "data/c*.json"))):
        ci = int(re.search(r"c(\d+)\.json", f).group(1))
        for k, h in enumerate(json.load(open(f))):
            if isinstance(h, list): h = "".join(h)
            i = ci * 10 + k
            if i >= len(meta) or meta[i][1] != "b": continue
            for m in re.finditer(r'<div class="e(?: cont)?" id="([^"]+)">(.*?)</div>(?=<div class="e|$|<div class="after)', h, re.S):
                if m.group(1) not in parts: order.append(m.group(1))
                parts[m.group(1)].append(m.group(2))
    for eid in order:
        h = " ".join(parts[eid])
        h = re.sub(r"<sup>([a-d])</sup>", r"^\1", h)
        text, refs, n = [], {}, 0
        for tok in re.split(r"(<[^>]+>)", h):
            if tok.startswith("<"):
                m = re.match(r'<a class="r"[^>]*href="https://www\.sefaria\.org/([^"]+)"', tok)
                if m: refs[n] = html.unescape(m.group(1))
                if re.match(r"</?p\b", tok): text.append(" "); n += 1
                continue
            t = html.unescape(tok); text.append(t); n += len(t)
        # pieces of an entry from two pages are joined with several spaces ("Bab.    ib."); make them one,
        # keeping Sefaria's link offsets in step
        raw = "".join(text)
        runs = [(m.start(), m.end() - m.start()) for m in WS2.finditer(raw)]
        if runs and refs:
            refs = {k - sum(min(n_ - 1, k - s_ - 1) for s_, n_ in runs if s_ < k - 1): v for k, v in refs.items()}
        yield eid, WS.sub(" ", raw), refs


def snippet(t, a):
    """the citation and what follows it, up to the next citation-ending mark"""
    s = t[a:a + 170]
    m = re.search(r";|\.—|\(\s*[A-Z][a-z]+\. [A-Z]|(?<=[.,)] )(?:[A-Z][a-zḥ]*\. ){1,3}(?:[IVXL]+\b|\d)|(?<=[.;] )[Ii]b\. (?:[IVXL]+\b|\d)|(?<=[.,)] )[A-Z][a-z]+\. R\. ", s[6:])
    if m: s = s[:m.start() + 6]
    s = s.strip().rstrip(",")
    if len(s) > 150: s = s[:150].rsplit(" ", 1)[0] + " …"
    return s


def main():
    out = {"b": defaultdict(lambda: defaultdict(list)), "y": defaultdict(lambda: defaultdict(list))}
    agree = Counter(); disagree = []
    for eid, t, refs in entry_texts():
        ctx = None                      # [kind "b"|"y"|"m"|"t", tractate, chapter, folio]
        yctx = None
        for m in P.finditer(t):
            g = m.group
            hit = None
            if g("tos"):
                ctx = ["t", ABBR[g("tt")], roman(g("tc")) if g("tc") else None, None]; continue
            if g("other"):
                ctx = None; continue
            if g("y"):
                ctx = ["y", ABBR[g("yt")], roman(g("yc")), g("yf")]
                hit = ("y", ctx[1], ctx[2], g("yf") + g("ys"))
            elif g("y2"):                    # "Meg. I, 71^b": a chapter and a folio is the Jerusalem Talmud's form
                if PRE_BAD.search(t[max(0, m.start() - 24):m.start()]): continue
                ctx = ["y", ABBR[g("y2t")], roman(g("y2c")), g("y2f")]
                hit = ("y", ctx[1], ctx[2], g("y2f") + g("y2s"))
            elif g("bablc"):                 # "Bab. ib. l. c.": the Babylonian Talmud, same tractate
                if ctx and "b" in HAS.get(ctx[1], ""): ctx = ["b", ctx[1], None, None]
                continue
            elif g("lc"):                    # "Bekh. l. c.": the tractate cited above
                key = ABBR[g("lct")]
                ctx = ["b" if "b" in HAS[key] else "m", key, None, None]; continue
            elif g("b"):
                if PRE_BAD.search(t[max(0, m.start() - 24):m.start()]) or t[max(0, m.start() - 3):m.start()] == "Y. ":
                    continue
                key = ABBR[g("bt")]
                if "b" not in HAS[key]: continue
                if t[max(0, m.start() - 6):m.start()] == "expl. " and ctx and ctx[0] in ("m", "y"):
                    yctx = ctx[:]                # an aside ("expl. Ber. 40^b"): keep the tractate for a later "Y. ib."
                else:
                    yctx = None
                ctx = ["b", key, None, g("bf")]
                hit = ("b", key, None, g("bf") + g("bs"))
            elif g("m"):
                ctx = ["m", ABBR[g("mt")], roman(g("mc")), None]; continue
            elif g("bc"):                    # a folio cited without its side: sets the tractate for what follows
                if not PRE_BAD.search(t[max(0, m.start() - 24):m.start()]):
                    ctx = ["b", ABBR[g("bct")], None, g("bcf")]
                continue
            elif not ctx:
                continue
            elif g("yib"):
                if yctx: ctx = yctx; yctx = None
                ch = roman(g("yic")) if g("yic") else (ctx[2] or 0)
                ctx = ["y", ctx[1], ch, g("yif")]
                hit = ("y", ctx[1], ch, g("yif") + g("yis"))
            elif g("bib") or g("par"):
                if "b" not in HAS[ctx[1]] or (g("par") and ctx[0] not in ("m", "b")): continue
                f_, s_ = (g("bif"), g("bis")) if g("bib") else (g("pf"), g("ps"))
                ctx = ["b", ctx[1], None, f_]
                hit = ("b", ctx[1], None, f_ + s_)
            elif g("side"):                  # "Ib.^b": the other side of the same folio
                if ctx[0] in ("b", "y") and ctx[3] and (ctx[0] == "y" or g("ss") in "ab"):
                    hit = (ctx[0], ctx[1], ctx[2], ctx[3] + g("ss"))
            elif (g("ib") or g("cont")) and ctx[0] != "t":
                k = "i" if g("ib") else "c"
                ch, fo, si = g(k + "c"), g(k + "f"), g(k + "s")
                if ctx[0] == "y":
                    if ch: ctx[2] = roman(ch)
                    ctx[3] = fo
                    hit = ("y", ctx[1], ctx[2], fo + si)
                elif ch:
                    continue                 # a chapter after a Babylonian citation: a Mishnah reference
                elif si in "ab" and "b" in HAS[ctx[1]]:
                    ctx = ["b", ctx[1], None, fo]
                    hit = ("b", ctx[1], None, fo + si)
            if not hit: continue
            corp, key, ch, daf = hit
            if corp == "y" and "y" not in HAS[key]: continue
            lst = out[corp][key][daf]
            cite = m.group(0).strip("() ")
            if not (lst and lst[-1][0] == eid):     # one row per entry and daf, with every citation of it
                lst.append([eid, ch or 0, snippet(t, m.start()), [cite]])
            elif cite not in lst[-1][3]:
                lst[-1][3].append(cite)
            # compare with Sefaria's link at the same place, when there is one
            r = refs.get(m.start()) or refs.get(m.start() + (5 if t[m.start():m.start() + 4] == "Bab." else 0))
            if r and corp == "b":
                rm = re.match(r"([A-Za-z_]+)\.(\d+[ab])", r)
                if rm:
                    ok = (rm.group(1), rm.group(2)) == (key, daf)
                    agree[ok] += 1
                    if not ok and len(disagree) < 4000: disagree.append((eid, t[m.start():m.start() + 30], r, key, daf))
    # drop folios outside the tractate; for the Jerusalem Talmud, whose tractates share one folio sequence per
    # volume, keep the folios that lie within the run of the tractate's own citations
    dropped = []
    for key in list(out["b"]):
        for d in list(out["b"][key]):
            f = int(d[:-1])
            if not (BMIN.get(key, 2) <= f <= BMAX[key]):
                dropped += [("b", key, d, r[0], r[2]) for r in out["b"][key].pop(d)]
    for key in list(out["y"]):
        fs = sorted(int(d[:-1]) for d, rows in out["y"][key].items() for r in rows)
        lo, hi = fs[int(len(fs) * .01)], fs[min(len(fs) - 1, int(len(fs) * .99))]
        chf = defaultdict(list)
        for d, rows in out["y"][key].items():
            for r in rows: chf[r[1]].append(int(d[:-1]))
        med = {c: sorted(v)[len(v) // 2] for c, v in chf.items() if c and len(v) >= 5}
        for d in list(out["y"][key]):
            f = int(d[:-1])
            if not (lo - 1 <= f <= hi + 1):
                dropped += [("y", key, d, r[0], r[2]) for r in out["y"][key].pop(d)]; continue
            for r in out["y"][key][d]:          # chapter missing or out of line with the folio: take the nearest chapter
                if med and (r[1] not in med or abs(med[r[1]] - f) > 3):
                    r[1] = min(med, key=lambda c: (abs(med[c] - f), c))
    json.dump(dropped, open("/tmp/claude-0/talmud_dropped.json", "w"), ensure_ascii=False, indent=0)
    print("dropped as out of range:", len(dropped))
    os.makedirs(os.path.join(SITE, "data/talmud"), exist_ok=True)
    for f in glob.glob(os.path.join(SITE, "data/talmud/*.json")): os.remove(f)
    idx = {"b": [], "y": []}
    def dkey(d):
        m = re.match(r"(\d+)([a-d])", d); return (int(m.group(1)), m.group(2))
    for corp in ("b", "y"):
        for key in ORDER:
            if key not in out[corp]: continue
            dafs = out[corp][key]
            ds = sorted(dafs, key=dkey)
            data = {d: dafs[d] for d in ds}
            json.dump(data, open(os.path.join(SITE, "data/talmud/%s_%s.json" % (corp, key)), "w"), ensure_ascii=False, separators=(",", ":"))
            chs = {}
            if corp == "y":
                for d in ds:
                    for row in dafs[d]: chs.setdefault(d, Counter())[row[1]] += 1
            idx[corp].append([key, HEB[key], [[d, len(dafs[d])] + ([sorted(c for c in chs[d] if c)] if corp == "y" else []) for d in ds]])
    json.dump(idx, open(os.path.join(SITE, "data/talmud/index.json"), "w"), ensure_ascii=False, separators=(",", ":"))
    nb = sum(len(v) for t in out["b"].values() for v in t.values()); ny = sum(len(v) for t in out["y"].values() for v in t.values())
    print("Bavli citations", nb, "in", len(out["b"]), "tractates; Yerushalmi", ny, "in", len(out["y"]), "tractates")
    print("agreement with Sefaria's links (Bavli):", dict(agree))
    json.dump(disagree, open("/tmp/claude-0/talmud_disagree.json", "w"), ensure_ascii=False, indent=0)


if __name__ == "__main__":
    main()
