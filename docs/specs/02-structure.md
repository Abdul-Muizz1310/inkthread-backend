# 02 · Structure: from inkgrid's reading to the graph's skeleton

The `structure` stage is pure. It takes a `Reading` and returns the skeleton graph draft: set-aside
entries, the section tree, one node per content block, `contains`, `continues` and `cites_note`
edges, table cell labels, flags, and per-page word geometry for the viewer.

## 1. The Reading (input)

`inkthread.domain.reading` defines a small model of what the domain needs from inkgrid. The adapter in
`inkthread.reader.adapt` builds it from an `inkgrid.Document` and its `VerificationReport`, so the
domain never imports inkgrid and its tests build Readings from literals.

| type | fields |
|---|---|
| `Reading` | `sha256`, `file_name`, `pages: PageSize[]`, `blocks: RBlock[]` (reading order), `links: RLink[]`, `findings: RFinding[]`, `defects: RDefect[]`, `producer: dict[str, str \| None]` |
| `RBlock` | `id` (`"b12"`), `key`, `kind` (inkgrid's seven), `text`, `regions`, `words: RWord[]`, and per kind: `level`/`number` (heading), `label` (list item, footnote), `term`/`body` (definition), `role` (furniture), `grid` (table) |
| `RWord` | `start`, `end` (offsets into the block text, or null when not aligned), `page`, `bbox`, `hidden`, `superscript` |
| `RGrid` | `n_rows`, `n_cols`, `header_rows`, `banner_rows`, `source`, `cells: RCell[]` |
| `RCell` | `row`, `col`, `row_span`, `col_span`, `text`, `carried`, `markers`, `page`, `bbox` (page coordinates, null when unknown) |
| `RLink` | `kind` (`footnote_call` \| `continuation`), `from_block`, `from_cell`, `to_block`, `label`, `method`, `status`, `reason` |
| `RDefect` | `code`, `block`, `cell`, `page`, `detail` |

### 1.1 Word alignment (adapter)

inkgrid builds a block's text by joining its words with one space and closing up line-end hyphens
(`hyphen_joins`). A table's text joins non-empty cell texts by a space and rows by `"\n"`. The adapter
aligns each word to the text by a forward search from a cursor, accepting the word without its trailing
hyphen when the word is the left side of a hyphen join. A word that is not found forward is searched from
the start among unclaimed offsets; a word still not found gets `start = end = null`. Alignment never
changes text.

## 2. Set-aside

Applied first; each rule names itself. A set-aside entry is
`{block, kind, text, page, bbox, reason}` with `reason` the rule id.

| rule | sets aside |
|---|---|
| `R-SET-furniture` | every inkgrid `furniture` block (`kind: "furniture"`) |
| `R-SET-toc` | a table of contents (`kind: "toc"`), below |

**R-SET-toc.** A TOC line is a heading, paragraph or list item of at most 160 characters whose text
ends in a page reference (an Arabic number up to 4 digits or a lowercase Roman numeral), optionally
after leader dots, and which prints no modal verb (`shall`, `must`, `may`, `will`). A TOC is a run of at
least three consecutive TOC lines, plus the heading just before the run when that heading reads
`contents`, `table of contents`, `list of tables`, `list of figures` or `list of exhibits` (any case). A
run of TOC lines that starts within three blocks after such a heading needs only two lines.

Keep-guard: a run is not set aside when more than half its lines end in a number that also appears as a
heading number later in the document **and** the run sits after the first page that holds a paragraph
of more than 40 words. (A numbered list in the body is content, not a TOC.)

## 3. Title

`R-SEC-title`. The title is the first heading on page 1 whose `level` is the smallest (largest type) of
all heading levels in the document, provided page 1 holds it. Its text becomes the document node's
text. A later heading whose folded text equals the title's (a repeated cover title) also cites the
document node and opens no section. A document with no such heading has `title: null` and the document
node's text is `""`.

## 4. Merging headings

`R-SEC-merge`. Two consecutive heading blocks merge into one section node when:
- they are on the same page and have the same `level`;
- the second has no number and no section keyword (§ 5);
- the vertical gap between them is at most 0.8 × the height of the first block's region;
- the merged text is at most 200 characters.

The section's text is the two texts joined by `"\n"`, and the node gets flag `merged_heading`. A third
heading may merge into the result under the same rules.

## 5. The section tree

**Keys.** Each heading gets a key:
- **keyword** headings start with `Part`, `Chapter`, `Title`, `Book`, `Appendix`, `Annex`,
  `Schedule`, `Exhibit` or `Attachment` (rank 0), `Article` (rank 1), or `Section` or `§` (rank 2),
  followed by a number, a letter or a Roman numeral. The match is case-insensitive.
- **numbered** headings carry inkgrid's `number` (`1`, `1.2`, `A.`). Rank is 2 + the number of dotted
  parts, so `1` is 3 and `1.2` is 4. A lettered number (`A.`) ranks 3.
- **plain** headings have neither.

**Stack.** Walk content blocks in reading order with a stack of open sections; the document is the
root. For each heading H, pop the stack top T while `closes(T, H)`, then push H as T's child.
`closes(T, H)` is true when:

| T \ H | keyed H | plain H |
|---|---|---|
| **numbered T, numbered H** | T's number is **not** a proper prefix of H's number | — |
| **keyed T (other pairs)** | `T.rank >= H.rank` | `T.level >= H.level` |
| **plain T** | `T.level >= H.level` | `T.level > H.level`, or `T.level == H.level` and T already contains a non-heading block |

Read the bottom-right cell this way: two plain headings of equal size in a row nest (the first is a
banner over the second); once the first has content, the next equal heading is its sibling. This
follows FeeLedger's measured rule (B § 7).

Every non-heading content block becomes a child of the stack top.

**Depth.** The document is 0; a section's depth is its parent's + 1; a part's depth is its section's
+ 1.

## 6. Parts

Each content block that is not a heading becomes one node:

| inkgrid kind | node kind | extra |
|---|---|---|
| `paragraph` | `paragraph` | — |
| `list_item` | `list_item` | `marker` = the printed label |
| `footnote` | `note` | `marker` = the label |
| `definition` | `definition` | — (the term is linked in spec 04) |
| `table` | `table` | `table` (below) |

**Table cells** (`R-SEC-cells`). For each cell:
- `is_header` is true when the cell's row is a header row (`row < header_rows`) or a banner row.
- `header_path` (non-header cells only): the texts of the header cells whose column range overlaps the
  cell's, top row first, non-empty, with consecutive repeats removed. Carried header cells count.
- `row_labels` (non-header cells only): the text of the nearest banner row above the cell (if any),
  then the non-empty texts of cells in the same row to its left that contain a letter.
- A table with `header_rows == 0` gets flag `header_not_found`.

## 7. Edges from inkgrid

| rule | edge | from inkgrid |
|---|---|---|
| `R-SEC-contains` | `contains` | the tree in § 5 |
| `R-INK-continues` | `continues`, child → parent | `links[kind=continuation]` |
| `R-INK-note` | `cites_note`, caller → note | `links[kind=footnote_call, status=resolved]` |

A footnote call's evidence is the marker in the caller's text. A `superscript` call uses the aligned
superscript word whose text equals the label. A `parenthetical` call uses the first `(label)`. A `named`
call uses the first "note N" or "footnote N". When none is found, the evidence is null. A call made from
a table cell carries the cell as the edge's `anchor`.

An `unresolved` call adds flag `note_not_found` and an `Unresolved{kind: "note"}` entry to the caller.
A `rejected` call is ignored: inkgrid decided it is not a call. A call whose caller is set aside is
ignored too.

## 8. Flags from inkgrid

- `hidden_text`: any of the node's words is hidden. The node lists the hidden words' spans in
  `hidden_spans`, which the agent layer strips from prompts.
- `text_defect`: the verifier reported a defect on one of the node's blocks; `detail` names the code.
  Reason `text_defect` is critical (tier D).
- inkgrid's document-level findings pass through to `graph.findings` unchanged.

## 9. Page geometry

For each page, a list of `{node, start, end, bbox}` for every aligned content word: the viewer draws
evidence spans from it. Set-aside words are listed with `node: null`. Stored beside the graph, not
inside it (spec 08).

## 10. Test cases

Alignment (adapter, on real inkgrid output from synthetic PDFs):
- T-ST-1 Every word of a paragraph aligns, and `text[start:end]` equals the word's text.
- T-ST-2 A hyphen-joined word aligns without its trailing hyphen.
- T-ST-3 Table words align inside the table text.
- T-ST-4 A block read from a PDF with hidden text has those words flagged `hidden`.

Set-aside:
- T-ST-5 Furniture blocks are set aside with `R-SET-furniture`, and nothing else is.
- T-ST-6 Five consecutive lines ending in page numbers after a "Contents" heading are set aside, with
  the heading.
- T-ST-7 Two TOC lines after "Table of Contents" are set aside; two TOC lines with no such heading are
  not.
- T-ST-8 A run with a modal verb ("Members must pay 5") is not a TOC.
- T-ST-9 Keep-guard: a numbered body list whose numbers are heading numbers, after a 40-word paragraph,
  is not set aside.

Title and merge:
- T-ST-10 The largest heading on page 1 becomes the document's text; a repeat on page 2 opens no section.
- T-ST-11 No heading on page 1: the title is null and the document's text is `""`.
- T-ST-12 Two same-level headings on adjacent lines merge with `"\n"` and flag `merged_heading`.
- T-ST-13 A numbered second heading, a different level, a different page or a wide gap does not merge.

Section tree (literal heading sequences → parents):
- T-ST-14 `1`, `1.1`, `1.2`, `2`, `2.1` nest by prefix.
- T-ST-15 `2.1` after `1.2` with no `2` heading becomes a child of the document, not of `1`.
- T-ST-16 `Part 1`, `1`, `2`, `Part 2`, `3`: the numbered sections nest under their part.
- T-ST-17 `Appendix A` after `3.2` closes back to the document.
- T-ST-18 A plain heading of smaller type nests under a numbered one; a plain heading of equal or larger
  type closes it.
- T-ST-19 Two equal plain headings in a row nest; after content, the next equal heading is a sibling.
- T-ST-20 Content before any heading is a child of the document.
- T-ST-21 (property) For any sequence of headings and paragraphs: every block is in exactly one place,
  the `contains` edges form a tree rooted at the document, reading order is preserved within each
  parent, and depth equals tree depth.

Parts and tables:
- T-ST-22 Each kind maps to its node kind; list items and notes keep their markers.
- T-ST-23 A 2-row-header table gives a value cell its two header texts, top first.
- T-ST-24 A spanning header covers every column it spans.
- T-ST-25 Row labels take the nearest banner row and the lettered cells to the left; numeric cells to the
  left are not labels.
- T-ST-26 `header_rows == 0` gives flag `header_not_found`.

Edges and flags:
- T-ST-27 A continuation link gives a `continues` edge from child to parent.
- T-ST-28 A resolved superscript call gives `cites_note` with the marker's span as evidence.
- T-ST-29 A call from a table cell carries the cell anchor.
- T-ST-30 An unresolved call flags `note_not_found` and lists the label; a rejected call adds nothing.
- T-ST-31 A verifier defect on a block flags `text_defect` on its node.
- T-ST-32 (property, G4) Every block id appears in exactly one node's `source.blocks` or in exactly one
  set-aside entry.
