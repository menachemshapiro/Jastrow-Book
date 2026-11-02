#!/usr/bin/env python3
"""Add the side by side view to headwords.html reports made before it existed, without running focus.py again.

    python3 build/audit/focus_patch.py                 every report folder in work/audit/focus/
    python3 build/audit/focus_patch.py DIR [DIR ...]   these report folders only

Each entry's whole HTML comes from the site, and its place in the scan from the cached OCR (map_entries alone,
about 2 s a page). The report's cards, flags and marks are kept; the old file is kept as headwords.orig.html.
"""
import glob, json, os, re, sys, time
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import focus as FO
import paths

OUT = os.path.join(paths.WORK, "audit")
_G = {}


def _init():
    import audit as AU, compare as CO, sitetext as ST
    CO.CFG.update(reread3=False, stage4=False)
    _G.update(CO=CO, book=ST.Book(), V=AU.vocab(ST.REPO))


def page_info(pid):
    """for one page: each entry's HTML and its parts in the scan, the page image's path and size, and the entry
    that runs on to the next page"""
    from PIL import Image
    CO, book = _G["CO"], _G["book"]
    wd = os.path.join(OUT, "pages", "p%04d" % int(pid))
    res = {"pid": pid, "ents": {}, "parts": {}, "img": None, "isz": None, "more": None}
    P = book.page(pid)
    for e in P.entries:
        res["ents"][e["eid"]] = FO.entry_html(P.html, e["eid"])
    try:
        nx = book.page(str(int(pid) + 1)).entries
        if nx and nx[0]["cont"] and P.entries and nx[0]["eid"] == P.entries[-1]["eid"]:
            res["more"] = (nx[0]["eid"], str(int(pid) + 1))
    except Exception:
        pass
    sp = os.path.join(wd, "scan.json")
    if not os.path.exists(sp) or not os.path.exists(os.path.join(wd, "page.png")): return res
    scan = json.load(open(sp))
    if "ocr" not in scan: return res
    try:
        pc = CO.PageCompare(P, scan, _G["V"], OUT)
        pc.map_entries()
        res["parts"] = {k: [x["box"] for x in v] for k, v in pc.entry_parts.items()}
    except Exception as e:
        print("  p. %s: %s: %s" % (pid, type(e).__name__, e), flush=True)
    res["img"] = os.path.join(wd, "page.png")
    res["isz"] = list(Image.open(res["img"]).size)
    return res


def read_data(html):
    i = html.index("DATA=") + len("DATA=")
    data, j = json.JSONDecoder().raw_decode(html, i)
    return data


def patch(folder, info):
    path = os.path.join(folder, "headwords.html")
    html = open(path, encoding="utf-8").read()
    data = read_data(html)
    for cid, r in data.items():
        pi = info.get(str(r["page"]))
        if not pi: continue
        r["ent"] = pi["ents"].get(r["eid"], "")
        r["parts"] = pi["parts"].get(r["eid"], [])
        r["isz"] = pi["isz"]
        r["pimg"] = os.path.relpath(pi["img"], folder) if pi["img"] else ""
        r["more"] = pi["more"][1] if pi["more"] and pi["more"][0] == r["eid"] else None
    kind = re.search(r"const KIND=(\"[^\"]*\")", html).group(1)
    run = re.search(r",RUN=(\"[^\"]*\")", html).group(1)
    script = "<script>const KIND=%s,RUN=%s,DATA=%s,FONTS=%s,SITECSS=%s;%s</script>" % (
        kind, run, json.dumps(data, ensure_ascii=False).replace("</", "<\\/"), json.dumps(FO.SITE_FONTS),
        json.dumps(FO.site_css()).replace("</", "<\\/"), FO.JS)
    a = html.index("<script>const KIND=")
    b = html.index("</script>", a) + len("</script>")
    html = html[:a] + script + html[b:]
    a = html.index("<style>")
    b = html.index("</style>", a) + len("</style>")
    html = html[:a] + "<style>" + FO.CSS + "</style>" + html[b:]
    html = html.replace("<span id=nm class=mut>", '<button id=sbsall onclick="sbsAll(!SBSALL)" title="open every card '
                        'shown as the whole entry, the site beside the scan">Side by side: all</button>'
                        "<span id=nm class=mut>", 1)
    btn = ('<button class="b-sbs" onclick="sbs(\'%s\')" title="the whole entry: the site as it looks on the website, '
           'beside the scan">Side by side</button>')
    html = re.sub(r"(<input placeholder=\"note\" onchange=\"note\('([^']+)',this.value\)\">)</div>",
                  lambda m: m.group(1) + btn % m.group(2) + "</div>", html)
    orig = os.path.join(folder, "headwords.orig.html")
    if not os.path.exists(orig): os.rename(path, orig)
    open(path, "w", encoding="utf-8").write(html)
    return len(data)


def main():
    folders = sys.argv[1:] or sorted(d for d in glob.glob(os.path.join(OUT, "focus", "*"))
                                     if os.path.exists(os.path.join(d, "headwords.html")))
    todo = []
    for d in folders:
        h = open(os.path.join(d, "headwords.html"), encoding="utf-8").read()
        if "id=sbsall" in h:
            print("already has the side by side view: %s" % d); continue
        todo.append((d, sorted({str(r["page"]) for r in read_data(h).values()}, key=int)))
    pages = sorted({p for _, ps in todo for p in ps}, key=int)
    if not pages: return
    print("%d report(s), %d pages ..." % (len(todo), len(pages)), flush=True)
    t = time.time()
    with Pool(os.cpu_count() or 2, initializer=_init) as pool:
        info = {r["pid"]: r for r in pool.imap_unordered(page_info, pages, chunksize=4)}
    print("pages read in %.0f s" % (time.time() - t), flush=True)
    for d, _ in todo:
        n = patch(d, info)
        print("  %s  (%d entries)" % (os.path.join(d, "headwords.html"), n), flush=True)


if __name__ == "__main__":
    main()
