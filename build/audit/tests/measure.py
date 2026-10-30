#!/usr/bin/env python3
"""Measure the audit: how many planted errors it finds, how many false alarms it gives on the unchanged site, and how
many places it leaves unclear (AUDIT_PLAN.md, "How we know it is getting better").

usage:
  python3 build/audit/tests/measure.py --pages 1-10                    # the real scans (work/audit/pages, OCR'd)
  python3 build/audit/tests/measure.py --pages 1-10 --synthetic        # worn synthetic pages, no scans needed
options: --seed N (which errors are planted; default 1), --per-page N (default 4), --out DIR (default
work/audit_measure), --label TEXT (kept with the result, e.g. "before"), --audit-args "..." (passed on to audit.py)

What it does:
  1. plants errors in a copy of data/ (tests/plant.py; the list in OUT/planted/planted.json);
  2. runs audit.py on the unchanged site, then on the copy. With the real scans, the OCR already in
     work/audit/pages is used (OUT/pages links to it, so the re-reads cached there are shared); with --synthetic, the
     pages are set from the unchanged site and made to look worn (tests/make_synthetic.py --worn);
  3. counts, and appends one line to OUT/results.tsv:
       found        planted errors with a finding at their place, "likely error" or "check", of any kind (a finding
                    the re-reading found to be the OCR's misreading does not count; a doubled phrase may be marked on
                    either copy)
       found_minor  planted errors with only a minor finding at their place
       false        findings ("likely error" or "check") on the unchanged site, comparing it with the scan (the checks
                    of the site's text alone, the Talmud checks and the layout are left out: the change being measured
                    does not touch them). On the synthetic pages every one is false; on the real scans some are real
                    errors in Sefaria's text: your marks then tell them apart (marked_false, marked_error)
       unclear      findings the re-reading left unclear, on the unchanged site, among the likely errors and checks
                    (the ones you would have to read)
Send Claude the summary it prints, or OUT/results.tsv."""
import argparse, glob, json, os, re, shutil, subprocess, sys, time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
AUD = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(AUD))
sys.path.insert(0, AUD); sys.path.insert(0, os.path.dirname(AUD))
import paths  # noqa: E402

SITE_ONLY = {"brackets", "sense_numbers", "stray_char", "headword_text", "headword_display", "alphabetical",
             "doubled_text", "doubled_word", "hyphen_space", "etc_first", "homonym_number"}
OTHER = {"layout", "scan_incomplete", "running_head", "page_number", "guide_word", "column_break_unset"}
UNREAD = {"hebrew_unread", "headword_unread"}


def compared(x):
    return x["type"] not in SITE_ONLY and x["type"] not in OTHER and x["type"] not in UNREAD and \
        not x["type"].startswith("talmud_")


def run_audit(site, out, pages, extra, env):
    cmd = [sys.executable, os.path.join(AUD, "audit.py"), "--pages", pages, "--site", site, "--out", out,
           "--no-talmud"] + extra
    t = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if r.returncode:
        sys.exit("audit.py failed:\n" + r.stdout[-2000:] + r.stderr[-3000:])
    m = re.search(r"this run:\s+(\S+)", r.stdout)
    rd = m.group(1)
    fs = [json.loads(l) for l in open(os.path.join(rd, "findings.jsonl"))]
    return fs, rd, time.time() - t


def at(x, p):
    """a finding at a planted error's place"""
    if str(x["page"]) != str(p["page"]): return False
    if x.get("off") is None:
        # a check of the site's text alone gives the entry and the words, not the place
        return x.get("eid") == p["eid"] and bool(p["new"]) and p["new"][:15] in (x.get("site") or "")
    a, b = x["off"], x.get("end") if x.get("end") is not None else x["off"]
    tol = 25 if p["kind"].startswith("missing") else 3
    lo = p["off"] - (len(p["new"]) + 1 if p["kind"] == "doubled" else 0)       # either copy of a doubled phrase
    return a <= p["end"] + tol and b >= lo - tol


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", default="1-10")
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--per-page", type=int, default=4)
    ap.add_argument("--out", default=os.path.join(paths.WORK, "audit_measure"))
    ap.add_argument("--label", default="")
    ap.add_argument("--audit-args", default="")
    a = ap.parse_args()
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    env = dict(os.environ)
    aud_out = os.path.join(out, "synthetic" if a.synthetic else "real")
    os.makedirs(aud_out, exist_ok=True)
    pages = []
    for part in a.pages.split(","):
        if "-" in part:
            x, y = part.split("-"); pages += [str(p) for p in range(int(x), int(y) + 1)]
        else: pages.append(part)
    if a.synthetic:
        sc = os.path.join(out, "synthetic_scans")
        if not glob.glob(os.path.join(sc, "*1.pdf")):
            print("setting worn synthetic pages %s..." % a.pages, flush=True)
            subprocess.run([sys.executable, os.path.join(HERE, "make_synthetic.py"), "--worn", sc] + pages, check=True,
                           capture_output=True)
        env["JASTROW_SCANS"] = sc
    else:
        # the OCR you already have: OUT/real/pages is a link to work/audit/pages
        src = os.path.join(paths.WORK, "audit", "pages")
        dst = os.path.join(aud_out, "pages")
        missing = [p for p in pages if not os.path.exists(os.path.join(src, "p%04d" % int(p), "scan.json"))]
        if missing: sys.exit("no OCR yet for pp. %s in %s: run audit.py --pages %s first" % (", ".join(missing), src, a.pages))
        if not os.path.lexists(dst): os.symlink(src, dst)
        # your marks, so the misreadings model is the same as in your own runs
        mk = os.path.join(paths.WORK, "audit", "marks.json")
        if os.path.exists(mk): shutil.copy(mk, os.path.join(aud_out, "marks.json"))
    print("planting errors...", flush=True)
    psite = os.path.join(out, "planted")
    os.makedirs(psite, exist_ok=True)
    r = subprocess.run([sys.executable, os.path.join(HERE, "plant.py"), REPO, psite, a.pages, "--seed", str(a.seed),
                        "--per-page", str(a.per_page)], capture_output=True, text=True, check=True)
    print(" ", r.stdout.strip())
    planted = json.load(open(os.path.join(psite, "planted.json")))
    extra = a.audit_args.split()
    print("auditing the unchanged site...", flush=True)
    f0, rd0, t0 = run_audit(REPO, aud_out, a.pages, extra, env)
    print("auditing the site with errors planted...", flush=True)
    f1, rd1, t1 = run_audit(psite, aud_out, a.pages, extra, env)

    def alarm(x): return compared(x) and x["sev"] <= 2 and x.get("verdict") != "ocr_misread"
    def hit(x): return x["sev"] <= 2 and x.get("verdict") != "ocr_misread"
    found, minor, missed = [], [], []
    for p in planted:
        # any finding at the place counts, the checks of the site's text included (they find doubled phrases)
        hits = [x for x in f1 if x["type"] not in UNREAD and at(x, p)]
        if any(hit(x) for x in hits): found.append((p, [x for x in hits if hit(x)]))
        elif hits: minor.append((p, hits))
        else: missed.append(p)
    false0 = [x for x in f0 if alarm(x)]
    minor0 = [x for x in f0 if compared(x) and x["sev"] == 3]
    # unclear: left for you to read (likely error or check); the minor ones are counted apart
    unclear0 = [x for x in f0 if compared(x) and x.get("verdict") == "unclear" and x["sev"] <= 2]
    unclear1 = [x for x in f1 if compared(x) and x.get("verdict") == "unclear" and x["sev"] <= 2]
    unclear0m = [x for x in f0 if compared(x) and x.get("verdict") == "unclear" and x["sev"] == 3]
    # your marks: which of the alarms on the unchanged site you marked
    mk = {}
    try: mk = {m["key"]: m.get("verdict") for m in json.load(open(os.path.join(aud_out, "marks.json")))["marks"]}
    except Exception: pass
    mv = Counter(mk.get(x.get("key")) for x in false0)
    err_keys = {k for k, v in mk.items() if v == "error"}
    err_found = sum(1 for x in f0 if x.get("key") in err_keys and x["sev"] <= 2 and x.get("verdict") != "ocr_misread")
    byk = Counter(p["kind"] for p in planted)
    fk = Counter(p["kind"] for p, _ in found)
    lines = ["measure %s: %s pages %s, seed %d%s" % (a.label or "", "synthetic" if a.synthetic else "real scans", a.pages,
                                                    a.seed, (" (" + a.audit_args + ")") if a.audit_args else ""),
             "planted errors found: %d of %d (minor only: %d, missed: %d)" % (len(found), len(planted), len(minor), len(missed)),
             "  by kind: " + ", ".join("%s %d/%d" % (k, fk[k], byk[k]) for k in sorted(byk)),
             "false alarms on the unchanged site (likely error or check): %d; minor: %d" % (len(false0), len(minor0)),
             "  by kind: " + ", ".join("%s %d" % kv for kv in Counter(x["type"] for x in false0).most_common()),
             "unclear after re-reading, left to you (likely error or check): %d on the unchanged site, %d with errors "
             "planted; minor and unclear: %d" % (len(unclear0), len(unclear1), len(unclear0m)),
             "verdicts on the unchanged site: " + ", ".join("%s %d" % kv for kv in Counter(
                 x.get("verdict") or "-" for x in f0 if compared(x)).most_common())]
    if mk:
        lines.append("your marks among those alarms: site is wrong %d, false alarm %d, not sure %d, unmarked %d; "
                     "findings you marked 'site is wrong' still reported: %d of %d"
                     % (mv["error"], mv["false"], mv["unsure"], mv[None], err_found, len(err_keys)))
    lines.append("missed: " + "; ".join("p. %s %s %s→%s" % (p["page"], p["kind"], p["old"][:25], p["new"][:25]) for p in missed))
    lines.append("minor only: " + "; ".join("p. %s %s %s→%s [%s]" % (p["page"], p["kind"], p["old"][:25], p["new"][:25],
                                                                    ",".join(sorted({x["type"] for x in h}))) for p, h in minor))
    lines.append("runs: %s (%.0f s), %s (%.0f s)" % (rd0, t0, rd1, t1))
    txt = "\n".join(lines)
    print(); print(txt)
    open(os.path.join(out, "last_summary.txt"), "w").write(txt + "\n")
    res = os.path.join(out, "results.tsv")
    new = not os.path.exists(res)
    with open(res, "a") as fh:
        if new: fh.write("time\tlabel\tmode\tpages\tseed\tplanted\tfound\tfound_minor\tfalse\tminor\tunclear\tmarked_false\tmarked_error\n")
        fh.write("%s\t%s\t%s\t%s\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\n" % (
            time.strftime("%Y-%m-%d %H:%M"), a.label, "synthetic" if a.synthetic else "real", a.pages, a.seed,
            len(planted), len(found), len(minor), len(false0), len(minor0), len(unclear0), mv["false"], mv["error"]))
    # the details, for tuning
    json.dump({"found": [[p, [x["type"] for x in h]] for p, h in found], "minor": [[p, [x["type"] for x in h]] for p, h in minor],
               "missed": missed, "false": false0, "unclear": unclear0},
              open(os.path.join(out, "last_details.json"), "w"), ensure_ascii=False, indent=1, default=str)


if __name__ == "__main__":
    main()
