# Known input-format gaps

`[documented]` This register describes five input limits of the
`itr-filing-copilot` skill. It records the evidence boundary and current parser
behaviour; it does not expand the formats the skill supports.

`[observed 2026-07-30, repository state]` The behaviours below were checked in
the current parser code and with the named local probes. No real tax document is
stored in this repository.

| Input | Current support boundary |
|---|---|
| Portal-generated PDFs with unmapped fonts | `[observed 2026-07-30, 13 portal downloads]` Refused after the Java envelope opens. `[observed 2026-07-31]` Cause now in doubt — see §1; one file refused the same way was Form-XObject-wrapped, not a font problem |
| Filed ITR-4 JSON | `[observed 2026-07-30, synthetic finite-number and ITR-2/3/4 probes]` Required leaves must be finite numbers; non-zero or indeterminate unread schedules flag |
| AIS JSON download | `[observed 2026-07-30, local non-PDF JSON probe]` Not parsed; non-PDF input is refused |
| A broker layout other than Zerodha | `[observed 2026-07-30, synthetic brand table and Schedule 112A probes]` Detected-but-unvalidated brands and unknown sources carry `UNVERIFIED LAYOUT`; only Zerodha is validated; real second-broker correctness is `[UNVERIFIED]` |
| Zerodha Tax P&L supplied as PDF | `[observed 2026-07-30, committed PDF probe]` Refused by the workbook reader |

## 1. Portal PDF font encoding

> `[observed 2026-07-31, one real employer-issued Form 16]` **The font-encoding
> attribution below is in doubt and the 13 downloads have not been re-tested.**
> A Form 16 was refused by the same text-decoding gate, with the same message
> naming font encoding, and the cause was not fonts. Its pages drew a
> page-number footer and invoked a Form XObject holding the entire certificate;
> `read_pdf.py` read only `/Contents` and recovered the four characters `1of9`
> across nine pages. Following `Do` into Form XObjects — now implemented, with
> `xobject_wrapped`, `xobject_nested` and `xobject_cycle` fixtures — reads the
> same file completely: 9 pages, 15,130 non-whitespace characters, and its
> stated salary and TDS totals then tied exactly to the AIS figures.
>
> `[inferred]` Portal exports may well be produced the same way — composing a
> page from reusable form objects is ordinary practice for the writers used in
> this domain — but that is reasoning from one employer-issued Form 16 and says
> nothing about how the untested portal downloads were produced. `[UNVERIFIED]`
> Whether any of the 13 is XObject-wrapped is unknown. Either way,
> **re-run the 13 downloads before doing any CMap work**, because the gate
> cannot tell the two causes apart. If they are wrapped
> too, this section closes without touching font handling. `[UNVERIFIED]`
> Whether any of the 13 is XObject-wrapped is unknown: they were not available
> when the walk was written.

**Missing:** `[observed 2026-07-30, 13 portal downloads]` `read_pdf.py` could not
produce readable text from the portal downloads in the observed set. `[inferred]`
The cause was recorded as font encoding; that diagnosis was made before the
XObject gap was known, and the gate cannot distinguish the two.

**What would unblock it:** `[inferred]` First, re-run the observed set against
the Form XObject walk. Only if refusals survive that does ToUnicode CMap and
font-encoding support become the next step, backed by an identifier-free
regression fixture reproducing the observed encoding.

**What happens today:** `[observed 2026-07-30, 13 portal downloads]` Six
acknowledgements, five Form 168 exports and two ITR-3 previews all unwrapped from
their Java envelope, then all 13 were refused by the text-decoding gate. One
refusal read `could not decode text from 81 of 81 pages`. No portal download in
that observed set was readable by the skill.

`[observed 2026-07-30, read_pdf.py and parser tests]` The refusal is fail-closed:
the reader returns no partial text when referenced content streams or
text-showing operators produce no readable words. The refusal names the unread
page count and says the document is incomplete rather than empty.

## 2. ITR-4 filed-return JSON

**Missing:** `[UNVERIFIED]` No real filed ITR-4 JSON has been inspected by this
project, so the portal's actual presumptive-income block names and shape are
unknown. `[observed 2026-07-30, parse_portal_json.py]` The parser contains no
specimen-backed mapping for the ITR-4 presumptive blocks.

**What would unblock it:** `[inferred]` Local inspection of a real filed ITR-4
JSON, followed by an identifier-free synthetic fixture covering the actual
44AD, 44ADA or 44AE shape once observed, would establish the missing evidence
without storing the real return.

**What happens today:** `[observed 2026-07-30, synthetic required-leaf table and
ITR-2/3/4 SchemaMarker probes]` Object presence, emptiness and unrelated keys no
longer stand in for readable tax figures. Every leaf feeding the payment or
aggregate-liability identities must pass the parser's existing `num()` test.
`num()` now means a finite usable number: absent and null leaves, booleans,
non-numeric strings, arrays, objects, NaN and positive or negative infinity
refuse, as does an integer outside the finite float range the parser computes
with. The message names every offending path and its value class without echoing
the value.

`[observed 2026-07-30, synthetic finite-number table]` Finite numeric values and
numeric strings remain usable: `0`, `"0"`, `"3,400"` and `3400.5` parse. Strings
such as `"NaN"`, `"inf"` and `"-Infinity"` refuse at the required-leaf boundary.
A bare `NaN` JSON token is refused at input because RFC 8259 does not permit it,
and output is serialized with non-finite values disabled before stdout or an
output file is touched. `[UNVERIFIED]` No real portal specimen establishes the
exact encoding of every required numeric leaf or whether a genuine nil return
writes zeros or omits the fields. The refusal marks the rule `[UNVERIFIED]`, asks
for an identifier-free specimen, and directs a user whose genuine return was
rejected to report a parser bug with the form and schema version only.

`[observed 2026-07-30, committed synthetic ITR-3 fixtures and unread-income
probes]` An unread schedule flags when any leaf is non-zero or indeterminate,
including null, a boolean, a non-numeric string or a container. Only a schedule
whose every leaf is a usable numeric zero stays out of the flag. Every unread
key remains listed in `schedules_not_checked`, and summary mode names that list
even when the unread schedule is proven zero. `[UNVERIFIED]` Behaviour against a
real portal ITR-4 schema, including which keys carry 44AD, 44ADA or 44AE income,
remains unknown.

**Known follow-up:** `[inferred]` An identifier-free real filed-return specimen
is needed to verify the finite numeric-leaf encodings and whether zero-valued
required fields are emitted. A separate specimen-backed mapping and exact
tests, or a specific unsupported-ITR-4 refusal until they exist, would close the
remaining presumptive-income boundary.
`[observed 2026-07-30, repository state]` Neither mapping change is implemented
here; the current parser exposes both gaps instead.

## 3. AIS JSON download

**Missing:** `[UNVERIFIED]` No real AIS JSON download or its encrypted archive
has been inspected by this project, so both container and JSON shapes are
unknown. `[observed 2026-07-30, parser code]` Only the AIS PDF has a parser path.

**What would unblock it:** `[inferred]` Local inspection of a real download,
followed by an identifier-free fixture and readers for the observed archive and
JSON shapes, would establish a testable implementation path.

**What happens today:** `[observed 2026-07-30, local non-PDF JSON probe]`
`parse_tax_docs.py` sends the input to the PDF reader and returns a structured
`does not start with %PDF` refusal. `open_ais.py` stops at the same PDF-signature
check. `[observed 2026-07-30, parse_portal_json.py]` An unknown JSON wrapper is
refused as neither a prefill nor a filed return. No AIS JSON is parsed and no
probe produced a traceback. `[UNVERIFIED]` The claim that the AIS JSON archive
uses the PDF credential has not been tested here.

## 4. Broker layouts other than Zerodha

**Missing:** `[UNVERIFIED]` No second broker's Tax P&L layout has been inspected,
so support for any non-Zerodha layout has not been validated.

`[observed 2026-07-30, two Zerodha workbooks]` Workbooks from two different
accounts had the same sheet names: `Tradewise Exits`, `Equity and Non Equity`,
`Mutual Funds`, `F&O`, `Currency`, and `Commodity`. They are two examples of one
layout, not evidence of two supported layouts.

**What would unblock it:** `[inferred]` Local inspection of another broker's Tax
P&L sheet names and header structure, followed by an identifier-free synthetic
fixture with exact bucket, row-count and gain assertions, would establish
evidence for that layout and earn its detected source label a place in
`VALIDATED_BROKER_LAYOUTS`. A file merely parsing without error is not evidence
that its layout is supported.

**What happens today:** `[observed 2026-07-30, five committed Schedule 112A CSV
fixtures and parser tests]` `parse_capital_gains.py` recognises the portal upload
template from the compound headings `Share/Unit acquired(1a)`, `Total
deductions(13) = 7 + 12`, and `Balance(14) = 6 - 13`; all five fixtures exit 2
and direct the reader to `check_112a_csv.py` instead of producing gains.
`[inferred]` Requiring all three exact normalised portal-number/formula headings
keeps the signature from firing on a genuine broker Tax P&L. `[observed
2026-07-30, synthetic brand-table and parser tests]` Brand detection remains
informational: `sources[].detected` still reports Groww, Upstox, Angel One,
INDmoney, Dhan, ICICI Direct, Kotak, HDFC Securities, Paytm Money, 5paisa, CAMS
or KFintech when its detector string is present. Only Zerodha is in the explicit
validated-layout set. Every detected-but-unvalidated brand, and a source with no
recognised brand, gets a prominent `UNVERIFIED LAYOUT` flag; affected totals are
described as heuristic matches that are not verified. A file with no recognised
rows is refused and directed to `--inspect`, and skipped sections are reported.
`[UNVERIFIED]` No output from a second broker has been checked against that
broker's stated totals.

**Known follow-up:** `[inferred]` A real-layout observation and an exact-output
fixture are the missing evidence for any additional broker claim. A source
outside `VALIDATED_BROKER_LAYOUTS` remains unverified even when a brand and rows
are recognised. The recurring pattern of safety-critical uncertainty living
outside `flags` may warrant a systemic output-schema guard, but that is broader
than this parser fix.

`[observed 2026-07-30, direct detect_source probes]` Brand detection uses bare
substrings: `Vardhan`, `Sudhan` and `Dhanraj` were each reported as `dhan`, while
headers for a Kotak or ICICI bank statement were reported as `kotak` or
`icici-direct`. The new validation boundary keeps those labels from making
figures look verified, but `sources[].detected` is still wrong. `[inferred]`
Brand detection needs a separate boundary-aware or structural fix; changing it
is outside this PR.

## 5. Zerodha Tax P&L delivered as PDF

**Missing:** `[observed 2026-07-30, maintainer inventory]` A Zerodha PDF specimen
exists, but its table layout has not been reverse-engineered. `[observed
2026-07-30, parse_capital_gains.py]` The capital-gains reader accepts workbook
and CSV inputs, not broker PDFs.

**What would unblock it:** `[inferred]` Local inspection of the specimen,
followed by an identifier-free synthetic PDF fixture with exact totals and
refusal cases, would establish the section and column mapping needed by the
existing capital-gains buckets.

**What happens today:** `[observed 2026-08-01, regression run]` Passing a PDF to
`parse_capital_gains.py` produces a structured refusal with exit code 2. The
message now names the file as a PDF, says this reader takes workbooks and CSV
only, points at the `.xlsx`/`.csv` download under Reports → Tax P&L, and warns
that converting the PDF is not a route worth trying because its tables are drawn
rather than stored. No traceback and no capital-gains result.

> `[superseded 2026-08-01]` This paragraph previously said the message reported
> the PDF as `not a valid .xlsx` and did not identify PDF as a known unsupported
> format. That was true when written and was fixed in #27; the paragraph was not
> updated with it. A known-gaps entry that describes a gap after it closes sends
> a reader to re-fix it.

## 6. Visible text dropped by the per-glyph clip test

**Missing:** `[observed 2026-07-31, one real employer-issued Form 16]`
`read_pdf.py` decides per-glyph visibility from `char_w = 0.5`, a guessed average
glyph width. Where the guess overshoots a run's true extent, the tail of a
perfectly visible run is dropped and nothing says so. That document lost 96
characters, including a run of statutory boilerplate — and fused a label into an
amount, which is the worse outcome, because a wrong figure does not look like a
gap the way a missing one does.

**What happens today:** `[observed 2026-08-01]`
`evals/fixtures/clip_drift_synthetic.pdf` reproduces it with no identifier and no
real figure: ordinary body text reads correctly, and the clipped run below it
comes back truncated. `test_parsers.py` asserts that truncation deliberately, so
a fix cannot land silently.

**What would unblock it:** `[inferred]` Read the font's own `/Widths` (with
`/FirstChar`, `/LastChar`, `/MissingWidth`, and `/W` + `/DW` for CIDFonts) and
advance by the real width per glyph. The estimate then leaves the decision
entirely. `[observed 2026-08-01, the committed fixtures]` Two of them pin the
ends this has to satisfy at once: the run in `clip_drift_synthetic.pdf` must
survive, and the overrun and mirrored cases in `test_parsers.py` must still be
clipped. `[inferred]` No value of `char_w` satisfies both, which is why tuning it
is not the fix. Tracked as issue #32.

`[observed 2026-08-01]` The fixture asserts its own premise when built: the run
must end inside the clip box under real Helvetica widths and outside it under
the flat 0.5 em estimate. Without that check a string merely long enough to
leave the box would be clipped correctly by any reader, and the test would keep
passing after #32 was fixed — proving the opposite of what it claims. The first
version of this fixture had exactly that defect.
