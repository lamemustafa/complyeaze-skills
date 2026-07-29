# The scripts

[← back to the README](../README.md)

The model does not do arithmetic, and does not read spreadsheets or PDFs by
eye. Twelve
scripts do that, in Python, with no dependencies at all. Nothing to install,
nothing that phones home, nothing that reads a file you did not name.

### `parse_capital_gains.py`

Reads a broker or registrar capital-gains statement and classifies every row into
the schedule it belongs to.

The mistakes this exists to prevent are the four that actually cost people money,
and all four survive a careful read of the file:

- equity mutual-fund long-term gains entered as "other than 112A", which forfeits
  the ₹1,25,000 exemption
- equity short-term gains taxed at slab instead of 20% under s.111A
- the ₹1,25,000 exemption claimed once per broker instead of once per PAN
- intraday profit reported as capital gains when it is speculative business income

It will not decide whether a mutual fund is equity-oriented. Nothing in the
statement says, and the answer moves money between 12.5%-with-exemption and slab
rates, so those rows come back as questions with the totals excluded. Where a
broker layout is unfamiliar, `--inspect` prints the structure rather than guessing
at it.

It also catches something no amount of care would: a Zerodha workbook states each
gain twice, once trade by trade and again scrip by scrip, so reading it whole
doubles the capital gains on the return. Two real files proved it. The parser now
recognises two views of one bucket by their totals, counts them once, skips the
"Open Positions" sheet because unrealised profit is not income, and reconciles
every bucket against the broker's own stated summary. When it prints *ties to the
statement's own summary*, that is an independent check, not a restatement.

Every bucket also comes back split into the five windows Schedule CG item F asks
for, keyed on the date of sale. On a real statement that split reproduced the
broker's own quarterly dividend breakdown to the paisa.

### `check_112a_csv.py`

Checks a Schedule 112A CSV before you upload it. The portal rejects this file in
three ways and names nothing useful in any of them.

The header contains non-breaking spaces and its quoting changes between downloads,
so a retyped header, last year's header, or one that has been through Excel comes
back as "Please import the details in correct template". Any derived column that
disagrees with its formula silently skips every row. So does a hyphen in a scrip
name. The script checks all fifteen columns and the arithmetic between them, and
`--template` compares your header byte for byte against a template downloaded in
this session.

### `compute_tax.py`

Both regimes for AY 2026-27, compared, with the cheaper one recommended.

<details>
<summary>What it handles, with sections</summary>

- s.87A ceiling, marginal relief, and the regime-conditional treatment of
  special-rate income: the second proviso inserted by the Finance Act 2025 for the
  new regime, s.112A(6) for the old
- s.112 land and building acquired before 23 July 2024: the lower of 12.5%
  unindexed and 20% indexed, per the second proviso to s.112(1)(a)
- basic-exemption absorption against 111A, 112A and 112 for residents, absorbing
  into 112A last because it already carries its own exemption
- 80CCD(2) at the right percentage for the regime and the employer type
- s.57(iia) family pension, old-regime age bands, Chapter VI-A kept off
  special-rate income
- surcharge with the new-regime 25% cap, the 15% cap on dividends and capital
  gains, and marginal relief computed from a recomputed tax at the threshold
- s.234F and s.234-I from a filing date and section, which are mutually exclusive
- s.288A and s.288B rounding, to the nearest ten

It refuses on a non-resident, a house-property loss, a capital loss needing
set-off, s.115BBE, and land or building without an indexed gain.

</details>

Its synthetic regression case deliberately exercises both statutory rounding
steps: ₹15,89,635 becomes ₹15,89,640 under s.288A, and ₹1,23,184.00 becomes
₹1,23,180 under s.288B.

`--summary` prints the six figures somebody actually reads — total income, tax,
taxes paid, and what is left either way — instead of the full JSON. The JSON
carries every intermediate step because a figure nobody can trace is a figure
nobody should file; the summary exists because making a filer find six numbers
in two hundred lines is how transcription errors get made.

`--presumptive-44ada-receipts` presumes 50% of professional gross receipts as
profit and taxes it at slab. It refuses above the ₹50 lakh ceiling unless
`--cash-receipts-within-5pc` says the condition that raises it to ₹75 lakh
holds, and refuses a declared profit below the presumption — that is lawful, but
it is not s.44ADA: it makes books mandatory under s.44AA and brings s.44AB audit
into play. It does not decide whether the profession is one s.44AA(1) notifies.

### `parse_tax_docs.py`

Reads AIS, TIS, Form 26AS, Form 168 and Form 16 straight from the PDF, and
reconciles them against each other.

TIS is a deduplicated roll-up of the AIS detail, so every TIS category should
equal the sum of its AIS information codes. The synthetic regression fixture
keeps five exact category totals:

```
Dividend                    SFT-015 + TDS-194K            = 4,280
Interest, savings bank      SFT-016(SB)                   = 8,745
PF withdrawal               TDS-192A                      = 5,43,210
Sale of securities          SFT-17-LES(M) + SFT-17-OTU(M) = 8,76,540
Purchase of securities      SFT-17(Pur)                   = 7,65,430
```

A category that does not tie is where a missed source hides. One trap is built
in: AIS lists dividend twice by design, under SFT-015 from the registrar and
again under TDS-194 from the company's own TDS return, for the same money. TIS
deduplicates; adding both overstates dividend income.

Nothing else open-source parses TIS at all.

**Part B2 detail rows.** Under each information code AIS prints a sub-table, and
the reader slices it by that table's own column headings. `SFT-016(SB)` comes out
one block per reporting bank — the only place any document says which bank
reported what, and the first place to look when the statements do not add up to
the AIS savings figure. `SFT-17` comes out one row per disposal, with the date,
scrip, ISIN and whether it was short or long term, which makes a broker statement
matchable line by line. On a real AIS, 108 of 108 disposals mapped and their
considerations reconciled to the category total to within ₹4 of per-row rounding.

No account number, PAN or TAN reaches the output.

### `parse_bank_statement.py`

Reads a bank statement for the two things a return needs from it: the interest
credited, which goes in Schedule OS with no s.80TTA deduction to soften it under
the new regime, and the credits large enough to need explaining before the return
is defensible.

Nothing is positional. The bank comes from the **IFSC prefix**, never a name on
the page — a NEFT narration mentioning another bank made a DCB statement read as
ICICI. Which way the money went comes from the step in the **running balance**,
checked against a figure printed on the row, so a deposit is told from a
withdrawal on any layout and a statement printed newest-first is read backwards
rather than inverted.

Three defects it exists to prevent, all found on real statements. HDFC writes
dates as `23.04.2025`; a pattern that took only `-` and `/` turned a 58-page
statement into two rows, and the same string matched the amount pattern, so
`23.04` was read as an amount. A narration that is nothing but the word
`INTEREST` was counted as zero — four quarterly credits missed. And nothing
filtered by financial year, so a statement crossing 31 March fed two years'
interest into one return; pass `--financial-year 2025-26`.

The strongest check in it is the quietest: **opening balance plus every movement
read must reach the closing balance.** Interest looks plausible when half the
pages were skipped and a credit list looks plausible when it is missing entries.
The running balance is the only thing in a statement that cannot be reconciled
unless every row between the two ends was understood.

### `reconcile_interest.py`

Puts the savings interest AIS was told about beside the statements you hold, and
names every row that appears on one side and not the other.

This exists because of an unexplained Schedule OS shortfall. TIS gave one figure,
the statements added to another, and the difference was a bare number with no
name on it. Two facts made it solvable and neither was visible: AIS
reports savings interest **one block per bank**, so it already knew which banks
had reported and how much each said, and the statements only covered some of
those banks.

Three answers come out and they mean different things. A bank in both lists
should agree; where it does not, the script reports the discrepancy, the AIS
feedback route and the evidence to retain without choosing either figure. **A bank
in AIS with no statement is where an unexplained shortfall almost always lives** —
the department has been told about that account and the return has not. A bank
with a statement that AIS never mentions is neither an error nor a licence: SFT
reporting has thresholds and gaps, and interest nobody reported is still taxable.

It refuses to guess. Where a reporter's printed name matches no bank you supplied
it says so rather than assigning it to the nearest one — on a live AIS one savings
block was reported by "CPRC CHENNAI", which is a processing centre and not a bank.
And a statement that fails its own opening-to-closing balance check is called out
before its shortfall gets blamed on a missing account.

### `parse_portal_json.py`

Reads the portal's prefill JSON and any filed return, and checks the totals in
them against the rows they are made of.

The prefill lists **every bank account the department holds**. That is the list
your statements have to cover; an account nobody collected a statement for is the
usual reason Schedule OS comes up short. It also carries the Form 26AS TDS rows
and the AIS `insights` block, so a credit claimed above what was deducted, or a
TDS row with a gross of zero, is caught before filing rather than at processing.

A filed return carries `ScheduleCFL` and `ScheduleUD` — the losses and the
unabsorbed depreciation a later year has to state again. The return that created
the loss must satisfy s.80 read with s.139(3); omission in a later year forgoes
set-off for that year but does not automatically extinguish the loss.

Two things it learned from real returns. **s.288B** rounds tax payable and refund
due to the nearest ten rupees, so an equality check can differ by a few rupees on
an honest return. And
`UseForRefund` does not exist in every schema version, so its absence is stated
as an absence rather than read as "no account nominated".

Nothing that identifies anybody is printed. Where two files have to be compared,
the comparison happens inside the script and only the answer comes out.

### `pdf_crypt.py`

The PDF standard security handler in pure Python: RC4 40 and 128-bit, AES-128 and
AES-256, revisions 2 to 6, user password and owner password.

Every document the portal hands a taxpayer about themselves arrives encrypted —
AIS, TIS, the s.143(1) intimation, most Form 16s — with a password that is the
taxpayer's own PAN and date of birth. The usual answer is `pip install pikepdf`,
a C extension, and a taxpayer who cannot build a wheel should still be able to
read their own tax statement.

RC4 is checked against RFC 6229, AES against FIPS 197 and NIST SP 800-38A, and
the whole handler against fixtures written by pikepdf, so the test is a
cross-validation against an independent implementation rather than a round trip.
Every revision has a published password-validation step, so a key that is wrong
is refused rather than used to produce plausible rubbish.

### `redact.py`

Takes identifiers out of anything about to be printed.

It exists because every other script promised not to reproduce a PAN and every
one of them was breaking that promise in the same place: **the file name**. The
portal names its downloads after the taxpayer — `<PAN>-Prefill-2026-28.json`,
`Form168_<PAN>_2026-27.pdf` — and those names were being copied verbatim into
every result, every refusal message and every `--json` file, by scripts whose
disclaimers said no identifier is reproduced. A promise kept in eleven places
and broken in the twelfth is not kept.

It handles only shapes with a defined format — PAN, TAN, Aadhaar, IFSC, long
digit runs — and is not a scrubber for free text. Anything loose enough to need
judgement is not printed at all rather than passed through it.

The boundaries are lookarounds on letters and digits rather than `\b`, because
`_` is a word character and `\b` therefore never fires inside a file name. The
first draft of this module had exactly the bug it was written to fix.

### `read_pdf.py`

Extracts PDF text with the layout intact, using only `zlib` from the standard
library. A PDF content stream is compressed PostScript-like operators, and
keeping the columns in columns is what makes a tax statement readable as a
table. It follows the font's ToUnicode map, including the ligature form of
`bfrange` that shifts every later character when it is mishandled.

No OCR. A scanned statement comes back empty, which means unreadable, never
"no transactions".

### `read_tabular.py` and `open_ais.py`

`read_tabular.py` reads `.xlsx` and `.csv` using only the standard library. An
`.xlsx` is a zip of XML, so reading one is about a hundred and fifty lines, and
that is a better trade than making a taxpayer debug a pip install before they can
open their own capital gains. Every reader also takes `--password-stdin`, which is how a password should
actually be supplied. A password in `argv` is readable by any other process on
the machine through `ps`, and it lands in the shell history besides:

```bash
python3 open_ais.py AIS.pdf --pan ABCDE1234F --dob 01/01/1990 --print-password \
    | python3 parse_tax_docs.py AIS.pdf TIS.pdf --password-stdin
```

`open_ais.py` derives the AIS and TIS password from
PAN and date of birth and confirms it opens the file, naming whether it was the
user or the owner password. It writes nothing: the readers take `--password` and
decrypt in memory, so no unprotected copy of a document carrying a PAN, an
Aadhaar number and a year of transactions is left in a Downloads folder.


---

See also [how it works](how-it-works.md) and [the eval tiers](../skills/itr-filing-copilot/evals/README.md).
