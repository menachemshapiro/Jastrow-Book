#!/usr/bin/env python3
"""Train Tesseract on the 1903 book itself, with Sefaria's text as the answer key.

Where the scan and the site agree, the site's text is what the page says. Those places are cut out of the scans and
written as training pairs (an image and its text), and Tesseract's best English and Hebrew models are fine-tuned on
them. The Hebrew training text carries Sefaria's vowel points, so the trained model learns to read them; the stock
model mostly can't. The audit then reads the scans with the trained models (audit.py --trained).

usage:
  python3 build/audit/train_ocr.py check                  the tools, the base models, the training scripts
  python3 build/audit/train_ocr.py prepare [--pages 1-200]  training pairs from pages the audit has OCR'd
  python3 build/audit/train_ocr.py train [--which eng|heb|both] [--iterations N]
  python3 build/audit/train_ocr.py fetch                  only the downloads train needs (models, tesstrain)
  python3 build/audit/train_ocr.py status                 what has been prepared and trained

What goes in, and what is left out:
  - English: stretches of three words or more on a line of the scan (the whole line where it has no Hebrew), every
    word of which the audit found word for word on the site, or as a misreading this OCR makes often (ocrmodel).
    The text is the site's, with its punctuation. Words divided at the line's end and raised letters (26ᵇ) are
    left out.
  - Hebrew: single words the audit paired with the site's, with the same letters; or (not headwords) letters this OCR
    is known to confuse. The text is the site's, with its vowel points.
  - The site's text has errors of its own; they are few among thousands of examples, and only words the audit could
    pair go in. Pages flagged as incomplete scans are left out.

Everything is in work/ocrtrain/ (the paths come from build/paths.py):
  gt/eng, gt/heb       the training pairs (NAME.png + NAME.gt.txt)
  tessdata_best/       Tesseract's best eng and heb models (downloaded once; the trainable kind)
  tesstrain/           Tesseract's training scripts (cloned once)
  data/                the training's working files
  models/              jeng.traineddata and jheb.traineddata, the result: python3 build/audit/audit.py --trained ...

Needs: tesseract with its training tools (lstmtraining, combine_tessdata, unicharset_extractor: on Ubuntu they come
with the tesseract-ocr package), make, git, `pip install python-bidi`, and an internet connection for the first
`train`. Training takes a few
hours on a laptop; it can be stopped and run again (tesstrain picks up where it was)."""
import argparse, glob, json, os, re, shutil, subprocess, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import paths  # noqa: E402

ROOT = os.path.join(paths.WORK, "ocrtrain")
AUDIT = os.path.join(paths.WORK, "audit")
BEST = "https://github.com/tesseract-ocr/tessdata_best/raw/main/%s.traineddata"
TESSTRAIN = "https://github.com/tesseract-ocr/tesstrain"
LANGDATA = "https://github.com/tesseract-ocr/langdata_lstm/raw/main/%s"
TOOLS = ("tesseract", "lstmtraining", "combine_tessdata", "unicharset_extractor", "make", "git")


def check():
    ok = True
    for t in TOOLS:
        w = shutil.which(t)
        print(("  ok       " if w else "  MISSING  ") + t + ("" if w else "  (Ubuntu: sudo apt install tesseract-ocr make git)"))
        ok = ok and bool(w)
    try:
        import bidi  # noqa: F401  (tesstrain needs it for Hebrew)
        print("  ok       python-bidi")
    except ImportError:
        print("  MISSING  python-bidi  (pip install python-bidi, in the same Python as the audit)"); ok = False
    for lang in ("eng", "heb"):
        p = os.path.join(ROOT, "tessdata_best", "%s.traineddata" % lang)
        print(("  ok       " if os.path.exists(p) else "  later    ") + "base model %s (downloaded by `train`)" % lang)
    print(("  ok       " if os.path.isdir(os.path.join(ROOT, "tesstrain")) else "  later    ") + "tesstrain (cloned by `train`)")
    n = len(glob.glob(os.path.join(AUDIT, "pages", "p*", "scan.json")))
    print("  %d pages OCR'd by the audit (the more, the better: 100 or more is a good start)" % n)
    return ok


def page_list(spec):
    have = sorted(int(os.path.basename(os.path.dirname(p))[1:]) for p in glob.glob(os.path.join(AUDIT, "pages", "p*", "scan.json")))
    if not spec: return [str(p) for p in have]
    want = set()
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-"); want |= set(range(int(a), int(b) + 1))
        else: want.add(int(part))
    return [str(p) for p in have if p in want]


def prepare(spec, clear=True):
    import sitetext as ST
    import compare as CO
    import ocrmodel as OM
    import report as RP
    from audit import vocab
    from PIL import Image
    book = ST.Book(paths.REPO)
    V = vocab(paths.REPO)
    CO.CFG["verify"] = False
    marks = RP.load_marks([os.path.join(AUDIT, "marks.json")])
    CO.CM, CO.HCM = OM.build(os.path.join(AUDIT, "pages"), marks)
    real_errors = {((m.get("finding") or {}).get("page"), (m.get("finding") or {}).get("eid")) for m in marks.values()
                   if m.get("verdict") == "error"}
    gt = {k: os.path.join(ROOT, "gt", k) for k in ("eng", "heb")}
    for d in gt.values():
        if clear and os.path.isdir(d): shutil.rmtree(d)
        os.makedirs(d, exist_ok=True)
    n_lat = n_heb = 0
    pages = page_list(spec)
    print("preparing training pairs from %d page(s)..." % len(pages))
    for pid in pages:
        wd = os.path.join(AUDIT, "pages", "p%04d" % int(pid))
        scan = json.load(open(os.path.join(wd, "scan.json")))
        if "ocr" not in scan: continue
        try:
            page = book.page(pid)
            pc = CO.PageCompare(page, scan, V, AUDIT)
            pc.run()
        except Exception as e:
            print("  p. %s: %s" % (pid, e)); continue
        if pc.stats.get("scan_problem") or any(f["type"] == "scan_incomplete" for f in pc.f): continue
        img = Image.open(os.path.join(wd, "page.png")).convert("L")
        lh = pc.lineh
        # ---- English lines
        matched = {j: si for si, j in pc.s2k.items()}
        # one site word against one scan word that this OCR misreads often: the site's word is the answer
        for tag, i1, i2, j1, j2 in pc.ops:
            if tag != "replace" or i2 - i1 != j2 - j1 or i2 - i1 > 3: continue
            for s_, k_ in zip(pc.S[i1:i2], pc.K[j1:j2]):
                if s_["heb"] or k_["hyph"]: continue
                n, _ = CO.CM.seen(OM.lat(s_["text"]), OM.lat(k_.get("raw", k_["text"])))
                if n is not None and n >= CO.CFG["cm_min"]: matched[k_["j"]] = s_["i"]
        flagged = {(f.get("eid")) for f in pc.f if f["sev"] <= 2}
        spos = {t["i"]: n for n, t in enumerate(pc.S)}
        by_line = {}
        for t in pc.k:
            for li in t.get("lines", [t["line"]]): by_line.setdefault(li, []).append(t)
        for ln in pc.lines:
            toks = sorted(by_line.get(ln["i"], []), key=lambda t: t["box"][0])
            # runs of English words on the line that the site has word for word, with nothing between them: the
            # whole line when it has no Hebrew, otherwise each stretch of three words or more between the Hebrew
            runs, cur = [], []
            for t in toks:
                good = (t["script"] == "lat" and t["key"] and not t["hyph"] and not t.get("page_end_hyph")
                        and len(t["lines"]) == 1 and t["j"] in matched)
                if good and cur and spos.get(matched[t["j"]], -9) != spos.get(matched[cur[-1]["j"]], -9) + 1:
                    runs.append(cur); cur = []
                if good: cur.append(t)
                else:
                    if cur: runs.append(cur)
                    cur = []
            if cur: runs.append(cur)
            for r_i, run in enumerate(runs):
                if len(run) < 3: continue
                S = [pc.S[spos[matched[t["j"]]]] for t in run if matched[t["j"]] in spos]
                if len(S) != len(run): continue
                if any(t["heb"] or t.get("sup") or t.get("side") for t in S): continue
                if any(t["eid"] in flagged or (pid, t["eid"]) in real_errors for t in S): continue
                text = re.sub(r"\s+", " ", page.plain[S[0]["off"]:S[-1]["end"]]).strip()
                if re.search("[\u0590-\u05ff]", text) or len(text) < 8: continue
                x0, x1 = run[0]["box"][0], run[-1]["box"][2]
                b = ln["box"]
                crop = img.crop((max(0, x0 - 8), max(0, int(b[1] - 0.18 * lh)), x1 + 8, int(b[3] + 0.18 * lh)))
                name = "p%04d_l%03d_%d" % (int(pid), ln["i"], r_i)
                crop.save(os.path.join(gt["eng"], name + ".png"))
                open(os.path.join(gt["eng"], name + ".gt.txt"), "w").write(text + "\n")
                n_lat += 1
        # ---- Hebrew words
        for k_, (t, w) in enumerate(pc.heb_pair_toks):
            a, b_ = OM.heb_letters(t["text"]), OM.heb_letters(w["text"])
            if len(a) < 2: continue
            if a != b_:
                if t["hw"]: continue
                n, _ = CO.HCM.seen(a, b_)
                if n is None or n < CO.CFG["cm_min"]: continue
            if (pid, t["eid"]) in real_errors: continue
            text = re.sub(r"[^֐-׿'\"״׳]", "", t["text"]).strip()
            if not text: continue
            bx = w["box"]
            crop = img.crop((max(0, bx[0] - 6), max(0, int(bx[1] - 0.3 * lh)), bx[2] + 6, int(bx[3] + 0.3 * lh)))
            name = "p%04d_w%04d" % (int(pid), k_)
            crop.save(os.path.join(gt["heb"], name + ".png"))
            open(os.path.join(gt["heb"], name + ".gt.txt"), "w").write(text + "\n")
            n_heb += 1
        print("  p. %s: %d English lines, %d Hebrew words so far" % (pid, n_lat, n_heb), flush=True)
    print("training pairs: %d English lines (%s), %d Hebrew words (%s)" % (n_lat, gt["eng"], n_heb, gt["heb"]))
    if n_lat < 300 or n_heb < 300:
        print("that is little to train on: audit more pages first (python3 build/audit/audit.py --pages 11-150), then "
              "prepare again")


def download(url, dest, what, min_size):
    """Download url to dest, trying three times. On failure: say plainly what failed and how to get the file by hand,
    and stop (no traceback). A file already at dest is kept. A download smaller than min_size bytes, or an HTML
    page, is taken as a failure (an error page saved under the model's name would break the training later)."""
    import time, socket, urllib.error
    if os.path.exists(dest) and os.path.getsize(dest) >= min_size: return
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    part = dest + ".part"
    err = None
    for attempt in range(3):
        if attempt: time.sleep(10)
        try:
            if os.path.exists(part): os.remove(part)
            with urllib.request.urlopen(url, timeout=60) as r, open(part, "wb") as f:
                shutil.copyfileobj(r, f)
            with open(part, "rb") as f: head = f.read(200).lstrip().lower()
            if os.path.getsize(part) < min_size or head.startswith((b"<!doctype", b"<html")):
                raise IOError("got %d bytes, not the file (an error page?)" % os.path.getsize(part))
            os.replace(part, dest)
            return
        except (urllib.error.URLError, socket.error, IOError) as e:
            err = e
            print("  %s: attempt %d failed: %s" % (what, attempt + 1, getattr(e, "reason", e)), flush=True)
    if os.path.exists(part): os.remove(part)
    msg = str(getattr(err, "reason", err))
    print("\ncould not download %s\n  from: %s\n  to:   %s\n  error: %s" % (what, url, dest, msg))
    if "name resolution" in msg or "Name or service not known" in msg or "getaddrinfo" in msg:
        print("This computer could not look up the server's name (DNS), so the download never started. Check:\n"
              "  getent hosts github.com raw.githubusercontent.com\n"
              "Both should print an address. If not: check the internet connection (Wi-Fi, VPN), or restart the\n"
              "name service: sudo systemctl restart systemd-resolved")
    print("Or download the file by hand, then run train again (files already there are kept):\n"
          "  curl -fL --retry 3 -o '%s' '%s'" % (dest, url))
    sys.exit(1)


def fetch():
    """The base models, tesstrain and its character-set files: everything train needs from the internet."""
    for lang in ("eng", "heb"):
        p = os.path.join(ROOT, "tessdata_best", "%s.traineddata" % lang)
        if not os.path.exists(p): print("downloading Tesseract's best %s model..." % lang, flush=True)
        download(BEST % lang, p, "the %s base model" % lang, 1000000)
    tt = os.path.join(ROOT, "tesstrain")
    if os.path.isdir(tt) and not os.path.exists(os.path.join(tt, "Makefile")):
        shutil.rmtree(tt)  # a clone that failed half-way
    if not os.path.isdir(tt):
        print("cloning tesstrain...", flush=True)
        if subprocess.run(["git", "clone", "--depth", "1", TESSTRAIN, tt]).returncode:
            if os.path.isdir(tt): shutil.rmtree(tt)
            sys.exit("\ncould not clone %s into %s\nCheck the internet connection, or clone it by hand:\n"
                     "  git clone --depth 1 %s '%s'" % (TESSTRAIN, tt, TESSTRAIN, tt))
    # the stock character sets of every script, which tesstrain wants (it would fetch them with wget)
    mk = open(os.path.join(tt, "Makefile")).read()
    scripts = " ".join(re.findall(r"^TESSERACT_SCRIPTS\s*\+?:?=\s*(.*)$", mk, re.M)).split()
    ld = os.path.join(ROOT, "data", "langdata")
    need = ["radical-stroke.txt"] + ["%s.unicharset" % x for x in scripts]
    todo = [f for f in need if not os.path.exists(os.path.join(ld, f))]
    if todo: print("downloading %d character-set files for tesstrain..." % len(todo), flush=True)
    for f in todo:
        download(LANGDATA % f, os.path.join(ld, f), f, 50)
    print("downloads: all there")


def train(which, iterations):
    if not check(): sys.exit("install what is missing first")
    fetch()
    os.makedirs(os.path.join(ROOT, "models"), exist_ok=True)
    for lang in (("eng", "heb") if which == "both" else (which,)):
        g = os.path.join(ROOT, "gt", lang)
        n = len(glob.glob(os.path.join(g, "*.gt.txt")))
        if n < 50: print("%s: only %d training pairs; run prepare first" % (lang, n)); continue
        # leftovers of a run that failed half-way (an empty .box or .lstmf) would be taken as done
        for f in glob.glob(os.path.join(g, "*.box")) + glob.glob(os.path.join(g, "*.lstmf")):
            if os.path.getsize(f) == 0: os.remove(f)
        it = iterations or (4000 if lang == "eng" else 8000)
        name = "j" + lang
        cmd = ["make", "-C", os.path.join(ROOT, "tesstrain"), "training", "MODEL_NAME=" + name, "START_MODEL=" + lang,
               "TESSDATA=" + os.path.join(ROOT, "tessdata_best"), "GROUND_TRUTH_DIR=" + g,
               "DATA_DIR=" + os.path.join(ROOT, "data"), "MAX_ITERATIONS=%d" % it,
               "PSM=" + ("7" if lang == "eng" else "8"), "PY_CMD=" + sys.executable] + (["LANG_TYPE=RTL"] if lang == "heb" else [])
        log = os.path.join(ROOT, "train_%s.log" % lang)
        print("training %s on %d pairs, %d iterations (log: %s)..." % (name, n, it, log), flush=True)
        with open(log, "w") as lf:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in p.stdout:
                lf.write(line)
                if re.search(r"At iteration \d+/\d+/\d+.*BCER train|Finished|best model|Error|error:", line):
                    print("  " + line.strip()[:160], flush=True)
            p.wait()
        out = os.path.join(ROOT, "data", name + ".traineddata")
        if p.returncode or not os.path.exists(out):
            print("%s: training failed (see %s)" % (name, log)); continue
        shutil.copy(out, os.path.join(ROOT, "models", name + ".traineddata"))
        print("%s: done: %s" % (name, os.path.join(ROOT, "models", name + ".traineddata")))
    print("next: python3 build/audit/audit.py --trained --pages 1-10   (pages are OCR'd again with the new models)")


def status():
    for lang in ("eng", "heb"):
        n = len(glob.glob(os.path.join(ROOT, "gt", lang, "*.gt.txt")))
        m = os.path.join(ROOT, "models", "j%s.traineddata" % lang)
        print("%s: %d training pairs; model: %s" % (lang, n, m if os.path.exists(m) else "not trained yet"))
        log = os.path.join(ROOT, "train_%s.log" % lang)
        if os.path.exists(log):
            last = [l for l in open(log) if "BCER" in l][-1:]
            if last: print("  last: " + last[0].strip()[:160])


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=("check", "prepare", "fetch", "train", "status"))
    ap.add_argument("--pages")
    ap.add_argument("--which", choices=("eng", "heb", "both"), default="both")
    ap.add_argument("--iterations", type=int)
    a = ap.parse_args()
    if a.cmd == "check": sys.exit(0 if check() else 1)
    if a.cmd == "prepare": prepare(a.pages)
    if a.cmd == "fetch": fetch()
    if a.cmd == "train": train(a.which, a.iterations)
    if a.cmd == "status": status()


if __name__ == "__main__":
    main()
