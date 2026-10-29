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

`--pages` also takes `1,5,7-9` or `all`. Each page's OCR is kept in `work/audit/pages/`, so a second run only compares again, which takes seconds. Add `--force` to OCR again, for example after changing `--dpi`. A page laid out by an older version of the layout step is laid out again by itself; it is OCR'd again only if its columns moved. Other options: `--jobs N`, `--dpi N` (default 400), `--no-talmud`, `--no-quotes`, `--no-verify`, `--entry-lines flush|indent`, `--out DIR`, `--site DIR`.

Needs: `pdftoppm` (poppler-utils), `tesseract` with the `eng` and `heb` models (`sudo apt install tesseract-ocr-heb`), and `pip install numpy pillow`. The scans are found through `build/paths.py` (`work/scans/*1.pdf` and `*2.pdf`, or `JASTROW_SCANS`). The quotation search needs Sefaria's Talmud text in `work/talmudtext`. Without it, only the range check runs.

## What comes out (in `work/audit/`)

| File | What |
|---|---|
| `summary.txt` | Counts by kind and per page. Paste this to Claude. |
| `findings.jsonl` | Every finding, one per line: page, entry, kind, severity, site text, OCR text, note |
| `report/index.html` | Start here. Likely errors first, then "worth a check"; minor ones are hidden until you tick their tile. Each finding is two boxes side by side: **Site** (the site's text with the words concerned highlighted, or a ‸ where words are missing) and **Book** (the scan crop with the words boxed in red, and what the OCR read). Filter by kind or page. Each finding can open the whole entry (text beside its stitched scan), the whole scan page, the layout picture and the site's page (local and live). Places where the OCR could not read the Hebrew are only counted (per page, at the foot): they say nothing about the site. |
| `report/entries.html` | Every entry: its scan, in all its parts (across columns and pages, in reading order), beside the site's text with every finding highlighted by severity. Hover over a highlight for what it is; click it to go to the finding. The same page links. |
| `marks.json` | Your verdicts. In the report, each finding has **Site is wrong**, **False alarm** and **Not sure**, and a note. They are kept in the browser as you go. In Chrome or Edge, **Autosave to a file…** (pick `jastrow-audit-marks.json` in Downloads once) then writes the file two seconds after every change and once a minute, so a crash loses nothing; after reopening the report, click **Resume autosave**. **Export marks** saves them as `jastrow-audit-marks-<date>-<time>.json` (in Downloads); each export holds every mark so far. Every marks file a run reads, and `work/audit/marks.json` before it is rewritten, is copied into `work/audit/marks_backup/` under its time, so no export or autosave overwrites the only copy. The next run reads that file from Downloads (or `--marks FILE`), merges it into `work/audit/marks.json`, and shows each verdict again on the same finding; filter by "not yet marked" to see only what is new. `summary.txt` then lists the false alarms by kind. Send Claude the marks file: each mark carries its finding, so it is all Claude needs to tune the audit. **Import marks** loads a file into a report by hand (Firefox keeps the browser's copy per run folder). |
| `pages/pNNNN/layout.png` | What the layout step found. Columns are red, the running head and foot green, a letter heading purple, lines blue. Look here first if a page's results look wrong. |

The "site page (local)" links expect the local preview: run `python3 -m http.server` in the repository, or point them elsewhere with `--site-url`. The live links go to the merged site (`main`), which may differ from your branch.

Severity: 1 = likely an error, 2 = check, 3 = minor or uncertain; the report shows `ib_named` and `abbreviation` in a section of their own, "Decide as a group". Two kinds group differences that look systematic, so they can be decided together: `ib_named` (the book prints "Ib." where the site names the work, e.g. "Snh.": Sefaria's expansion?) and `abbreviation` (the same abbreviation spelt with a letter more or less, e.g. the site's "Kidd." for the book's "Kid."). Treated as the OCR's doing, so minor or dropped: a word divided at a line's end however the OCR read the hyphen (rule 2.8); a space the OCR lost ("R.s.", "thealphabet"); c read as e; a misread Roman numeral; a headword whose reading is too unclear to compare (counted as not checked); two spellings of one word whose order can't be told from the OCR; a printer's signature at a column's foot. A number the OCR misread in a familiar way (a raised folio letter read as a digit: 39ᵇ as 895; a digit as a letter where the site has the digits) is minor. A column break the audit could only estimate is a check.

## How it works

1. **Scan** (`scan.py`). Each page is rendered from the PDF (book page n ≤ 683 → PDF 1 page n+16; n ≥ 684 → PDF 2 page n−683) and straightened. Its layout is found next:
   - the running head, and a rule under it;
   - a printed vertical rule between the columns (pp. 6 and 8 have one), taken out first;
   - the line pitch, measured in each column separately;
   - the gutter, found in two passes so that a letter heading crossing it doesn't narrow it;
   - any band crossing the gutter, which is a letter heading part-way down the page;
   - the column segments (two above such a heading, two below);
   - a printer's signature line at the foot, which is ignored.

   A column's box is never set into the gutter. A layout that cannot be right (a gutter much wider than a few percent of the page, a "heading" more than five lines high) is reported as a layout finding rather than used. Every column is OCR'd twice, with Tesseract's English and Hebrew models.
2. **Site** (`sitetext.py`). The page's HTML from `data/` becomes word tokens. Each token knows its entry, its offset in the text the column break is counted in, and whether it is Hebrew, a headword, a binyan form or a sense number. It also knows which right-to-left island the browser sets it in. The site's own column breaks are worked out the way `index.html` does it (letter pages, mid-page letters, `pages.json`).
3. **Compare** (`compare.py`). Each scan word is classed as Hebrew or English by which OCR reads it more confidently. A word hyphenated at a line's end is joined (rule 2.8). The whole page is aligned word for word in reading order, so an entry that runs from one column into the next, or onto the next page, is compared as one piece. The differences are then classified:
   - run-together and split words; words and numbers that differ (re-read at double size before being reported); folio sides;
   - text missing on the site, or not in the scan; doubled text;
   - words that slipped across a page break;
   - column breaks, compared with the site's (`column_break`), or proposed where the site has none (`column_break_unset`, with the offset to put in `breaks_all2.json` or `mid_breaks.json`);
   - Hebrew: the same words in the same left-to-right order on each line as the site shows them; headwords letter by letter. The order is checked only on words of three letters or more that the OCR read closely (`heb_order_sim`) and confidently (`heb_order_conf`), with boxes clearly apart; it is a likely error only when every word was read exactly. A headword whose letters differ is read again by itself at double size (cached in `reread_heb.json`); if the second reading agrees with the site, nothing is reported. A difference in letters the OCR confuses, or a ו or י more or less (a holam, shuruk or hiriq read as a letter), is minor. A site word the OCR read too poorly to pair (it dropped or added letters) is counted as not checked, not reported as different; short "words" the OCR makes of vowel points (דד, זז) are ignored;
   - entries: the site's entries are paired, in order, with the lines the book indents. The book indents an entry's first line by about an em and sets the lines after it flush; each line is measured against its own column's flush edge, so a column box that is a little off does not matter. One left over on either side is a missing entry, or two entries run into one;
   - the running head: page number and guide words. A wrong page number means the PDF page mapping is off.
   - **is the scan page whole?** (`scan_incomplete`, listed first in the report and in `summary.txt`). The page is flagged when:
     - the text runs to the image's edge (cropped);
     - there is a blank stretch of several lines inside a column;
     - a run of 15 or more of the site's words is not in the scan at all (the message says whether at the top, middle or foot);
     - under 75% of the site's words are found;
     - the image or text block is a different size from the other pages in the run.

     A column that ends lines above the other is reported as a "check", because the book balances its columns. Findings on a flagged page may come from the scan, not the site.
4. **Site-only checks** (`checks.py`): unbalanced brackets, sense numbers out of sequence, "un- worthy" hyphens, stray characters, repeated phrases, headword punctuation and display, alphabetical order.
5. **Bavli** (`checks.py`, using `talmud_index.citations` and `talsearch`). Each citation is checked against the tractate's range. Then the Hebrew that follows it (past a short remark such as "(prov.)"; Hebrew before it only when no full stop, semicolon or "v." comes between) is searched, without and with Jastrow's bracketed variants, and with the readings he names after it ("read …", "Ar.", "ed. …", "Ms. M. …") put in. When the phrase isn't found, every word of it on the cited daf (all but one, for three words or more) counts as found. It is searched on the cited daf, its neighbouring amudim, the rest of the tractate, and the whole Bavli, with abbreviations expanded (rule 2.5).

## Limits

- Tesseract does not read vowel points reliably. Hebrew is compared by its letters, and only headwords letter by letter.
- Whether the browser *shows* a headword correctly is checked from the site's markup (`unicode-bidi` islands, spacing), not by rendering the page.
- Thresholds live in `compare.CFG`. They were tuned on synthetic pages (`tests/make_synthetic.py`) and will need adjusting on the real scans.

## Testing without the scans

`tests/make_synthetic.py OUTDIR 1 2 3` sets the site's text as a two-column book page and writes a PDF laid out like the real ones. Run the audit on it with `JASTROW_SCANS=OUTDIR`. On unchanged text it should report almost nothing; on a copy of `data/` with errors put in, it should find them.
