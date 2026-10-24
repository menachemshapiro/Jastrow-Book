#!/usr/bin/env python3
"""Find places where Sefaria's text runs two words together, as the page shows them:
  "ch. same.Targ. Gen." (no space after a period), "= nextTarg." or "sameIthpalp." (a word run into the
  next abbreviation), "כְּרוּב ITarg." (a homonym's numeral run into the next word), "v. אָבַרPi." (Hebrew run
  into a binyan), and "Sabb. 11Sabb. 110^a" (a citation repeated, the first copy cut short).
Lists only; nothing is changed. usage: python3 build/runtogether.py <site dir> <out.json>"""
import sys, os, re, json
from collections import defaultdict
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
SITE, OUT = sys.argv[1], sys.argv[2]
sys.argv = [sys.argv[0], SITE]
import talmud_index as T

CAP = (r"(?:Targ|Ib|Pl|Pi|Pa|Pu|Hif|Hof|Nif|Af|Ithpe|Ithpa|Ithpol|Ithpalp|Ithpalal|Hithpa|Hithpol|Polel|Palp|Pilp|Nithpa|Pe|Pual|"
       r"Constr|Fem|Part|Inf|Imper|Sabb|Ber|Snh|Pes|Yoma|Succ|Keth|Kidd|Gitt|Git|Yeb|Ned|Naz|Sot|Meg|Taan|Erub|Bets|Men|Zeb|Bekh|"
       r"Tem|Ḥull|Ḥag|Nidd|Hor|Macc|Shebu|Tosef|Gen|Ex|Lev|Num|Deut|Midr|Yalk|Pesik|Tanḥ|Sifra|Sifré|Mekh|Cmp|Lam|Koh|Cant|Esth|"
       r"Ps|Prov|Is|Jer|Ez|Var|Ms|Deriv|Denom|Trnsf|Metaph|Euphem|Arakh|Kel|Ohol|Neg|Par|Toh|Mikv|Maksh|Zab|Yad|Ukts|Shebi|Ter|Maas|Dem|Kil|Orl|Bicc|Shek|Eduy|Ab|Aboth|Tam|Midd|Kinn)")
KINDS = [
    ("no space after a period", re.compile(r"(?<=[a-zא-ת֑-ׇ)\]׳])\.(?=[A-ZḤ][a-zḥ])")),
    ("word run into the next abbreviation", re.compile(r"(?<=[a-z])(?=" + CAP + r"\.)")),
    ("numeral run into the next word", re.compile(r"(?<=[א-ת֑-ׇ] )(?:I|II|III|IV)(?=" + CAP + r"\.)")),
    ("Hebrew run into the next word", re.compile(r"(?<=[א-ת֑-ׇ])(?=" + CAP + r"\.)")),
    ("citation repeated", re.compile(r"\b((?:[A-Z][\w’]*\.\s){1,3}(?:R\.\s)?(?:s\.\s|to\s[IVXLC]+,\s)?)(\d+)(?=\1\2)")),
]
# words that legitimately join a lowercase letter and a capital
OK = re.compile(r"(?:Mc|Mac|d’|b’|v’|l’)$")

def main():
    meta = json.load(open(os.path.join(SITE, "data/pages.json")))["pages"]
    hw = {r[0]: r for r in json.load(open(os.path.join(SITE, "data/hw.json")))}
    items = []
    for eid, t, refs in T.entry_texts():
        for kind, rx in KINDS:
            for m in rx.finditer(t):
                a = m.start()
                if kind == "word run into the next abbreviation" and OK.search(t[max(0, a - 3):a]): continue
                ctx = t[max(0, a - 45):a] + "⟦" + t[a:a + 22].split(" ")[0] + "⟧"
                pi = hw[eid][1] if eid in hw else None
                items.append({"kind": kind, "entry": eid, "page": meta[pi][0] if pi is not None else None,
                              "context": t[max(0, a - 50):a + 50], "at": a, "match": t[a - 1:a + 1] if not m.group(0) else m.group(0)})
    json.dump(items, open(OUT, "w"), ensure_ascii=False, indent=0)
    from collections import Counter
    print(len(items), Counter(i["kind"] for i in items))

if __name__ == "__main__":
    main()
