"""Search the Talmud for Jastrow's quotation, the way he writes it: an abbreviation (בנ׳) stands for the headword or a
form of it, so it matches any word beginning so; any word may carry prefixes (ו, ה, ב, ל, מ, כ, ד, ש); spelling may
be full or defective (with or without ו and י as vowel letters)."""
import re, json, sys
import corpus
NIK, FIN = corpus.NIK, corpus.FIN
B = corpus.bavli(); Y = corpus.yerushalmi()
PRE = r"(?:[והבלמכדש]{0,3})"
def flex(w):
    w = w.replace("ו", "").replace("י", "")          # strip vowel letters, then allow them anywhere
    return "".join(c + "[וי]*" for c in w)
def pattern(heb):
    s = NIK.sub("", heb).replace("…", " … ")
    parts = []
    for t in s.split():
        if t in ("וכ׳", "וכו׳", "וגו׳", "וכ'"): break
        if t == "…": parts.append(None); continue
        ab = t.endswith(("׳", "'"))
        w = re.sub(r"[^א-ת]", "", t).translate(FIN)
        if not w: continue
        parts.append((ab, w))
    rx = []
    for p in parts:
        if p is None: rx.append(r"(?:\S+ ){0,8}"); continue
        ab, w = p
        if ab: rx.append(PRE + "[וי]*" + flex(w) + r"\S* ")
        else:
            core = flex(w)
            rx.append(PRE + "[וי]*" + core + " ")
    return "".join(rx).rstrip(), len([p for p in parts if p and not p[0]]), len([p for p in parts if p])
def find(heb):
    rx, nw, n = pattern(heb)
    if n < 2 and nw < 1: return []
    R = re.compile(r"(?:^| )" + rx.replace(r"\S* ", r"\S*(?: |$)") + r"(?= |$)")
    hits = []
    for (t, daf), txt in B.items():
        if R.search(txt.translate(FIN) + " "): hits.append(("b", t, daf))
    for (t, col), (chs, txt) in Y.items():
        if R.search(txt.translate(FIN) + " "): hits.append(("y", t, col, chs))
    return hits
if __name__ == "__main__":
    print(find(sys.argv[1]))
