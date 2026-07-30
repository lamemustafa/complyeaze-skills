# Known input-format gaps

`[documented]` This register describes five input limits of the
`itr-filing-copilot` skill. It records the evidence boundary and current parser
behaviour; it does not expand the formats the skill supports.

`[observed 2026-07-30, repository state]` The behaviours below were checked in
the current parser code and with the named local probes. No real tax document is
stored in this repository.

| Input | Current support boundary |
|---|---|
| Portal-generated PDFs with unmapped fonts | `[observed 2026-07-30, 13 portal downloads]` Refused after the Java envelope opens |
| Filed ITR-4 JSON | `[observed 2026-07-30, skeleton ITR-4 probe]` Recognised, but can return a complete-looking partial result |
| AIS JSON download | `[observed 2026-07-30, local non-PDF JSON probe]` Not parsed; non-PDF input is refused |
| A broker layout other than Zerodha | `[observed 2026-07-30, Schedule 112A CSV probe]` Generic headings parsed source `unknown`; real second-broker correctness is `[UNVERIFIED]` |
| Zerodha Tax P&L supplied as PDF | `[observed 2026-07-30, committed PDF probe]` Refused by the workbook reader |

## 1. Portal PDF font encoding

**Missing:** `[observed 2026-07-30, 13 portal downloads]` `read_pdf.py` cannot
map the font encoding used by the portal downloads in the observed set to
readable text.

**What would unblock it:** `[inferred]` ToUnicode CMap and font-encoding support
in `read_pdf.py`, backed by an identifier-free regression fixture reproducing
the observed encoding, would provide a testable implementation path.

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

**What happens today:** `[observed 2026-07-30, skeleton ITR-4 probe]` This is
**not** a clean unsupported-format refusal. The detector accepts an `ITR4`
wrapper, and a skeleton carrying the shared required blocks returns a
complete-looking filed-return result with every figure `0.0` and no refusal.
`[observed 2026-07-30, parse_portal_json.py]` The output can state separately
that presumptive schedules were not checked, but recognition of the wrapper
does not fail closed on the unseen format. `[UNVERIFIED]` Behaviour against a
real portal ITR-4 schema remains unknown.

**Known follow-up:** `[inferred]` A specimen-backed mapping and exact tests, or a
specific unsupported-ITR-4 refusal until they exist, would close the partial-read
boundary. `[observed 2026-07-30, repository state]` Neither change is implemented
here.

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
fixture with exact bucket and refusal assertions, would establish evidence for
that layout.

**What happens today:** `[observed 2026-07-30, Schedule 112A CSV probe]` This is
**not** a guaranteed clean refusal. `parse_capital_gains.py` accepted
the committed Schedule 112A CSV as source `unknown`, emitted 2 rows and a
117,400 gain in the 112A bucket, and exited 0. Generic heading and column matches
can therefore produce an answer for an unvalidated source. `[observed
2026-07-30, parser code and tests]` A file with no recognised rows is refused and
directed to `--inspect`, and skipped sections are reported. `[UNVERIFIED]` No
output from a second broker has been checked against that broker's stated
totals.

**Known follow-up:** `[inferred]` A real-layout observation and an exact-output
fixture are the missing evidence for any additional broker claim. A source
reported as `unknown` remains unverified even when rows are recognised.

## 5. Zerodha Tax P&L delivered as PDF

**Missing:** `[observed 2026-07-30, maintainer inventory]` A Zerodha PDF specimen
exists, but its table layout has not been reverse-engineered. `[observed
2026-07-30, parse_capital_gains.py]` The capital-gains reader accepts workbook
and CSV inputs, not broker PDFs.

**What would unblock it:** `[inferred]` Local inspection of the specimen,
followed by an identifier-free synthetic PDF fixture with exact totals and
refusal cases, would establish the section and column mapping needed by the
existing capital-gains buckets.

**What happens today:** `[observed 2026-07-30, committed PDF probe]` Passing a
PDF to `parse_capital_gains.py` produces a structured refusal with exit code 2.
Every extension other than `.csv`, `.txt`, `.tsv` and `.xls` falls through to
the `.xlsx` loader, so the message says the PDF `is not a valid .xlsx` and
suggests re-saving it as a workbook or CSV. The probe produced no traceback and
no capital-gains result. The refusal does not identify PDF as a known
unsupported Zerodha format.
