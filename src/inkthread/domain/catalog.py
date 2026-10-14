"""Every rule and agent task the pipeline can name, with one line on what it does.

`why` (spec 06 § 6) prints these. A test checks that every rule id the code uses appears here.
"""

from __future__ import annotations

from collections.abc import Mapping

RULES: Mapping[str, str] = {
    "inkgrid": "read from the PDF's text layer by inkgrid",
    "R-SET-furniture": "a running header, footer or page number repeated across pages",
    "R-SET-toc": "a table of contents: lines that end in page numbers",
    "R-SEC-title": "the largest heading on page 1 is the document's title",
    "R-SEC-merge": "two heading lines of the same size, one under the other, are one heading",
    "R-SEC-contains": "a section contains the blocks under its heading",
    "R-SEC-part": "a content block becomes a part of the graph",
    "R-SEC-cells": "each table cell carries its column headers and row labels",
    "R-INK-continues": "inkgrid joined a table continued across a page break",
    "R-INK-note": "inkgrid resolved a footnote call to its note",
    "R-INK-flags": "inkgrid marked hidden text or its verifier found a defect",
    "R-TERM-glossary": "a glossary block defines the term at the start of its text",
    "R-TERM-quoted": "a quoted term followed by means, shall mean or is defined as",
    "R-TERM-bare": "a capitalised term at the start of the text followed by means or is defined as",
    "R-TERM-the-term": 'the term "X" defines X',
    "R-TERM-parenthetical": 'a parenthetical (the "X") names a term',
    "R-TERM-acronym": "a long form followed by its acronym in parentheses defines the acronym",
    "R-TERM-use": "a part prints a defined term",
    "R-CITE-cfr": "a Code of Federal Regulations citation",
    "R-CITE-usc": "a United States Code citation",
    "R-CITE-eu": "an EU regulation, directive or decision",
    "R-CITE-publaw": "a US public law",
    "R-CITE-act": "a named Act",
    "R-CITE-named": "a named outside rules, code, agreement or policy",
    "R-CITE-standard": "an ISO, IEC, NIST, FIPS, RFC or IEEE standard",
    "R-CITE-url": "a URL or DOI",
    "R-REF-section": "a section, article, part or appendix reference resolved to its heading",
    "R-REF-caption": "a table or figure reference resolved through its caption",
    "R-REF-positional": "the table below or above, resolved to the nearest one (weak)",
    "R-REF-identifier": "an identifier printed in another table's key column",
    "R-PREC-notwithstanding": "notwithstanding a reference: this part prevails over it",
    "R-PREC-supersedes": "supersedes, replaces or takes precedence over a reference",
    "R-PREC-except-as": "except as provided in a reference: that part prevails",
    "R-PREC-unless-otherwise": "unless otherwise provided in a reference: that part prevails",
    "R-PREC-subject-to": "subject to a reference: that part qualifies this one",
    "R-GOV-leadin": "a part ending in a colon or as follows governs what follows it",
    "R-ROLE-obligation": "a modal of obligation: shall, must, is required to",
    "R-ROLE-permission": "is permitted or entitled to, or may",
    "R-ROLE-prohibition": "shall not, must not, may not, is prohibited",
    "R-ROLE-condition": "provided that, subject to, eligible, or if",
    "R-ROLE-exception": "except, unless, notwithstanding, does not apply",
    "R-ROLE-definition": "the text defines a term",
    "R-ROLE-computation": "how figures are calculated or combined",
    "R-ROLE-method": "how something is measured or aggregated",
    "R-ROLE-procedure": "ordered steps",
    "R-ROLE-temporal": "a date, deadline or effective period",
    "R-ROLE-quantitative": "an amount, rate, percentage or measure",
    "R-ROLE-scope": "what a document or section applies to",
    "R-ROLE-convention": "a notation or abbreviation declared",
    "R-ROLE-example": "an illustration: for example, e.g.",
    "R-ROLE-external_pointer": "sends the reader to another document",
    "R-ROLE-administrative": "contact details, copyright or revision history",
    "R-ROLE-summary": "sits under a summary or overview heading",
}

TASKS: Mapping[str, str] = {
    "A-classify": "a model typed a part the rules left untyped, quoting the words that say so",
    "A-relate": "a model linked a part to what it qualifies, governs or illustrates",
    "A-verify": "a second model judged the first model's claim",
}
