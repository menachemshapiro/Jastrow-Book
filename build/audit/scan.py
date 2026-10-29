"""The scan side of the audit: render a book page from the HebrewBooks PDFs, find its layout, OCR it.

Layout of a dictionary page, top to bottom:
  running head (guide word, page number, guide word), sometimes with a rule under it;
  one or more *segments* of two columns. A page where a letter begins part-way down has two segments, one above
  the letter's heading and one below it; the heading (a band that crosses the gutter) separates them;
  sometimes a printer's signature line at the foot, which is not part of the text.
Reading order: segment 1 left, segment 1 right, (heading), segment 2 left, segment 2 right.

Everything is in the coordinates of the deskewed page image saved as page.png."""
import csv, glob, io, json, os, re, subprocess
import numpy as np
from PIL import Image, ImageDraw

# book page n <= 683 is page n+16 of PDF 1; n >= 684 is page n-683 of PDF 2 (GUIDELINES.md)
VOL2_FROM, VOL1_SHIFT, VOL2_SHIFT = 684, 16, -683


def pdf_for(pid, scans):
    n = int(pid)
    want = "1" if n < VOL2_FROM else "2"
    cands = sorted(glob.glob(os.path.join(scans, "*%s.pdf" % want)))
    if not cands:
        raise FileNotFoundError("no scan PDF ending in %s.pdf in %s" % (want, scans))
    return cands[0], (n + VOL1_SHIFT if n < VOL2_FROM else n + VOL2_SHIFT)


def render(pid, scans, out_png, dpi):
    pdf, pn = pdf_for(pid, scans)
    prefix = out_png[:-4]
    subprocess.run(["pdftoppm", "-f", str(pn), "-l", str(pn), "-r", str(dpi), "-gray", "-png", "-singlefile", pdf, prefix],
                   check=True, capture_output=True)
    return pdf, pn


def otsu(a):
    hist = np.bincount(a.ravel(), minlength=256).astype(float)
    tot = a.size; sum_all = np.dot(np.arange(256), hist)
    wb = sb = 0.0; best, thr = -1, 128
    for t in range(256):
        wb += hist[t]
        if wb == 0: continue
        wf = tot - wb
        if wf == 0: break
        sb += t * hist[t]
        mb, mf = sb / wb, (sum_all - sb) / wf
        v = wb * wf * (mb - mf) ** 2
        if v > best: best, thr = v, t
    return thr


def runs(mask, min_len=1):
    """(start, end) of runs of True"""
    m = np.concatenate([[False], mask, [False]]).astype(np.int8)
    d = np.diff(m)
    s, e = np.where(d == 1)[0], np.where(d == -1)[0]
    return [(int(a), int(b)) for a, b in zip(s, e) if b - a >= min_len]


def close_runs(rs, gap):
    out = []
    for a, b in rs:
        if out and a - out[-1][1] <= gap: out[-1] = (out[-1][0], b)
        else: out.append((a, b))
    return out


def deskew(img):
    a = np.asarray(img)
    thr = otsu(a)
    small = Image.fromarray(((a < thr) * 255).astype(np.uint8)).reduce(4)
    best, best_s = 0.0, -1
    for ang in np.arange(-2.0, 2.01, 0.1):
        r = np.asarray(small.rotate(float(ang), resample=Image.NEAREST, fillcolor=0), dtype=np.float32)
        s = np.var(r.sum(1))
        if s > best_s: best, best_s = float(ang), s
    if abs(best) >= 0.05:
        img = img.rotate(best, resample=Image.BICUBIC, fillcolor=255)
    return img, round(best, 2)


def layout(img):
    """find the body, the gutter, the bands that cross it, and the column segments"""
    a = np.asarray(img)
    H, W = a.shape
    thr = otsu(a)
    ink = a < thr
    # dark scanner borders: rows/columns near the edge that are mostly black
    for ax in (0, 1):
        frac = ink.mean(axis=ax)
        n = len(frac)
        bad = np.where(frac > 0.45)[0]
        for i in bad:
            if i < 0.08 * n or i > 0.92 * n:
                if ax == 0: ink[:, i] = False
                else: ink[i, :] = False
    rows = ink.sum(1) > max(3, 0.003 * W)
    cols = ink.sum(0) > max(3, 0.003 * H)
    rr, cr = runs(rows, 4), runs(cols, 4)
    if not rr or not cr:
        return {"error": "blank page?", "thr": int(thr)}
    y0, y1 = rr[0][0], rr[-1][1]
    x0, x1 = cr[0][0], cr[-1][1]
    body = ink[y0:y1, x0:x1]
    bw = x1 - x0
    # text lines over the full width, for the line height and the gaps between lines
    lines = runs(body.sum(1) > max(2, 0.002 * bw), 3)
    hts = [b - a_ for a_, b in lines]
    lineh = float(np.median(hts)) if hts else 30.0
    gaps = [lines[i + 1][0] - lines[i][1] for i in range(len(lines) - 1)]
    medgap = float(np.median(gaps)) if gaps else lineh / 3
    lo, hi = int(0.3 * bw), int(0.7 * bw)
    # gutter, first roughly: the strip in the middle of the body where few rows have ink (a letter heading or the
    # running head may cross it)
    frac = body[int(0.05 * len(body)):].mean(0)
    rough = close_runs(runs(frac[lo:hi] < 0.03, 2), 10)
    if not rough:
        return {"error": "no gutter found", "thr": int(thr), "body": [x0, y0, x1, y1]}
    rg = max(rough, key=lambda r: r[1] - r[0])
    q_ = max(1, (rg[1] - rg[0]) // 4)
    crossing = body[:, lo + rg[0] + q_:lo + rg[1] - q_ + 1].any(axis=1)
    anyink = body.any(axis=1)
    keep = ~np.zeros(len(body), bool)
    for s_, e_ in close_runs(runs(crossing, 1), max(2, int(lineh / 2))):
        # the whole of what crosses: out to the blank rows around it (at most a line and a half each way)
        k = 0
        while s_ > 0 and anyink[s_ - 1] and k < 1.5 * lineh: s_ -= 1; k += 1
        k = 0
        while e_ < len(body) and anyink[e_] and k < 1.5 * lineh: e_ += 1; k += 1
        keep[max(0, s_ - 2):e_ + 2] = False
    # then exactly, without those rows: the widest strip of (almost) no ink. The columns' lines that stand out (an
    # entry's first line) count as ink, so the gutter ends where they begin. A printed vertical rule inside the
    # gutter (a narrow strip inked over most of the height), or a speck, does not split it.
    colsum = body[keep].sum(0)
    nrows = max(1, int(keep.sum()))
    white = colsum[lo:hi] <= max(1, 0.0005 * nrows)
    wr = runs(white, 2)
    merged = []
    for r in wr:
        if merged:
            a_, b_ = merged[-1][1], r[0]
            rule_ = b_ - a_ <= 8 and all(colsum[lo + x] > 0.5 * nrows for x in range(a_, b_))
            speck = b_ - a_ <= 4 and all(colsum[lo + x] < 0.01 * nrows for x in range(a_, b_))
            if rule_ or speck:
                merged[-1] = (merged[-1][0], r[1]); continue
        merged.append(r)
    wr = merged
    if not wr:
        return {"error": "no gutter found", "thr": int(thr), "body": [x0, y0, x1, y1]}
    g = max(wr, key=lambda r: (r[1] - r[0]) - 0.2 * abs((r[0] + r[1]) / 2 - (hi - lo) / 2))
    g0, g1 = x0 + lo + g[0], x0 + lo + g[1]
    # a printed vertical rule in the gutter: columns inked over most of the body's height
    rule = [x for x in range(g0, g1) if ink[y0:y1, x].mean() > 0.5]
    # bands that cross the gutter: a letter heading, a rule across the page, the running head. Ink must cover a
    # good part of the gutter's middle (a word that sticks out of a column, or a speck, does not)
    q = max(1, (g1 - g0) // 4)
    rs = set(rule)
    mid = [x for x in range(g0 + q, g1 - q) if x not in rs] or list(range(g0, g1))
    span = ink[y0:y1, mid].sum(1) > 0
    bands = []
    for s, e in close_runs(runs(span, 2), max(2, int(lineh / 2))):
        cover = ink[y0 + s:y0 + e, mid].any(axis=0).mean()
        if cover >= 0.4: bands.append((y0 + s, y0 + e))
    full = ink.sum(1) > 0
    def grow(b0, b1, cap):
        """extend a band to the blank rows around it, at most `cap` rows each way"""
        k = 0
        while b0 > y0 and full[b0 - 1] and k < cap: b0 -= 1; k += 1
        k = 0
        while b1 < y1 and full[b1] and k < cap: b1 += 1; k += 1
        return b0, b1
    # running head: the first line, if a larger gap or a rule follows it, or it crosses the gutter
    header = None
    if lines:
        h0, h1 = lines[0]
        gap_after = gaps[0] if gaps else 0
        crosses = any(b0 <= y0 + h1 and b1 >= y0 + h0 for b0, b1 in bands)
        rule_next = len(lines) > 1 and lines[1][1] - lines[1][0] < 0.4 * lineh and gap_after < 1.5 * lineh
        if (h1 - h0) < 2.2 * lineh and (gap_after > 1.8 * medgap or crosses or rule_next):
            header = [x0, y0 + h0, x1, y0 + h1]
            # a rule just under it belongs to it: any ink before the first full text line
            yy = y0 + h1
            while yy < y1 and yy < y0 + h1 + 1.5 * lineh:
                if full[yy]:
                    r0 = yy
                    while yy < y1 and full[yy]: yy += 1
                    if yy - r0 < 0.4 * lineh: header[3] = yy
                    else: break
                yy += 1
    top = header[3] if header else y0
    # foot: a short last line after a larger gap (a printer's signature)
    footer = None
    if len(lines) > 3:
        f0, f1 = lines[-1]
        if (f1 - f0) < 1.5 * lineh and gaps[-1] > 2.5 * medgap and gaps[-1] > 0.8 * lineh:
            footer = [x0, y0 + f0, x1, y0 + f1]
    bottom = footer[1] if footer else y1
    heads = []
    for b0, b1 in bands:
        if b1 <= top + 1 or b0 >= bottom - 1: continue
        kind = "heading" if b1 - b0 >= 0.8 * lineh else "rule"
        if kind == "heading": b0, b1 = grow(b0, b1, int(1.5 * lineh))
        heads.append({"box": [x0, b0, x1, b1], "kind": kind})
    # segments between the bands; a column's box is trimmed to its text lines (rows of ink at least half a line
    # high), so a rule or the foot of a heading letter is not taken for text
    cuts = [top]
    for h in heads: cuts += [h["box"][1], h["box"][3]]
    cuts.append(bottom)
    segs = []
    for s_, e_ in zip(cuts[0::2], cuts[1::2]):
        if e_ - s_ < 0.6 * lineh: continue
        seg = {"y": [s_, e_], "cols": []}
        for side, (cx0, cx1) in (("L", (x0, g0)), ("R", (g1, x1))):
            sub = ink[s_:e_, cx0:cx1]
            rr_ = [r for r in runs(sub.sum(1) > 1, 2)]
            rr_ = [r for r in close_runs(rr_, max(1, int(medgap / 2))) if r[1] - r[0] >= 0.5 * lineh]
            if not rr_: continue
            sub = sub[rr_[0][0]:rr_[-1][1]]
            cc_ = runs(sub.sum(0) > 3, 2)
            if not cc_: continue
            box = [cx0 + cc_[0][0], s_ + rr_[0][0], cx0 + cc_[-1][1], s_ + rr_[-1][1]]
            seg["cols"].append({"side": side, "box": box})
        if seg["cols"]: segs.append(seg)
    # a column's left edge from its right edge (justified) and the widest column: a column with no line standing
    # out (one long entry running on) would otherwise seem to start further right
    widths = [c["box"][2] - c["box"][0] for sg in segs for c in sg["cols"]]
    if widths:
        W_ = max(widths)
        for sg in segs:
            for c in sg["cols"]:
                if c["box"][2] - c["box"][0] > 0.6 * W_: c["box"][0] = min(c["box"][0], c["box"][2] - W_)
    return {"thr": int(thr), "body": [x0, y0, x1, y1], "lineh": lineh, "medgap": medgap, "gutter": [g0, g1],
            "rule": bool(rule), "header": header, "footer": footer, "bands": heads, "segments": segs, "size": [W, H]}


def tesseract(png, lang, psm, dpi):
    r = subprocess.run(["tesseract", png, "stdout", "-l", lang, "--psm", str(psm), "--dpi", str(dpi),
                        "-c", "tessedit_create_tsv=1"],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("tesseract failed on %s: %s" % (png, r.stderr[-300:]))
    out = []
    rd = csv.reader(io.StringIO(r.stdout), delimiter="\t", quoting=csv.QUOTE_NONE)
    head = next(rd, None)
    for row in rd:
        if len(row) < 12 or row[0] != "5": continue
        txt = row[11].strip()
        if not txt: continue
        out.append({"block": int(row[2]), "par": int(row[3]), "line": int(row[4]), "word": int(row[5]),
                    "box": [int(row[6]), int(row[7]), int(row[6]) + int(row[8]), int(row[7]) + int(row[9])],
                    "conf": float(row[10]), "text": txt})
    return out


def ocr_page(img, lay, wd, dpi):
    """OCR every column with the English and the Hebrew model; the running head and headings once each"""
    res = {"tokens": [], "lines": [], "heb": [], "header": None, "headings": []}
    li = 0
    for si, seg in enumerate(lay["segments"]):
        for col in seg["cols"]:
            x0, y0, x1, y1 = col["box"]
            pad = 6
            box = [max(0, x0 - pad), max(0, y0 - pad), x1 + pad, y1 + pad]
            name = os.path.join(wd, "col%d%s.png" % (si, col["side"]))
            img.crop(box).save(name)
            eng = tesseract(name, "eng", 4, dpi)
            heb = tesseract(name, "heb", 4, dpi)
            # lines in order of appearance
            order = {}
            for w in eng:
                k = (w["block"], w["par"], w["line"])
                if k not in order: order[k] = len(order)
            lb = {}
            for w in eng:
                w["box"] = [w["box"][0] + box[0], w["box"][1] + box[1], w["box"][2] + box[0], w["box"][3] + box[1]]
                k = order[(w["block"], w["par"], w["line"])]
                lb.setdefault(k, []).append(w)
            # sort lines top to bottom (tesseract's blocks can come out of order)
            for k in sorted(lb, key=lambda k: np.median([w["box"][1] for w in lb[k]])):
                ws = sorted(lb[k], key=lambda w: w["box"][0])
                lbox = [min(w["box"][0] for w in ws), min(w["box"][1] for w in ws),
                        max(w["box"][2] for w in ws), max(w["box"][3] for w in ws)]
                res["lines"].append({"i": li, "seg": si, "col": col["side"], "box": lbox, "colbox": col["box"]})
                for j, w in enumerate(ws):
                    res["tokens"].append({"text": w["text"], "conf": w["conf"], "box": w["box"], "seg": si,
                                          "col": col["side"], "line": li, "first": j == 0, "last": j == len(ws) - 1})
                li += 1
            for w in heb:
                w["box"] = [w["box"][0] + box[0], w["box"][1] + box[1], w["box"][2] + box[0], w["box"][3] + box[1]]
                res["heb"].append({"text": w["text"], "conf": w["conf"], "box": w["box"], "seg": si, "col": col["side"]})
    if lay.get("header"):
        name = os.path.join(wd, "header.png")
        img.crop(lay["header"]).save(name)
        res["header"] = {"eng": " ".join(w["text"] for w in tesseract(name, "eng", 7, dpi)),
                         "heb": [w["text"] for w in sorted(tesseract(name, "heb", 7, dpi), key=lambda w: w["box"][0])]}
    for k, b in enumerate(lay.get("bands", [])):
        if b["kind"] != "heading": continue
        name = os.path.join(wd, "heading%d.png" % k)
        img.crop(b["box"]).save(name)
        res["headings"].append({"box": b["box"], "heb": " ".join(w["text"] for w in tesseract(name, "heb", 7, dpi))})
    return res


def overlay(img, lay, ocr, path):
    """a small picture of what the layout step found, for checking it by eye"""
    im = img.convert("RGB")
    d = ImageDraw.Draw(im)
    if lay.get("header"): d.rectangle(lay["header"], outline=(0, 160, 0), width=6)
    if lay.get("footer"): d.rectangle(lay["footer"], outline=(0, 160, 0), width=6)
    for b in lay.get("bands", []): d.rectangle(b["box"], outline=(200, 0, 200), width=6)
    for si, seg in enumerate(lay.get("segments", [])):
        for c in seg["cols"]:
            d.rectangle(c["box"], outline=(220, 0, 0), width=5)
            d.text((c["box"][0] + 8, c["box"][1] + 8), "%d%s" % (si + 1, c["side"]), fill=(220, 0, 0))
    if ocr:
        for ln in ocr["lines"]:
            d.rectangle(ln["box"], outline=(0, 90, 255), width=1)
    if lay.get("gutter"):
        g0, g1 = lay["gutter"]
        d.line([(g0, 0), (g0, im.height)], fill=(255, 150, 0), width=2)
        d.line([(g1, 0), (g1, im.height)], fill=(255, 150, 0), width=2)
    im.thumbnail((1100, 1600))
    im.save(path)


def process(pid, scans, workdir, dpi, force=False):
    """render, deskew, find the layout, OCR; cached in workdir/pNNNN/"""
    wd = os.path.join(workdir, "pages", "p%04d" % int(pid))
    os.makedirs(wd, exist_ok=True)
    out = os.path.join(wd, "scan.json")
    if os.path.exists(out) and not force:
        return json.load(open(out))
    raw = os.path.join(wd, "raw.png")
    if force or not os.path.exists(raw):
        pdf, pn = render(pid, scans, raw, dpi)
    else:
        pdf, pn = pdf_for(pid, scans)
    img = Image.open(raw).convert("L")
    img, angle = deskew(img)
    img.save(os.path.join(wd, "page.png"))
    lay = layout(img)
    lay["angle"] = angle
    res = {"pid": str(pid), "pdf": os.path.basename(pdf), "pdf_page": pn, "dpi": dpi, "layout": lay}
    if "error" not in lay:
        res["ocr"] = ocr_page(img, lay, wd, dpi)
    overlay(img, lay, res.get("ocr"), os.path.join(wd, "layout.png"))
    json.dump(res, open(out, "w"), ensure_ascii=False)
    return res
