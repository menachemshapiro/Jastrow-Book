"""Plain consonantal text of every daf of the Bavli and every Venice column of the Yerushalmi, from Sefaria's export."""
import json, re, glob, os, html, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths
Z = paths.TALMUD
NIK = re.compile("[֑-ׇ]")
FIN = str.maketrans("ךםןףץ", "כמנפצ")
def norm(s):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    s = NIK.sub("", s).translate(FIN)
    s = re.sub(r"[^א-ת ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()
def bavli():
    out = {}
    for f in glob.glob(Z + "/Sefaria-Bavli/Talmud/Bavli/*/*/merged.json"):
        d = json.load(open(f)); name = os.path.basename(os.path.dirname(f)).replace(" ", "_")
        for i, seg in enumerate(d["text"]):
            if not seg: continue
            daf = "%d%s" % (i // 2 + 1, "ab"[i % 2])
            out[(name, daf)] = norm(" ".join(seg if isinstance(seg, list) else [seg]))
    return out
VC = re.compile(r'data-overlay="Venice Columns" data-value="(\d+[a-d])"')
def yerushalmi():
    out = {}
    for f in glob.glob(Z + "/Sefaria-Yerushalmi/Talmud/Yerushalmi/*/*/merged.json"):
        d = json.load(open(f)); name = os.path.basename(os.path.dirname(f)).replace("Jerusalem Talmud ", "").replace(" ", "_")
        col = None; buf = {}
        for ci, chap in enumerate(d["text"]):
            for hi, hal in enumerate(chap):
                for si, seg in enumerate(hal):
                    # split the segment at column markers
                    pos = 0
                    for m in VC.finditer(seg):
                        if col: buf.setdefault(col, []).append((ci + 1, seg[pos:m.start()]))
                        col = m.group(1); pos = m.end()
                    if col: buf.setdefault(col, []).append((ci + 1, seg[pos:]))
        for c, parts in buf.items():
            out[(name, c)] = (sorted({p[0] for p in parts}), norm(" ".join(p[1] for p in parts)))
    return out
