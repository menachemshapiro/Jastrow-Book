#!/usr/bin/env python3
"""Plant known errors in a copy of the site's data/, for measuring the audit (tests/measure.py).

usage: python3 build/audit/tests/plant.py SITE OUTSITE PAGES [--seed N] [--per-page N]
Copies SITE/data to OUTSITE/data and puts errors of the kinds Sefaria's text has into the given pages' text:
  typo         a letter or two changed as Sefaria's own OCR changes them: m -> rn, e -> c, n -> u, u -> n, h -> b
  missing      one English word left out
  missing2     two English words left out
  doubled      a phrase of three to five words repeated
  heb_swap     two neighbouring Hebrew words of a quotation swapped
  hw_letter    a letter of a headword changed for a look-alike (ב/כ, ד/ר, ה/ח, ו/ז, ס/ם)
  number       a digit of a folio number changed
The list of what was planted, with each error's page, entry and place, goes to OUTSITE/planted.json.
Only the text is changed, never the markup."""
import argparse, html as H, json, os, random, re, shutil, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sitetext as ST  # noqa: E402

KINDS = ["typo", "missing", "doubled", "heb_swap", "hw_letter", "typo", "missing2", "number", "typo", "doubled"]
TYPO = [("m", "rn"), ("e", "c"), ("n", "u"), ("u", "n"), ("h", "b"), ("rn", "m"), ("c", "e")]
HW = [("ב", "כ"), ("כ", "ב"), ("ד", "ר"), ("ר", "ד"), ("ה", "ח"), ("ח", "ה"), ("ו", "ז"), ("ס", "ם")]
TAG = re.compile(r"<[^>]+>|[^<]+")


def nodes(html):
    """the text nodes of a page: (html start, html end, plain start), for nodes with no character entity"""
    out, plain = [], 0
    for m in TAG.finditer(html):
        t = m.group(0)
        if t.startswith("<"): continue
        u = H.unescape(t)
        if u == t: out.append((m.start(), m.end(), plain))
        plain += len(u)
    return out


def html_pos(html, off):
    """where plain offset `off` is in the HTML (None if it falls in a node with an entity)"""
    for a, b, p in nodes(html):
        if p <= off <= p + (b - a): return a + off - p, (a, b, p)
    return None, None


def same_node(html, a, b):
    pa, na = html_pos(html, a)
    pb, nb = html_pos(html, b)
    return (pa, pb) if na is not None and na == nb else (None, None)


def plant_one(page, html, kind, rng, used):
    """one error of `kind` in the page's HTML: (new html, record) or None"""
    toks = [t for t in page.tokens if not t["h2"] and t["eid"] and t["eid"] not in used]
    rng.shuffle(toks)
    lat = [t for t in toks if not t["heb"] and re.fullmatch(r"[a-z]{4,}", t["text"]) and not t["hw"]]
    if kind == "typo":
        for t in lat:
            for a, b in rng.sample(TYPO, len(TYPO)):
                k = t["text"].find(a, 1)
                if k < 0: continue
                new = t["text"][:k] + b + t["text"][k + len(a):]
                pa, pb = same_node(html, t["off"], t["end"])
                if pa is None: continue
                return html[:pa] + new + html[pb:], dict(kind=kind, eid=t["eid"], off=t["off"], end=t["off"] + len(new),
                                                        old=t["text"], new=new)
    if kind in ("missing", "missing2"):
        n = 1 if kind == "missing" else 2
        for t in lat:
            ts = [x for x in page.tokens if t["i"] <= x["i"] < t["i"] + n]
            if len(ts) < n or any(x["heb"] or x["eid"] != t["eid"] or not re.fullmatch(r"[a-z]{3,}", x["text"]) for x in ts): continue
            a, b = ts[0]["off"], ts[-1]["end"]
            if page.plain[b:b + 1] != " ": continue
            pa, pb = same_node(html, a, b + 1)
            if pa is None: continue
            old = page.plain[a:b + 1]
            return html[:pa] + html[pb:], dict(kind=kind, eid=t["eid"], off=a, end=a, old=old.strip(), new="")
    if kind == "doubled":
        for t in lat:
            n = rng.randint(3, 5)
            ts = [x for x in page.tokens if t["i"] <= x["i"] < t["i"] + n]
            if len(ts) < n or any(x["heb"] or x["eid"] != t["eid"] for x in ts): continue
            a, b = ts[0]["off"], ts[-1]["end"]
            pa, pb = same_node(html, a, b)
            if pa is None: continue
            ph = page.plain[a:b]
            return html[:pb] + " " + ph + html[pb:], dict(kind=kind, eid=t["eid"], off=b, end=b + 1 + len(ph), old="",
                                                          new=ph)
    if kind == "heb_swap":
        for t in toks:
            if not t["heb"] or t["hw"] or len(t["skel"]) < 3: continue
            n = page.tokens[t["i"] + 1] if t["i"] + 1 < len(page.tokens) else None
            if not n or not n["heb"] or n["hw"] or len(n["skel"]) < 3 or n["skel"] == t["skel"]: continue
            if page.plain[t["end"]:n["off"]] != " ": continue
            pa, pb = same_node(html, t["off"], n["end"])
            if pa is None: continue
            new = n["text"] + " " + t["text"]
            return html[:pa] + new + html[pb:], dict(kind=kind, eid=t["eid"], off=t["off"], end=n["end"],
                                                    old=page.plain[t["off"]:n["end"]], new=new)
    if kind == "hw_letter":
        for t in toks:
            if not t["hw"] or not t["heb"] or len(t["skel"]) < 3: continue
            for a, b in rng.sample(HW, len(HW)):
                k = t["text"].find(a)
                if k < 0: continue
                new = t["text"][:k] + b + t["text"][k + 1:]
                pa, pb = same_node(html, t["off"], t["end"])
                if pa is None: continue
                return html[:pa] + new + html[pb:], dict(kind=kind, eid=t["eid"], off=t["off"], end=t["end"],
                                                        old=t["text"], new=new)
    if kind == "number":
        for t in toks:
            m = re.fullmatch(r"(\d{2,3})([a-d]?)\W*", t["text"])
            if t["heb"] or not m: continue
            d = m.group(1)
            k = rng.randrange(len(d))
            nd = str((int(d[k]) + rng.randint(1, 8)) % 10)
            new = t["text"][:k] + nd + t["text"][k + 1:]
            pa, pb = same_node(html, t["off"], t["off"] + len(d))
            if pa is None: continue
            return html[:pa] + new[:len(d)] + html[pb:], dict(kind=kind, eid=t["eid"], off=t["off"], end=t["end"],
                                                              old=t["text"], new=new)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("site"); ap.add_argument("out"); ap.add_argument("pages")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--per-page", type=int, default=4)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    if os.path.exists(os.path.join(a.out, "data")): shutil.rmtree(os.path.join(a.out, "data"))
    shutil.copytree(os.path.join(a.site, "data"), os.path.join(a.out, "data"))
    book = ST.Book(a.site)
    pages = []
    for part in a.pages.split(","):
        if "-" in part:
            x, y = part.split("-"); pages += [str(p) for p in range(int(x), int(y) + 1)]
        else: pages.append(part)
    planted, chunks, k = [], {}, 0
    pj = os.path.join(a.out, "data", "pages.json")
    pjd = json.load(open(pj))
    meta = pjd["pages"]
    for pid in pages:
        page = book.page(pid)
        html = page.html
        used = set()
        recs = []
        # plant from the end of the page backwards, so that earlier offsets stay right
        for n in range(a.per_page):
            kind = KINDS[k % len(KINDS)]; k += 1
            r = plant_one(page, html, kind, rng, used)
            if r is None: continue
            html2, rec = r
            # keep the plants in different entries; re-read the page, and move the offsets of the earlier plants
            # (and the site's column break) that come after this one
            used.add(rec["eid"])
            html = html2
            rec["page"] = pid
            recs.append(rec)
            old_len = len(page.plain)
            page = page_from(book, pid, html)
            d = len(page.plain) - old_len
            for q in recs[:-1]:
                if rec["off"] <= q["off"]: q["off"] += d; q["end"] += d
            m = meta[book.index[pid]]
            if m[6] is not None and m[6] >= 0 and rec["off"] < m[6]: m[6] += d
        i = book.index[pid]
        c = i // ST.CHUNK
        if c not in chunks: chunks[c] = json.load(open(os.path.join(a.out, "data", "c%03d.json" % c)))
        chunks[c][i % ST.CHUNK] = html
        planted += recs
    for c, data in chunks.items():
        json.dump(data, open(os.path.join(a.out, "data", "c%03d.json" % c), "w"), ensure_ascii=False)
    json.dump(pjd, open(pj, "w"), ensure_ascii=False)
    json.dump(planted, open(os.path.join(a.out, "planted.json"), "w"), ensure_ascii=False, indent=1)
    from collections import Counter
    print("planted %d errors on %d pages: %s" % (len(planted), len(pages),
                                                 ", ".join("%s %d" % kv for kv in Counter(r["kind"] for r in planted).items())))


def page_from(book, pid, html):
    """a Page of `pid` with other HTML"""
    p = ST.Page.__new__(ST.Page)
    m = book.meta[book.index[pid]]
    p.pid = pid
    p.first, p.last, p.kind, p.known = m[2], m[3], m[5], m[6]
    p.below = m[7] if len(m) > 7 else None
    p.html = html
    p._parse(); p._breaks()
    return p


if __name__ == "__main__":
    main()
