# 04 · Link: the deterministic resolvers

The `link_rules` stage is pure. It adds term and external nodes and the `defines`, `uses_term`,
`refers_to`, `cites_external`, `overrides`, `qualifies` and `governs` edges that the text states in so
many words. It generalises FeeLedger's S9 (B § 10–12): forward, named and inverse footnote resolution
already happened in inkgrid; term, section, caption, positional and precedence resolution happen here.

Rules run in this order: definitions and terms (§ 2–3), citations (§ 4), internal references (§ 5),
identifiers (§ 6), precedence (§ 7), lead-ins (§ 8). Each edge is built with `Edge.make`, which derives
its id, so a resolver that fires twice adds one edge.

**Evidence side.** An edge's evidence is the span of text that licenses it. It sits in the source node
except for precedence language printed in the part that yields ("subject to Section 5", "except as
provided in Section 5"); those edges carry `evidence_on: "target"`. Spec 01 § 7 invariant 6 checks the
span against whichever node `evidence_on` names.

## 1. Sentences

A sentence boundary is a `.`, `;`, `?` or `!` followed by whitespace and an uppercase letter or `(`,
except after a known abbreviation (`e.g.`, `i.e.`, `etc.`, `No.`, `Sec.`, `Fig.`, `U.S.`, `Inc.`,
`Ltd.`, `vs.`, `cf.`) or a single capital initial. Sentences give windows for § 7 and § 8; every
offset is into the node's original text.

## 2. Definitions

`find_definitions(text) → [DefinitionHit{term: Span, cue: Span, shape}]`, shared with spec 03's
`R-ROLE-definition`. Shapes, each a rule:

| rule | shape | example | term |
|---|---|---|---|
| `R-TERM-glossary` | a `definition` block | inkgrid's `term` / `body` | the block's `term`, at the start of its text |
| `R-TERM-quoted` | a quoted term + `means`, `shall mean`, `has the meaning`, `refers to`, `is defined as`, `includes` | `"Micro entity" means …` | the quoted words |
| `R-TERM-bare` | at the start of the text, 1–6 Title Case or ALL CAPS words + `means`, `shall mean`, `is defined as` | `Business Day means …` | those words |
| `R-TERM-the-term` | `the term "X"` / `the terms "X"` | `the term "Member"` | X |
| `R-TERM-parenthetical` | `(the "X")`, `("X")`, `(hereinafter "X")`, `(hereinafter referred to as "X")`, `(each a "X")`, `(an "X")` | `the agreement (the "Agreement")` | X |
| `R-TERM-acronym` | `Long Form (ACR)` where ACR spells the long form's initials (a word that is itself an acronym of ≤ 4 capitals contributes all its letters; `of`, `and`, `for`, `the`, `in`, `on`, `&` contribute none) | `AI Risk Management Framework (AI RMF)` | the acronym; the long form is an alias |

Both straight and curly quotes count. A term is 1–80 characters, at most 8 words. These are never
terms: a single character, or one of `A`, `An`, `The`, `This`, `That`, `It`, `I`, `We`, `You`.

## 3. Terms and their uses

**Term key.** A multi-word term's key is its casefolded, whitespace-folded form. A one-word term or an
acronym keys as printed (case-sensitive). The term node's id comes from the key (spec 01 § 5); its text
and label are the term as printed at its first definition.

**`defines`.** One edge from each defining node to the term, evidence = the term's span there,
`R-TERM-<shape>`. A term defined by more than one node gets one edge per definer and flag
`multiple_definitions` with the count.

**`uses_term`** (`R-TERM-use`). Every content node is scanned for every term's forms:
- the term, its regular plural (`+s`, `+es`, `y → ies`) and possessive (`'s`, `’s`);
- multi-word terms match case-insensitively with any whitespace between words;
- one-word terms and acronyms match case-sensitively;
- all matches are on word boundaries;
- longer terms claim their characters first, so `Micro Entity Fee` hides the `Micro Entity` inside it;
- an acronym's alias long form counts as a use of the acronym's term.

One edge per (node, term), evidence = the first unclaimed occurrence, label = the form matched. A node
that defines a term never gets `uses_term` to it. Set-aside text is never scanned.

## 4. Citations to outside sources

`find_citations(text) → [CitationHit{span, key, rule}]`, shared with spec 03's
`R-ROLE-external_pointer`. Each match becomes (or reuses) an `external` node keyed by its normalised
form and a `cites_external` edge (evidence = the match, label = the printed citation).

| rule | matches | normalised key |
|---|---|---|
| `R-CITE-cfr` | `37 CFR 1.27`, `37 C.F.R. § 1.16(a)`, `12 CFR Part 1026` | `37 cfr 1.27` (no `§`, no `part`) |
| `R-CITE-usc` | `35 U.S.C. 41`, `15 USC § 78c(a)` | `35 usc 41` |
| `R-CITE-eu` | `Regulation (EU) 2016/679`, `Directive 2014/65/EU` | folded, lowercase |
| `R-CITE-publaw` | `Pub. L. 112-29`, `Public Law 112-29` | `public law 112-29` |
| `R-CITE-act` | `the Leahy-Smith America Invents Act`, `the Securities Exchange Act of 1934` (one or more capitalised words before `Act`, not only `This`/`That`/`Such`/`Said`/`The`) | folded, lowercase, without a leading `the` |
| `R-CITE-named` | `of the Exchange Rules`, `of the FINRA By-Laws`: `of the` + up to 8 capitalised words ending in Rules, Rulebook, Code, Regulation(s), Directive, By-laws, Agreement, Handbook, Guide, Manual, Standard or Policy | the named document, folded, lowercase |
| `R-CITE-standard` | `ISO/IEC 27001:2022`, `NIST SP 800-53`, `NIST AI 100-1`, `FIPS 140-3`, `RFC 8118`, `IEEE 754` | folded, lowercase |
| `R-CITE-url` | `https://…`, `doi:10.…`, a bare DOI `10.NNNN/…` | the URL or DOI without a trailing slash or punctuation |

Overlapping matches keep the longest. A document never cites itself: a citation whose key equals the
document title's folded key is dropped.

## 5. Internal references

**Section references** (`R-REF-section`). A reference word (`Section(s)`, `Sec.`, `Clause(s)`,
`Article(s)`, `Chapter(s)`, `Part(s)`, `Paragraph(s)`, `Appendix`, `Appendices`, `Annex(es)`,
`Schedule(s)`, `Exhibit(s)`, `Rule(s)`, `§`, `§§`) followed by one or more refs. A ref is `4`, `4.2`,
`4.2(a)(i)`, `A`, `B.3` or a Roman numeral. Refs are joined by `,`, `and`, `or`, `to`, `through`, `-`
or `–`. A range expands over the section numbers the tree knows between its ends, inclusive.

The section index maps (counter, number) to section nodes, from spec 02 § 5's keys: keyword headings
under their keyword (`appendix` covers annex, schedule and exhibit), numbered headings under `num`.
A ref resolves by its own keyword first, then by `num`. A ref with parentheses that is not itself a
heading resolves to the deepest heading whose number is a prefix (`1.16(a)` → `1.16`), with the full
ref as the label.

A ref is **external, not internal**, when the words after it, within its sentence, are `of`, `in` or
`under` + optional `the` + a citation from § 4 (`Section 10(b) of the Securities Exchange Act`). Then
the citation's `cites_external` edge carries the whole phrase as its label, and no `refers_to` is made.

A ref that resolves to the node's own section, written `this Section …`, is skipped. A ref that does
not resolve adds flag `reference_unresolved` and an `Unresolved{kind: "reference", text, span}` to
the node. A resolved ref adds `refers_to` (evidence = the ref, label = the printed ref).

**Caption references** (`R-REF-caption`). `Table 3`, `Figure 2`, `Fig. 2`, `Exhibit A`, `Chart 1`
resolve through a caption index: a heading or paragraph whose text starts with that phrase marks a
caption, and the target is the first table within the next two content nodes, else the caption node
itself. Unresolved as above.

**Positional references** (`R-REF-positional`, weak). `the following/preceding/above/below table`
(also schedule, list, chart, figure) and `the table below/above` resolve to the nearest table (or list
item, for `list`) in that direction within four content nodes in the same section. A miss adds nothing:
positional words are too common to flag.

## 6. Identifiers in tables

`R-REF-identifier`. Some tables print a key column: rule numbers, fee codes, clause ids. A column is a
key column when it is one of the first two, or its header text contains `code`, `id`, `no.`,
`number`, `§`, `rule`, `section`, `article`, `clause` or `ref`, **and** at least 60% of its body cells
are identifiers. An identifier is at most 20 characters, contains a digit, contains a letter or one of
`.`, `-`, `/`, `(`, and is not a money amount (`1,234.56`) or a bare integer.

Every content node's text is then scanned for identifiers on word boundaries. A hit outside the table
that indexes it adds `refers_to` from the node to that table, label = the identifier. A hit inside a
table cell adds the cell as the edge's anchor. A hit inside the indexing table itself adds nothing, since
an edge cannot loop.

## 7. Precedence

`R-PREC-*`. Inside one sentence, a cue followed by a resolved section or caption reference to T:

| rule | cue | edge | evidence on |
|---|---|---|---|
| `R-PREC-notwithstanding` | `notwithstanding` | `overrides`: this → T | source |
| `R-PREC-supersedes` | `supersedes`, `replaces`, `in lieu of`, `in place of`, `takes precedence over`, `prevails over`, `overrides` | `overrides`: this → T | source |
| `R-PREC-except-as` | `except as (otherwise) provided/set out/set forth/stated/specified/described in/by/under` | `overrides`: T → this | target |
| `R-PREC-unless-otherwise` | `unless otherwise provided/stated/specified in/by/under` | `overrides`: T → this | target |
| `R-PREC-subject-to` | `subject to` | `qualifies`: T → this | target |

The evidence runs from the cue's first character to the reference's last. A reference consumed by a
precedence rule makes no plain `refers_to`.

## 8. Lead-ins

`R-GOV-leadin`. A paragraph or list item whose text ends with `:`, `as follows`, `as follows:` or `the
following:` governs what follows it directly in the same section: the next content node when it is a
table, or each list item in the unbroken run that starts there. Evidence is the node's last sentence.

## 9. Test cases

Definitions and terms:
- T-LK-1 Each definition shape in § 2 finds its term with the right span; curly and straight quotes
  both work.
- T-LK-2 `Artificial Intelligence (AI)` and `AI Risk Management Framework (AI RMF)` define acronyms;
  `Annual Report (XYZ)` does not.
- T-LK-3 A glossary `definition` block defines its `term`.
- T-LK-4 `uses_term`: `Business Day` matches `business days` (case and plural); `Member` matches
  `Members` and `Member's` but not `member`.
- T-LK-5 Longest first: `Micro Entity Fee` used in a node yields a use of that term, not of
  `Micro Entity`.
- T-LK-6 The defining node gets `defines`, not `uses_term`; another node using the term gets
  `uses_term` with the first occurrence as evidence.
- T-LK-7 Two definers of one term: one term node, two `defines` edges, flag `multiple_definitions` 2.
- T-LK-8 Stop terms (`The`, `A`, single characters) never become terms.

Citations:
- T-LK-9 Each row in § 4 matches its example and keys it; `37 CFR 1.27` and `37 C.F.R. § 1.27` share
  one external node.
- T-LK-10 `This Act` alone is not a citation; `the Patent Act` is.
- T-LK-11 A URL loses its trailing period.

Internal references:
- T-LK-12 `Section 4.2` resolves to the `4.2` heading; `Sections 4.2 and 4.3` to both; `Sections
  4.2–4.4` to the three that exist.
- T-LK-13 `1.16(a)` resolves to `1.16` with label `1.16(a)`.
- T-LK-14 `Section 10(b) of the Securities Exchange Act` makes `cites_external`, not `refers_to`.
- T-LK-15 `Section 9` with no such heading flags `reference_unresolved` and lists it.
- T-LK-16 `this Section 4.2` inside 4.2 makes nothing.
- T-LK-17 `Table 3` resolves to the table after the `Table 3: …` caption.
- T-LK-18 `the table below` resolves to the next table within four nodes, as a weak rule; with no table
  in reach it adds nothing.

Identifiers:
- T-LK-19 A table whose first column holds `1.16(a)`, `1.16(t)`, `1.17(b)` is a key table; a paragraph
  printing `1.16(t)` refers to it with label `1.16(t)`.
- T-LK-20 Money amounts, bare integers and the indexing table itself make no identifier edge.

Precedence and lead-ins:
- T-LK-21 `Notwithstanding Section 4, …` → `overrides` this → §4, evidence on source.
- T-LK-22 `Except as provided in Section 5, …` → `overrides` §5 → this, evidence on target.
- T-LK-23 `Subject to Section 3, …` → `qualifies` §3 → this; no plain `refers_to` for that ref.
- T-LK-24 A cue and a reference in different sentences make no precedence edge.
- T-LK-25 `The fees are as follows:` followed by a table governs the table; followed by three list items
  governs all three; followed by a paragraph governs nothing.
- T-LK-26 (property) Every edge this stage makes passes spec 01 § 7 invariant 6 against the node its
  `evidence_on` names, and no edge loops.
