# Jastrow-Book

Marcus Jastrow's *Dictionary of the Targumim, the Talmud Babli and Yerushalmi, and the Midrashic Literature* (1903), laid out page for page as in the printed book, two columns per page, with the same first and last words in each column. The text comes from [Sefaria](https://www.sefaria.org/).

The site is a single page (`index.html`) that reads the dictionary from `data/`.

## What's here

| Path | What it is |
| --- | --- |
| `index.html` | The viewer: spread, single-page and text views, search, contents by each page's first word, and a larger-type reader for any entry |
| `data/` | The pages (`c000.json`–`c174.json`, ten pages each), the page list with column breaks (`pages.json`) and the headword index (`hw.json`) |
| `build/build2.py` | Builds the pages from Sefaria's 2026 Jastrow text, using the page breaks in Sefaria's 2018 data |
| `build/make_site2.py` | Turns the built pages into `data/`, with the title pages, preface footnotes and text repairs |
| `build/breaks_all2.json` | The column break on each page, as a character offset into the page's text, checked against scans of the 1903 printing |

## Rebuilding `data/`

Sources (not in this repository because of their size): Sefaria's current Jastrow export (`jastrow-complete.json`) and the 2018 Sefaria-Data Jastrow XML (`Jastrow-full.xml`), which has the page breaks.

```
python3 build/build2.py Jastrow-full.xml jastrow-complete.json out2
BREAKS=build/breaks_all2.json python3 build/make_site2.py out2 . jastrow-complete.json
```
