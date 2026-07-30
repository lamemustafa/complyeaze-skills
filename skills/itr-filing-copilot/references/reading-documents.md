# Reading the documents

Everything a return is reconciled against arrives as a file: a broker workbook,
an AIS PDF, a TIS PDF, Form 26AS or Form 168, Form 16, the portal's own JSON.
Reading them by eye is where transcription errors come from, and reading them
with a language model is where invented figures come from. Five scripts read
them instead, with nothing but the standard library.

## Encrypted files open in place

AIS, TIS, the s.143(1) intimation and most Form 16s download encrypted with the
lowercase PAN followed by the date of birth as `ddmmyyyy`. `pdf_crypt.py`
implements the PDF standard security handler — RC4 40 and 128-bit, AES-128 and
AES-256, revisions 2 to 6, user password or owner password — so every reader
takes `--password` and decrypts as it reads.

```
python3 scripts/open_ais.py AIS.pdf --pan ABCDE1234F --dob 01/01/1990
python3 scripts/open_ais.py AIS.pdf --pan ABCDE1234F --dob 01/01/1990 --print-password \
    | python3 scripts/parse_tax_docs.py AIS.pdf TIS.pdf --password-stdin
```

Every reader takes `--password-stdin` as well, and that is the form to prefer.
A password given in `argv` is readable by any other process on the machine
through `ps`, and the shell keeps it in history — for a credential that is the
taxpayer's own PAN and date of birth, and which opens every other document they
own, that is worth avoiding.

`open_ais.py` no longer writes a decrypted copy. Leaving `AIS_decrypted.pdf` in
a Downloads folder — a PAN, an Aadhaar number, every bank account and a year of
transactions, unprotected and forgotten — is a worse outcome than the one it
solved. What it does now is confirm the password works and say whether it opened
as the user or the owner password, which is the difference between a wrong date
of birth and a wrong PAN.

The cipher is checked against RFC 6229, FIPS 197 and NIST SP 800-38A, and the
whole handler against fixtures written by pikepdf, so the test is a
cross-validation against an independent implementation rather than a round trip.
`[observed]` end to end on live AY 2026-27 downloads: AIS and TIS at `/V 1 /R 2`,
Form 16 and a s.143(1) intimation at `/V 2 /R 3`.

## The department's own documents

```
python3 scripts/parse_tax_docs.py AIS.pdf TIS.pdf 26AS.pdf Form16.pdf
```

Detects each document, extracts it, and reconciles them against each other.
`--text` dumps the extracted text when a layout is unfamiliar.

**AIS against TIS is the strongest check available on these two documents.**
TIS is a deduplicated roll-up of the AIS detail, so each category should equal
the sum of its AIS information codes. The synthetic regression fixture keeps
five exact category totals:

```
Dividend                    SFT-015 + TDS-194K            = 4,280
Interest, savings bank      SFT-016(SB)                   = 8,745
PF withdrawal               TDS-192A                      = 5,43,210
Sale of securities          SFT-17-LES(M) + SFT-17-OTU(M) = 8,76,540
Purchase of securities      SFT-17(Pur)                   = 7,65,430
```

A category that does not tie is where a missed source hides. One trap is built
in: **AIS lists dividend twice by design**, once under SFT-015 from the
registrar and again under TDS-194 from the company's own TDS return, covering
the same money. TIS deduplicates them; adding both overstates dividend income.
s.194K dividend on mutual-fund units is a separate source and does add. That
duplicate-channel behaviour, with s.194K remaining separate, was `[observed]` on
a live AY 2026-27 pair in July 2026; the exact totals above are synthetic
regression values.

**Part B2 detail rows say which, not just how much.** Under every information
code AIS prints a sub-table, and the reader slices it by that table's own column
headings. Two of them matter.

`SFT-016(SB)` is **one block per reporting bank**. This is the only place any
document says which bank reported what. When the statements do not add up to the
AIS savings figure, that breakdown is where the difference is: a bank that
reported and whose statement you never collected, or a bank absent from AIS whose
interest is real anyway. On a live AIS four banks reported separate blocks whose
amounts summed to the category total. `[observed]`

`SFT-17` is **one row per disposal** — date, scrip, ISIN, short or long term, and
the seven figures the form carries. It makes a broker statement matchable line by
line. On a live AIS 108 of 108 disposals mapped; the summed considerations
exceeded the stated total by 4 rupees, inside the half-rupee-per-row tolerance.
AIS rounds each row to whole rupees and totals the unrounded figures, so a larger
difference means rows lost or counted twice. `[observed]`

**No identifier is printed.** The account number a savings figure was reported
against is redacted by column name; PAN- and TAN-shaped tokens and any run of
nine or more digits are redacted wherever they appear. Both were needed: a page
footer carrying a download ID landed on the same grid row as a security name, and
the reporting bank's own TAN sat in the source field.

**Form 168 is the Form 26AS successor** under the Income-tax Act 2025, titled
"Form 168 / Annual Tax Statement" and keyed on **Tax Year**, not assessment
year. It reuses Parts I to IX, splits Part X into defaults and other demands,
and adds Part XI for credit allowed by the Assessing Officer u/s 398. Parts VIII
and IX are informational — TDS you deducted as a *buyer* is not your credit, and
the script excludes them from the total. `[observed]`

**Form 16 Part B** yields the s.17(1)/(2)/(3) split, s.10 exemptions, the s.16
deductions, Chapter VI-A, and the regime the employer computed on. The regime
line reads *"Whether opting out of taxation u/s 115BAC(1A)?"* — "No" means the
new regime was used. That is the employer's choice for TDS, not a binding
election: the filer may still choose the other regime, subject to Form 10-IEA
and the due date.

Every figure in Part B sits at the end of its row with two decimals. Numbers
inside a label — "section 17(2)", "Form No. 12BA" — are not amounts, and an
earlier version read them as the value.

## Broker and registrar statements

```
python3 scripts/parse_capital_gains.py "Tax P&L.xlsx" [more files...]
python3 scripts/parse_capital_gains.py --inspect unknown_broker.xlsx
```

Classifies every row into an ITR bucket, totals each one, names the schedule it
lands on, and splits each bucket into the five Schedule CG item F windows.

The four mistakes it exists to prevent are the ones that actually cost money,
and every one survives a careful read of the file:

- equity-MF long-term gains entered as "other than 112A", forfeiting the
  ₹1,25,000 exemption
- equity short-term gains taxed at slab instead of 20% u/s 111A
- the ₹1,25,000 exemption claimed once per broker instead of once per PAN
- intraday profit reported as capital gains when it is speculative business
  income, which forces ITR-3

**A broker workbook usually states the same gains more than once.** Zerodha
gives every trade on a Tradewise Exits sheet and restates the same gains scrip
by scrip on the segment summary sheet. Reading both doubles the capital gains on
the return. The parser recognises two views of one bucket by comparing totals,
counts the detail once, and names the sheet it dropped. Where two views disagree
it keeps both and asks you to resolve it.

It also reconciles each bucket against the broker's own realised-profit
breakdown and prints "ties to the statement's own summary" when they agree. **A
bucket that does not tie is a stop.**

It will not read an "Open Positions" sheet, because unrealised profit on a
holding still open is not income. It will not use a raw `Profit` column when a
`Taxable Profit` column exists, because the second carries 31 January 2018
grandfathering.

Anything it cannot settle from the statement comes back under
`needs_confirmation`, excluded from the totals, with the question that settles
it: a mutual fund that may or may not be equity-oriented, unlisted shares, a
buyback, land or building, anything foreign. For the mutual-fund one AIS settles
it — **SFT-18-EMF with non-zero STT is equity-oriented, SFT-18-OTU with zero STT
is not.**

## Bank statements

```
python3 scripts/parse_bank_statement.py kotak.pdf dcb.pdf [more...]
```

A statement holds thousands of rows and a return needs two answers out of it.

**Interest credited**, for Schedule OS. Under the new regime there is no s.80TTA
deduction against it, so the whole figure is taxable at slab rates. AIS carries
it under `SFT-016(SB)` but only from banks that filed, so a bank missing from
AIS does not mean the interest was not earned. Where the statement and AIS
differ, report the discrepancy without choosing either figure, submit AIS
feedback if the information item is wrong, and retain the statement, feedback
acknowledgement and reconciliation working paper if filing from the statement.

**Credits that need explaining.** A large credit is not income by itself: a gift
from a relative is outside the charge entirely, a loan is not income, a transfer
between the taxpayer's own accounts is nothing at all. But each one has to be
*identified* before the return is defensible. An unexplained credit is where a
s.68 addition starts, and a gift from a non-relative above ₹50,000 is taxable
**in full** under s.56(2)(x), not just on the excess.

The bank is identified from the **IFSC prefix**, never from a name on the page —
a NEFT narration mentioning another bank made a DCB statement read as ICICI.

The interest match is deliberately narrow (`SB Int`, `Int Pd`, `Credit
Interest`, `Interest Paid`) so a UPI payment to someone named "Interest" does not
become income. One widening was safe: a narration that is **nothing but** the
word `INTEREST`, with no counterparty and no channel, is a bank's own quarterly
credit. `[observed]` — four quarterly credits on a real statement were being
counted as zero.

**Which way the money went is read from the running balance.** For two
consecutive rows the change in the last figure on the row is the movement,
signed, and the test that the last figure really is a balance is that the change
equals a figure printed on the row. Where that holds the direction of every row
is known; where it does not, no credit is offered at all rather than a guess.
Statements printed newest-first are recognised and read backwards — reading one
forwards inverts every credit into a debit, which turns your withdrawals into the
receipts you have to explain. A row that cannot be signed, such as the first row
of a statement with no previous balance, is reported as undetermined rather than
dropped.

**Dates.** HDFC writes `23.04.2025`, Kotak `23-04-2025`, ICICI `23/04/2025`, and
two-digit years turn up on all of them. The dot mattered twice: with only `-` and
`/` accepted a 58-page statement yielded **2** transaction rows, and the same
string matched the amount pattern, so `23.04` was read as ₹23.04. Dates are now
masked out of a line before any figure is read from it. The same statement now
reads **777** rows with every balance step reconciling. `[observed]`

**Financial year.** Pass `--financial-year 2025-26`. India's year runs 1 April to
31 March, so a statement that crosses that date holds interest belonging to two
different returns; without the filter they are added together and the split is
reported so the sum is at least visible.

## Schedule 112A CSV

```
python3 scripts/check_112a_csv.py filled.csv --template fresh_download.csv
```

Checks all fifteen columns and the arithmetic between them before upload. See
`portal-traps.md` for the three ways the portal rejects this file.

## What none of them do

No OCR. A scanned statement has no text layer and comes back empty, which is
"unreadable", never "no transactions". No network. Nothing is read that was not
named on the command line. And no figure is reproduced from a PAN, an Aadhaar
number or an account number, though the source files carry all three — keep them
out of public issues.

## Putting AIS and the statements side by side

```
python3 scripts/reconcile_interest.py --ais AIS.pdf --password ... \
    kotak.pdf dcb.pdf --financial-year 2025-26
```

A return's Schedule OS was short by ₹921 and nobody could say why. Both halves of
the answer were already on the page: AIS reports savings interest **one block per
account**, so it knew which banks had reported and how much, and the statements
covered only some of those banks. This joins the two lists and names every row
that appears on one side and not the other.

Three answers, and they mean different things:

- **A bank in both** should agree. Where it does not, do not choose either figure:
  check the statement period and 31 March boundary, submit AIS feedback if the
  information item is wrong, and retain the statement, feedback acknowledgement
  and reconciliation working paper if filing on the statement figure.
- **A bank in AIS with no statement** is where an unexplained shortfall almost
  always lives. The department has been told about the account; the return has
  not.
- **A bank with a statement AIS never mentions** is neither an error nor a
  licence. SFT reporting has thresholds and gaps, and interest nobody reported is
  still taxable.

It refuses to guess. Where a reporter's printed name matches no bank you supplied
it says so rather than picking the nearest — on a live AIS one savings block was
reported by "CPRC CHENNAI", a processing centre and not a bank. Both sides are
aggregated per bank before anything is compared, because two accounts at one bank
produce two AIS blocks and comparing each against the bank's whole statement
total reported that bank twice, disagreeing with itself. And a statement that
fails its own opening-to-closing balance check is named before its shortfall gets
blamed on a missing account.

## The portal's own JSON

```
python3 scripts/parse_portal_json.py PREFILL.json
python3 scripts/parse_portal_json.py PREFILL.json LAST_YEARS_RETURN.json
```

Two different documents are both called "the JSON".

**The prefill** is the department's view of you before you start: every bank
account it holds, the Form 26AS TDS rows, the AIS-derived `insights` block, and
the regime forms on record. The bank list is the most useful thing in it — it is
the list your statements have to cover, and an account nobody collected a
statement for is the usual reason Schedule OS is short.

Savings interest appears in as many as three places in one prefill: `insights`
from AIS, `form24q` from the employer, and a `form26as` block. They agreeing does
not mean they are right. They are not independent — a bank that reported to
neither is missing from all three, and only the statements will show it.

**The filed return** carries `ScheduleCFL` and `ScheduleUD`: the losses and the
unabsorbed depreciation a later year has to state again. Nobody reconstructs
those from a PDF a year on. Under s.80 read with s.139(3), the return that
created the loss must have been filed by its s.139(1) due date. Omitting the
brought-forward figure in a later year forgoes set-off for that year and creates
an evidence problem, but does not automatically extinguish the loss.
`ScheduleAMTC` carries the AMT credit the same way.

Every total in these files is an identity over rows the same file carries, so
each one is checked: the TDS schedules against their own totals and against
Part B-TTI, the four components of taxes paid against their sum, net tax plus
s.234 interest against the aggregate, and taxes paid less liability against the
refund or the balance payable.

That last one has a trap in it. **s.288B rounds tax payable and refund due to
the nearest ten rupees**, five rounding up. Run against five real returns from
AY 2021-22 to AY 2026-27, an equality check fired on four of them; every
difference was within four rupees and matched the statutory rounding, not a
defect. `[observed]`

**`UseForRefund` does not exist in every schema version.** On an AY 2024-25
ITR-2 no bank row carries it, and reading its absence as "no account nominated"
reports a defect on a return that was filed and refunded two years ago. The
absence is stated as an absence. `[observed]`

**Nothing that identifies anybody comes out.** Not the PAN, the Aadhaar number,
an account number, the mobile number or the email address, all of which these
files carry. Where two files have to be compared — the same taxpayer? the same
TDS? — the comparison happens inside the script and only the answer is printed.

## Reconciliation is the gate

`parse_tax_docs.py` reconciles AIS against TIS category by category, which is
the strongest check those two documents allow, and ties Form 16 TDS to Form
26AS or Form 168. `parse_capital_gains.py` classifies every trade into an ITR
bucket and splits each one into the Schedule CG item F windows. `[observed,
repository code and parser tests]`

**A bucket or category that does not tie is a stop, not a rounding difference.**
The readers refuse rather than guess about a fund that may or may not be
equity-oriented, a buyback, land, anything foreign or an unrecognised layout.
`[observed, parser tests]`

**Reconcile every rupee against AIS/TIS before touching the portal.** Build an
explicit tie-out:

```
AIS "sale of listed equity share"     8,45,610
  = STCG consideration                6,50,321
  + LTCG (112A) consideration         1,95,290
                                      ---------
                                      8,45,611   (₹1 rounding — fine, document it)
```

Where broker data and AIS disagree on **income** (dividends are the usual
culprit — AIS lags SFT filings), report the discrepancy and do not choose either
figure without source evidence. `[documented]` Submit AIS feedback if the
information item is wrong. `[inferred]` If filing from the primary record,
retain it, the feedback acknowledgement and a reconciliation working paper; a
mismatch may draw a proposed s.143(1)(a) adjustment, which should be answered
with the evidence rather than by declaring income that was not earned.
