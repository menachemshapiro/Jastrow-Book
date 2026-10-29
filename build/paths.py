"""Where the build scripts find the files that are not in the repository.

Every path defaults to the layout of work/ in the repository (see LOCAL_SETUP.md in Jastrow-Notes):
  work/out2/                       the intermediate build that make_site2.py reads
  work/data/jastrow-complete.json  Sefaria's current text
  work/data2018/full/              Sefaria's 2018 XML, with the page breaks
  work/talmudtext/talmudtext/z/    Sefaria's Bavli and Yerushalmi, for the quotation search
  work/proofing/proofing-page/     the proofing list's cards
  work/ocr/, work/scans/           the raw OCR and the HebrewBooks scans
  work/reports/                    reports the scripts write (the indexes' disagreements, etc.)
To change one, put it in config.json at the top of the repository (see build/config.example.json; a
relative path there is read from the repository), or set an environment variable JASTROW_<NAME>,
e.g. JASTROW_WORK=/data/jastrow. The environment wins over config.json; WORK moves all the others."""
import json, os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_cfg = os.path.join(REPO, "config.json")
_cfg = json.load(open(_cfg)) if os.path.exists(_cfg) else {}


def _get(name, default):
    v = os.environ.get("JASTROW_" + name) or _cfg.get(name.lower()) or default
    return os.path.join(REPO, os.path.expanduser(v))       # an absolute path is kept as it is


WORK = _get("WORK", "work")
OUT2 = _get("OUT2", os.path.join(WORK, "out2"))
CURRENT = _get("CURRENT", os.path.join(WORK, "data", "jastrow-complete.json"))
XML = _get("XML", os.path.join(WORK, "data2018", "full", "Jastrow-full.xml"))
TALMUD = _get("TALMUD", os.path.join(WORK, "talmudtext", "talmudtext", "z"))
PROOFING = _get("PROOFING", os.path.join(WORK, "proofing", "proofing-page"))
OCR = _get("OCR", os.path.join(WORK, "ocr"))
SCANS = _get("SCANS", os.path.join(WORK, "scans"))
REPORTS = _get("REPORTS", os.path.join(WORK, "reports"))
BREAKS = os.path.join(REPO, "build", "breaks_all2.json")


def report(name):
    """the path of a report file, in REPORTS (made if missing)"""
    os.makedirs(REPORTS, exist_ok=True)
    return os.path.join(REPORTS, name)


if __name__ == "__main__":
    for k in ("REPO", "WORK", "OUT2", "CURRENT", "XML", "TALMUD", "PROOFING", "OCR", "SCANS", "REPORTS", "BREAKS"):
        p = globals()[k]
        print("%-9s %s%s" % (k, p, "" if os.path.exists(p) else "   (missing)"))
