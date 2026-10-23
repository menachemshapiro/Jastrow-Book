#!/usr/bin/env python3
"""Build Jastrow pages from Sefaria's 2026 text, placed on the book's pages using the 2018 XML's page breaks.

Pass A  walk the 2018 XML into an event stream (open/close/text/pgbrk), marking entry boundaries.
Pass B  add the page break the XML lacks (1107) at an estimated offset.
Pass C  for every entry, render a 2026 version (2018 head line + 2026 senses), align its letters with
        the 2018 version, and move the page breaks across. Entries where 2026 lost text keep 2018.
Pass D  replay the stream into pages.
usage: python3 -I build2.py <Jastrow-full.xml> <jastrow-complete.json> <outdir>
"""
import sys, json, re, html, os, difflib, unicodedata, collections
from lxml import etree
import lxml.html

XML, CUR, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(OUT, exist_ok=True)
root = etree.parse(XML, etree.XMLParser(load_dtd=False, resolve_entities=False)).getroot()
cur = json.load(open(CUR))["entries"]
HW2RID = {}
for rid, v in cur.items():
    HW2RID.setdefault(v.get("headword", "").strip(), rid)

SYNTH_BREAKS = {}   # page -> (new page, chars of text after its start)
# entry merged into its predecessor in Sefaria's data as a fake binyan "[[."; page 1107 starts with it
MERGED = {"P01197": ("P01197b", "1107")}
MERGED_PAGES = {v[1] for v in MERGED.values()}


def clean(t):
    return (t or "").replace("\r", "").replace("\n", "")


TAGMAP = {
    "italic": ("i", None), "bold": ("b", None), "sup": ("sup", None), "sub": ("sub", None),
    "underline": ("u", None), "pos": ("span", "pos"), "language-key": ("span", "lk"),
    "language-reference": ("span", "lr"), "plural-form": ("span", "pl"),
    "senses": ("span", "ss"), "sense": ("span", "s"), "number": ("span", "n"),
    "definition": ("span", "d"), "notes": ("span", "nt"), "alternative": ("span", "alt"),
    "binyan-name": ("i", "bn"), "binyan-form": ("span", "bf"), "derivatives": ("span", "der"),
    "hw-number": ("span", "hn"), "table": ("table", None), "tr": ("tr", None), "td": ("td", None),
}
SPACED = {"pos", "language-key", "language-reference", "plural-form", "number", "definition", "notes",
          "hw-number", "binyan-form", "binyan-name"}
HEAD_TAGS = {"head-word", "hw-number", "pos", "plural-form", "language-key", "language-reference"}


class Rec:
    """Records an event stream."""
    def __init__(self):
        self.ev = []
        self.last = " "

    def open(self, tag, attrs=""):
        self.ev.append(("open", tag, attrs))

    def close(self):
        self.ev.append(("close",))

    def text(self, t):
        t = clean(t)
        if t:
            self.ev.append(("text", t))
            self.last = t[-1]

    def mark(self, *a):
        self.ev.append(a)

    def soft_space_for(self, first):
        if not first or first.isspace() or first in ".,;:)]—":
            return
        if self.last.isspace() or self.last in "([—-":
            return
        self.text(" ")

    def soft_space(self, el):
        self.soft_space_for("".join(el.itertext()).replace("\n", "")[:1])


# ---------------------------------------------------------------- pass A: 2018 events
def walk(el, R):
    tag = el.tag
    if not isinstance(tag, str):
        R.text(el.tail); return
    if tag == "pgbrk":
        R.mark("pgbrk", el.get("id")[2:]); R.text(el.tail); return
    if tag in ("front", "body", "back"):
        R.mark("section", tag)
        for c in el: walk(c, R)
        return
    if tag == "chapter":
        kids = list(el)
        if len(kids) > 1 and kids[0].tag == "title" and kids[1].tag == "pgbrk":
            R.mark("pgbrk", kids[1].get("id")[2:])
            R.mark("letterpage")
            kids = [kids[0]] + kids[2:]
        for c in kids: walk(c, R)
        return
    if tag == "title":
        R.open("h2", ' class="letter" lang="he" dir="rtl"'); R.text(el.text); R.close(); R.text(el.tail); return
    if tag == "p":
        R.open("p", ' class="fm"'); R.text(el.text)
        for c in el: walk(c, R)
        R.close(); R.text(el.tail); return
    if tag == "entry":
        R.mark("entry_start", el.get("id"), el)
        entry_body(el, R, None)
        R.mark("entry_end", el.get("id"))
        R.text(el.tail)
        return
    if tag == "xref":
        R.open("a", ' class="x" href="#%s"' % el.get("rid")); R.text(el.text); R.close(); R.text(el.tail); return
    if tag in SPACED:
        R.soft_space(el)
    h, cls = TAGMAP[tag]
    R.open(h, (' class="%s"' % cls) if cls else "")
    R.text(el.text)
    for c in el: walk(c, R)
    R.close(); R.text(el.tail)


def headwords(group, R):
    R.open("span", ' class="hw" lang="he" dir="rtl"')
    prev = ""
    for gi, h in enumerate(group):
        t = clean(h.text).strip()
        if gi:
            R.text(" " if prev.endswith(",") else ", ")
        R.text(t); prev = t
    R.close(); R.text(" ")


def entry_body(el, R, new_senses):
    """2018 entry -> events. If new_senses (a 2026 entry) is given, the head line comes from 2018 and
    everything after it from 2026."""
    eid = el.get("id")
    R.open("div", ' class="e" id="%s"' % eid)
    R.open("p", ' class="ep"')
    kids = list(el)
    i = 0
    while i < len(kids):
        c = kids[i]
        if new_senses is not None and c.tag not in HEAD_TAGS and c.tag != "pgbrk":
            break
        if c.tag == "head-word":
            group = []
            while i < len(kids) and kids[i].tag == "head-word":
                group.append(kids[i]); i += 1
            headwords(group, R)
            continue
        if c.tag == "binyan" and (c.findtext("binyan-name") or "").strip() == "[[." and eid in MERGED:
            nid, pg = MERGED[eid]
            R.close(); R.close(); R.mark("pgbrk", pg); R.mark("subentry", nid)
            R.open("div", ' class="e" id="%s"' % nid); R.open("p", ' class="ep"')
            R.open("span", ' class="hw" lang="he" dir="rtl"'); R.text(clean(c.findtext("binyan-form")).strip()); R.close(); R.text(" ")
            for b in c:
                if b.tag in ("binyan-name", "binyan-form"): continue
                walk(b, R)
            i += 1; continue
        if c.tag == "binyan":
            R.close(); R.open("p", ' class="bin"'); R.text(c.text)
            for b in c:
                walk(b, R)
                if b.tag in ("binyan-name", "binyan-form"):
                    R.text(" ")
            R.close(); R.open("p", ' class="ep tail"'); R.text(c.tail)
            i += 1; continue
        walk(c, R)
        i += 1
    if new_senses is not None:
        R.mark("headend")
        render_senses(new_senses, R)
    R.close(); R.close()


# ---------------------------------------------------------------- 2026 senses
SUPL = {"ᵃ": "a", "ᵇ": "b", "ᶜ": "c", "ᵈ": "d"}
SUPRE = re.compile("[ᵃᵇᶜᵈ]")


def emit_text(t, R):
    t = clean(t)
    pos = 0
    for m in SUPRE.finditer(t):
        R.text(t[pos:m.start()]); R.open("sup"); R.text(SUPL[m.group(0)]); R.close(); pos = m.end()
    R.text(t[pos:])


def ref_target(a):
    dr = a.get("data-ref") or ""
    if dr.startswith("Jastrow, "):
        name = re.sub(r" \d+$", "", dr[len("Jastrow, "):]).strip()
        rid = HW2RID.get(name)
        return ("x", rid) if rid else (None, None)
    href = (a.get("href") or "").lstrip("/")
    return ("r", "https://www.sefaria.org/" + href) if href else (None, None)


def emit_html(frag, R):
    if not frag:
        return
    node = lxml.html.fragment_fromstring(frag, create_parent="div")
    def rec(n):
        for c in n:
            tag = c.tag if isinstance(c.tag, str) else None
            if tag in ("i", "em"):
                R.open("i"); emit_text(c.text, R); rec(c); R.close()
            elif tag in ("b", "strong"):
                R.open("b"); emit_text(c.text, R); rec(c); R.close()
            elif tag in ("sup", "sub"):
                R.open(tag); emit_text(c.text, R); rec(c); R.close()
            elif tag == "a":
                kind, tgt = ref_target(c)
                if kind == "x":
                    R.open("a", ' class="x" href="#%s"' % tgt)
                elif kind == "r":
                    R.open("a", ' class="r" target="_blank" rel="noopener" href="%s"' % html.escape(tgt))
                else:
                    R.open("span")
                emit_text(c.text, R); rec(c); R.close()
            elif tag == "br":
                R.text(" ")
            else:  # span dir=rtl and anything else: transparent
                emit_text(c.text, R); rec(c)
            emit_text(c.tail, R)
    emit_text(node.text, R)
    rec(node)


def first_char_html(frag):
    t = html.unescape(re.sub(r"<[^>]+>", "", frag or "")).replace("\n", "")
    return t[:1]


def render_senses(v, R):
    def senses(ss, depth):
        for s in ss:
            g = s.get("grammar")
            if g and (g.get("verbal_stem") or "").strip() == "[[." and v["rid"] in MERGED:
                nid, pg = MERGED[v["rid"]]
                R.close(); R.close(); R.mark("pgbrk", pg); R.mark("subentry", nid)
                R.open("div", ' class="e" id="%s"' % nid); R.open("p", ' class="ep"')
                bf = g.get("binyan_form") or []
                R.open("span", ' class="hw" lang="he" dir="rtl"'); R.text((bf[0] if isinstance(bf, list) else bf).strip()); R.close(); R.text(" ")
                senses(s.get("senses", []), depth + 1)
                continue
            if g and (g.get("verbal_stem") or g.get("binyan_form")):
                R.close(); R.open("p", ' class="bin"')
                if g.get("verbal_stem"):
                    R.open("i", ' class="bn"'); R.text(g["verbal_stem"]); R.close(); R.text(" ")
                bf = g.get("binyan_form") or []
                if isinstance(bf, str): bf = [bf]
                if bf:
                    R.open("span", ' class="bf"'); R.text(", ".join(x.strip() for x in bf)); R.close(); R.text(" ")
                if s.get("definition"):
                    R.open("span", ' class="d"'); emit_html(s["definition"], R); R.close()
                senses(s.get("senses", []), depth + 1)
                R.close(); R.open("p", ' class="ep tail"')
                continue
            R.open("span", ' class="s"')
            if s.get("number"):
                R.soft_space_for(s["number"][:1])
                R.open("span", ' class="n"'); R.text(s["number"]); R.close()
            if s.get("definition"):
                R.soft_space_for(first_char_html(s["definition"]))
                R.open("span", ' class="d"'); emit_html(s["definition"], R); R.close()
            senses(s.get("senses", []), depth + 1)
            R.close()
    R.open("span", ' class="ss"')
    senses(v["content"].get("senses", []), 0)
    R.close()


# ---------------------------------------------------------------- alignment helpers
KEEP = re.compile(r"[א-תa-zA-Z0-9Ͱ-Ͽἀ-῿]")


def plain_of(ev):
    return "".join(e[1] for e in ev if e[0] == "text")


def keep_index(s):
    """normalized string + list mapping each kept char to its raw index"""
    chars, idx = [], []
    for i, ch in enumerate(s):
        b = unicodedata.normalize("NFD", ch)[0]
        if KEEP.match(b):
            chars.append(b); idx.append(i)
    return "".join(chars), idx


def split_events_at(ev, offsets_ids):
    """insert ('pgbrk', id) events at raw text offsets (sorted)."""
    out, pos = [], 0
    todo = sorted(offsets_ids)
    k = 0
    for e in ev:
        if e[0] != "text":
            out.append(e); continue
        t = e[1]
        start = pos
        while k < len(todo) and todo[k][0] <= start + len(t):
            cut = todo[k][0] - start
            if cut < 0: cut = 0
            if t[:cut]:
                out.append(("text", t[:cut]))
            out.append(("pgbrk", todo[k][1]))
            t = t[cut:].lstrip(" ")
            start = todo[k][0]
            k += 1
        if t:
            out.append(("text", t))
        pos += len(e[1])
    while k < len(todo):
        out.append(("pgbrk", todo[k][1])); k += 1
    return out


def dedupe_head(ev):
    """drop a repeat of the head line (pos, language key...) at the start of the 2026 senses"""
    k = next(i for i, e in enumerate(ev) if e[0] == "headend")
    # head text after the headword span
    depth, start = 0, None
    for i, e in enumerate(ev[:k]):
        if e[0] == "open" and 'class="hw"' in e[2]: start = i
    if start is None: return ev
    j = start
    while ev[j][0] != "close": j += 1
    head, _ = keep_index(plain_of(ev[j + 1:k]))
    if len(head) < 2: return ev
    rest, _ = keep_index(plain_of(ev[k + 1:]))
    if not rest.startswith(head): return ev
    n = len(head)
    out = ev[:k + 1]
    for e in ev[k + 1:]:
        if n > 0 and e[0] == "text":
            t = e[1]; cut = 0
            while cut < len(t) and n > 0:
                if KEEP.match(unicodedata.normalize("NFD", t[cut])[0]): n -= 1
                cut += 1
            if n == 0:
                while cut < len(t) and t[cut] in " ,.;": cut += 1
            t = t[cut:]
            if t: out.append(("text", t if n else " " + t.lstrip()))
            continue
        out.append(e)
    DEDUP.append(out[0][2] if False else None)
    return out


DEDUP = []
# ---------------------------------------------------------------- run
A = Rec()
for c in root:
    walk(c, A)
ev = A.ev

# pass B: synthetic page break(s)
out = []
pending = None
for e in ev:
    if e[0] == "pgbrk" and e[1] in SYNTH_BREAKS:
        out.append(e); pending = [SYNTH_BREAKS[e[1]][0], SYNTH_BREAKS[e[1]][1]]; continue
    if pending and e[0] == "text":
        t = e[1]
        if len(t) >= pending[1]:
            j = t.find(" ", pending[1])
            j = len(t) if j < 0 else j
            out.append(("text", t[:j])); out.append(("pgbrk", pending[0], "est")); rest = t[j:].lstrip()
            if rest: out.append(("text", rest))
            pending = None
            continue
        pending[1] -= len(t)
    out.append(e)
ev = out

# pass C: per entry, swap in 2026
stats = collections.Counter()
INS = []
fallback = []
res = []
i = 0
while i < len(ev):
    e = ev[i]
    if e[0] != "entry_start":
        res.append(e); i += 1; continue
    eid, el = e[1], e[2]
    j = i + 1
    while ev[j][0] != "entry_end": j += 1
    old = ev[i + 1:j]
    v = cur.get(eid)
    use_new = v is not None and any(s for s in v["content"].get("senses", []))
    new = None
    if use_new:
        R = Rec(); entry_body(el, R, v); new = dedupe_head(R.ev)
        po, pn = plain_of(old), plain_of(new)
        a, ai = keep_index(po); b, bi = keep_index(pn)
        if a == b:
            ops = [("equal", 0, len(a), 0, len(b))]
        else:
            ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
        deleted = sum(i2 - i1 for t, i1, i2, j1, j2 in ops if t == "delete")
        lost = sum(max(0, (i2 - i1) - (j2 - j1)) for t, i1, i2, j1, j2 in ops if t == "replace")
        inserted = [b[j1:j2] for t, i1, i2, j1, j2 in ops if t in ("insert", "replace") and j2 - j1 >= 4]
        if inserted: INS.append((eid, inserted[:3]))
        if deleted + lost >= 4:
            use_new = False
            fallback.append((eid, deleted + lost))
        else:
            stats["same" if a == b else "changed"] += 1
    if not use_new:
        stats["2018"] += 1
        res.append(("entry_start", eid)); res.extend(old); res.append(("entry_end", eid))
    else:
        # move page breaks across
        brks, pos = [], 0
        for x in old:
            if x[0] == "text": pos += len(x[1])
            elif x[0] == "pgbrk" and x[1] not in MERGED_PAGES: brks.append((pos, x[1], x[2] if len(x) > 2 else None))
        moved = []
        for R0, pid, flag in brks:
            N = sum(1 for k in ai if k < R0)
            M = len(b)
            for t, i1, i2, j1, j2 in ops:
                if i1 <= N < i2 or (N == i2 == len(a) and t == "equal"):
                    M = j1 + (N - i1) if t == "equal" else j1
                    break
            P = bi[M] if M < len(bi) else len(pn)
            while P > 0 and not pn[P - 1].isspace():
                P -= 1
            moved.append((P, pid if not flag else pid))
            if flag: stats["est_moved"] += 1
        new2 = split_events_at(new, moved)
        # restore the "estimated" flag
        new2 = [(x[0], x[1], "est") if x[0] == "pgbrk" and any(b_[1] == x[1] and b_[2] for b_ in brks) else x for x in new2]
        stats["breaks_moved"] += len(moved)
        res.append(("entry_start", eid)); res.extend(new2); res.append(("entry_end", eid))
    i = j + 1
ev = res
print(dict(stats), "fallback to 2018:", len(fallback), "head repeats removed:", len(DEDUP))
json.dump(fallback, open(os.path.join(OUT, "fallback.json"), "w"))
json.dump(INS, open(os.path.join(OUT, "inserted.json"), "w"), ensure_ascii=False)


# ---------------------------------------------------------------- pass D: pages
class Emitter:
    def __init__(self):
        self.pages, self.cur, self.stack, self.entry_stack, self.section = [], None, [], [], "front"

    def new_page(self, pid, est=False):
        if self.cur is not None:
            self.cur["html"].extend("</%s>" % t for t, a in reversed(self.stack))
        self.cur = {"id": pid, "html": [], "entries": [], "cont": self.entry_stack[-1] if self.entry_stack else None,
                    "section": self.section, "estimated": est, "letter": False}
        self.pages.append(self.cur)
        for t, a in self.stack:
            if a.startswith(' class="e" '):
                a = a.replace('class="e"', 'class="e cont"', 1)
            if 'class="ep' in a or 'class="bin' in a:
                a += ' data-c="1"'
            self.cur["html"].append("<%s%s>" % (t, a))


E = Emitter()
E.new_page("i")
entries = {}
for e in ev:
    k = e[0]
    if k == "open":
        E.stack.append((e[1], e[2])); E.cur["html"].append("<%s%s>" % (e[1], e[2]))
    elif k == "close":
        t, a = E.stack.pop(); E.cur["html"].append("</%s>" % t)
    elif k == "text":
        E.cur["html"].append(html.escape(e[1], quote=False))
    elif k == "pgbrk":
        E.new_page(e[1], est=len(e) > 2 and e[2] == "est")
    elif k == "section":
        E.section = e[1]
    elif k == "letterpage":
        E.cur["letter"] = True
    elif k == "entry_start":
        E.cur["entries"].append(e[1]); E.entry_stack.append(e[1])
    elif k == "entry_end":
        E.entry_stack.pop()
    elif k == "subentry":
        if E.cur["cont"] == E.entry_stack[-1] and not E.cur["entries"]: E.cur["cont"] = None
        E.entry_stack[-1] = e[1]
        if E.cur["entries"] or E.cur["cont"]: E.cur["entries"].append(e[1])
E.cur["html"].extend("</%s>" % t for t, a in reversed(E.stack))

hw_of = {}
for el in root.iter("entry"):
    hw_of[el.get("id")] = [clean(h.text).strip() for h in el.findall("head-word")]
hw_of["P01197b"] = ["עָקַם"]


def guide(hws):
    for h in hws:
        g = re.sub(r"\([^)]*\)", "", h)
        g = re.sub(r"[*,;.()?=\[\]]", "", g).strip().split(" ")[0] if g.strip() else ""
        if re.search("[א-ת]", g):
            return g
    return ""


out_pages = []
for p in E.pages:
    body = "".join(p["html"])
    body = re.sub(r'<p class="ep tail"(?: data-c="1")?></p>', "", body)
    body = re.sub(r'<p class="ep"></p>', "", body)
    ids = ([p["cont"]] if p["cont"] else []) + p["entries"]
    for eid in p["entries"]:
        entries[eid] = {"id": eid, "hw": hw_of.get(eid, []), "page": p["id"]}
    out_pages.append({"id": p["id"], "section": p["section"], "html": body, "entries": p["entries"], "cont": p["cont"],
                      "estimated": p["estimated"], "letter": p["letter"],
                      "first": guide(hw_of.get(ids[0], [])) if ids else "", "last": guide(hw_of.get(ids[-1], [])) if ids else ""})
json.dump({"pages": out_pages}, open(os.path.join(OUT, "pages_all.json"), "w"), ensure_ascii=False)
json.dump(entries, open(os.path.join(OUT, "entries.json"), "w"), ensure_ascii=False)
print(len(out_pages), "pages;", len(entries), "entries")
