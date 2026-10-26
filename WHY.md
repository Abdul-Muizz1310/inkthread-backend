# Why inkthread

## The obvious version

Split the PDF into chunks, ask a model for entity–relation triples, merge them into a graph. It demos
well. Every node is a model-written summary, provenance stops at the chunk, and the run is never the
same twice.

## Why I built it differently

FeeLedger taught me that in a fee schedule a number is almost never self-describing. Its currency is in
a banner, its unit in a header on the previous page, and a footnote may replace it. The meaning lives in
the structure, so inkthread builds the structure first, from inkgrid's reading, with rules that name
themselves. Free models only see what the rules left open. Their answers are ids, closed labels and
quotes; a quote counts only when it snaps to the page's own words, and a second model judges each claim.
A hash-chained op log must explain every node and thread before a graph is stored, and recorded answers
make every graph replay byte for byte.

Each job is a Langfuse trace shaped like the run, down to every model attempt and what it cost. A trace
is kept for weeks and an upload is not (DR-0029), so an upload's trace carries the shape, the models,
the tokens and the failures, but none of the document's words: one export hook strips them from every
span that is not a sample's, fail-closed.

## What I'd change

The rules over-link: a defined term that is also a common capitalised word picks up false uses. I would
add a small hand-labelled edge set and measure precision before tuning, and give term matching a scope
model (the definition that governs a use, not just any definition).
