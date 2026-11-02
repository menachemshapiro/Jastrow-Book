#!/usr/bin/env python3
"""Add the side by side views to focus.py reports made before they existed, without running focus.py again.

    python3 build/audit/focus_patch.py                 every report folder in work/audit/focus/
    python3 build/audit/focus_patch.py DIR [DIR ...]   these report folders only

headwords.html: each entry's whole HTML comes from the site, and its place in the scan from the cached OCR
(map_entries alone, about 2 s a page). columns.html: each page gets a button for the website's page beside the
whole scan page (no reading needed). Both: the OK / Wrong / Not sure buttons say what they mean. The cards, flags
and marks are kept; each old file is kept as headwords.orig.html / columns.orig.html.
"""
import glob, html as H, json, os, re, sys, time
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
    html = new_script(html, data, FO.site_css())
    html = html.replace("<span id=nm class=mut>", '<button id=sbsall onclick="sbsAll(!SBSALL)" title="open every card '
                        'shown as the whole entry, the site beside the scan">Side by side: all</button>'
                        "<span id=nm class=mut>", 1)
    btn = ('<button class="b-sbs" onclick="sbs(\'%s\')" title="the whole entry: the site as it looks on the website, '
           'beside the scan">Side by side</button>')
    html = re.sub(r"(<input placeholder=\"note\" onchange=\"note\('([^']+)',this.value\)\">)</div>",
                  lambda m: m.group(1) + btn % m.group(2) + "</div>", html)
    save(path, verdicts(html))
    return len(data)


def new_script(html, data, sitecss):
    """the report's script and stylesheet, as focus.py now writes them"""
    kind = re.search(r"const KIND=(\"[^\"]*\")", html).group(1)
    run = re.search(r",RUN=(\"[^\"]*\")", html).group(1)
    script = "<script>const KIND=%s,RUN=%s,DATA=%s,FONTS=%s,SITECSS=%s,SITE0=%s;%s</script>" % (
        kind, run, json.dumps(data, ensure_ascii=False).replace("</", "<\\/"), json.dumps(FO.SITE_FONTS),
        json.dumps(sitecss).replace("</", "<\\/"), json.dumps(FO.SITE_URL), FO.JS)
    a = html.index("<script>const KIND=")
    b = html.index("</script>", a) + len("</script>")
    html = html[:a] + script + html[b:]
    a = html.index("<style>")
    b = html.index("</style>", a) + len("</style>")
    return html[:a] + "<style>" + FO.CSS + "</style>" + html[b:]


def verdicts(html):
    """OK / Wrong / Not sure say what they mean (on each button, and once at the top)"""
    if 'title="the site is right here' in html: return html
    html = re.sub(r'<button class="b-ok" onclick="mark\(\'([^\']+)\',\'ok\'\)">OK</button>'
                  r'<button class="b-wrong" onclick="mark\(\'\1\',\'wrong\'\)">Wrong</button>'
                  r'<button class="b-unsure" onclick="mark\(\'\1\',\'unsure\'\)">Not sure</button>',
                  lambda m: FO.VERDICTS % (m.group(1), m.group(1), m.group(1)), html)
    return html.replace("</h1><div class=mut>", "</h1><div class=mut>" + FO.VERDICT_HELP + " ", 1)


def save(path, html):
    orig = path[:-5] + ".orig.html"
    if not os.path.exists(orig): os.rename(path, orig)
    open(path, "w", encoding="utf-8").write(html)


def patch_columns(folder):
    path = os.path.join(folder, "columns.html")
    html = open(path, encoding="utf-8").read()
    if "b-psbs" not in html:
        html = new_script(html, read_data(html), "")
        html = html.replace("<span id=nm class=mut>", FO.SITE_INPUT + "<span id=nm class=mut>", 1)
        html = re.sub(r"<div class=pgbox><div class=pg>p\. ([^<]+)</div>", lambda m: FO.page_box(H.unescape(m.group(1)), folder), html)
    new = verdicts(html)
    if new != open(path, encoding="utf-8").read(): save(path, new)


def main():
    folders = [os.path.abspath(d) for d in sys.argv[1:]] or sorted(glob.glob(os.path.join(OUT, "focus", "*")))
    todo = []
    for d in folders:
        if os.path.exists(os.path.join(d, "columns.html")):
            patch_columns(d)
            print("  %s" % os.path.join(d, "columns.html"), flush=True)
        hp = os.path.join(d, "headwords.html")
        if not os.path.exists(hp): continue
        h = open(hp, encoding="utf-8").read()
        if "id=sbsall" in h:
            if verdicts(h) != h: save(hp, verdicts(h))
            continue
        todo.append((d, sorted({str(r["page"]) for r in read_data(h).values()}, key=int)))
    pages = sorted({p for _, ps in todo for p in ps}, key=int)
    if not pages: return
    print("%d report(s), %d pages ..." % (len(todo), len(pages)), flush=True)
    t = time.time()
    with Pool(os.cpu_count() or 2, initializer=_init) as pool:
        info = {}
        for r in pool.imap_unordered(page_info, pages, chunksize=4):
            info[r["pid"]] = r
            if len(info) % 100 == 0:
                print("  %d of %d pages  (%.0f s)" % (len(info), len(pages), time.time() - t), flush=True)
    print("pages read in %.0f s" % (time.time() - t), flush=True)
    for d, _ in todo:
        n = patch(d, info)
        print("  %s  (%d entries)" % (os.path.join(d, "headwords.html"), n), flush=True)


if __name__ == "__main__":
    main()
