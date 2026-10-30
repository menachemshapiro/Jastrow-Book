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
  --no-reread     skip stage 3: re-reading each disagreement with the OCR's character alternatives and scoring
                  Sefaria's reading and the OCR's against them (cached in pages/pNNNN/reread3.json)
  --no-stage4     skip stage 4: comparing each entry's words as a bag before their order
  --cfg K=V       set a threshold of compare.CFG for this run (e.g. --cfg re_err=2.5); may be given more than once
  --trained       OCR with the models trained on this book (build/audit/train_ocr.py); pages read with
                  other models are OCR'd again. --ocr-models DIR: models from another folder
  --word-count    also compare each entry's word count (off: on pp. 1-10 it found only OCR noise)
  --entry-lines flush|indent   how an entry's first line sits in the book: indented by about an em, the rest
                  flush (the default; so the 1903 book is set, checked on pp. 2, 6 and 8), or the other way round
  --out DIR       where everything goes (default work/audit)
  --site DIR      the site to audit (default: this repository's data/)
  --marks FILE    your verdicts, exported from the report ("Export marks"); OUT/marks.json and
                  ~/Downloads/jastrow-audit-marks*.json are read anyway, merged and kept in OUT/marks.json
  --site-url URL  where the report's "site page (local)" links go (default http://localhost:8000/, the local
                  preview: python3 -m http.server in the repository)

Results, in the --out folder (work/audit):
  index.html                     every run so far, newest first
  runs/<pages>_<date>_<time>/    one folder per run, never overwritten:
      summary.txt                a short summary (paste this to Claude)
      findings.jsonl             every finding, one per line
      report/index.html          the findings, page by page, each with its piece of the scan
      report/entries.html        every entry: its scan (all parts) beside the site's text
  pages/pNNNN/                   each page's scan and OCR, shared by all runs (layout.png: what the layout step
                                 found: columns red, headings purple, lines blue)
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
                # Hebrew words by their letters, for stage 3's "is the OCR's reading a word at all?"
                for hw in ST.HEBWORD.findall(w):
                    sk = ST.heb_skel(hw)
                    if len(sk) >= 2: v["h:" + sk] += 1
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
    ap.add_argument("--word-count", action="store_true")
    ap.add_argument("--no-reread", action="store_true")
    ap.add_argument("--no-stage4", action="store_true")
    ap.add_argument("--cfg", action="append", default=[], help="K=V: a compare.CFG value for this run")
    ap.add_argument("--trained", action="store_true", help="OCR with the models trained on the book (train_ocr.py)")
    ap.add_argument("--ocr-models", help="a folder with jeng/jheb.traineddata (default with --trained: work/ocrtrain/models)")
    ap.add_argument("--entry-lines", choices=("flush", "indent"), default="indent")
    ap.add_argument("--out", default=os.path.join(paths.WORK, "audit"))
    ap.add_argument("--site", default=paths.REPO)
    ap.add_argument("--site-url", default="http://localhost:8000/")
    ap.add_argument("--marks", help="a marks file exported from the report (also read: OUT/marks.json and "
                    "~/Downloads/jastrow-audit-marks*.json)")
    args = ap.parse_args()
    if args.check:
        sys.exit(0 if check(args) else 1)
    if not args.pages:
        ap.error("give --pages (e.g. --pages 1-10) or --check")
    import compare as CO
    import checks as CK
    import report as RP
    if args.no_verify: CO.CFG["verify"] = False
    if args.word_count: CO.CFG["word_count"] = True
    if args.no_reread: CO.CFG["reread3"] = False
    if args.no_stage4: CO.CFG["stage4"] = False
    for kv in args.cfg:
        k, v = kv.split("=", 1)
        if k not in CO.CFG: sys.exit("no such setting in compare.CFG: %s" % k)
        old = CO.CFG[k]
        CO.CFG[k] = (v.lower() in ("1", "true", "yes", "on")) if isinstance(old, bool) else type(old)(v)
    if args.trained or args.ocr_models:
        md = os.path.abspath(args.ocr_models or os.path.join(paths.WORK, "ocrtrain", "models"))
        if not any(os.path.exists(os.path.join(md, "j%s.traineddata" % l)) for l in ("eng", "heb")):
            sys.exit("no trained models in %s: run build/audit/train_ocr.py first" % md)
        os.environ["JASTROW_OCR_MODELS"] = md
        print("OCR models trained on the book, from %s (pages read with other models are OCR'd again)" % md)
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
    V = vocab(args.site)
    # 2a. this OCR's misreadings on this book: count them on every page of the run (quickly: no re-reading), keep
    # them with the page, and build the model from every page audited so far and the user's marks
    import ocrmodel as OM
    print("measuring the OCR's misreadings...")
    saved = {k: CO.CFG[k] for k in ("verify", "reread3", "stage4")}
    CO.CFG.update(verify=False, reread3=False, stage4=False)
    for n_, pid in enumerate(run):
        sp = os.path.join(args.out, "pages", "p%04d" % int(pid), "scan.json")
        if not os.path.exists(sp): continue
        scan = json.load(open(sp))
        if "ocr" not in scan: continue
        if n_ % 10 == 0: print("  p. %s (%d of %d)" % (pid, n_ + 1, len(run)), flush=True)
        try:
            pc = CO.PageCompare(book.page(pid), scan, V, args.out)
            pc.run()
            OM.save_pairs(os.path.dirname(sp), pc.pairs())
        except Exception as e:
            print("  p. %s: %s" % (pid, e))
    CO.CFG.update(saved)
    mf = [os.path.join(args.out, "marks.json")] + ([args.marks] if args.marks else []) + \
        sorted(glob.glob(os.path.expanduser("~/Downloads/jastrow-audit-marks*.json")))
    CO.CM, CO.HCM = OM.build(os.path.join(args.out, "pages"), RP.load_marks(mf))
    print("  %d Latin and %d Hebrew pairs counted, from every page audited so far" % (CO.CM.pairs, CO.HCM.pairs))
    print("comparing...")
    findings, pages, entries = [], {}, []
    for n_, pid in enumerate(run):
        sp = os.path.join(args.out, "pages", "p%04d" % int(pid), "scan.json")
        if n_ % 10 == 0: print("  p. %s (%d of %d)" % (pid, n_ + 1, len(run)), flush=True)
        page = book.page(pid)
        pages[pid] = {}
        if os.path.exists(sp):
            scan = json.load(open(sp))
            if "ocr" in scan:
                pc = CO.PageCompare(page, scan, V, args.out)
                findings += pc.run()
                pages[pid] = {"stats": pc.stats, "scan": scan}
                for w in scan["layout"].get("warnings", []):
                    findings.append(CK.finding(pid, "layout", 2, None, "", "layout: " + w))
                for e in page.entries:
                    if e["eid"] in pc.entry_parts: entries.append((pid, e["eid"], pc.entry_parts[e["eid"]]))
            else:
                findings.append(CK.finding(pid, "layout", 1, None, "", "the page's layout could not be read: %s" %
                                           scan["layout"].get("error")))
        elif pid in errors:
            findings.append(CK.finding(pid, "layout", 1, None, "", "the scan could not be processed: %s" % errors[pid]))
        findings += CK.site_checks(book, pid)
    # the same doubled words found twice, by the comparison ("doubled") and by the check of the site's text
    # ("doubled_text"): keep the second, which names both copies
    dt = {(x["page"], x.get("eid")) for x in findings if x["type"] == "doubled_text"}
    findings = [x for x in findings if not (x["type"] == "doubled" and (x["page"], x.get("eid")) in dt)]
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
    # each run gets its own folder, so an earlier report is never overwritten; the OCR stays shared in pages/
    label = "p" + re.sub(r"[^0-9a-z-]+", "_", args.pages.lower()).strip("_")[:40] + "_" + time.strftime("%Y-%m-%d_%H%M%S")
    rdir = os.path.join(args.out, "runs", label)
    os.makedirs(rdir, exist_ok=True)
    # your verdicts from earlier runs: the report's "Export marks" file, kept in --out as marks.json (a fresh export
    # still in Downloads is picked up too). The latest verdict on each finding wins; the merge is saved back
    mfiles = [os.path.join(args.out, "marks.json")] + ([args.marks] if args.marks else []) + \
        sorted(glob.glob(os.path.expanduser("~/Downloads/jastrow-audit-marks*.json")))
    marks = RP.load_marks(mfiles)
    # every marks file read, and the merged file before it is rewritten, is copied into marks_backup/ under the
    # time it was made (a copy only when its contents are new): no export or autosave can overwrite the only copy
    import hashlib
    bdir = os.path.join(args.out, "marks_backup")
    seen = set()
    if os.path.isdir(bdir):
        for f in os.listdir(bdir):
            try: seen.add(hashlib.sha1(open(os.path.join(bdir, f), "rb").read()).hexdigest())
            except OSError: pass
    for f in mfiles:
        if not os.path.exists(f): continue
        data = open(f, "rb").read()
        h_ = hashlib.sha1(data).hexdigest()
        if h_ in seen: continue
        os.makedirs(bdir, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d_%H%M%S", time.localtime(os.path.getmtime(f)))
        open(os.path.join(bdir, "%s_%s" % (stamp, os.path.basename(f))), "wb").write(data)
        seen.add(h_)
    if marks:
        json.dump({"version": 1, "marks": sorted(marks.values(), key=lambda m: m.get("time") or "")},
                  open(os.path.join(args.out, "marks.json"), "w"), ensure_ascii=False, indent=1)
        print("your marks: %d, from %s" % (len(marks), ", ".join(os.path.basename(f) for f in mfiles if os.path.exists(f))))
    idx, summary = RP.write(rdir, findings, pages, entries, book, run, scans=paths.SCANS, site_url=args.site_url,
                            pages_root=args.out, marks=marks, label=label)
    if tstats:
        extra = "Bavli citations: " + ", ".join("%s %d" % kv for kv in sorted(tstats.items()))
        summary += "\n" + extra
        open(os.path.join(rdir, "summary.txt"), "a").write(extra + "\n")
    # an index of all runs, newest first
    runs = sorted((d for d in os.listdir(os.path.join(args.out, "runs"))
                   if os.path.exists(os.path.join(args.out, "runs", d, "report", "index.html"))), reverse=True,
                  key=lambda d: d.rsplit("_", 2)[-2:])
    import html as _h
    rows = []
    for d in runs:
        sm = os.path.join(args.out, "runs", d, "summary.txt")
        first = open(sm).read().splitlines()[:2] if os.path.exists(sm) else []
        rows.append('<li><a href="runs/%s/report/index.html">%s</a> <span style="color:#777">%s</span></li>' %
                    (d, _h.escape(d), _h.escape(" · ".join(first))))
    open(os.path.join(args.out, "index.html"), "w").write(
        '<!doctype html><meta charset="utf-8"><title>Jastrow audit runs</title><body style="font:15px system-ui;'
        'margin:24px"><h1>Audit runs</h1><ul>%s</ul>' % "\n".join(rows))
    print()
    print(summary)
    print()
    print("this run:   %s" % rdir)
    print("report:     %s" % idx)
    print("summary:    %s" % os.path.join(rdir, "summary.txt"))
    print("all runs:   %s" % os.path.join(args.out, "index.html"))
    print("done in %.0f s" % (time.time() - t0))


if __name__ == "__main__":
    main()
