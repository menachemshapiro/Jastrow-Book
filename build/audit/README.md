# The audit: the site against the 1903 scans

Compares every page of the site with an OCR of the HebrewBooks scans and lists the differences, each with the piece of the scan it comes from. It also checks the site's text on its own, and its Bavli references. It runs on your computer with no Claude involved. You send Claude only `summary.txt`, plus any findings you want judged.

## Running it

```
source ~/jastrow/venv/bin/activate
cd ~/jastrow/Jastrow-Book
python3 build/audit/audit.py --check            # tools, Hebrew model, scans, paths
python3 build/audit/audit.py --pages 1-10       # the pilot
xdg-open work/audit/report/index.html            # the report
```

`--pages` also takes `1,5,7-9` or `all`. Each page's OCR is kept in `work/audit/pages/`, so a second run only compares again, which takes seconds. Add `--force` to OCR again, for example after changing `--dpi`. Other options: `--jobs N`, `--dpi N` (default 400), `--no-talmud`, `--no-quotes`, `--no-verify`, `--entry-lines flush|indent`, `--out DIR`, `--site DIR`.

Needs: `pdftoppm` (poppler-utils), `tesseract` with the `eng` and `heb` models (`sudo apt install tesseract-ocr-heb`), and `pip install numpy pillow`. The scans are found through `build/paths.py` (`work/scans/*1.pdf` and `*2.pdf`, or `JASTROW_SCANS`). The quotation search needs Sefaria's Talmud text in `work/talmudtext`. Without it, only the range check runs.

## What comes out (in `work/audit/`)

| File | What |
|---|---|
| `summary.txt` | Counts by kind and per page. Paste this to Claude. |
| `findings.jsonl` | Every finding, one per line: page, entry, kind, severity, site text, OCR text, note |
| `report/index.html` | The findings page by page, filterable, each with its scan crop (the words concerned boxed in red) |
| `report/entries.html` | Every entry: its scan, in all its parts (across columns and pages, in reading order), beside the site's text |
| `pages/pNNNN/layout.png` | What the layout step found. Columns are red, the running head and foot green, a letter heading purple, lines blue. Look here first if a page's results look wrong. |

Severity: 1 = likely an error, 2 = check, 3 = minor or uncertain.

## How it works

1. **Scan** (`scan.py`). Each page is rendered from the PDF (book page n ≤ 683 → PDF 1 page n+16; n ≥ 684 → PDF 2 page n−683) and straightened. Its layout is found next:
   - the running head, and a rule under it;
   - the gutter, found in two passes so that a letter heading crossing it doesn't narrow it;
   - any band crossing the gutter, which is a letter heading part-way down the page;
   - the column segments (two above such a heading, two below);
   - a printer's signature line at the foot, which is ignored.

   A column's left edge is taken from its justified right edge, so a column with no entry starting in it is still measured right. Every column is OCR'd twice, with Tesseract's English and Hebrew models.
2. **Site** (`sitetext.py`). The page's HTML from `data/` becomes word tokens. Each token knows its entry, its offset in the text the column break is counted in, and whether it is Hebrew, a headword, a binyan form or a sense number. It also knows which right-to-left island the browser sets it in. The site's own column breaks are worked out the way `index.html` does it (letter pages, mid-page letters, `pages.json`).
3. **Compare** (`compare.py`). Each scan word is classed as Hebrew or English by which OCR reads it more confidently. A word hyphenated at a line's end is joined (rule 2.8). The whole page is aligned word for word in reading order, so an entry that runs from one column into the next, or onto the next page, is compared as one piece. The differences are then classified:
   - run-together and split words; words and numbers that differ (re-read at double size before being reported); folio sides;
   - text missing on the site, or not in the scan; doubled text;
   - words that slipped across a page break;
   - column breaks, compared with the site's (`column_break`), or proposed where the site has none (`column_break_unset`, with the offset to put in `breaks_all2.json` or `mid_breaks.json`);
   - Hebrew: the same words in the same left-to-right order on each line as the site shows them; headwords letter by letter;
   - entries: the site's entries are paired, in order, with the lines the book starts at the column's edge. One left over on either side is a missing entry, or two entries run into one;
   - the running head: page number and guide words. A wrong page number means the PDF page mapping is off.
   - **is the scan page whole?** (`scan_incomplete`, listed first in the report and in `summary.txt`). The page is flagged when:
     - the text runs to the image's edge (cropped);
     - there is a blank stretch of several lines inside a column;
     - a run of 15 or more of the site's words is not in the scan at all (the message says whether at the top, middle or foot);
     - under 75% of the site's words are found;
     - the image or text block is a different size from the other pages in the run.

     A column that ends lines above the other is reported as a "check", because the book balances its columns. Findings on a flagged page may come from the scan, not the site.
4. **Site-only checks** (`checks.py`): unbalanced brackets, sense numbers out of sequence, "un- worthy" hyphens, stray characters, repeated phrases, headword punctuation and display, alphabetical order.
5. **Bavli** (`checks.py`, using `talmud_index.citations` and `talsearch`). Each citation is checked against the tractate's range. Then the Hebrew that follows it is searched on the cited daf, its neighbouring amudim, the rest of the tractate, and the whole Bavli, with abbreviations expanded (rule 2.5).

## Limits

- Tesseract does not read vowel points reliably. Hebrew is compared by its letters, and only headwords letter by letter.
- Whether the browser *shows* a headword correctly is checked from the site's markup (`unicode-bidi` islands, spacing), not by rendering the page.
- Thresholds live in `compare.CFG`. They were tuned on synthetic pages (`tests/make_synthetic.py`) and will need adjusting on the real scans.

## Testing without the scans

`tests/make_synthetic.py OUTDIR 1 2 3` sets the site's text as a two-column book page and writes a PDF laid out like the real ones. Run the audit on it with `JASTROW_SCANS=OUTDIR`. On unchanged text it should report almost nothing; on a copy of `data/` with errors put in, it should find them.
