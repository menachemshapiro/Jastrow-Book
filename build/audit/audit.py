#!/usr/bin/env python3
"""Audit the site against the 1903 scans, page by page: OCR each page, align it with the site's text, and report
every difference found, with the piece of the scan it comes from. Also checks the site's text on its own, and its
Bavli references (folio in range; the quotation found on that daf).

usage:
  python3 build/audit/audit.py --check                 check the tools, the Hebrew OCR model, the scans and paths
  python3 build/audit/audit.py --pages 1-10            audit pages 1 to 10 (also "1,5,7-9", or "all")
options:
  --jobs N        pages OCR'd at once (default: the number of processor cores)
  --dpi N         resolution the scans are rendered at (default 400)
  --force         render and OCR again even if a page was done before (otherwise the OCR is reused)
  --no-talmud     skip the Bavli checks;  --no-quotes  only the range check, not the quotation search
  --no-verify     don't re-read differing words a second time
  --entry-lines flush|indent   how an entry's first line sits in the book: flush with the column's edge, the
                  rest indented (hanging indent; the default), or the other way round
  --out DIR       where everything goes (default work/audit)
  --site DIR      the site to audit (default: this repository's data/)
  --site-url URL  where the report's "site page (local)" links go (default http://localhost:8000/, the local
                  preview: python3 -m http.server in the repository)

Results, in the --out folder:
  summary.txt             a short summary (paste this to Claude)
  findings.jsonl          every finding, one per line
  report/index.html       the findings, page by page, each with its piece of the scan
  report/entries.html     every entry: its scan (all parts, across columns and pages) beside the site's text
  pages/pNNNN/layout.png  what the layout step found on each page (columns red, headings purple, lines blue)
Paths (scans, Talmud text) come from build/paths.py: config.json or JASTROW_* variables."""
import argparse, glob, json, os, re, shutil, subprocess, sys, time
from collections import Counter
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import paths  # noqa: E402
import sitetext as ST  # noqa: E402


def parse_pages(spec, book):
    body = book.body_pages()
    if spec == "all": return body
    out = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            out += [p for p in body if p.isdigit() and int(a) <= int(p) <= int(b)]
        elif part in book.index:
            out.append(part)
        else:
            sys.exit("no such page: %s" % part)
    return out


def check(args):
    ok = True
    def say(good, msg):
        nonlocal ok
        ok = ok and good
        print(("  ok   " if good else "  MISSING ") + msg)
    print("tools:")
    for t in ("pdftoppm", "tesseract"):
        say(shutil.which(t) is not None, t)
    if shutil.which("tesseract"):
        langs = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True).stdout.split()
        say("eng" in langs, "tesseract English model (eng)")
        say("heb" in langs, "tesseract Hebrew model (heb)  — Ubuntu: sudo apt install tesseract-ocr-heb")
    try:
        import numpy, PIL  # noqa
        say(True, "python: numpy, pillow")
    except ImportError as e:
        say(False, "python: %s  — pip install numpy pillow" % e)
    print("scans (%s):" % paths.SCANS)
    for v in ("1", "2"):
        c = sorted(glob.glob(os.path.join(paths.SCANS, "*%s.pdf" % v)))
        say(bool(c), "volume %s PDF: %s" % (v, c[0] if c else "a file ending in %s.pdf" % v))
    print("site: %s" % args.site)
    say(os.path.exists(os.path.join(args.site, "data", "pages.json")), "data/pages.json")
    print("Talmud text, for the quotation search (%s):" % paths.TALMUD)
    say(os.path.isdir(paths.TALMUD), "Sefaria's Bavli (optional; without it only the range check runs)")
    print("all set" if ok else "something is missing (see above)")
    return ok


def scan_one(a):
    pid, scans, out, dpi, force = a
    import scan as SC
    t = time.time()
    try:
        r = SC.process(pid, scans, out, dpi, force)
        err = r["layout"].get("error")
        return pid, time.time() - t, err
    except Exception as e:
        return pid, time.time() - t, "%s: %s" % (type(e).__name__, e)


def vocab(site):
    """how often each word (as compared) occurs on the site"""
    v = Counter()
    for f in glob.glob(os.path.join(site, "data", "c*.json")):
        for pg in json.load(open(f)):
            h = "".join(pg) if isinstance(pg, list) else pg
            for w in re.sub(r"<[^>]+>", " ", h).split():
                k = ST.key(w)
                if k: v[k] += 1
    return v


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--pages")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--dpi", type=int, default=400)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-talmud", action="store_true")
    ap.add_argument("--no-quotes", action="store_true")
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--entry-lines", choices=("flush", "indent"), default="flush")
    ap.add_argument("--out", default=os.path.join(paths.WORK, "audit"))
    ap.add_argument("--site", default=paths.REPO)
    ap.add_argument("--site-url", default="http://localhost:8000/")
    args = ap.parse_args()
    if args.check:
        sys.exit(0 if check(args) else 1)
    if not args.pages:
        ap.error("give --pages (e.g. --pages 1-10) or --check")
    import compare as CO
    import checks as CK
    import report as RP
    if args.no_verify: CO.CFG["verify"] = False
    CO.CFG["entry_lines"] = args.entry_lines
    book = ST.Book(args.site)
    run = parse_pages(args.pages, book)
    os.makedirs(args.out, exist_ok=True)
    t0 = time.time()
    # 1. render and OCR (in parallel; each tesseract on one core)
    os.environ["OMP_THREAD_LIMIT"] = "1"
    todo = [(p, paths.SCANS, args.out, args.dpi, args.force) for p in run]
    print("OCR of %d page(s), %d at a time (pages done before are reused; --force to redo)..." % (len(run), args.jobs))
    errors = {}
    with Pool(max(1, min(args.jobs, len(run)))) as pool:
        for pid, secs, err in pool.imap_unordered(scan_one, todo):
            print("  p. %-5s %5.1f s%s" % (pid, secs, ("  ERROR " + err) if err else ""), flush=True)
            if err: errors[pid] = err
    # 2. compare
    print("comparing...")
    V = vocab(args.site)
    findings, pages, entries = [], {}, []
    for pid in run:
        sp = os.path.join(args.out, "pages", "p%04d" % int(pid), "scan.json")
        page = book.page(pid)
        pages[pid] = {}
        if os.path.exists(sp):
            scan = json.load(open(sp))
            if "ocr" in scan:
                pc = CO.PageCompare(page, scan, V, args.out)
                findings += pc.run()
                pages[pid] = {"stats": pc.stats, "scan": scan}
                for e in page.entries:
                    if e["eid"] in pc.entry_parts: entries.append((pid, e["eid"], pc.entry_parts[e["eid"]]))
            else:
                findings.append(CK.finding(pid, "layout", 1, None, "", "the page's layout could not be read: %s" %
                                           scan["layout"].get("error")))
        elif pid in errors:
            findings.append(CK.finding(pid, "layout", 1, None, "", "the scan could not be processed: %s" % errors[pid]))
        findings += CK.site_checks(book, pid)
    # the scans against each other: a page whose image or text block is a different size from the rest of the run
    sizes = {pid: pages[pid]["scan"]["layout"] for pid in run if pages[pid].get("scan")}
    for pid, l in sizes.items():
        if not l.get("size"):              # pages OCR'd before the size was recorded
            from PIL import Image
            l["size"] = list(Image.open(os.path.join(args.out, "pages", "p%04d" % int(pid), "page.png")).size)
    if len(sizes) >= 3:
        import statistics as stt
        mw = stt.median(l["size"][0] for l in sizes.values() if l.get("size"))
        mh = stt.median(l["size"][1] for l in sizes.values() if l.get("size"))
        bw = stt.median(l["body"][2] - l["body"][0] for l in sizes.values())
        for pid, l in sizes.items():
            notes = []
            if l.get("size") and (abs(l["size"][0] - mw) > 0.08 * mw or abs(l["size"][1] - mh) > 0.08 * mh):
                notes.append("the scan image is %dx%d, the other pages about %dx%d" % (l["size"][0], l["size"][1], mw, mh))
            if (l["body"][2] - l["body"][0]) < 0.92 * bw:
                notes.append("the text block is %d%% as wide as on the other pages" % round(100 * (l["body"][2] - l["body"][0]) / bw))
            if notes:
                findings.append(CK.finding(pid, "scan_incomplete", 1, None, "", "; ".join(notes) + ": a cropped or partial scan?",
                                           boxes=[l["body"]]))
                pages[pid].setdefault("stats", {})["scan_problem"] = True
    # 3. Bavli references
    tstats = Counter()
    if not args.no_talmud:
        print("checking Bavli references%s..." % ("" if args.no_quotes else " (and their quotations)"))
        T = CK.Talmud(args.site, with_quotes=not args.no_quotes)
        if not args.no_quotes and not T.search:
            print("  (no Talmud text at %s: only the range check)" % paths.TALMUD)
        for pid in run:
            eids = [e["eid"] for e in book.page(pid).entries if not e["cont"]]
            f, s = T.check(pid, eids)
            findings += f; tstats += s
    # 4. report
    print("writing the report...")
    idx, summary = RP.write(args.out, findings, pages, entries, book, run, scans=paths.SCANS, site_url=args.site_url)
    if tstats:
        extra = "Bavli citations: " + ", ".join("%s %d" % kv for kv in sorted(tstats.items()))
        summary += "\n" + extra
        open(os.path.join(args.out, "summary.txt"), "a").write(extra + "\n")
    print()
    print(summary)
    print()
    print("report: %s" % idx)
    print("done in %.0f s" % (time.time() - t0))


if __name__ == "__main__":
    main()
