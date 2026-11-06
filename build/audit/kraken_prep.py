"""Training lines for kraken from a line review (linereview.py's lines.json): KRAKEN_PLAN.md phase 2.

Each line of the review gets one of these:
  held      a held-out page (pp. 151-160: the gold lines and the test pages): never trained on
  checked   the user marked it on a line review page (Right / Fixed: that text; Bad / Skip: left out)
  agree     no word of the site's read otherwise by two readers or more, no word two readers see that the site
            lacks, no flag on the line or on the lines next to it: the site's text, as printed (below), admitted by
            machine (gold lines: 115 of 116 right; the one wrong was next to a flagged line, now held back)
  gemini    the readers differ, but Gemini (examples, low thinking) reads the site's words (same_reading): admitted
            (on the gold lines of pp. 151, 155: 119 of 202 such lines, all right; never where the site was wrong)
  vision    the same with Google Cloud Vision's reading (vision_lines.py), once its gold-line test says it is safe
  check     the rest: for the user, on check.html, the site's text as printed proposed, Gemini shown as a reader
  dots      the text has "…": the book's number of dots is not known, so the user writes it (also on check.html)

The training text is the site's as the book prints it: no space before a comma ("X, v.", the site has "X , v.");
"=" without spaces, a divided word with its hyphen and raised folio letters (done by linereview.py). Final stops
are the site's (fixes-nov). Vowel points are Sefaria's, unchecked.

  python3 build/audit/kraken_prep.py plan    --review work/audit/lines/b1/lines.json --marks ~/Downloads/jastrow-lines-*.json
  python3 build/audit/kraken_prep.py gemini  --review ... --yes      # spends credit: run plan first for the estimate
  python3 build/audit/kraken_prep.py review  --review ... --marks ...   # writes check.html beside lines.json
  python3 build/audit/kraken_prep.py export  --review ... --marks ...   # PAGE XML, even and odd pages apart

export writes OUT/even/pNNNN.xml and OUT/odd/pNNNN.xml: kraken's own PAGE XML of the page (its line cuts, so
training lines are cut as kraken cuts them when reading), keeping only the admitted lines, each with its text
in display order, left to right as printed (see display(); --logical for reading order). Run export in kraken's
environment (it uses kraken's bidi code). Train with  ketos train -f page --no-reorder OUT/even/*.xml ...
"""
import argparse, glob, html as H, json, os, re, sys, time, unicodedata
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import paths  # noqa: E402
import linereview as LR  # noqa: E402
import gemini_lines as G  # noqa: E402

HELD = set(range(151, 161))
DISPUTE_FLAGS = {"estimated", "two_lines", "crosses_gutter", "no_site_text", "hyphen_guess", "divided_word"}
TRUST_VISION = False   # Vision admits lines only once its gold-line test (vision_lines.py score) has been seen
MODEL, THINKING, VARIANT = "gemini-3.5-flash", "low", "examples"
CACHE = os.path.join(paths.report("gemini_lines"), "%s@%s" % (MODEL, THINKING), "train.json")
PILOT = os.path.join(paths.WORK, "audit", "lines", "pilot", "lines.json")      # the worked examples' boxes
PILOT_MARKS = os.path.expanduser("~/Downloads/jastrow-lines-pilot-2026-11-052122.json")
AGOROT_PER_LINE = (0.8, 1.5)   # examples @low: ~4,340 tokens in, ~820 out with thinking (6 Nov usage files),
                               # priced from the 6 Nov spend (~30 NIS for ~750 lines at ~4,500 thinking tokens)


def printed(site):
    """the site's text for a line as the book prints it"""
    s = site.strip()
    s = re.sub(r"\s+,", ",", s)                       # "X , v." -> "X, v."
    s = re.sub(r"\be\.g\.", "e. g.", s)                # the book spaces these (the user, 6 Nov; scan p. 1)
    s = re.sub(r"\bi\.e\.", "i. e.", s)
    return re.sub(r"\s+", " ", s)


# a Hebrew phrase as linereview's page sets it (its HW / HSEP / HPH): a comma list of single words runs left to
# right, as the book prints form lists (GUIDELINES 2.9); anything else is one right-to-left run
HW = "[\u05D0-\u05EA][\u0591-\u05C7\u05D0-\u05EA\u05F3\u05F4'\"\u2019*\u05BE-]*"
HPH = re.compile(HW + "(?:(?: +|, ?| *\\( *" + HW + "(?: +" + HW + ")* *\\) *)" + HW + ")*")
LRM = "\u200e"


def display(text):
    """the training label: the line in display order, left to right as on the scan, so that what the user approved
    on the check page is what kraken learns (trained with --no-reorder). Kraken's own bidi code does the
    reordering, with a left-to-right mark after each comma of a single-word list, as the page shows it."""
    from kraken.lib.bidi import get_display

    def lists(m):
        parts = re.split(r"(, ?)", m.group(0))
        if len(parts) > 1 and all(not re.search(r"[ ()]", p) for p in parts[::2]):
            return "".join(p + LRM if k % 2 else p for k, p in enumerate(parts))
        return m.group(0)
    t = HPH.sub(lists, unicodedata.normalize("NFD", text))
    return get_display(t, base_dir="L").replace(LRM, "")


def letters(s):
    """compared with Gemini: everything but vowel points and spaces"""
    return re.sub(r"[֑-ׇ\s]", "", G.norm(s))


def same_reading(site, gem):
    """Gemini read the site's line: the same English words in the same order, the same Hebrew words in any order
    (its order of Hebrew in a mixed line often differs from the site's), the same punctuation marks; vowel points
    and Gemini's markdown (*word*, _word_) left out. On the gold lines: 119 of 202 admitted, all right"""
    from collections import Counter

    def sig(t):
        w = LR.words(t)
        return ([LR.norm_word(x) for x in w if not LR.HEB_LETTER.search(x)],
                Counter(LR.norm_word(x) for x in w if LR.HEB_LETTER.search(x)),
                Counter(re.sub(r"[^.,;:()\[\]]", "", t)))
    return sig(G.norm(site)) == sig(re.sub(r"[*_]", "", G.norm(gem)))


def nz(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def load_marks(files):
    """(page, kraken line id) -> the latest mark; a later file wins"""
    out = {}
    for f in files:
        for x in json.load(open(os.path.expanduser(f)))["lines"]:
            k = (x["page"], x.get("kid"))
            if k not in out or (x.get("time") or "") >= (out[k].get("time") or ""): out[k] = x
    return out


def load_cache():
    return json.load(open(CACHE)) if os.path.exists(CACHE) else {}


def gkey(r):
    return "%s:%s" % (r["page"], r["kid"])


def classify(recs, marks, gem, vis=None):
    vis = vis or {}
    for r in recs:
        if r["page"] in vis: r["readers"]["vision"] = vis[r["page"]].get(r["kid"], "")
        r["text"] = printed(r["site"])
        r["why"] = ""
        g = gem.get(gkey(r))
        if g and g.get("box") == r["box"]: r["readers"]["gemini"] = G.norm(g["text"])
        if int(r["page"]) in HELD:
            r["tier"] = "held"; continue
        m = marks.get((r["page"], r["kid"]))
        if m and nz(m.get("site")) in (nz(r["site"]), nz(r["text"])):
            if m["status"] in ("ok", "fixed"):
                r["tier"], r["text"] = "checked", printed(m["text"])
                if "…" in r["text"]: r["tier"], r["why"] = "dots", "marked, but still has …"
            else:
                r["tier"] = "out"
            continue
        if "…" in r["text"]:
            r["tier"] = "dots"; continue
        flags = set(r["flags"]) & DISPUTE_FLAGS
        if r.get("near_flag"): flags.add("next_to_flagged")
        most = max([n for *_, n in r["sitew"]] or [0])
        if not flags and most < 2 and not r["extra"]:
            r["tier"] = "agree"; continue
        if "gemini" in r["readers"] and same_reading(r["text"], r["readers"]["gemini"]):
            r["tier"] = "gemini"; continue
        if TRUST_VISION and r["readers"].get("vision") and same_reading(r["text"], r["readers"]["vision"]):
            r["tier"] = "vision"; continue
        r["tier"] = "check" if "gemini" in r["readers"] else "disputed"
        r["two"] = not flags and not r["extra"]          # only two readers read a word otherwise: Gemini first
        r["why"] = ",".join(sorted(flags)) or "readers differ"
    return recs


def mark_neighbours(recs):
    """a line next to a flagged one (same page and column) may have lost or gained a word at its end: on the gold
    lines, 151:100 began with the word its flagged neighbour had taken"""
    by = {}
    for r in recs: by.setdefault((r["page"], r["col"]), []).append(r)
    for ls in by.values():
        ls.sort(key=lambda r: r["rank"])
        for i, r in enumerate(ls):
            nb = ls[max(0, i - 1):i] + ls[i + 1:i + 2]
            r["near_flag"] = any(set(n["flags"]) & DISPUTE_FLAGS for n in nb)


def setup(a):
    rv = json.load(open(a.review))
    marks = load_marks(sum((glob.glob(os.path.expanduser(f)) for f in a.marks), []))
    mark_neighbours(rv["lines"])
    import vision_lines as VL          # Google Cloud Vision's readings, for the pages read so far (vision_lines.py)
    vis = {}
    for p in {r["page"] for r in rv["lines"]}:
        v = VL.page_readings(p, os.path.basename(rv["lines"][0]["xml"]))
        if v: vis[p] = v
    return rv, classify(rv["lines"], marks, load_cache(), vis)


def has_heb(s): return bool(LR.HEB_LETTER.search(s))


def cmd_plan(a):
    rv, recs = setup(a)
    from collections import Counter
    c = Counter(r["tier"] for r in recs)
    pages = sorted({int(r["page"]) for r in recs})
    print("%d lines on %d pages (%s-%s)" % (len(recs), len(pages), pages[0], pages[-1]))
    for t in ("checked", "agree", "gemini", "vision", "disputed", "check", "dots", "out", "held"):
        if c[t]:
            n = [r for r in recs if r["tier"] == t]
            print("  %-9s %5d  (with Hebrew %d)" % (t, len(n), sum(1 for r in n if has_heb(r["text"]))))
    adm = sum(c[t] for t in ("checked", "agree", "gemini", "vision"))
    print("admitted for training now: %d; for the user to check: %d" % (adm, c["check"] + c["dots"] + c["disputed"]))
    two = sum(1 for r in recs if r["tier"] == "disputed" and r.get("two"))
    for what, n in (("--on two (two readers differ, nothing flagged)", two), ("--on all (every disputed line)", c["disputed"])):
        if n:
            lo, hi = (n * x / 100 for x in AGOROT_PER_LINE)
            print("Gemini %s: %d lines, about %.1f-%.1f NIS" % (what, n, lo, hi))


def cmd_gemini(a):
    rv, recs = setup(a)
    todo = [r for r in recs if r["tier"] == "disputed" and (a.on == "all" or r.get("two"))]
    if a.limit: todo = todo[:a.limit]
    if not todo: print("no disputed lines without a Gemini reading"); return
    lo, hi = (len(todo) * x / 100 for x in AGOROT_PER_LINE)
    if not a.yes:
        sys.exit("%d lines, about %.1f-%.1f NIS. Rerun with --yes to spend it." % (len(todo), lo, hi))
    from google import genai
    from google.genai import types
    import threading
    from concurrent.futures import ThreadPoolExecutor
    client = genai.Client(api_key=open(os.path.expanduser("~/jastrow/gem_api.txt")).read().strip())
    img = lambda b: types.Part.from_bytes(data=b, mime_type="image/png")  # noqa: E731
    cfg = types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_level=THINKING))
    PL, gold = G.load(PILOT, PILOT_MARKS)
    shots = []
    for ek in G.EXAMPLES:
        shots += [img(G.crop(ek[0], PL[ek]["box"], 1)), "Transcription: " + gold[ek]]
    cache = load_cache()
    uf = CACHE[:-5] + ".usage.json"
    usage = json.load(open(uf)) if os.path.exists(uf) else {}
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    lock, done = threading.Lock(), [0]
    print("%d lines to read" % len(todo), flush=True)

    def one(r):
        contents = [G.PROMPT + "\n\nExamples:"] + shots + ["Now this line:", img(G.crop(r["page"], r["box"], 1))]
        u = []
        ans = G.ask(client, MODEL, contents, cfg, u)
        with lock:
            cache[gkey(r)] = {"box": r["box"], "text": ans}
            if u: usage[gkey(r)] = u[-1]
            done[0] += 1
            if done[0] % 20 == 0 or done[0] == len(todo):
                json.dump(cache, open(CACHE, "w"), ensure_ascii=False, indent=0); json.dump(usage, open(uf, "w"))
                print("  %d/%d" % (done[0], len(todo)), flush=True)
    with ThreadPoolExecutor(a.threads) as ex:
        list(ex.map(one, todo))
    json.dump(cache, open(CACHE, "w"), ensure_ascii=False, indent=0); json.dump(usage, open(uf, "w"))
    if usage:
        n = len(usage); s = [sum(v[i] for v in usage.values()) for i in range(3)]
        print("tokens per line: in %d, out %d, thinking %d (%d lines)" % (s[0] / n, s[1] / n, s[2] / n, n))
    cmd_plan(a)


def cmd_review(a):
    rv, recs = setup(a)
    show = [r for r in recs if r["tier"] in ("check", "dots", "disputed")]
    # first the lines Gemini disputed, then the dots, then the Hebrew lines (what the model most needs), page order within
    order = {"check": 0, "dots": 1, "disputed": 2}
    show.sort(key=lambda r: (order[r["tier"]], not has_heb(r["text"]), int(r["page"]), r["rank"]))
    for r in show:
        r["site_orig"], r["site"] = r["site"], r["text"]     # the card proposes the training text
        if r["tier"] == "dots": r["flags"] = sorted(set(r["flags"]) | {"dots"})
        LR.mark_readers(r)
    name = rv["run"] + "-check"
    marks = load_marks(sum((glob.glob(os.path.expanduser(f)) for f in a.marks), []))
    prior = [m for m in marks.values() if any(m["page"] == r["page"] and m.get("kid") == r["kid"] for r in show)]
    flags = dict(LR.FLAG_TEXT, dots="the site has …: write the dots as the book prints them (how many, spaced or not)")
    page = LR.PAGE % {"name": H.escape(name), "run": json.dumps(name), "lines": json.dumps(show, ensure_ascii=False),
                      "flags": json.dumps(flags), "prior": json.dumps(prior, ensure_ascii=False),
                      "recheck": "[]", "made": json.dumps(time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()))}
    out = os.path.join(os.path.dirname(os.path.abspath(a.review)), "check.html")
    open(out, "w").write(page)
    print("%d lines to check (%d batches of 20)\n%s" % (len(show), -(-len(show) // 20), out))


def cmd_export(a):
    rv, recs = setup(a)
    keep = {}
    for r in recs:
        if r["tier"] in a.tiers.split(","):
            keep.setdefault(r["page"], {})[r["kid"]] = display(r["text"]) if a.visual else unicodedata.normalize("NFD", r["text"])
    pdir = os.path.join(paths.WORK, "audit", "pages")
    n = {"even": [0, 0], "odd": [0, 0]}
    for pg, lines in sorted(keep.items(), key=lambda x: int(x[0])):
        if int(pg) in HELD: sys.exit("held-out page %s in the export" % pg)
        side = "even" if int(pg) % 2 == 0 else "odd"
        xml = os.path.join(a.out, side, "p%04d.xml" % int(pg))
        os.makedirs(os.path.dirname(xml), exist_ok=True)
        src = os.path.join(pdir, "p%04d" % int(pg), a.xml)
        ET.register_namespace("", "http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15")
        tree = ET.parse(src); root = tree.getroot()
        ns = root.tag.split("}")[0] + "}"
        for page in root.iter(ns + "Page"):
            page.set("imageFilename", os.path.abspath(os.path.join(pdir, "p%04d" % int(pg), "page.png")))
        for parent in list(root.iter()):
            for ln in [c for c in parent if c.tag == ns + "TextLine"]:
                if ln.get("id") not in lines:
                    parent.remove(ln); continue
                for c in [c for c in ln if c.tag in (ns + "Word", ns + "TextEquiv")]: ln.remove(c)
                te = ET.SubElement(ln, ns + "TextEquiv"); ET.SubElement(te, ns + "Unicode").text = lines[ln.get("id")]
        tree.write(xml, encoding="UTF-8", xml_declaration=True)
        n[side][0] += 1; n[side][1] += len(lines)
    for s, (p, l) in n.items(): print("%-4s %2d pages, %5d lines  %s" % (s, p, l, os.path.join(a.out, s)))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], epilog=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["plan", "gemini", "review", "export"])
    ap.add_argument("--review", required=True, help="linereview.py's lines.json")
    ap.add_argument("--marks", nargs="*", default=[], help="line review exports (jastrow-lines-*.json; globs allowed)")
    ap.add_argument("--yes", action="store_true", help="gemini: spend the credit")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--on", choices=["two", "all"], default="two",
                    help="gemini: only lines where just two readers differ and nothing is flagged (default), or all disputed")
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--tiers", default="checked,agree,gemini,vision", help="export: which tiers go in")
    ap.add_argument("--xml", default="kraken_mccatmus.xml")
    ap.add_argument("--logical", dest="visual", action="store_false",
                    help="export: labels in reading order (for ketos --reorder) instead of display order")
    ap.add_argument("--out", default=os.path.join(paths.WORK, "kraken", "train"))
    a = ap.parse_args()
    {"plan": cmd_plan, "gemini": cmd_gemini, "review": cmd_review, "export": cmd_export}[a.cmd](a)


if __name__ == "__main__":
    main()
