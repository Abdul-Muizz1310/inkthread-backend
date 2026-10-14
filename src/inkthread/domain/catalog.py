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
}

TASKS: Mapping[str, str] = {
    "A-classify": "a model typed a part the rules left untyped, quoting the words that say so",
    "A-relate": "a model linked a part to what it qualifies, governs or illustrates",
    "A-verify": "a second model judged the first model's claim",
}
