"""Google Cloud Vision as a reader of the scans: one request per page, its words put on kraken's lines.

Setup: Jastrow-Notes/CLOUD_VISION_SETUP.md. The key is read from ~/jastrow/vision_api.txt and never printed.

  python3 build/audit/vision_lines.py read --pages 1-20,151,155 --yes   # spends requests: one per page not yet cached
  python3 build/audit/vision_lines.py score                             # free: the gold lines of pp. 151, 155

read     sends each page's page.png (DOCUMENT_TEXT_DETECTION, Hebrew and English hinted) and caches the whole
         answer in REPORTS/vision/pNNNN.json; a cached page is never sent again.
score    puts Vision's words on kraken's lines (page_readings) and scores them on the user's gold lines beside the
         other readers (character error rate: whole line, Hebrew letters, Latin; points left out, as Vision drops
         most), then asks the question that matters: on the gold lines, when Vision reads the site's words
         (kraken_prep.same_reading), how often is the site right? And on batch 1, how many disputed lines would it admit.
kraken_prep.py takes Vision in as a reader by itself once a page is cached (tier "vision").
"""
import argparse, base64, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import paths  # noqa: E402

CACHE = paths.report("vision")
URL = "https://vision.googleapis.com/v1/images:annotate"
PAGES = os.path.join(paths.WORK, "audit", "pages")


def parse_pages(s):
    out = []
    for part in s.split(","):
        a, _, b = part.partition("-")
        out += list(range(int(a), int(b or a) + 1))
    return out


def cached(page):
    f = os.path.join(CACHE, "p%04d.json" % int(page))
    return json.load(open(f)) if os.path.exists(f) else None


def cmd_read(a):
    import requests
    todo = [p for p in parse_pages(a.pages) if cached(p) is None]
    if not todo: print("all pages cached"); return
    if not a.yes: sys.exit("%d pages to send (one request each). Rerun with --yes." % len(todo))
    if len(todo) > a.max: sys.exit("%d pages is more than --max %d: raise --max if you mean it" % (len(todo), a.max))
    key = open(os.path.expanduser("~/jastrow/vision_api.txt")).read().strip()
    os.makedirs(CACHE, exist_ok=True)
    for p in todo:
        f = os.path.join(PAGES, "p%04d" % p, "page.png")
        if not os.path.exists(f): print("p. %d: no page.png, skipped" % p); continue
        body = {"requests": [{"image": {"content": base64.b64encode(open(f, "rb").read()).decode()},
                              "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
                              "imageContext": {"languageHints": ["he", "en"]}}]}
        # the key goes in a header, not the URL, so that no error message can print it
        r = requests.post(URL, json=body, headers={"X-goog-api-key": key}, timeout=120)
        try: d = r.json()
        except ValueError: sys.exit("p. %d: HTTP %d, not JSON" % (p, r.status_code))
        err = d.get("error") or (d.get("responses") or [{}])[0].get("error")
        if r.status_code != 200 or err:
            sys.exit("p. %d: HTTP %d: %s" % (p, r.status_code, (err or {}).get("message", "")[:300]))
        res = d["responses"][0]
        json.dump(res, open(os.path.join(CACHE, "p%04d.json" % p), "w"), ensure_ascii=False)
        print("p. %d: %d words" % (p, len(words_of(res))), flush=True)


def words_of(res):
    """Vision's words: text (symbols joined, in the order Vision gives them) and box in page.png's pixels"""
    out = []
    for pg in (res.get("fullTextAnnotation") or {}).get("pages", []):
        for bl in pg.get("blocks", []):
            for pa in bl.get("paragraphs", []):
                for w in pa.get("words", []):
                    t = "".join(s.get("text", "") for s in w.get("symbols", []))
                    v = w.get("boundingBox", {}).get("vertices", [])
                    xs, ys = [p.get("x", 0) for p in v], [p.get("y", 0) for p in v]
                    if t and xs: out.append({"text": t, "box": [min(xs), min(ys), max(xs), max(ys)]})
    return out


def base_y(line, x):
    """kraken's baseline height at x"""
    b = line["base"] or [[line["box"][0], line["box"][3]], [line["box"][2], line["box"][3]]]
    for (x0, y0), (x1, y1) in zip(b, b[1:]):
        if x0 <= x <= x1 and x1 > x0: return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return b[0][1] if x < b[0][0] else b[-1][1]


def page_readings(page, xml="kraken_mccatmus.xml", reverse_heb=False):
    """{kraken line id: Vision's reading of that line}, or None if the page isn't cached. A word goes to the line
    whose box holds its middle; where boxes overlap (vowel points), to the line whose baseline is nearest below
    the word's middle"""
    import linereview as LR
    res = cached(page)
    if res is None: return None
    K = LR.kraken_lines(os.path.join(PAGES, "p%04d" % int(page), xml))
    got = {k["id"]: [] for k in K}
    for w in words_of(res):
        cx, cy = (w["box"][0] + w["box"][2]) / 2, (w["box"][1] + w["box"][3]) / 2
        cand = [k for k in K if k["box"][0] - 10 <= cx <= k["box"][2] + 10 and k["box"][1] - 5 <= cy <= k["box"][3] + 5]
        if not cand: continue
        k = min(cand, key=lambda k: (base_y(k, cx) < cy - 0.25 * (w["box"][3] - w["box"][1]), abs(base_y(k, cx) - cy)))
        got[k["id"]].append(w)
    out = {}
    for kid, ws in got.items():
        ws.sort(key=lambda w: w["box"][0])
        texts = [w["text"][::-1] if reverse_heb and LR.HEB_LETTER.search(w["text"]) else w["text"] for w in ws]
        s = " ".join(LR.logical(texts))
        s = re.sub(r" ([,.;:)\]])", r"\1", s)
        out[kid] = re.sub(r"([(\[]) ", r"\1", s)
    return out


def cmd_score(a):
    import gemini_lines as G
    import kraken_prep as KP
    L, gold = G.load(a.pilot, a.gold)
    keys = [k for k in gold if k[0] in ("151", "155")]
    for rev in (False, True):
        V = {p: page_readings(p, reverse_heb=rev) for p in ("151", "155")}
        if any(v is None for v in V.values()): sys.exit("pp. 151, 155 not read yet: run read --pages 151,155 first")
        readers = {"vision" + (" (Hebrew reversed)" if rev else ""): {k: V[k[0]].get(L[k]["kid"], "") for k in keys}}
        if not rev:
            for r in ("tesseract", "pdf"): readers[r] = {k: L[k]["readers"].get(r, "") for k in keys}
            readers["site"] = {k: L[k]["site"] for k in keys}
        for name, ans in readers.items():
            err, tot = [0, 0, 0], [0, 0, 0]
            for k in keys:
                g, h = G.norm(gold[k]), G.norm(ans[k])
                pg, ph = G.parts(g), G.parts(h)
                for i, (x, y) in enumerate([(re.sub(r"[֑-ׇ]", "", g), re.sub(r"[֑-ׇ]", "", h)),
                                            (pg[0], ph[0]), (pg[2], ph[2])]):
                    err[i] += G.lev(x, y); tot[i] += len(x)
            print("%-28s CER no points %5.1f%%   Hebrew letters %5.1f%%   Latin %5.1f%%" % (
                name, *(100 * e / max(1, t) for e, t in zip(err, tot))))
    V = {p: page_readings(p) for p in ("151", "155")}
    n = ok = 0
    for k in keys:
        v = V[k[0]].get(L[k]["kid"], "")
        if v and KP.same_reading(KP.printed(L[k]["site"]), v):
            n += 1; ok += KP.letters(KP.printed(L[k]["site"])) == KP.letters(KP.printed(gold[k]))
    print("gold lines where Vision reads the site's words: %d of %d; the site right on %d of them" % (n, len(keys), ok))
    if os.path.exists(a.review):
        class A: review = a.review; marks = a.marks
        rv, recs = KP.setup(A)
        from collections import Counter
        print("batch 1 (%s):" % os.path.relpath(a.review), dict(Counter(r["tier"] for r in recs)))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], epilog=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["read", "score"])
    ap.add_argument("--pages", default="151,155")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--max", type=int, default=30, help="read: refuse more pages than this in one run")
    ap.add_argument("--pilot", default=os.path.join(paths.WORK, "audit", "lines", "pilot", "lines.json"))
    ap.add_argument("--gold", default=os.path.expanduser("~/Downloads/jastrow-lines-pilot-2026-11-052122.json"))
    ap.add_argument("--review", default=os.path.join(paths.WORK, "audit", "lines", "b1", "lines.json"))
    ap.add_argument("--marks", nargs="*", default=["~/Downloads/jastrow-lines-pilot-2026-11-052122.json",
                                                    "~/Downloads/jastrow-lines-b1-check-*.json"])
    a = ap.parse_args()
    {"read": cmd_read, "score": cmd_score}[a.cmd](a)


if __name__ == "__main__":
    main()
