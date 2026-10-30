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

`--pages` also takes `1,5,7-9` or `all`. Each page's OCR is kept in `work/audit/pages/`, so a second run only compares again, which takes seconds. Add `--force` to OCR again, for example after changing `--dpi`. A page laid out by an older version of the layout step is laid out again by itself; it is OCR'd again only if its columns moved. Other options: `--jobs N`, `--dpi N` (default 400), `--no-talmud`, `--no-quotes`, `--no-verify`, `--no-reread` (skip stage 3), `--no-stage4`, `--entry-lines flush|indent`, `--out DIR`, `--site DIR`.

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
   - word counts (`word_count`): each entry's English words, the site's against the book's. Differences the word-by-word comparison let pass without a finding, or with only a minor one (OCR noise, next to Hebrew), are added up per entry; an entry with two or more of the book's or the site's words left over is reported, with the words and the likely cause. Only words the book uses elsewhere count, and not numbers or Roman numerals. A safety net: on test pages the word-by-word comparison had already caught what it would catch;
   - the running head: page number and guide words. A wrong page number means the PDF page mapping is off.
   - **is the scan page whole?** (`scan_incomplete`, listed first in the report and in `summary.txt`). The page is flagged when:
     - the text runs to the image's edge (cropped);
     - there is a blank stretch of several lines inside a column;
     - a run of 15 or more of the site's words is not in the scan at all (the message says whether at the top, middle or foot);
     - under 75% of the site's words are found;
     - the image or text block is a different size from the other pages in the run.

     A column that ends lines above the other is reported as a "check", because the book balances its columns. Findings on a flagged page may come from the scan, not the site.
   - **stage 4, content first, order second** (`compare.stage4`): per entry, the words each side has that the other lacks are compared as a bag before their order. The same words on both sides at different places are one finding, "Same words, other order" (`order_differs`), not "missing" plus "extra". A word missing on one side and a word like it extra on the other (alike once the letters the OCR confuses are made the same) are one word read or typed two ways: a `word_differs`, which stage 3 tests. Hebrew words are paired as a bag too, and their order is then checked on each line and across lines (the word the site gives first must stand on the earlier line). A phrase doubled is caught whichever copy the alignment takes for the book's. What is not an error (AUDIT_PLAN.md, "Things to look out for") is applied before: words divided at a line's end however the OCR read the hyphen, final letters, mirrored brackets, vowel points (Hebrew is compared by its letters), spacing and punctuation.
   - **stage 3, both readings tested against the image** (`reread.py`, `compare.stage3`): every word, number, Hebrew and headword-letter finding, every Hebrew order finding, and every stretch of text the OCR did not match, is read again with Tesseract's character alternatives (`-c lstm_choice_mode=2`, hOCR): for each character it read, the others it considered and their confidences. It is read four ways, at the page's size and at double size, in grey and in black and white, cut to the word's own ink (from the OCR's box out to the spaces on either side; the OCR's box of a word it misread often leaves out a letter). Then Sefaria's reading and the OCR's are scored letter by letter against the alternatives: the best path that lines the reading up with them, each letter costing its confidence, a letter not among the alternatives (or missing, or one too many) costing much more. Each finding gets a verdict, shown in the report with both readings and their scores (and a filter):
     - **the OCR misread the book**: every letter of Sefaria's is among the alternatives and the word is nearly as likely as the OCR's (`re_ok`), or read with Sefaria's word as the only dictionary word (`--user-words`, system dictionaries off) the OCR finds it. Not a finding: kept as minor, with the scores.
     - **likely Sefaria's error**: the four reads agree on another word, it fits well, it is much likelier than Sefaria's (`re_err`), and the two are one word read two ways. Raised to "likely error".
     - **unclear**: both fit, or neither (worn print, or a crop that missed the word). For you.
     Then the words are asked too ("which side"): where the OCR's reading is no word of the book (seen once or never on the site) and Sefaria's is a common one, the OCR misread worn type. Numbers are judged on their digits (a raised side letter read as one more digit is allowed for). Next to Hebrew, each of Sefaria's English words is looked for among the scan's words of the gap: if all are there, the OCR took them for Hebrew or noise. For Hebrew order, both placings of the two words are scored against the two places in the scan: only the site's placing confirmed by the image is an error. Everything read is cached in `pages/pNNNN/reread3.json`, by crop, way of reading and model, so a second run reads nothing again. The reads use the same models as the OCR (`scan.lang_args`), so `--trained` swaps in the trained ones; the cache keeps them apart. Thresholds are in `compare.CFG` (`re_ok`, `re_err`, `re_good`, `re_weak`, `near_word`, `heb_order_conf_low`).
4. **Site-only checks** (`checks.py`): unbalanced brackets, sense numbers out of sequence, "un- worthy" hyphens, stray characters, repeated phrases, headword punctuation and display, alphabetical order.
5. **Bavli** (`checks.py`, using `talmud_index.citations` and `talsearch`). Each citation is checked against the tractate's range. Then the Hebrew that follows it (past a short remark such as "(prov.)"; Hebrew before it only when no full stop, semicolon or "v." comes between) is searched, without and with Jastrow's bracketed variants, and with the readings he names after it ("read …", "Ar.", "ed. …", "Ms. M. …") put in. When the phrase isn't found, every word of it on the cited daf (all but one, for three words or more) counts as found. It is searched on the cited daf, its neighbouring amudim, the rest of the tractate, and the whole Bavli, with abbreviations expanded (rule 2.5).

## Learning from the book itself

- **The OCR's misreadings, measured** (`ocrmodel.py`). Each run first counts, on every page audited so far, how the OCR misreads this book: wherever one site word stands against one scan word, the change between them ("5;" → "53", ב → כ). The counts are kept in `pages/pNNNN/pairs.json`. Your marks teach it too: a "false alarm" counts three times, a "site is wrong" is left out. A difference made only of changes seen three times or more is minor ("a misreading this OCR makes often"); once enough pairs are counted, a change never seen before stands out, and a confident, re-read word with such a change is a likely error.
- **Which side is wrong.** Sefaria's text was made by OCR too, so its typos are the same confusions ("narne" for "name"). A site word that is rare on the whole site (twice or less) where the book reads a common one (five times or more) is reported as a likely error in Sefaria's text.
- **Training the OCR on the book** (`train_ocr.py`). Where the scan and the site agree, the site's text is what the page says: those places are cut out as training pairs (English stretches of three words or more, Hebrew words with their vowel points), and Tesseract's best models are fine-tuned on them. Then `audit.py --trained` reads the scans with the trained models; pages read with other models are OCR'd again by themselves.

```
pip install python-bidi                                   # once
python3 build/audit/audit.py --pages 1-150                # the more pages OCR'd, the more to train on
python3 build/audit/train_ocr.py check
python3 build/audit/train_ocr.py prepare                  # training pairs from every page OCR'd
python3 build/audit/train_ocr.py train                    # a few hours; can be stopped and run again
python3 build/audit/train_ocr.py status
python3 build/audit/audit.py --trained --pages 1-10       # the audit with the trained models
```

## Limits

- Tesseract does not read vowel points reliably. Hebrew is compared by its letters, and only headwords letter by letter.
- Whether the browser *shows* a headword correctly is checked from the site's markup (`unicode-bidi` islands, spacing), not by rendering the page.
- Thresholds live in `compare.CFG`. They were tuned on synthetic pages (`tests/make_synthetic.py`) and will need adjusting on the real scans.

## Measuring it

`tests/measure.py` says whether a change to the audit makes it better (AUDIT_PLAN.md, "How we know it is getting better"). It plants errors of the kinds Sefaria's text has in a copy of `data/` (`tests/plant.py`: typos rn/m, c/e, n/u, u/n, h/b; one or two words missing; a phrase doubled; two Hebrew words swapped; a headword letter changed for a look-alike; a folio digit), audits the unchanged site and the copy, and counts:

- **found**: planted errors with a "likely error" or "check" at their place (not one the re-reading settled as the OCR's);
- **false**: "likely error" and "check" findings on the unchanged site from the comparison with the scan (the checks of the site's text alone, the Talmud checks and the layout are left out); on the real scans your marks say which of them are real;
- **unclear**: findings the re-reading left unclear among those, the ones you would have to read.

```
python3 build/audit/tests/measure.py --pages 1-10 --label after                 # the real scans' OCR in work/audit/pages
python3 build/audit/tests/measure.py --pages 1-10 --label before --audit-args "--no-reread --no-stage4"
python3 build/audit/tests/measure.py --pages 1-10 --synthetic                     # no scans needed
```

Each run adds a line to `work/audit_measure/results.tsv` and prints a summary (also in `last_summary.txt`); `--seed N` plants other errors. Keep a change only if it doesn't make these worse.

## Testing without the scans

`tests/make_synthetic.py [--worn] OUTDIR 1 2 3` sets the site's text as a two-column book page and writes a PDF laid out like the real ones; `--worn` makes it look like a worn printing scanned in grey (faint, broken and spread ink, speckles, grey paper, blur). Run the audit on it with `JASTROW_SCANS=OUTDIR`. On unchanged text it should report almost nothing; on a copy of `data/` with errors put in, it should find them.
