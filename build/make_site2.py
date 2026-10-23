#!/usr/bin/env python3
"""Turn pages_all.json + entries.json into site data: page chunks, page index, headword index."""
import json, re, os, sys

SRC, OUT = sys.argv[1], sys.argv[2]
CHUNK = 10
os.makedirs(os.path.join(OUT, "data"), exist_ok=True)

pages = json.load(open(os.path.join(SRC, "pages_all.json")))["pages"]
BREAKS = json.load(open(os.environ["BREAKS"])) if os.environ.get("BREAKS") else {}

TITLE1 = """<div class="tp">
<div class="tp-a">A DICTIONARY</div>
<div class="tp-b">OF THE TARGUMIM, THE TALMUD BABLI<br>AND YERUSHALMI, AND THE MIDRASHIC<br>LITERATURE</div>
<div class="tp-c">COMPILED BY</div>
<div class="tp-d">MARCUS JASTROW, <span class="sc">Ph. D. Litt. D.</span></div>
<div class="tp-e">WITH AN INDEX OF SCRIPTURAL QUOTATIONS</div>
<div class="tp-ded"><span class="tp-to">TO</span><span class="tp-wife">MY WIFE</span><span class="tp-love">IN LOVE AND GRATITUDE</span></div>
<img class="tp-emb" src="emblem.png" alt="Printer\u2019s mark of W. Drugulin, Leipzig">
<div class="tp-pr">W. DRUGULIN, ORIENTAL PRINTER, LEIPZIG (GERMANY).</div>
<div class="tp-pub"><div><span>LONDON, W.C.: LUZAC &amp; Co.</span><small>46, GREAT RUSSELL STREET</small></div><div><span>NEW YORK: G. P. PUTNAM\u2019S SONS</span><small>27 W. 23d STREET</small></div></div>
<div class="tp-yr">1903</div>
</div>"""
TITLE2 = """<div class="tp tp2">
<div class="tp-a">A DICTIONARY</div>
<div class="tp-b">OF THE TARGUMIM, THE TALMUD BABLI<br>AND YERUSHALMI, AND THE MIDRASHIC<br>LITERATURE</div>
<div class="tp-c">COMPILED BY</div>
<div class="tp-d">MARCUS JASTROW, <span class="sc">Ph. D. Litt. D.</span></div>
<div class="tp-e">WITH AN INDEX OF SCRIPTURAL QUOTATIONS</div>
<div class="tp-vol">VOLUME II:</div>
<div class="tp-let" lang="he" dir="rtl">\u05dc\u2014\u05ea</div>
<div class="tp-pub"><div><span>LONDON, W.C.: LUZAC &amp; Co.</span><small>46, GREAT RUSSELL STREET</small></div><div><span>NEW YORK: G. P. PUTNAM\u2019S SONS</span><small>27 W. 23d STREET</small></div></div>
<div class="tp-yr">1903</div>
</div>"""
FOOTNOTES = {
    "v": '<div class="fns"><p class="fn"><sup>1</sup> For these Aramaic elements the traditional (though admittedly incorrect) term Chaldaic (Ch., ch.) is retained in the Dictionary, wherever the designation is required for distinction from the corresponding Hebrew forms.</p></div>',
    "vi": '<div class="fns"><p class="fn"><sup>1</sup> The attempt to make biliteral roots the basis for radical definitions of stems was found too cumbersome and too much subject to misunderstanding, and was therefore abandoned with the beginning of the third letter of the alphabet.</p></div>',
}
FOOTNOTES.update({
    "vii": '<div class="fns"><p class="fn"><sup>1</sup> In fact where Pesaḥim 50<sup>b</sup> has תגרי סימטא, Tosefta Biccurim end, in Mss. Erfurt and Vienna, reads תגרי שמיטה, which is obviously a corruption of שימטה, the pure Hebrew form for the Aramaic סימטא.</p></div>',
    "viii": '<div class="fns"><p class="fn"><sup>1</sup> That Arukh ed. Kohut and Buber in Lam. R. read אספריתא, with ת for ס, cannot be taken into consideration in view of the numerous evidences in favor of אספריסא.</p><p class="fn"><sup>2</sup> Compare Targum I Chronicles V, 12, ברם מלכותא, ‘a portion of the kingdom’ and the particle ברם ‘besides’, and B’rakhoth 39<sup>a</sup> פרמינהו פרימי, ‘he chopped them into pieces.’</p></div>',
    "ix": '<div class="fns"><p class="fn"><sup>1</sup> See Dictionary s. v. טצהר for an explanation of the misinterpretation which the word has suffered at the hands of commentators.</p></div>',
    "x": '<div class="fns"><p class="fn"><sup>1</sup> This אפרכסת has nothing in common with ארפכס (ἅρπαξ = ὑδράρπαξ, ἁρπάγιον), ‘the waterclock’, which appears in Gen. R. s. 4. In Kelim XIV, 6, and XXX, 4, where a metal <i>harpax</i> and a glass <i>harpax</i> are respectively mentioned, the Arukh has preserved the correct reading ארפכס, where the editions have אפרכס. The latter reading has misled the commentators into identifying the word with אפרכסת, and it forced Maimonides, who realized the difficulty of a ‘glass hopper’, to assume the meaning of a hopper-shaped vessel, a funnel.</p></div>',
    "xi": '<div class="fns"><p class="fn"><sup>1</sup> See Jastrow, Transposed Stems, Drugulin, Leipzig 1891, and the Dictionary under the respective words.</p></div>',
})
FIXES = {
    "vii": [("dialectically = <sup>1</sup>שמט,", "dialectically = שמט<sup>1</sup>,")],
    "xi": [("contracted forms לשישית and שלשושית.</p>", "contracted forms לשישית and שלשושית.<sup>1</sup></p>")],
    "xiii": [('<p class="fm">Philadelphia, May, 1903.MARCUS JASTROW</p>', '<p class="fm sig"><span>Philadelphia, May, 1903.</span><span>MARCUS JASTROW</span></p>')],
}
# binyan names lost in Sefaria's data ("*." etc.), read from the 1903 scans; in page order
BINYAN = {"114": "*Pi.", "142": "*Hif.", "148": "*Ithpe.", "151": "*Hif.", "153": "*Ithpe.", "154": "*Nif.", "155": "*Af.",
  "161": "*Pa.", "162": "*Polel", "173": "*Hif.", "191": "*Af.", "208": "*Af.", "210": "*Polel", "251": "*Hof.", "285": "*Af.",
  "331": "*Hif.", "382": "*Hif.", "430": "[Af.", "478": "*Ithpa.", "479": "[Pi.", "498": "*Hof.", "506": "[Pa.", "546": "*Af.",
  "576": "*Pa.", "586": "*Pu.", "646": "*Pi.", "683": "*Pa.", "738": "*Ithpol.", "875": "*Hof.", "879": "*Ithpe.", "932": "*Hif.",
  "992": "*Hithpa.", "1042": "*Pi.", "1045": "*Af.", "1056": "[Hif.", "1089": "*Palp.", "1208": "*Hif.", "1272": "*Polel",
  "1301": "*Af.", "1316": "[Nif.", "1375": "*Hithpa.", "1441": "Pa.", "1479": "[Hif.", "1488": "*Ithpe.", "1493": "*Hithpa.",
  "1501": "*Ithpe.", "1516": "*Ithpa.", "1670": "*Pa.", "1701": "*Af."}
BADBN = re.compile(r'<i class="bn">([^<A-Za-z]*)</i>')
VERSE119 = ('<div class="verse" dir="rtl" lang="he"><span>ויאמרו לאמר</span><span>אשירה לד׳ כי גאה גאה</span><span>סוס</span>'
            '<span>ורכבו רמה בים</span><span>עזי וזמרת יה ויהי לי</span><span></span></div>'
            '<p class="ep" data-c="1">Ib. <span class="h">א׳ ע״ג א׳ וכ׳</span> small brick (lath) above small brick and brick above brick; e.g. (Esth. IX, 7 sq.)</p>'
            '<div class="verse v2" dir="rtl" lang="he"><span>פרשנדתא</span><span>ואת</span><span>דלפון.</span><span>ואת</span></div>')
def fix_special(pid, h):
    h = re.sub(r'<p class="bin"><i class="bn">[^<A-Za-z]*</i> </p>', "", h)
    if pid in BINYAN:
        h, n = BADBN.subn('<i class="bn">%s</i>' % BINYAN[pid], h, count=1)
        assert n == 1, pid
    if pid == "119":
        a = h.index('<p class="bin"> <i class="bn">סוס.</i>')
        b = h.index('<i class="bn">דלפון.</i>'); b = h.index("</p>", b) + 4
        h = h[:a] + VERSE119 + h[b:]
    if pid == "658":
        h = h.replace('<p class="bin"><i class="bn">,.</i> <span class="bf">כְּפוּשָׁה</span> ', '<p class="ep sub"><span class="hw" lang="he" dir="rtl">כְּפוּשָׁה</span>, ')
    if pid == "1522":
        h = re.sub(r'<p class="bin"><i class="bn">\(\.</i> <span class="bf">שׁוֹגֵם</span> <span class="s"><span class="d">\) <a class="x" href="#U00230">שֶׁגֶם</a>',
                   '<p class="ep sub"><span class="hw" lang="he" dir="rtl">שֶׁגֶם (שׁוֹגֵם)</span><span class="s"><span class="d">', h)
    if pid == "319":
        a = '<div class="e cont" id="D01003"><p class="ep" data-c="1"><p class="bin" data-c="1"><span class="bf">דְּקִילִין, דְּקִילָן</span> <span class="s"><span class="d">, '
        assert a in h, pid
        h = h.replace(a, '<div class="e" id="D01003b"><p class="ep"><span class="hw" lang="he" dir="rtl">*דְּקִילִין, דְּקִילָן</span><span class="s"><span class="d">, ')
    if pid == "937":
        a = '<div class="e cont" id="N01268"><p class="ep" data-c="1"><p class="bin" data-c="1"><span class="bf">נ</span> <span class="s"><span class="d">רווד, '
        assert a in h, pid
        h = h.replace(a, '<div class="e" id="N01268b"><p class="ep"><span class="hw" lang="he" dir="rtl">נרווד</span><span class="s"><span class="d">, ')
    if pid == "1032":
        h = h.replace('<i class="bn">נִסְתַּר.</i> <span class="bf">הִסְתַּתֵּר</span>', '<span class="bf">נִסְתַּר</span>, <i class="bn">Hithpa.</i> <span class="bf">הִסְתַּתֵּר</span>')
    # corrections checked against the 1903 printing, one record per change (build/text_fixes.json)
    for fx in TEXT_FIXES.get(pid, []):
        assert h.count(fx["old"]) == 1, (pid, fx["old"])
        h = h.replace(fx["old"], fx["new"])
    return h

TEXT_FIXES = {}
_tf = os.path.join(os.path.dirname(os.path.abspath(__file__)), "text_fixes.json")
if os.path.exists(_tf):
    for fx in json.load(open(_tf, encoding="utf-8")):
        TEXT_FIXES.setdefault(str(fx["page"]), []).append(fx)

AFTER = {"683": '<div class="after"><span class="sc">End of Volume I.</span></div>',
         "1705": '<div class="after theend"><span>THE END.</span></div>'}
PREF = {"v", "vi", "vii", "viii", "ix", "x", "xi", "xii", "xiii"}

newpages = []
for p in pages:
    if p["id"] in ("i", "iv"):
        continue                       # reprint pages (Hebrew half-title, 1971/2004 copyright)
    p["kind"] = ""
    if p["id"] == "iii":
        p["html"] = TITLE1; p["kind"] = "title"
    elif p["id"] in PREF:
        p["kind"] = "pref"
        p["html"] = p["html"].replace('<p class="fm"><b>Preface.</b></p>', '<h1 class="pt">PREFACE.</h1><div class="orn"></div>')
        for a, b in FIXES.get(p["id"], []):
            assert a in p["html"], (p["id"], a)
            p["html"] = p["html"].replace(a, b)
        p["html"] += FOOTNOTES.get(p["id"], "")
    elif p["id"] in ("xv", "xvi", "xvii", "xviii"):
        p["kind"] = "abbr"
    elif p["section"] == "back":
        p["kind"] = "idx" if int(p["id"]) >= 1722 else "back"
    elif p.get("letter"):
        p["kind"] = "letter"
    _old = p["html"]
    p["html"] = fix_special(p["id"], p["html"])
    if p["html"] != _old and BREAKS.get(p["id"]) is not None:
        # a repair changed the text: move the column break by the same amount
        import difflib as _dl, html as _H
        def _pt(h): return "".join(_H.unescape(x) for x in re.split(r"(<[^>]+>)", h) if not x.startswith("<"))
        a_, b_ = _pt(_old), _pt(p["html"]); k = BREAKS[p["id"]]
        ops_ = _dl.SequenceMatcher(None, a_, b_, autojunk=False).get_opcodes()
        for n_, (t_, i1, i2, j1, j2) in enumerate(ops_):
            if i1 <= k < i2 or (k == i2 and t_ == "equal"):
                BREAKS[p["id"]] = j1 + (k - i1) if t_ == "equal" else j1
                nx = ops_[n_ + 1] if n_ + 1 < len(ops_) else None
                if t_ == "equal" and k == i2 and nx and nx[0] == "insert" and re.fullmatch(r"[\s.,;:]+", b_[nx[3]:nx[4]]):
                    BREAKS[p["id"]] = nx[4]      # punctuation added at the break stays with the first column
                break
    p["html"] += AFTER.get(p["id"], "")
    newpages.append(p)
    if p["id"] == "683":
        newpages.append({"id": "684", "section": "body", "html": TITLE2, "entries": [], "cont": None,
                         "estimated": False, "kind": "vtitle", "first": "", "last": ""})
pages = newpages
entries = json.load(open(os.path.join(SRC, "entries.json")))

HEB_RUN = re.compile(
    "[\u05D0-\u05EA][\u0591-\u05F4'\"\u2019-]*"
    "(?:(?:[ \u00a0]|\u2026|, )+[\u05D0-\u05EA][\u0591-\u05F4'\"\u2019-]*)*")
DOT = re.compile("(?<=[\u05D0-\u05EA\u0591-\u05C7])\u0307")


def fix_text(seg):
    seg = DOT.sub("ׄ", seg)
    return HEB_RUN.sub(lambda m: '<span class="h">%s</span>' % m.group(0), seg)


def transform(h):
    parts = re.split(r"(<[^>]+>)", h)
    out = []
    in_hw = 0
    for p in parts:
        if p.startswith("<"):
            if p.startswith('<span class="hw"'):
                in_hw = 1
            elif p == "</span>" and in_hw:
                in_hw = 0
            out.append(p)
            continue
        out.append((DOT.sub("\u05C4", p) if in_hw else fix_text(p)) if p else p)
    h = "".join(out)
    return h.replace('href="#e=', 'href="#')


meta = []
for i, p in enumerate(pages):
    meta.append([p["id"], {"front": "f", "body": "b", "back": "x"}[p["section"]], p["first"], p["last"], 1 if p["estimated"] else 0, p["kind"], BREAKS.get(p["id"]) if BREAKS.get(p["id"]) is not None else -1])

for c in range(0, len(pages), CHUNK):
    chunk = []
    for p in pages[c:c + CHUNK]:
        h = transform(p["html"])
        if p["id"] in ("xv", "xvi", "xvii", "xviii"):
            h = h.replace('<p class="fm">', '<p class="fm" dir="auto">')
        chunk.append(h)
    json.dump(chunk, open(os.path.join(OUT, "data", "c%03d.json" % (c // CHUNK)), "w"),
              ensure_ascii=False, separators=(",", ":"))

import html as _html
cur = json.load(open(sys.argv[3]))["entries"]
TAG = re.compile(r"<[^>]+>")
hw = []
for p_i, p in enumerate(pages):
    src = p["html"]
    for eid in p["entries"]:
        e = entries[eid]
        k = src.find('<div class="e" id="%s">' % eid)
        seg = src[k:src.find('<div class="e', k + 10) if src.find('<div class="e', k + 10) > 0 else len(src)]
        seg = re.sub(r'<span class="hw".*?</span>', "", seg, count=1)
        g = re.sub(r"\s+", " ", _html.unescape(TAG.sub("", seg))).strip()
        if len(g) > 80:
            g = g[:80].rsplit(" ", 1)[0] + "\u2026"
        sef = cur.get(eid, {}).get("headword", "")
        hw.append([eid, p_i, "|".join(h.strip() for h in e["hw"]), g, sef])

json.dump({"chunk": CHUNK, "pages": meta}, open(os.path.join(OUT, "data", "pages.json"), "w"),
          ensure_ascii=False, separators=(",", ":"))
json.dump(hw, open(os.path.join(OUT, "data", "hw.json"), "w"), ensure_ascii=False, separators=(",", ":"))
print(len(pages), "pages,", len(hw), "headword rows,", (len(pages) + CHUNK - 1) // CHUNK, "chunks")
