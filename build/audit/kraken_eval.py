"""A kraken model read on the gold lines (pp. 151, 155: the user's checked lines, never trained on) and scored
beside the other readers. KRAKEN_PLAN.md phase 5. Run in kraken's environment:

  source ~/jastrow/kraken-venv/bin/activate
  python3 build/audit/kraken_eval.py read  --model work/kraken/b1/model_odd/best_0.9727.safetensors --name b1_odd
  python3 build/audit/kraken_eval.py score --names b1_even,b1_odd

read   runs `kraken ocr` with the model on each page's own kraken lines (the segmentation already made, so the
       lines are the same ones the gold marks were made on) and keeps the PAGE XML in work/kraken/eval/<name>/.
       The model gives display order (trained with --no-reorder), kept as it is (--no-reorder): kraken's own
       reordering would reverse the book's left-to-right Hebrew lists.
       With --into NAME (e.g. kraken_b1.xml) the reading goes into each page's folder instead, in reading order,
       where kraken_prep.py takes it as a reader (tier "kraken").
score  character error rates in display order (the gold text through kraken_prep.display(), as the labels), whole line / without points / Hebrew letters / points / Latin, on the gold lines, for
       each model named, and for the site, Tesseract, the PDF layer, stock McCATMuS and the Gemini runs cached.
"""
import argparse, glob, json, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import paths  # noqa: E402
import gemini_lines as G  # noqa: E402
import linereview as LR  # noqa: E402

PAGES = os.path.join(paths.WORK, "audit", "pages")
EVAL = os.path.join(paths.WORK, "kraken", "eval")
POINTS = re.compile(r"[֑-ׇ]")


def cmd_read(a):
    od = os.path.join(EVAL, a.name)
    os.makedirs(od, exist_ok=True)
    for p in a.pages.split(","):
        src = os.path.join(PAGES, "p%04d" % int(p), a.xml)
        img = os.path.abspath(os.path.join(PAGES, "p%04d" % int(p), "page.png"))
        s = re.sub(r'imageFilename="[^"]*"', 'imageFilename="%s"' % img, open(src).read(), count=1)
        tmp = os.path.join(od, "p%04d_in.xml" % int(p))
        open(tmp, "w").write(s)
        out = os.path.join(PAGES, "p%04d" % int(p), a.into) if a.into else os.path.join(od, "p%04d.xml" % int(p))
        cmd = ["kraken", "--threads", str(a.threads), "-x", "-f", "xml", "-i", tmp, out, "ocr", "-m", a.model,
               "--base-dir" if a.into else "--no-reorder"] + (["L"] if a.into else [])
        r = subprocess.run(cmd, capture_output=True, text=True)
        os.remove(tmp)
        if r.returncode or not os.path.exists(out):
            sys.exit("p. %s: kraken failed:\n%s" % (p, (r.stdout + r.stderr)[-1500:]))
        print("p. %s: %d lines read" % (p, len(LR.kraken_lines(out))), flush=True)
    json.dump({"model": os.path.abspath(a.model)}, open(os.path.join(od, "model.json"), "w"))


def disp(t, raw=False):
    """a line in display order (left to right as printed), as the training labels are: the models' own output is
    that already (read with --no-reorder); every other reading goes through kraken_prep.display()"""
    import unicodedata
    import kraken_prep as KP
    t = G.norm(t)
    return unicodedata.normalize("NFD", t if raw else KP.display(t))


def score_one(gold, ans, keys, raw=False):
    err, tot = [0] * 5, [0] * 5
    for k in keys:
        g, h = disp(gold[k]), disp(ans.get(k, ""), raw)
        pg, ph = G.parts(g), G.parts(h)
        for i, (x, y) in enumerate([(g, h), (POINTS.sub("", g), POINTS.sub("", h)), (pg[0], ph[0]), (pg[1], ph[1]), (pg[2], ph[2])]):
            err[i] += G.lev(x, y); tot[i] += len(x)
    return [100 * e / max(1, t) for e, t in zip(err, tot)]


def cmd_score(a):
    L, gold = G.load(a.pilot, a.gold)
    keys = sorted((k for k in gold if k[0] in a.pages.split(",")), key=lambda k: (int(k[0]), k[1]))
    R = {"site": {k: L[k]["site"] for k in keys}}
    for r in ("tesseract", "pdf", "kraken"):
        R[{"kraken": "kraken McCATMuS (stock)"}.get(r, r)] = {k: L[k]["readers"].get(r, "") for k in keys}
    for cf in sorted(glob.glob(os.path.join(paths.report("gemini_lines"), "*", "examples.json"))):
        c = json.load(open(cf))
        if sum(1 for k in keys if c.get("%s:%d" % k)) < 0.9 * len(keys): continue      # a short trial run
        R["gemini " + os.path.basename(os.path.dirname(cf))] = {k: c.get("%s:%d" % k, "") for k in keys}
    for name in [n for n in a.names.split(",") if n]:
        got = {}
        for p in a.pages.split(","):
            f = os.path.join(EVAL, name, "p%04d.xml" % int(p))
            if not os.path.exists(f): sys.exit("%s: p. %s not read (kraken_eval.py read)" % (name, p))
            got.update({(p, kid): t for kid, t in ((k["id"], k["kraken"]) for k in LR.kraken_lines(f))})
        R["kraken " + name] = {k: got.get((k[0], L[k]["kid"]), "") for k in keys}
    print("%d gold lines (pp. %s). Character error rate:" % (len(keys), a.pages))
    print("%-36s %6s %8s %7s %7s %6s" % ("reader", "whole", "no pts", "Hebrew", "points", "Latin"))
    print("(all in display order, left to right as printed, as the training labels are)")
    for name, ans in R.items():
        print("%-36s %5.1f%% %7.1f%% %6.1f%% %6.1f%% %5.1f%%" % (
            name, *score_one(gold, ans, keys, raw=name.startswith("kraken b"))))
    if a.show:
        for name in [n for n in a.names.split(",") if n]:
            ans = R["kraken " + name]
            worst = sorted(keys, key=lambda k: -G.lev(disp(gold[k]), disp(ans[k], True)))[:a.show]
            print("\n== kraken %s: worst lines (in reading order)" % name)
            from kraken.lib.bidi import get_display
            for k in worst:
                print("%s:%d\n  gold   %s\n  kraken %s" % (k[0], k[1], G.norm(gold[k]), get_display(G.norm(ans[k]), base_dir="L")))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], epilog=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["read", "score"])
    ap.add_argument("--model")
    ap.add_argument("--name")
    ap.add_argument("--names", default="")
    ap.add_argument("--pages", default="151,155")
    ap.add_argument("--xml", default="kraken_mccatmus.xml")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--into", help="read: write each page's PAGE XML into its own folder under this name, in reading "
                                   "order (kraken's reordering), as a reader for kraken_prep.py: e.g. kraken_b1.xml")
    ap.add_argument("--show", type=int, default=0, help="score: print each model's N worst lines")
    ap.add_argument("--pilot", default=os.path.join(paths.WORK, "audit", "lines", "pilot", "lines.json"))
    ap.add_argument("--gold", default=os.path.expanduser("~/Downloads/jastrow-lines-pilot-2026-11-052122.json"))
    a = ap.parse_args()
    if a.cmd == "read" and not (a.model and a.name): sys.exit("read needs --model and --name")
    {"read": cmd_read, "score": cmd_score}[a.cmd](a)


if __name__ == "__main__":
    main()
