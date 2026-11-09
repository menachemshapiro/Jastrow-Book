#!/usr/bin/env python3
"""Tesseract trained on whole checked lines (the trial of 8 Nov): can a trained Tesseract be a second reader beside
kraken, making its own mistakes?

The lines are the ones kraken trains on (kraken_prep.py export: checked by the user, or agreed by the readers and
the site), with the same labels: display order (left to right as printed), no vowel points. Each line is cut from
the page along kraken's line polygon. One half of the pages only (odd by default), so the model can later vouch for
lines on the other half; pp. 151 and 155 (the gold lines) are never in it.

  python3 build/audit/tess_lines.py prepare [--half odd]       line images + texts into work/ocrtrain/lines/<half>/
  python3 build/audit/tess_lines.py bench [--start heb]        a few minutes of training: seconds per iteration
  python3 build/audit/tess_lines.py train [--start heb] [--iterations N]
  python3 build/audit/tess_lines.py score [--model NAME]       the gold lines read and scored beside the others
  python3 build/audit/tess_lines.py read [--pages 1-100]       every kraken line read by the other half's model
  python3 build/audit/tess_lines.py compare [--batches b1,b2]  what it would admit and what it doubts, per batch

Runs in ~/jastrow/kraken-venv (the labels go through kraken's own bidi, as for kraken). The training is capped like kraken's (train_tess.sh).
"""
import argparse, glob, json, os, re, shutil, subprocess, sys, time, unicodedata
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import paths  # noqa: E402

ROOT = os.path.join(paths.WORK, "ocrtrain")
LINES = os.path.join(ROOT, "lines")
PAGES = os.path.join(paths.WORK, "audit", "pages")
LREV = os.path.join(paths.WORK, "audit", "lines")
DL = os.path.expanduser("~/Downloads")
PHONE = os.path.join(LREV, "phone")
BATCHES = [  # review, marks (globs)
    ("b1", ["jastrow-lines-pilot-2026-11-052122.json", "jastrow-lines-b1-check-*.json"], "jastrow-lines-b1-check-phone-*.json"),
    ("b2", ["jastrow-lines-b2-check-*.json"], "jastrow-lines-b2-check-phone-*.json"),
    ("b3", ["jastrow-lines-b3-check-*.json"], "jastrow-lines-b3-check-phone-*.json"),
    ("b4", ["jastrow-lines-b4-check-*.json"], "jastrow-lines-b4-check-phone-*.json"),
]
PAD = 4


def marks_for(dl_globs, phone_glob):
    out = []
    for g in dl_globs: out += sorted(glob.glob(os.path.join(DL, g)))
    out += sorted(glob.glob(os.path.join(PHONE, phone_glob)))
    return out


def crop_line(img, pts):
    from PIL import Image, ImageDraw
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    x0, y0 = max(0, min(xs) - PAD), max(0, min(ys) - PAD)
    x1, y1 = min(img.width, max(xs) + PAD), min(img.height, max(ys) + PAD)
    c = img.crop((x0, y0, x1, y1))
    m = Image.new("L", c.size, 0)
    ImageDraw.Draw(m).polygon([(x - x0, y - y0) for x, y in pts], fill=255)
    m = m.point(lambda v: 255 if v else 0)
    white = Image.new("L", c.size, 255)
    # a little room around the polygon, so letters touching its edge are not cut
    from PIL import ImageFilter
    m = m.filter(ImageFilter.MaxFilter(5))
    return Image.composite(c, white, m)


def lines_of(xml):
    root = ET.parse(xml).getroot(); ns = root.tag.split("}")[0] + "}"
    img = next(root.iter(ns + "Page")).get("imageFilename")
    out = []
    for ln in root.iter(ns + "TextLine"):
        co = ln.find(ns + "Coords"); u = ln.find(ns + "TextEquiv/" + ns + "Unicode")
        pts = [tuple(int(v) for v in p.split(",")) for p in co.get("points").split()]
        out.append((ln.get("id"), pts, u.text if u is not None else None))
    return img, out


def prepare(half):
    from PIL import Image
    tmp = os.path.join(ROOT, "lines_export")
    shutil.rmtree(tmp, ignore_errors=True)
    for b, dlg, ph in BATCHES:
        rev = os.path.join(LREV, b, "lines.json")
        if not os.path.exists(rev): continue
        m = marks_for(dlg, ph)
        print("== %s (%d mark files)" % (b, len(m)), flush=True)
        r = subprocess.run([sys.executable, os.path.join(HERE, "kraken_prep.py"), "export", "--review", rev, "--out", tmp] +
                           (["--marks"] + m if m else []), capture_output=True, text=True)
        print(r.stdout.strip()[-400:] or r.stderr.strip()[-800:])
        if r.returncode: sys.exit("export failed")
    out = os.path.join(LINES, half)
    shutil.rmtree(out, ignore_errors=True); os.makedirs(out)
    n = chars = 0
    for xml in sorted(glob.glob(os.path.join(tmp, half, "*.xml"))):
        imgf, lines = lines_of(xml)
        img = Image.open(imgf).convert("L")
        pg = int(re.search(r"p(\d+)\.xml", xml).group(1))
        for k, (lid, pts, t) in enumerate(lines):
            if not t or not t.strip(): continue
            t = unicodedata.normalize("NFC", t.strip())
            name = os.path.join(out, "p%04d_%03d" % (pg, k))
            crop_line(img, pts).save(name + ".png")
            open(name + ".gt.txt", "w", encoding="utf-8").write(t + "\n")
            n += 1; chars += len(t)
    json.dump({"half": half, "lines": n, "chars": chars, "made": time.strftime("%Y-%m-%d %H:%M")},
              open(os.path.join(out, "info.json"), "w"))
    print("%s half: %d lines, %d characters -> %s" % (half, n, chars, out))


def make_cmd(name, start, gt, iterations, extra=()):
    return ["make", "-C", os.path.join(ROOT, "tesstrain"), "training", "MODEL_NAME=" + name, "START_MODEL=" + start,
            "TESSDATA=" + os.path.join(ROOT, "tessdata_best"), "GROUND_TRUTH_DIR=" + gt,
            "DATA_DIR=" + os.path.join(ROOT, "data"), "MAX_ITERATIONS=%d" % iterations, "PSM=13",
            "PY_CMD=" + sys.executable] + list(extra)


def run_train(name, start, half, iterations, log):
    gt = os.path.join(LINES, half)
    if not glob.glob(os.path.join(gt, "*.gt.txt")): sys.exit("run prepare first")
    for f in glob.glob(os.path.join(gt, "*.box")) + glob.glob(os.path.join(gt, "*.lstmf")):
        if os.path.getsize(f) == 0: os.remove(f)
    cmd = make_cmd(name, start, gt, iterations)
    t0 = time.time(); best = None; last = None
    with open(log, "w") as lf:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in p.stdout:
            lf.write(line); lf.flush()
            m = re.search(r"At iteration (\d+)/(\d+)/(\d+).*?BCER train=([\d.]+)%", line)
            if m:
                last = (int(m.group(2)), float(m.group(4)), time.time() - t0)
                if re.search(r"New best", line): best = last
                print("  iteration %s: train error %.2f%%  (%.0f min)" % (m.group(2), last[1], last[2] / 60), flush=True)
            elif re.search(r"Finished|Error|error:|Deserialize failed", line):
                print("  " + line.strip()[:200], flush=True)
        p.wait()
    return p.returncode, best, last, time.time() - t0


def bench(start, half):
    """a short run in its own folder: seconds per iteration, counted after the line files are made"""
    name = "jbench_" + start
    shutil.rmtree(os.path.join(ROOT, "data", name), ignore_errors=True)
    log = os.path.join(ROOT, "bench_%s.log" % start)
    rc, best, last, secs = run_train(name, start, half, int(os.environ.get("BENCH_IT", "300")), log)
    txt = open(log).read()
    its = [(int(a), float(b)) for a, b in re.findall(r"At iteration \d+/(\d+)/\d+.*?BCER train=([\d.]+)%", txt)]
    print("bench %s: exit %s; %s" % (start, rc, its[-3:]))
    shutil.rmtree(os.path.join(ROOT, "data", name), ignore_errors=True)


def train(start, half, iterations):
    name = "jline_%s_%s" % (half, start)
    log = os.path.join(ROOT, "train_%s.log" % name)
    print("training %s: %d iterations (log %s)" % (name, iterations, log), flush=True)
    rc, best, last, secs = run_train(name, start, half, iterations, log)
    out = os.path.join(ROOT, "data", name + ".traineddata")
    if rc or not os.path.exists(out): sys.exit("%s: training failed (exit %s); see %s" % (name, rc, log))
    os.makedirs(os.path.join(ROOT, "models"), exist_ok=True)
    shutil.copy(out, os.path.join(ROOT, "models", name + ".traineddata"))
    print("%s: done in %.1f h; best train error %s; model %s" % (name, secs / 3600, best and "%.2f%% at %d" % (best[1], best[0]),
          os.path.join(ROOT, "models", name + ".traineddata")))


HEBL = re.compile("[\u05d0-\u05ea]")


def read_visual(f, model, td):
    """a line image read by the model, as printed, left to right: Tesseract's words put back in the order of their
    boxes, each Hebrew word's letters (which it gives in logical order) turned round, its bidi marks dropped. The
    model learned the lines in that order (the labels are display order), so this is its own reading"""
    r = subprocess.run(["tesseract", f, "stdout", "--tessdata-dir", td, "-l", model, "--psm", "13", "-c", "tessedit_create_tsv=1"],
                       capture_output=True, text=True)
    words = []
    for row in r.stdout.splitlines()[1:]:
        c = row.split("\t")
        if len(c) < 12 or not c[11].strip(): continue
        w = re.sub("[\u200e\u200f\u202a-\u202e\u2066-\u2069]", "", c[11])
        if HEBL.search(w): w = w[::-1]
        words.append((int(c[6]), w))
    return " ".join(w for _, w in sorted(words))


MIRROR = str.maketrans("()[]{}", ")(][}{")


def word_logical(v):
    """a reading in printed order with each Hebrew word's letters back in logical order (and its brackets mirrored):
    what same_reading compares (it takes the English in order and the Hebrew words in any order)"""
    return " ".join(w[::-1].translate(MIRROR) if HEBL.search(w) else w for w in v.split())


def logical(v):
    """a reading in printed order (left to right, as read_visual gives it) in logical order, for showing and using
    on a check card: the bidi algorithm with a left-to-right base turns each right-to-left run round, words and
    letters (word_logical turns only the letters, enough for same_reading; the user saw Hebrew phrases backwards,
    9 Nov)"""
    from kraken.lib.bidi import get_display
    return get_display(v, base_dir="L")


def score(model):
    """the gold lines cut along kraken's polygons, read by the model (psm 13), scored as kraken_eval does: the reading
    taken as display order, and as logical order put through display(); the better of the two is reported"""
    from PIL import Image
    import kraken_eval as E
    import kraken_prep as KP
    G = E.G
    L, gold = G.load(os.path.join(LREV, "pilot", "lines.json"), os.path.join(DL, "jastrow-lines-pilot-2026-11-052122.json"))
    keys = sorted((k for k in gold if k[0] in ("151", "155")), key=lambda k: (int(k[0]), k[1]))
    tmp = os.path.join(ROOT, "gold_crops"); os.makedirs(tmp, exist_ok=True)
    polys = {}
    for p in ("151", "155"):
        _, lines = lines_of(os.path.join(PAGES, "p%04d" % int(p), "kraken_mccatmus.xml"))
        img = Image.open(os.path.join(PAGES, "p%04d" % int(p), "page.png")).convert("L")
        for lid, pts, _ in lines: polys[(p, lid)] = (img, pts)
    td = os.path.join(ROOT, "models")
    got = {}
    for k in keys:
        img, pts = polys[(k[0], L[k]["kid"])]
        f = os.path.join(tmp, "%s_%03d.png" % k); crop_line(img, pts).save(f)
        got[k] = read_visual(f, model, td)
    json.dump({"%s:%d" % k: v for k, v in got.items()}, open(os.path.join(ROOT, "gold_%s.json" % model), "w"), ensure_ascii=False, indent=0)
    e = E.score_one(gold, got, keys, raw=True)
    print("%-26s whole %5.1f%%  no pts %5.1f%%  Hebrew letters %5.1f%%  Latin %5.1f%%   (kraken r3: no pts 1.5-1.6%%, Hebrew 2.3-3.1%%, Latin 1.3-1.4%%)" % (
        model, e[0], e[1], e[2], e[4]))
    adm = right = 0
    for k in keys:
        h = got[k]
        for t in (word_logical(h),):
            if t and KP.same_reading(L[k]["site"], t):
                adm += 1; right += G.norm(L[k]["site"]) == G.norm(gold[k]); break
    print("as a tie-breaker: agrees with the site on %d of %d gold lines; the site right on %d of them" % (adm, len(keys), right))
    for k in keys[:5]: print("  %s:%d\n    gold %s\n    read %s" % (k[0], k[1], gold[k], got[k]))


def model_for(page):
    """the model that never saw this page: odd pages are read by the even model and the reverse; a page neither
    trained on (over 100) by the other half's model too, so both halves are used"""
    want = "jline_%s_eng" % ("even" if int(page) % 2 else "odd")
    if os.path.exists(os.path.join(ROOT, "models", want + ".traineddata")): return want
    return None


def read_pages(spec, threads):
    """every kraken line of these pages read by the trained Tesseract of the other half, in printed order:
    work/audit/pages/pNNNN/tess_line.json {"model", "lines": {line id: text}}"""
    from PIL import Image
    from concurrent.futures import ThreadPoolExecutor
    pages = []
    for part in spec.split(","):
        lo, _, hi = part.partition("-"); pages += list(range(int(lo), int(hi or lo) + 1))
    td = os.path.join(ROOT, "models"); os.environ["OMP_THREAD_LIMIT"] = "1"      # many single-line reads side by side
    tmp = os.path.join(ROOT, "read_tmp"); os.makedirs(tmp, exist_ok=True)
    done = 0
    for pg in pages:
        d = os.path.join(PAGES, "p%04d" % pg); xml = os.path.join(d, "kraken_mccatmus.xml")
        model = model_for(pg)
        if not os.path.exists(xml): print("p. %d: no kraken lines (not segmented)" % pg); continue
        if not model: print("p. %d: no trained model for it" % pg); continue
        _, lines = lines_of(xml)
        img = Image.open(os.path.join(d, "page.png")).convert("L")
        jobs = []
        for k, (lid, pts, _) in enumerate(lines):
            f = os.path.join(tmp, "%04d_%03d.png" % (pg, k)); crop_line(img, pts).save(f); jobs.append((lid, f))
        def one(j): return j[0], read_visual(j[1], model, td)
        with ThreadPoolExecutor(threads) as ex: got = dict(ex.map(one, jobs))
        for _, f in jobs: os.remove(f)
        json.dump({"model": model, "lines": got}, open(os.path.join(d, "tess_line.json"), "w"), ensure_ascii=False)
        done += 1
        print("p. %d: %d lines read by %s" % (pg, len(got), model), flush=True)
    print("%d pages read" % done)


def compare(batches):
    """how the trained Tesseract would change the check pages: per batch, the lines it reads as the site has them,
    against the tiers kraken_prep gives today. 'would admit': disputed lines it agrees with the site on; 'doubts':
    lines admitted without the user (agree / kraken) that it reads otherwise"""
    import argparse as AP
    import kraken_prep as KP
    for b, dlg, ph in BATCHES:
        if batches and b not in batches: continue
        rev = os.path.join(LREV, b, "lines.json")
        if not os.path.exists(rev): continue
        a = AP.Namespace(review=rev, marks=marks_for(dlg, ph), xml="kraken_mccatmus.xml")
        rv, recs = KP.setup(a)
        tl = {}
        for p in {r["page"] for r in recs}:
            f = os.path.join(PAGES, "p%04d" % int(p), "tess_line.json")
            if os.path.exists(f): tl[p] = json.load(open(f))["lines"]
        from collections import Counter
        c = Counter(); ex = {"admit": [], "doubt": []}
        for r in recs:
            t = tl.get(r["page"], {}).get(r["kid"])
            if t is None: c["not read"] += 1; continue
            same = bool(t.strip()) and KP.same_reading(r["text"], word_logical(t))
            tier = r["tier"]
            c[(tier, same)] += 1
            if not same and tier in ("agree", "kraken"): ex["doubt"].append((r["page"], r["rank"], tier, r["text"], t))
            if same and tier not in KP.ADMITTED and tier not in ("held", "out"): ex["admit"].append((r["page"], r["rank"], tier, r["text"]))
        tiers = sorted({k[0] for k in c if isinstance(k, tuple)})
        print("== %s: %d lines" % (b, len(recs)))
        for t in tiers:
            y, n = c[(t, True)], c[(t, False)]
            print("  %-9s %5d   trained Tesseract reads it as the site: %5d (%4.1f%%)" % (t, y + n, y, 100.0 * y / max(1, y + n)))
        if c["not read"]: print("  not read by Tesseract: %d" % c["not read"])
        print("  would admit (now to check, Tesseract agrees with the site): %d" % len(ex["admit"]))
        print("  doubts (admitted without you, Tesseract reads otherwise): %d" % len(ex["doubt"]))
        for x in ex["doubt"][:4]: print("    %s:%d %s\n      site %s\n      tess %s" % x)
        json.dump(ex, open(os.path.join(ROOT, "compare_%s.json" % b), "w"), ensure_ascii=False, indent=0)


GREEK_CH = re.compile("[\u0370-\u03ff\u1f00-\u1fff]")
GREEK_OCR = os.path.join(LREV, "phone", "greek_ocr.json")


def greek(batches, threads):
    """the lines with Greek (in the site's text) read by Tesseract's own Greek model (grc, with eng for the rest),
    for the check pages' "Greek OCR" reader: work/audit/lines/phone/greek_ocr.json {"page:rank": {"t", "n"}}.
    Lines already there (with notes made on claude.ai, 9 Nov) are kept. Needs work/ocrtrain/tessdata_grc
    (grc.traineddata from tessdata_best, eng from the system)"""
    import subprocess
    from PIL import Image
    from concurrent.futures import ThreadPoolExecutor
    td = os.path.join(ROOT, "tessdata_grc")
    got = json.load(open(GREEK_OCR, encoding="utf-8")) if os.path.exists(GREEK_OCR) else {}
    tmp = os.path.join(ROOT, "read_tmp"); os.makedirs(tmp, exist_ok=True)
    env = dict(os.environ, OMP_THREAD_LIMIT="1")
    jobs = []
    for b, _, _ in BATCHES:
        if batches and b not in batches: continue
        rev = os.path.join(LREV, b, "lines.json")
        if not os.path.exists(rev): continue
        rv = json.load(open(rev, encoding="utf-8")); recs = rv["lines"] if isinstance(rv, dict) else rv
        want = {}
        for r in recs:
            k = "%s:%s" % (r["page"], r["rank"])
            if k not in got and GREEK_CH.search(r["site"]): want.setdefault(str(r["page"]), []).append((k, r["kid"]))
        for pg, ks in sorted(want.items(), key=lambda x: int(x[0])):
            d = os.path.join(PAGES, "p%04d" % int(pg)); _, lines = lines_of(os.path.join(d, "kraken_mccatmus.xml"))
            pts = {lid: p for lid, p, _ in lines}
            img = Image.open(os.path.join(d, "page.png")).convert("L")
            for k, kid in ks:
                if kid not in pts: continue
                f = os.path.join(tmp, "grc_%s.png" % k.replace(":", "_")); crop_line(img, pts[kid]).save(f); jobs.append((k, f))
    def one(j):
        out = subprocess.run(["tesseract", j[1], "-", "--tessdata-dir", td, "-l", "grc+eng", "--psm", "7"],
                             capture_output=True, text=True, env=env).stdout
        os.remove(j[1]); return j[0], " ".join(out.split())
    with ThreadPoolExecutor(threads) as ex:
        for k, t in ex.map(one, jobs): got[k] = {"t": t, "n": []}
    json.dump(got, open(GREEK_OCR, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print("%d lines with Greek read (%d in all) -> %s" % (len(jobs), len(got), GREEK_OCR))


VIEWS_OUT = os.path.join(LREV, "phone", "tess_views.json")


def views(n_spot=60, seed=9):
    """two views for the phone page (9 Nov), as cards like check.html's (the site's text as the proposed text, the
    readers' differences marked, the trained Tesseract's reading added as a reader "tess_trained"):
      spot     n_spot lines of pp. 101-300 picked at random where the trained Tesseract reads as the site and kraken
               reads otherwise (no "…" lines): would a Tesseract tier admit only right lines?
      against  every line of pp. 1-300 where kraken and the trained Tesseract read alike and the site otherwise:
               likely site errors (75 of 88 among the user's checks), in page order
    -> work/audit/lines/phone/tess_views.json {"lines": [card], "spot": [ids], "against": [ids]}"""
    import argparse as AP, random
    import kraken_prep as KP, linereview as LR
    cards, spot_pool, against, greek_ = {}, [], [], []
    for b, dlg, ph in BATCHES:
        rev = os.path.join(LREV, b, "lines.json")
        if not os.path.exists(rev): continue
        a = AP.Namespace(review=rev, marks=marks_for(dlg, ph), xml="kraken_mccatmus.xml")
        rv, recs = KP.setup(a)
        tl = {}
        for r in recs:
            if r["tier"] in ("held", "out"): continue
            p = r["page"]
            if p not in tl:
                f = os.path.join(PAGES, "p%04d" % int(p), "tess_line.json")
                tl[p] = json.load(open(f))["lines"] if os.path.exists(f) else {}
            t, k = tl[p].get(r["kid"]), r["readers"].get("kraken_b1")
            if not t or not t.strip() or not k:
                t, k = t or "", k or ""
            tL = word_logical(t)
            st = KP.printed(r["site"])          # the site as printed (the training text evens out spacing), not the user's text
            ok = bool(t.strip()) and bool(k.strip())
            ts, ks, tk = (KP.same_reading(st, tL), KP.same_reading(st, k), KP.same_reading(k, tL)) if ok else (False, False, False)
            key = "%s:%d" % (p, r["rank"])
            pick = None
            if int(p) > 100 and GREEK_CH.search(r["text"]) and r["tier"] not in KP.ADMITTED: pick = "greek"
            elif tk and not ts: pick = "against"
            elif ts and not ks and int(p) > 100 and "…" not in r["site"] and r["tier"] != "checked": pick = "spot"
            if not pick: continue
            if t.strip(): r["readers"]["tess_trained"] = logical(t)
            r["site_orig"], r["site"] = r["site"], r["text"]
            if "…" in r["site"]: r["flags"] = sorted(set(r["flags"]) | {"dots"})
            LR.mark_readers(r)
            r["run"] = rv["run"] + "-check"; r["batch"] = b; r["hard"] = 0
            cards[key] = r
            {"against": against, "spot": spot_pool, "greek": greek_}[pick].append(key)
    old = json.load(open(VIEWS_OUT, encoding="utf-8")) if os.path.exists(VIEWS_OUT) else {}
    if old.get("spot"):                                   # the spot check already made (and marked) stays as it was
        spot = old["spot"]
        for c in old["lines"]:
            k = "%s:%d" % (c["page"], c["rank"])
            if k in spot and k not in cards: cards[k] = c
    else: spot = random.Random(seed).sample(spot_pool, min(n_spot, len(spot_pool)))
    keep = set(spot) | set(against) | set(greek_)
    order = lambda k: (int(k.split(":")[0]), int(k.split(":")[1]))
    json.dump({"lines": [cards[k] for k in sorted(keep, key=order)], "spot": sorted(spot, key=order),
               "against": sorted(against, key=order), "greek": sorted(greek_, key=order)}, open(VIEWS_OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print("spot check: %d of %d lines; kraken and Tesseract against the site: %d; Greek lines of pp. 101-300 to check: %d -> %s"
          % (len(spot), len(spot_pool), len(against), len(greek_), VIEWS_OUT))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], epilog=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["prepare", "bench", "train", "score", "read", "compare", "greek", "views"])
    ap.add_argument("--pages", default="1-100")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--batches", default="")
    ap.add_argument("--half", default="odd", choices=["odd", "even"])
    ap.add_argument("--start", default="heb", choices=["heb", "eng"])
    ap.add_argument("--iterations", type=int, default=20000)
    ap.add_argument("--model")
    a = ap.parse_args()
    if a.cmd == "prepare": prepare(a.half)
    elif a.cmd == "bench": bench(a.start, a.half)
    elif a.cmd == "train": train(a.start, a.half, a.iterations)
    elif a.cmd == "read": read_pages(a.pages, a.threads)
    elif a.cmd == "views": views()
    elif a.cmd == "greek": greek([x for x in a.batches.split(",") if x], a.threads)
    elif a.cmd == "compare": compare([x for x in a.batches.split(",") if x])
    else: score(a.model or "jline_%s_%s" % (a.half, a.start))


if __name__ == "__main__":
    main()
