# Jastrow — ספר המלים

Marcus Jastrow's *A Dictionary of the Targumim, the Talmud Babli and Yerushalmi, and the Midrashic Literature* (London: Luzac, 1903), laid out as the printed book. Every page and every column begins and ends on the same word as the 1903 edition, so a reference to "Jastrow p. 1087" lands on the right page.

**Read it at [menachemshapiro.github.io/Jastrow-Book](https://menachemshapiro.github.io/Jastrow-Book/).**

## What you can do

**Read**
- **Spread** shows two facing pages, **Page** shows one, and **Text** reflows the page's text for a small screen.
- To turn pages, use ‹ ›, the slider, the arrow keys, or swipe on a phone. Type a page number to jump to it; the preface and abbreviations use their Roman numerals.
- Click any entry to read it in larger type. The whole entry is shown, even when it runs over two columns or pages. From there you can step to the previous or next entry, change the type size, show the entry on its page, open it on Sefaria, copy a citation, or copy a link to it.
- Dotted words are cross-references within the dictionary. Source citations ("Ber. 26ᵇ") open the passage on Sefaria.

**Find**
- **Search** matches headwords as you type, in Hebrew with or without vowel points, or by page number. "Search all text" looks through every entry, in English and Hebrew.
- **א־ב** opens a Hebrew keyboard, either alphabetical or in the standard Israeli layout.
- **Contents** lists every page by its first and last headword, letter by letter, like the book's running heads.
- **Citations** lists the entries that cite a chosen daf of the בבלי or the ירושלמי, with the tractate and daf in Hebrew.
  - Citations are read from Jastrow's own abbreviations. The Bavli is cited by daf and amud ("Ber. 26ᵇ"), and the Yerushalmi by chapter plus the folio and column of the Krotoshin edition ("Y. Ber. VIII, 12ᶜ").
  - "Ib." and a bare folio count as the tractate cited just before.
  - The index holds about 31,900 Bavli and 12,200 Yerushalmi citations. Sefaria links many of the same Bavli citations, and the two agree in all but one case.
- **Targumim and Midrash Rabbah**, in the same panel, list the entries that cite a chapter (or a section of the Rabbah), verse by verse, with the book and chapter in Hebrew. Choose the source from the menu:
  - תרגום אונקלוס: "Targ. O. Gen. XVII, 4", or "Targ. Gen. XVII, 4" (on the Torah, "Targ." alone is Onkelos). About 3,800 citations.
  - תרגום יונתן על התורה (Pseudo-Jonathan): Jastrow's "Targ. Y." and "Targ. Y. I". About 3,200.
  - תרגום ירושלמי (the Fragment Targum): "Targ. Y. II". About 600.
  - תרגום יונתן על הנביאים: "Targ. Is. XXX, 2", "Targ. I Sam. …". About 4,600.
  - תרגום כתובים: Psalms, Proverbs, Job, the Megillot (and Targum Sheni to Esther, "Targ. II Esth.") and Chronicles. About 6,600.
  - מדרש רבה: on the Torah by section ("Gen. R. s. 19"), on the Megillot by the verse commented on ("Lam. R. to I, 5") or the introduction. About 10,800.
  - Where Sefaria links the same citation, the two agree in all but a handful of cases. Most of those are "Targ. Y. ib." right after a "Targ. Y. II" citation: Sefaria reads it as Y. II, and this index, following Jastrow's abbreviations, as Y. I.

**Link**
- A page: `#p1087`
- An entry, by its Sefaria id: `#P00866` (opens the page with the entry in the reader; the reader's "Copy link" button gives this link)
- A daf: `#t/b/Berakhot/26b` or `#t/y/Berakhot/12c`
- A chapter of Onkelos: `#t/o/Genesis/17`; a section of Bereshit Rabbah: `#t/r/Bereishit_Rabbah/19`

## Sources and thanks

- **Text: [Sefaria](https://www.sefaria.org/Jastrow).** The dictionary text is Sefaria's digitization of Jastrow, as Sefaria served it in October 2026. The entry ids, the links to sources and the "Open on Sefaria" links are also Sefaria's. Many thanks to Sefaria for making it freely available.
- **Checked against the book.** Column breaks, title pages and corrections were checked against scans of the 1903 printing from [HebrewBooks.org](https://hebrewbooks.org/).
- **Public domain.** The dictionary itself (1903) is in the public domain.

## Corrections

Changes to Sefaria's text are kept in [`build/text_fixes.json`](build/text_fixes.json). Each record gives the page, the text before and after, and the reason for the change, checked against the 1903 printing. Each correction is its own commit, so the history shows every change.

## What's in the repository

| Path | What it is |
| --- | --- |
| `index.html` | The whole site: viewer, search, keyboard, contents, entry reader and Talmud finder |
| `data/c000.json`–`c174.json` | The pages, ten to a file |
| `data/pages.json` | The page list: labels, first and last headwords, and the column break on each page |
| `data/hw.json` | The headword index |
| `data/talmud/` | Every Talmud citation, by tractate and daf |
| `data/targum/` | Every Targum citation, by Targum, book, chapter and verse |
| `data/midrash/` | Every Midrash Rabbah citation, by book and section or verse |
| `build/build2.py` | Builds the pages from Sefaria's current text, using the 2018 page breaks |
| `build/make_site2.py` | Turns the built pages into `data/`, adding the title pages, preface footnotes and text corrections |
| `build/text_fixes.json` | Corrections to the text, one record per change |
| `build/breaks_all2.json` | Each page's column break, as a character offset into that page's text |
| `build/talmud_index.py` | Builds `data/talmud/` from the entry text |
| `build/targum_index.py` | Builds `data/targum/` from the entry text |
| `build/midrash_index.py` | Builds `data/midrash/` from the entry text |
| `favicon.ico`, `icon-*.png`, `og.png`, `site.webmanifest` | Icons and the image shown in link previews |

## Rebuilding `data/`

The two sources aren't in this repository because of their size. They are Sefaria's current Jastrow export (`jastrow-complete.json`, from Sefaria's dictionary API) and the 2018 Sefaria-Data Jastrow XML (`Jastrow-full.xml`).

```
python3 build/build2.py Jastrow-full.xml jastrow-complete.json out2
BREAKS=build/breaks_all2.json python3 build/make_site2.py out2 . jastrow-complete.json
python3 build/talmud_index.py .
python3 build/targum_index.py .
python3 build/midrash_index.py .
```
