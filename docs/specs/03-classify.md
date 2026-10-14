# 03 · Classify: what each part does

A part's **kind** is its shape (paragraph, table, note). Its **roles** are what it does: oblige,
permit, define, compute, illustrate. Roles are multi-label and closed (spec 01 § 4). FeeLedger's fee
taxonomy (`fee_schedule`, `calculation_rule`, `footnote_fee_bearing` …) is generalised here; R-7's
"measure vs apply" split survives as `method` vs `computation`.

## 1. Taxonomy

| role | the part… | decided by |
|---|---|---|
| `obligation` | requires something (shall, must, is required to) | rule |
| `permission` | allows something (may, is entitled to) | rule (weak for bare "may") |
| `prohibition` | forbids something (shall not, may not, must not) | rule |
| `condition` | sets when or to whom something applies (if, provided that, eligible) | rule (weak for bare "if") |
| `exception` | carves something out (except, notwithstanding, does not apply) | rule |
| `definition` | defines a term | rule (spec 04 § 2's detector) |
| `computation` | says how figures are applied, combined or derived | rule |
| `method` | says how something is measured, aggregated or performed | rule |
| `procedure` | gives ordered steps | rule, agent |
| `temporal` | states dates, deadlines, validity windows | rule |
| `quantitative` | states figures: amounts, rates, percentages, measures | rule |
| `scope` | says what a document or section covers | rule, agent |
| `convention` | declares a notation, abbreviation or symbol | rule |
| `example` | illustrates | rule (weak for "e.g."), agent |
| `external_pointer` | sends the reader to another document | rule (spec 04 § 4's detector) |
| `administrative` | contact details, revision history, copyright, document control | rule |
| `summary` | sits under an abstract, summary or overview heading | rule |
| `claim` | states a finding, result or conclusion | agent only |

Roles apply to `paragraph`, `list_item`, `note` and `definition` nodes. A `table` gets only
`quantitative` and `temporal`. Sections, terms and externals get none.

## 2. Rules

Each rule is a function `text → Match | None` over the node's own text, so its evidence is a verbatim
span (`Span(start, end, text[start:end])`) of the cue that fired. One assignment per role per node;
the first match in reading order is the evidence. Patterns are case-insensitive unless noted.

| rule | role | fires on | weak? |
|---|---|---|---|
| `R-ROLE-obligation` | obligation | `shall`, `must`, `is/are required to`, `is/are obliged to`, `has/have to`, `is/are responsible for`; not when followed by `not`; not `shall mean`, `shall include`, `shall have the meaning` | no |
| `R-ROLE-prohibition` | prohibition | `shall not`, `must not`, `may not`, `cannot`, `is/are prohibited`, `is/are not permitted`, `is/are forbidden` | no |
| `R-ROLE-permission` | permission | `is/are permitted to`, `is/are entitled to`, `is/are allowed to`; or `may` + a word, unless the word is `be`, `not`, `vary`, `differ`, `change`, `include`, `also`, `have`, `result`, `occur` or `apply` | `may` is weak |
| `R-ROLE-condition` | condition | `provided that`, `on condition that`, `subject to`, `in the event of/that`, `only if`, `eligible`, `eligibility`, `qualify/qualifies/qualified`, `threshold`, `at least` + a number; or `if` | `if` is weak |
| `R-ROLE-exception` | exception | `except`, `excluding`, `other than`, `notwithstanding`, `save as/that/for`, `unless`, `does/do/shall/will not apply`, `is/are exempt`, `exemption`, `with the exception of` | no |
| `R-ROLE-definition` | definition | a `definition` block, or spec 04 § 2 finds a definition in the text | no |
| `R-ROLE-computation` | computation | `calculated`, `computed`, `calculation`, `multiplied by`, `divided by`, `the sum/total of`, `the greater/lesser/higher/lower of`, `pro rata`, `percent(age) of`, `per cent of`, `formula`, `is equal to` | no |
| `R-ROLE-method` | method | `measured`, `aggregated`, `averaged`, `average daily`, `on a daily/monthly/quarterly/annual basis`, `billing period`, `determined by/on/using`, `methodology`, `is assessed on/by` | no |
| `R-ROLE-procedure` | procedure | `step` + a number, `the following steps`; or a list item with a numeric or letter label whose text opens with one of: submit, complete, enter, select, click, open, attach, file, sign, send, provide, review, ensure, verify, record, notify (case-sensitive capital) | no |
| `R-ROLE-temporal` | temporal | a date (`January 19, 2025`, `19 January 2025`, `2025-01-19`, `1/19/2025`), or `effective`, `expire(s)`, `no later than`, `within N days/months/years/business days`, `deadline`, `commencing` | no |
| `R-ROLE-quantitative` | quantitative | a currency amount (`$`, `€`, `£`, `¥` or an ISO code before or after a number), a percentage (`%`, `per cent`, `percent`), basis points (`bp`, `bps`, `basis point(s)`), or a number with a unit of measure | no |
| `R-ROLE-scope` | scope | `applies/apply/shall apply to`, `applicable to`, `this section/part/chapter/schedule/document/policy/agreement/guide/standard applies/covers/governs/sets out`, `unless otherwise stated/specified/indicated/noted`, `for the purpose(s) of this` | no |
| `R-ROLE-convention` | convention | `denoted by`, `denotes`, `is/are indicated by`, `indicates`, `is/are shown in/as`, `figures in brackets/parentheses`, `abbreviated as`, `referred to as`, `hereinafter` | no |
| `R-ROLE-example` | example | `for example`, `for instance`, `worked example`, `to illustrate`, `illustrative`, `example` + optional number + `:`; or `e.g.` | `e.g.` is weak |
| `R-ROLE-external_pointer` | external_pointer | spec 04 § 4 finds a citation, or `available at`, `as set out in the`, `published on/at`, a URL | no |
| `R-ROLE-administrative` | administrative | an email address, `tel`/`phone`/`fax` + a number, `contact us`, `enquiries`, `inquiries`, `revision history`, `document control`, `last revised/updated`, `copyright`, `all rights reserved`, `©` | no |
| `R-ROLE-summary` | summary | an ancestor section's title, without its number, is `abstract`, `summary`, `executive summary`, `overview`, `key findings`, `key points` or `highlights`; evidence is null | no |

Every pattern is anchored on word boundaries, so `must` never fires inside `mustard`.

## 3. Confidence of a role

A rule-made role has basis `explicit`, maker `{actor: "rule", id: <rule id>}` and reason
`explicit_rule` (info, tier A), or `weak_rule` (flag, tier B) when only a weak cue fired. Agent-made
roles are scored in spec 05 § 7.

## 4. The residual

The residual is every `paragraph`, `list_item` or `note` node with no role after the rules, whose
text has at least 40 characters once hidden spans are removed. The `classify_agent` stage receives it,
in reading order. Everything else is final for this stage.

## 5. Test cases

Pass:
- T-CL-1 "Members must file the form." → obligation, evidence `must`.
- T-CL-2 "Members must not file twice." → prohibition, not obligation.
- T-CL-3 "'Business Day' shall mean any day…" → definition, not obligation.
- T-CL-4 "Applicants may request a refund." → permission (weak, tier B); "Results may vary." → none.
- T-CL-5 "Provided that the applicant qualifies…" → condition (strong); "If filed late…" → condition
  (weak).
- T-CL-6 "Notwithstanding Section 4, …" → exception.
- T-CL-7 "The fee is calculated as the greater of…" → computation.
- T-CL-8 "Volume is measured on a monthly basis." → method.
- T-CL-9 A list item `1.` "Submit the form." → procedure; a list item `•` "Submit the form." → none.
- T-CL-10 "Effective January 19, 2025" → temporal; "Section 2.1.10" → not temporal.
- T-CL-11 "$350.00", "0.13 EUR", "2.5%", "15 bps", "3 basis points" → quantitative each.
- T-CL-12 A table with a numeric body cell → quantitative; a table with words only → none.
- T-CL-13 "This section applies to all members." → scope.
- T-CL-14 "Figures in parentheses denote rebates." → convention.
- T-CL-15 "For example, a member that…" → example (strong); "(e.g., a bank)" → example (weak).
- T-CL-16 "See 37 CFR 1.27." → external_pointer.
- T-CL-17 "Contact fees@example.com" → administrative.
- T-CL-18 A paragraph under "Executive Summary" → summary with null evidence.
- T-CL-19 One sentence firing four rules gets four roles, each with its own cue as evidence.
- T-CL-20 (property) Every rule-made role's evidence satisfies `text[start:end] == quote`.
- T-CL-21 The residual holds untyped paragraphs of 40+ characters and nothing else, in reading order.

Fail / negative:
- T-CL-22 "mustard", "mayor", "shallow", "iffy" fire nothing (word boundaries).
- T-CL-23 A section, term or external node gets no roles.
- T-CL-24 A 39-character untyped paragraph is not residual; a paragraph that is all hidden text is not
  residual.
