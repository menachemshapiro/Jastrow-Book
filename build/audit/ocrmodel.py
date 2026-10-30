"""What this OCR does to this book: a measured model of its misreadings.

About 85% of the site's words are found word for word in the scan. Around them, wherever one word of the site stands
against one word of the scan, the two differ; nearly always because the OCR misread the 1903 page, rarely because
Sefaria's text is wrong. Counting those differences, change by change ("5;" read as "53" is the change ";" -> "3";
"בָּא" read as "כא" is ב -> כ), says which misreadings this OCR makes on this book, and how often. A difference made
only of changes seen many times is most likely the OCR's; one with a change never seen before stands out.

The counts are kept per page (pages/pNNNN/pairs.json), so the model grows as more pages are audited. The user's marks
teach it too: a pair marked "false alarm" counts three times; one marked "site is wrong" is left out, since it is a
real difference and not a misreading."""
import difflib, json, os, re, unicodedata
from collections import Counter

NIK = re.compile("[֑-ׇ]")
MAXBLK = 3                       # changes longer than this (on either side) are not counted: a word, not a misreading


def blocks(a, b):
    """the changes that turn a into b: [(from, to)], each at most MAXBLK characters a side ('' = nothing)"""
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal": continue
        x, y = a[i1:i2], b[j1:j2]
        if len(x) > MAXBLK or len(y) > MAXBLK: out.append(("<long>", "<long>"))
        else: out.append((x, y))
    return out


class Confusions:
    """counts of changes from the site's text to the OCR's reading, for one script"""

    def __init__(self, name):
        self.name = name
        self.edit = Counter()            # (from, to) -> how many times
        self.pairs = 0

    def add(self, site, scan, w=1):
        if site == scan: return
        for blk in blocks(site, scan):
            if blk[0] != "<long>": self.edit[blk] += w
        self.pairs += w

    def seen(self, site, scan, own=True):
        """how often the rarest change in this pair has been seen elsewhere (own=True: the pair itself is among the
        counts, so it is taken out once), and the changes. None if a change is too long to be a misreading"""
        bl = blocks(site, scan)
        if not bl: return None, []
        if any(b[0] == "<long>" for b in bl): return 0, bl
        n = min(self.edit[b] - (1 if own else 0) for b in bl)
        return max(0, n), bl

    def describe(self, bl):
        return ", ".join("%s→%s (%d×)" % (x or "∅", y or "∅", self.edit[(x, y)]) for x, y in bl)


def heb_letters(s):
    """Hebrew letters only: the OCR's vowel points are too unreliable to count"""
    s = NIK.sub("", s)
    return re.sub("[^א-ת]", "", s)


def lat(s):
    """a Latin word as compared: NFC, no outer spaces"""
    return unicodedata.normalize("NFC", s.strip())


def save_pairs(wd, pairs):
    """pairs: {"lat": [[site, scan], ...], "heb": [...]} for one page"""
    os.makedirs(wd, exist_ok=True)
    json.dump(pairs, open(os.path.join(wd, "pairs.json"), "w"), ensure_ascii=False)


def build(pages_dir, marks=None):
    """the model from every audited page's pairs.json, with the user's marks: (Latin, Hebrew)"""
    L, H = Confusions("lat"), Confusions("heb")
    bad, good = set(), set()
    for m in (marks or {}).values():
        f = m.get("finding") or {}
        pair = (f.get("site") or f.get("site_heb") or "", f.get("scan") or f.get("scan_heb") or "")
        if m.get("verdict") == "error": bad.add(pair)
        elif m.get("verdict") == "false": good.add(pair)
    if os.path.isdir(pages_dir):
        for d in sorted(os.listdir(pages_dir)):
            p = os.path.join(pages_dir, d, "pairs.json")
            if not os.path.exists(p): continue
            try: pr = json.load(open(p))
            except Exception: continue
            for a, b in pr.get("lat", []):
                if (a, b) in bad: continue
                L.add(lat(a), lat(b), 3 if (a, b) in good else 1)
            for a, b in pr.get("heb", []):
                if (a, b) in bad: continue
                H.add(heb_letters(a), heb_letters(b), 3 if (a, b) in good else 1)
    return L, H
