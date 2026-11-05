"""Does the book end an entry with a full stop? For each entry whose text on the site does not end with one, the
scan line where the entry ends (an entry always ends a line, the next begins a new one) is read off the audit's
pages: Tesseract and the PDF's own OCR layer. The user, 5 Nov: keep the dictionary's own final stops, add none
it does not print.

usage: python3 build/audit/final_stops.py [--pages 1-1704] [--jobs 3] [--site ~/jastrow/jb-site]
Writes REPORTS/final_stops.json: {eid: {"page", "verdict": stop|none|unclear, "tess", "pdf", "site_end"}}."""
import argparse, glob, json, os, re, sys
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(HERE))
import paths  # noqa: E402
import linereview as LR  # noqa: E402

G = {}
STOPS = '.?!'


def init(site, out):
    import audit as AU, compare as CO, ocrmodel as OM, report as RP, sitetext as ST
    G.update(CO=CO, book=ST.Book(site), V=AU.vocab(site), out=out)
    mf = [os.path.join(out, "marks.json")] + sorted(glob.glob(os.path.expanduser("~/Downloads/jastrow-audit-marks*.json")))
    CO.CM, CO.HCM = OM.build(os.path.join(out, "pages"), RP.load_marks(mf))
    CO.CFG.update(reread3=False, stage4=False)
    LR.CM[0] = CO.CM


def ends_with_stop(text):
    """'yes' if a reader's line ends with a full stop, 'no' if with a letter or digit, None if unsure"""
    ws = text.split()
    if not ws: return None
    last = ws[-1]
    if LR.HEB_LETTER.search(last):
        # the Hebrew reader gives a word with its punctuation on the visual left (".בזא"), either end
        if last[0] == "." or last[-1] == ".": return "yes"
        if last[-1].isalpha() and last[0].isalpha(): return "no"
        return None
    if last[-1] == ".": return "yes"
    if last[-1].isalnum(): return "no"
    return None


def page(pid):
    import focus as FO
    CO, out = G["CO"], G["out"]
    wd = os.path.join(out, "pages", "p%04d" % int(pid))
    try:
        scan = json.load(open(os.path.join(wd, "scan.json")))
        pc = CO.PageCompare(G["book"].page(str(pid)), scan, G["V"], out)
        FO.run_page(pc, CO, headwords=False)
        from PIL import Image
        size = Image.open(os.path.join(wd, "page.png")).size
    except Exception as e:  # noqa: BLE001
        return {"_err_%s" % pid: str(e)[:200]}
    PW = LR.pdf_words(scan, size)
    bags = {ln["i"]: {LR.norm_word(w) for w in LR.words(LR.tess_text(scan, ln["i"], CO)) if LR.norm_word(w)} for ln in pc.lines}
    for w in PW:
        k = LR.norm_word(w["text"])
        if k and pc.lines: bags[LR.near_line(pc.lines, w["box"])["i"]].add(k)
    W = {}
    sl = LR.site_lines(pc, CO, bags, where_out=W)
    where, toks, order = W["where"], W["toks"], W["order"]
    res = {}
    for n, t in enumerate(toks):
        e = t["eid"]
        if not e or n + 1 >= len(toks) or toks[n + 1]["eid"] == e: continue      # not the entry's last word here
        if t["text"].rstrip()[-1:] in STOPS + "]": continue                      # ends with a stop (or a bracket)
        r = where[n]
        if r is None: res[e] = {"page": str(pid), "verdict": "unclear", "why": "not placed"}; continue
        if where[n + 1] == r: res[e] = {"page": str(pid), "verdict": "unclear", "why": "next entry on the same line"}; continue
        li = order[r]["i"]
        b = order[r]["box"]
        tess = LR.tess_text(scan, li, CO)
        pdf = " ".join(LR.logical([w["text"] for w in sorted((w for w in PW if LR.in_box(w, b)), key=lambda w: w["box"][0])]))
        v = [ends_with_stop(tess), ends_with_stop(pdf)]
        # a full stop seen by either reader is taken (the OCR misses stops more often than it invents them)
        verdict = "stop" if "yes" in v else "none" if v == ["no", "no"] else "unclear"
        res[e] = {"page": str(pid), "verdict": verdict, "tess": tess[-40:], "pdf": pdf[-40:], "site_end": sl[li]["text"][-40:]}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", default="1-1704")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--site", default=os.path.expanduser("~/jastrow/jb-site"))
    ap.add_argument("--out", default=os.path.join(paths.WORK, "audit"))
    ap.add_argument("--save", default=paths.report("final_stops.json"))
    a = ap.parse_args()
    ps = []
    for part in a.pages.split(","):
        x, _, y = part.partition("-"); ps += list(range(int(x), int(y or x) + 1))
    ps = [p for p in ps if os.path.exists(os.path.join(a.out, "pages", "p%04d" % p, "scan.json"))]
    allr = {}
    with Pool(a.jobs, initializer=init, initargs=(a.site, a.out)) as pool:
        for k, r in enumerate(pool.imap(page, ps, chunksize=4)):
            allr.update(r)
            if k % 100 == 0: print("  %d/%d pages" % (k, len(ps)), flush=True)
    json.dump(allr, open(a.save, "w"), ensure_ascii=False, indent=0)
    from collections import Counter
    print(Counter(v["verdict"] for k, v in allr.items() if not k.startswith("_err")), "errors:",
          sum(1 for k in allr if k.startswith("_err")), "->", a.save)


if __name__ == "__main__":
    main()
