"""Gemini as a line reader, scored on the user's checked lines (the line review export).

Each line is cropped from the full-resolution page (work/audit/pages/pNNNN/page.png, the line review's box) and
sent to Gemini alone. Variants:
  plain     the crop as is, "transcribe exactly"
  big       the crop enlarged 2x
  examples  the crop, after three worked examples (checked lines of p. 13, never scored here)
  checker   the crop and the site's text: "correct this text to match the image"
Every answer is cached in REPORTS/gemini_lines/<model>/<variant>.json, so a rerun spends no quota on lines
already read. The key is read from ~/jastrow/gem_api.txt and never printed.

usage: python3 build/audit/gemini_lines.py --variants plain,big --pages 151,155 [--limit 20] [--model gemini-3.5-flash]
       python3 build/audit/gemini_lines.py --score-only
Scores: CER (edits / gold characters) whole line; Hebrew letters only; Hebrew points only; Latin only; lines exact.
"""
import argparse, io, json, os, re, sys, time, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import paths  # noqa: E402

PROMPT = (
    "This image is one printed line from Jastrow's Dictionary of the Targumim, Talmud and Midrash (1903): English "
    "with Hebrew and Aramaic words, some with vowel points. Transcribe the line exactly as printed, character by "
    "character. Keep the book's punctuation, spacing, abbreviations, brackets, dashes and hyphens (a word broken at "
    "the line's end keeps its hyphen). Write Hebrew in logical (reading) order with every vowel point and dagesh "
    "that is printed, and none that is not; write the Hebrew abbreviation mark as ׳ (geresh). Write the superscript "
    "folio letters as ᵃ ᵇ ᶜ ᵈ. Do not correct, complete or modernise anything. Output only the line, nothing else.")
CHECK = (
    "\n\nA digital text of this line (it may have errors) is:\n{site}\n\nCompare it with the image and output the "
    "line exactly as printed in the image, changing only what differs from the print. Output only the line.")
EXAMPLES = [("13", 2), ("13", 18), ("13", 30)]

HEB = re.compile(r"[א-ת]")
PTS = re.compile(r"[ְ-ׇּׁׂ]")


def lev(a, b):
    if len(a) < len(b): a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def norm(s):
    s = unicodedata.normalize("NFC", s or "")
    s = s.replace("'", "׳").replace("’", "׳").replace('"', "״").replace("…", "...")
    return re.sub(r"\s+", " ", s).strip()


def parts(s):
    """the line split into the three things scored apart: Hebrew letters, Hebrew points, Latin + digits + punctuation"""
    d = unicodedata.normalize("NFD", s)
    return ("".join(HEB.findall(d)), "".join(PTS.findall(d)),
            "".join(c for c in d if not HEB.match(c) and not PTS.match(c) and not c.isspace() and c not in "ְֽֿ"))


def crop(page, box, scale):
    from PIL import Image
    img = Image.open(os.path.join(paths.WORK, "audit", "pages", "p%04d" % int(page), "page.png")).convert("L")
    x0, y0 = max(0, box[0] - 12), max(0, box[1] - 6)
    x1, y1 = min(img.size[0], box[2] + 12), min(img.size[1], box[3] + 6)
    c = img.crop((x0, y0, x1, y1))
    if scale != 1: c = c.resize((int(c.width * scale), int(c.height * scale)), Image.LANCZOS)
    buf = io.BytesIO(); c.save(buf, "PNG"); return buf.getvalue()


def load(review, export):
    L = {(l["page"], l["rank"]): l for l in json.load(open(review))["lines"]}
    gold = {}
    for m in json.load(open(export))["lines"]:
        if m["status"] in ("ok", "fixed") and (m["page"], m["rank"]) in L:
            gold[(m["page"], m["rank"])] = m["text"]
    return L, gold


def ask(client, model, contents):
    from google.genai import errors
    for attempt in range(40):    # the free tier is often "high demand" (503) for minutes at a time
        try:
            r = client.models.generate_content(model=model, contents=contents)
            return (r.text or "").strip()
        except errors.ClientError as e:  # noqa: PERF203
            msg = str(e)
            if getattr(e, "code", None) == 429:
                if "PerDay" in msg or "per day" in msg.lower():
                    raise SystemExit("daily free-tier quota reached; rerun tomorrow (answers so far are cached)")
                time.sleep(min(300, 30 * (attempt + 1))); continue
            raise
        except errors.ServerError as e:
            print("    %s, waiting" % str(e)[:40], flush=True)
            time.sleep(min(300, 20 * (attempt + 1)))
    raise SystemExit("gave up after repeated errors (answers so far are cached)")


def run(a, L, gold):
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=open(os.path.expanduser("~/jastrow/gem_api.txt")).read().strip())
    img = lambda b: types.Part.from_bytes(data=b, mime_type="image/png")  # noqa: E731
    pages = a.pages.split(",")
    keys = sorted((k for k in gold if k[0] in pages), key=lambda k: (int(k[0]), k[1]))
    if a.limit: keys = keys[:a.limit]
    for v in a.variants.split(","):
        cf = os.path.join(a.cache, a.model, v + ".json")
        os.makedirs(os.path.dirname(cf), exist_ok=True)
        cache = json.load(open(cf)) if os.path.exists(cf) else {}
        todo = [k for k in keys if "%s:%d" % k not in cache]
        print("%s: %d lines to read (%d cached)" % (v, len(todo), len(keys) - len(todo)), flush=True)
        shots = []
        if v == "examples":
            for ek in EXAMPLES:
                shots += [img(crop(ek[0], L[ek]["box"], 1)), "Transcription: " + gold[ek]]
        for n, k in enumerate(todo):
            l = L[k]
            pic = img(crop(k[0], l["box"], 2 if v == "big" else 1))
            if v == "checker": contents = [pic, PROMPT + CHECK.format(site=l["site"])]
            elif v == "examples": contents = [PROMPT + "\n\nExamples:"] + shots + ["Now this line:", pic]
            else: contents = [pic, PROMPT]
            cache["%s:%d" % k] = ask(client, a.model, contents)
            json.dump(cache, open(cf, "w"), ensure_ascii=False, indent=0)
            if n % 10 == 9 or n == len(todo) - 1: print("  %d/%d" % (n + 1, len(todo)), flush=True)
            time.sleep(a.sleep)


def score(a, L, gold):
    import glob
    base = {"site": {"%s:%d" % k: L[k]["site"] for k in gold}}
    for r in ("tesseract", "pdf", "kraken"):
        base[r] = {"%s:%d" % k: L[k]["readers"].get(r, "") for k in gold}
    for cf in sorted(glob.glob(os.path.join(a.cache, "*", "*.json"))):
        base[os.path.relpath(cf, a.cache)[:-5]] = json.load(open(cf))
    pages = a.pages.split(",")
    print("%-34s %5s %7s %7s %7s %7s %6s" % ("reader", "lines", "CER", "heb", "points", "latin", "exact"))
    worst = {}
    for name, ans in base.items():
        ks = [k for k in gold if k[0] in pages and "%s:%d" % k in ans]
        if not ks: continue
        tot = [0] * 4; err = [0] * 4; exact = 0; per = []
        for k in ks:
            g, h = norm(gold[k]), norm(ans["%s:%d" % k])
            pg, ph = parts(g), parts(h)
            for i, (x, y) in enumerate([(g, h)] + list(zip(pg, ph))):
                e = lev(x, y); err[i] += e; tot[i] += len(x)
            exact += g == h
            per.append((lev(g, h), k, g, h))
        print("%-34s %5d %6.1f%% %6.1f%% %6.1f%% %6.1f%% %5.0f%%" % (
            name, len(ks), *(100 * e / max(1, t) for e, t in zip(err, tot)), 100 * exact / len(ks)))
        worst[name] = sorted(per, reverse=True)[:a.show]
    if a.show:
        for name, w in worst.items():
            if name in ("site", "tesseract", "pdf", "kraken"): continue
            print("\n== %s: worst lines" % name)
            for e, k, g, h in w:
                print("%s:%d (%d)\n  gold   %s\n  reader %s" % (k[0], k[1], e, g, h))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", default="plain")
    ap.add_argument("--pages", default="151,155")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--model", default="gemini-3.5-flash")
    ap.add_argument("--sleep", type=float, default=7.0, help="seconds between requests (free tier)")
    ap.add_argument("--review", default=os.path.join(paths.WORK, "audit", "lines", "pilot", "lines.json"))
    ap.add_argument("--export", default=os.path.expanduser("~/Downloads/jastrow-lines-pilot-2026-11-052024.json"))
    ap.add_argument("--cache", default=paths.report("gemini_lines"))
    ap.add_argument("--score-only", action="store_true")
    ap.add_argument("--show", type=int, default=0, help="print the N worst lines of each Gemini variant")
    a = ap.parse_args()
    L, gold = load(a.review, a.export)
    if not a.score_only: run(a, L, gold)
    score(a, L, gold)


if __name__ == "__main__":
    main()
