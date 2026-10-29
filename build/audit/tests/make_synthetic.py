#!/usr/bin/env python3
"""Make a synthetic 'scan' PDF from the site's own text, for testing the audit without the real scans.

usage: python3 build/audit/tests/make_synthetic.py OUTDIR PAGE [PAGE ...]
Writes OUTDIR/Synthetic_1.pdf with each book page at the PDF page the real scan would have (n+16), white filler pages
elsewhere. The pages are set in two columns at the site's column break, with a running head, a letter heading where
the site has one, hanging indents, line-end hyphens, superscript folio sides and Hebrew phrases set right to left.
Fonts: DejaVu (Latin) and DejaVu Sans or Noto Sans Hebrew (Hebrew); needs Pillow with raqm for right-to-left text."""
import os, sys, glob
from PIL import Image, ImageDraw, ImageFont, features

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sitetext as S  # noqa: E402

DPI = 300
PW, PH = int(8.0 * DPI), int(11.0 * DPI)
MX, MY = int(0.7 * DPI), int(0.6 * DPI)
GUT = int(0.25 * DPI)


def font(cands, size):
    for c in cands:
        for f in glob.glob(c):
            return ImageFont.truetype(f, size)
    raise SystemExit("no font found among %s" % cands)


LAT = ["/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", "/usr/share/fonts/truetype/*/DejaVuSerif.ttf"]
HEB = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/*/NotoSansHebrew*.ttf"]


def set_page(p, size=30):
    fl, fh, fs = font(LAT, size), font(HEB, size), font(LAT, int(size * 0.6))
    space = fl.getlength(" ")
    lh = int(size * 1.25)
    colw = (PW - 2 * MX - GUT) // 2
    indent = int(size * 1.2)
    img = Image.new("L", (PW, PH), 255)
    d = ImageDraw.Draw(img)
    # running head
    y = MY
    d.text((MX, y), p.first, font=fh, fill=0, direction="rtl")
    d.text((PW // 2 - 20, y), p.pid, font=fl, fill=0)
    d.text((PW - MX - fh.getlength(p.last, direction="rtl"), y), p.last, font=fh, fill=0, direction="rtl")
    y += lh + 6
    d.line([(MX, y), (PW - MX, y)], fill=0, width=3)
    y += lh // 2
    toks = [t for t in p.tokens if not t["h2"]]
    big = font(HEB, size * 3)
    if p.letter_text and not p.mid_letter:
        d.text((PW // 2 - 40, y), p.letter_text, font=big, fill=0, direction="rtl")
        y += size * 4
    # segments of two columns: above and below a letter heading part-way down the page
    if p.mid_letter:
        h2 = min(t["off"] for t in p.tokens if t["h2"])
        segs = [[t for t in toks if t["off"] < h2], [t for t in toks if t["off"] > h2]]
    else:
        segs = [toks]
    for si, stoks in enumerate(segs):
        brk = p.site_breaks[si] if si < len(p.site_breaks) else None
        if brk is None:
            h = len(stoks) // 2; cols = [stoks[:h], stoks[h:]]
        else:
            cols = [[t for t in stoks if t["off"] < brk], [t for t in stoks if t["off"] >= brk]]
        y = set_cols(d, cols, y, colw, indent, space, lh, fl, fh, fs) + lh // 2
        if p.mid_letter and si == 0:
            d.text((PW // 2 - 40, y), p.letter_text, font=big, fill=0, direction="rtl")
            y += size * 4
    return img, y


def set_cols(d, cols, top, colw, indent, space, lh, fl, fh, fs):
    bottoms = []
    left_eids = {t["eid"] for t in cols[0]}
    def continues_from_left(t):
        return ci == 1 and t["eid"] in left_eids
    for ci, ct in enumerate(cols):
        x0 = MX + ci * (colw + GUT)
        lines, cur, w, start_entry = [], [], 0, True
        prev_e = None
        ind = 0
        def flush(new_entry, last=True):
            nonlocal cur, w, ind
            if cur: lines.append((ind, cur, last))
            cur, w = [], 0
            ind = 0 if new_entry else indent
        k = 0
        items = [(t["text"], t) for t in ct]
        first = True
        while k < len(items):
            txt, t = items[k]
            newe = t["eid"] != prev_e and not t["cont"]
            if t["eid"] != prev_e:
                if not first: flush(newe)
                else: ind = 0 if (newe and k == 0 and not continues_from_left(t)) else indent
                prev_e = t["eid"]
            first = False
            f = fh if t["heb"] else fl
            tw = f.getlength(txt, direction="rtl" if t["heb"] else None)
            if w and ind + w + space + tw > colw:
                # hyphenate a long Latin word at the line's end
                if not t["heb"] and txt.isalpha() and len(txt) >= 7:
                    room = colw - ind - w - space
                    for cut in range(len(txt) - 3, 2, -1):
                        if fl.getlength(txt[:cut] + "-") <= room:
                            cur.append((txt[:cut] + "-", t, fl)); flush(False, last=False)
                            items[k] = (txt[cut:], t)
                            break
                    else:
                        flush(False, last=False)
                    continue
                flush(False, last=False)
            cur.append((txt, t, f)); w += (space if w else 0) + tw
            k += 1
        flush(False)
        yy = top
        for ind, ws, last in lines:
            # as the site shows it: the words of one right-to-left island (a Hebrew span) in reverse order
            out, i = [], 0
            while i < len(ws):
                u = ws[i][1]["unit"]
                if ws[i][1]["heb"] or (u >= 0 and any(x[1]["heb"] and x[1]["unit"] == u for x in ws)):
                    j = i
                    while j < len(ws) and ws[j][1]["unit"] == u: j += 1
                    out += ws[i:j][::-1]; i = j
                else:
                    out.append(ws[i]); i += 1
            xx = x0 + ind
            # justified, like the book: the spare width goes between the words (not on a paragraph's last line)
            natural = sum(f.getlength(txt, direction="rtl" if t["heb"] else None) for txt, t, f in out) + space * (len(out) - 1)
            gap = space + ((colw - ind - natural) / (len(out) - 1) if (not last and len(out) > 1) else 0)
            for txt, t, f in out:
                if t["side"] and txt.endswith(t["side"]) and not t["heb"]:
                    num = txt[:-1] if txt[-1] == t["side"] else txt
                    d.text((xx, yy), num, font=fl, fill=0); xx += fl.getlength(num)
                    d.text((xx, yy - 4), t["side"], font=fs, fill=0); xx += fs.getlength(t["side"]) + gap
                    continue
                d.text((xx, yy), txt, font=f, fill=0, direction="rtl" if t["heb"] else None)
                xx += f.getlength(txt, direction="rtl" if t["heb"] else None) + gap
            yy += lh
        bottoms.append(yy)
    return max(bottoms)


def main():
    out, pages = sys.argv[1], sys.argv[2:]
    if not features.check("raqm"): sys.exit("Pillow needs raqm for right-to-left text")
    os.makedirs(out, exist_ok=True)
    book = S.Book(os.environ.get("JASTROW_SITE", S.REPO))
    imgs = {}
    for pid in pages:
        p = book.page(pid)
        size = 34
        while True:
            img, bottom = set_page(p, size)
            if bottom < PH - MY or size <= 14: break
            size -= 1
        if pid == pages[0]:
            ImageDraw.Draw(img).text((MX, PH - MY // 2), "Jastrow, Dictionary.", font=font(LAT, 20), fill=0)
        imgs[int(pid) + 16] = img
        print("page", pid, "type size", size)
    n = max(imgs)
    blank = Image.new("L", (40, 55), 255)
    seq = [imgs.get(i, blank) for i in range(1, n + 1)]
    seq[0].save(os.path.join(out, "Synthetic_1.pdf"), save_all=True, append_images=seq[1:], resolution=DPI)
    print("wrote", os.path.join(out, "Synthetic_1.pdf"))


if __name__ == "__main__":
    main()
