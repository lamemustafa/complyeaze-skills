---
name: itr-filing-copilot
description: Prepare, reconcile and file an Indian income tax return (ITR-1/2/3/4) on the incometax.gov.in portal. Use when the user mentions ITR, income tax return, filing taxes in India, Form 16, AIS, TIS, Form 26AS, capital gains statement, broker tax P&L, Schedule CG, Schedule BP, or says "file my ITR", "help with income tax", "which ITR form". Covers document reconciliation, form and schedule selection, field-by-field portal entry, CBDT validation rules, the traps that block upload, and post-filing rectification and revision.
license: Apache-2.0
metadata:
  author: ComplyEaze
  version: "0.1.2" # x-release-please-version
  assessment-year: "2026-27"
  last-verified: "2026-07-28"
  jurisdiction: "IN"
---

# ITR Filing Copilot

> **General reference only — not tax advice.** This skill is not a law firm, accounting
> firm, registered tax practitioner, e-return intermediary or filing service. Its output
> may be incomplete, outdated or wrong; tax law changes mid-year and every figure is
> assessment-year specific. Nothing here is reviewed against a particular person's
> residency, elections, prior-year positions or open notices. **The taxpayer is legally
> responsible for every figure in the filed return.** Have a qualified professional review
> before filing or payment. Not affiliated with, endorsed by or operated by the Income Tax
> Department, CBDT or the Government of India.

Take a taxpayer from a pile of documents to a filed, e-verified return.

**AY 2026-27 = FY 2025-26 = the Income-tax Act, 1961.** The Income-tax Act 2025
commences 1 April 2026 and its first tax year is 2026-27, so the first returns under it
are filed in 2027. The portal runs both modules concurrently — if a screen quotes a
section you do not recognise, check which Act's module you are in.

**The tax arithmetic is the easy part.** In practice most of the effort goes into
portal mechanics: which schedules to add, what order to fill them in, which
dropdown value the form will accept, and which CBDT validation rule is silently
blocking upload. This skill front-loads that knowledge.

## Scope

Handles: resident individuals, ITR-1 / ITR-2 / ITR-3 / ITR-4 (non-audit), salary,
capital gains (equity, MF, debt), other sources, intraday/speculative business,
presumptive income under 44AD/44ADA/44AE, partner-in-firm, PF withdrawals.
Known input gaps and current behaviour: [`references/known-gaps.md`](references/known-gaps.md).

**Never fabricate a JSON identity.** If you ever generate or hand-edit an ITR JSON,
`CreationInfo.SWCreatedBy` / `JSONCreatedBy` are **registered software-provider codes
issued by the department** (`SW########`). Emitting someone else's code stamps a private
individual's return as that vendor's output. Do not copy one from another project, and do
not invent a `Digest`. Prefer the portal's own output; audit it, don't forge it.

Escalate to a CA, do not guess: audit cases (44AB), F&O with meaningful
turnover, non-residents, foreign assets/income (Schedule FA/FSI/TR), ESOP
deferral, business with real books, HUF/deceased/representative filings, any
open notice or assessment. State plainly that the user, not the preparer, is legally
responsible for the filed figures.

---

## Phase 0 — Intake conversation

When invoked cold, **do not ask for everything at once.** Run this sequence; each step's
answer changes what you ask next.

**1. Orient, in two questions.** Whose return, and which assessment year. "Filing for
yourself or someone else?" matters — a third-party filing needs you to state plainly that
the taxpayer, not the preparer, is legally responsible for the figures.

**2. Ask for the anchor documents first**, not a shopping list:

> Start with these four — **AIS**, **TIS**, **Form 26AS**, and **Form 16** if there was
> salary. Everything else follows from what those show.

**3. Handle password protection before it blocks you.** AIS and TIS PDFs are encrypted.
The password is **lowercase PAN + date of birth as `ddmmyyyy`**, concatenated. Ask for the
date of birth *when you hit the encrypted file*, not upfront — asking for a DOB before
there is a reason reads as data collection.

```
python3 scripts/open_ais.py AIS.pdf --pan ABCDE1234F --dob 01/01/1990
python3 scripts/open_ais.py AIS.pdf --pan ABCDE1234F --dob 01/01/1990 --print-password \
    | python3 scripts/parse_tax_docs.py AIS.pdf TIS.pdf --password-stdin
```

`open_ais.py` confirms whether the password opened as the user or owner and writes
nothing: every reader decrypts in memory, so no unprotected copy of a document carrying
a PAN, an Aadhaar number and a year of transactions is left in a Downloads folder.

The credential opens the s.143(1) intimation PDF; AIS JSON is `[UNVERIFIED]` and unread here.

**4. Ask for bank and broker statements regardless of what AIS shows.**

> **AIS silence does not mean the income does not exist.** A filer with a full year of
> equity and ETF disposals had **nothing** reported under any SFT category — no
> SFT-017, no SFT-018, no depository rows at all. The capital gains were real and the
> return would have been wrong.

SFT reporting has thresholds, lags, and gaps. Depositories miss off-market transfers.
Some brokers report late or not at all. **Never conclude "no capital gains" from an empty
AIS.** Ask directly:

> Do they hold a demat or broking account — Zerodha, Groww, Upstox, ICICI Direct,
> anything? If yes, get the **Tax P&L for the financial year** whether or not AIS shows
> a single trade.

Same for banks: AIS carries savings interest via SFT-016, but only from banks that
reported. Ask which accounts exist, then get a statement or interest certificate for each
one AIS does not name.

**5. Read the anchors, then ask for what they prove is missing.** This is the step
that separates a useful intake from a form:

| What AIS/26AS shows | Ask for |
|---|---|
| SFT-017 / SFT-018 sale of securities | broker **Tax P&L** for the FY — mandatory, decides ITR-2 vs ITR-3 |
| Salary from more than one TAN | the second Form 16 |
| Interest from a bank with no statement supplied | that account's statement or interest certificate |
| A challan in Part B3 | which AY it belongs to — September challans usually belong to the *previous* AY |
| Nothing for Apr–Sep but salary later | confirm there was genuinely no earlier employer |
| TDS u/s 192A | PF withdrawal — ask about years of continuous service |

**6. Reconcile before asking anything else.** Build the tie-out. Unexplained bank credits,
figures that differ between AIS and the source, gaps in the year — these become the
question list, and they are far more useful than generic prompts.

**7. Then ask the framing questions**, once you know what the return actually is:

- **How much detail do they want?** Plain steps, or the rule numbers and JSON field names
  too. Get this before writing anything long.
- **Are they filing themselves on the portal, or do they want a computation to hand to a
  CA?** Completely different deliverables.
- Anything the documents cannot tell you: was a large credit a gift and from whom; is a
  recurring EMI an education loan; were there other accounts or assets.

**8. Only now produce the guide.** A filing walkthrough written before reconciliation is
guesswork with formatting.

**Escalate rather than proceed** if intake surfaces: a 44AB audit case, F&O with meaningful
turnover, non-residence, foreign assets, ESOP deferral, real books, an HUF or deceased or
representative filing, or any open notice.

---

## Phase 1 — Intake and reconciliation

Collect before computing anything:

| Document | Gives you |
|---|---|
| **AIS** and **TIS** (portal → AIS) | What the department already believes. The anchor. |
| **Form 26AS** | TDS by TAN and section. Authoritative for tax credits. |
| **Form 16 / 16A** | Salary breakup, employer TAN |
| **Broker tax P&L** (Zerodha/Groww/Upstox…) | Realised gains by category, turnover, charges |
| **Bank interest certificates** | Savings/FD interest |
| **Prefill JSON** (portal → offline utility → download prefill) | Portal's own view: bank accounts, TDS rows, flags |
| Prior year's ITR JSON | Carry-forwards, bank list, regime history |

**Do not read these documents by eye.** `parse_tax_docs.py`, `parse_capital_gains.py`,
`parse_bank_statement.py`, `parse_portal_json.py` and `check_112a_csv.py` read them,
standard library only, and `references/reading-documents.md` covers all of it:

```
python3 scripts/parse_tax_docs.py AIS.pdf TIS.pdf 26AS.pdf Form16.pdf --password ...
python3 scripts/parse_capital_gains.py "Tax P&L.xlsx"
python3 scripts/parse_bank_statement.py kotak.pdf dcb.pdf --financial-year 2025-26
python3 scripts/parse_portal_json.py PREFILL.json LAST_YEARS_RETURN.json
python3 scripts/reconcile_interest.py --ais AIS.pdf kotak.pdf dcb.pdf --password ...
```

`parse_tax_docs.py` reconciles AIS against TIS category by category, which is
the strongest check these two documents allow, and ties Form 16 TDS to Form 26AS
or Form 168. `parse_capital_gains.py` classifies every trade into an ITR bucket
and splits each one into the Schedule CG item F windows.

`parse_bank_statement.py` pulls savings interest for Schedule OS and lists the
credits that need explaining before the return is defensible — a gift from a
non-relative above ₹50,000 is taxable in full under s.56(2)(x), not just on the
excess. Pass `--financial-year`: a statement that crosses 31 March holds
interest belonging to two different returns, and adding them together is silent.

`parse_portal_json.py` reads the prefill and any filed return. The prefill lists
**every bank account the department holds** — the list your statements have to
cover, and an account nobody collected a statement for is the usual reason
Schedule OS is short. A filed return carries **ScheduleCFL and ScheduleUD**, the
losses and unabsorbed depreciation a later year must state again.

**AIS Part B2 answers "which".** `parse_tax_docs.py` breaks out the detail rows:
savings interest one block per reporting bank, sale of securities one row per
disposal. `reconcile_interest.py` then puts that list beside the statements and
names every account on one side and not the other — **a bank in AIS with no
statement is where a Schedule OS shortfall almost always lives.** No account
number is ever printed.

**A bucket or a category that does not tie is a stop, not a rounding
difference.** Both scripts refuse rather than guess: a fund that may or may not
be equity-oriented, a buyback, land, anything foreign, an unrecognised layout.

**Reconcile every rupee against AIS/TIS before touching the portal.** This is
what makes the return defensible later. Build an explicit tie-out:

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
information item is wrong. `[inferred]` If filing from the primary record, retain
it, the feedback acknowledgement and a reconciliation working paper; a mismatch
may draw a proposed s.143(1)(a) adjustment, which should be answered with the
evidence rather than by declaring income that was not earned.

## Phase 2 — Form selection

**First check whether filing is mandatory at all** — income below the basic exemption
limit does not settle it. The seventh proviso to s.139(1) forces a return on current-account
deposits over ₹1 crore, foreign travel over ₹2 lakh, or electricity over ₹1 lakh; **Rule
12AB** adds business turnover over ₹60 lakh, professional receipts over ₹10 lakh, aggregate
TDS+TCS of ₹25,000 (₹50,000 if 60 or over), and savings deposits of ₹50 lakh. A **resident
holding any foreign asset or signing authority files regardless of income** (fourth proviso)
— and that also means Schedule FA, which is an escalate case. Thresholds in
`references/rates-ay2026-27.md`.

```
Business/professional income (incl. intraday or F&O)?  → ITR-3
Partner in a firm/LLP?                                 → ITR-3
Presumptive 44AD/44ADA/44AE, income ≤ ₹50L?            → ITR-4
Capital gains, >2 house properties, foreign assets?    → ITR-2
Salary + up to 2 houses + other sources, ≤ ₹50L?       → ITR-1
```

**ITR-1 and ITR-4 now take two house properties** and **LTCG u/s 112A up to ₹1,25,000**.
They still have no Schedule CG, CYLA, BFLA or CFL — so *any* capital loss, any STCG, any
LTCG outside 112A, or any brought-forward loss forces ITR-2. So does any special-rate
income: ITR-1 has no row for lottery or online-gaming winnings.

**The portal does not enforce most of this.** Wrong-form ITR-1 and ITR-4 uploads fire
Category B advisories only — they succeed, and CPC catches them later. Form selection is
your job, not the validator's.

A ₹6 intraday loss on three trades forces ITR-3, with Balance Sheet, P&L and
audit questions. Check for intraday explicitly — clients rarely mention it.

## Phase 3 — Regime

New regime (115BAC) is the default. Old regime requires **Form 10-IEA filed
before the due date**, and with business income the choice becomes sticky for
future years. Compare both, but if total income is under ₹12L the s.87A rebate
usually makes the comparison moot.

**The s.87A rebate behaves differently in each regime, and this is the most contested
computation on the portal.** New regime: the second proviso to s.87A (Finance Act 2025)
caps it at tax at s.115BAC(1A) rates, so it never reaches 111A / 112A / 112. Old regime:
s.112A(6) bars it against 112A tax, but **s.111A carries no such bar** — on the statute it
is allowable against STCG. Whether the utility agrees is `[UNVERIFIED]`. Compute it, read
the portal's own figure, and if they differ give the taxpayer both numbers and say what
the difference turns on. Details in `references/rates-ay2026-27.md`.

## Phase 4 — Compute

Use `references/rates-ay2026-27.md`. **Re-verify rates against a current source
every assessment year** — treat the reference file as shape, not truth.

**Do not do this arithmetic yourself.** Run `scripts/compute_tax.py` and use what it
prints. It is stdlib-only, reads nothing from disk, and carries golden cases plus
invariant checks that run in CI.

```
python3 scripts/compute_tax.py --salary 1660000 --savings-interest 4100 \
    --refund-interest 529 --winnings-115bbj 6 --tds 121950
```

It computes both regimes and recommends one; handles the s.87A ceiling, its marginal
relief and the regime-conditional treatment of special-rate income; applies the 112A
exemption and the basic-exemption absorption provisos; caps 80CCD(2) at the right
percentage for the regime and employer type; applies the s.57(iia) family-pension
deduction; charges surcharge with the 15% cap and marginal relief; computes s.234F and
s.234-I from `--filing-date`; and rounds under s.288A/288B (**to the nearest** ten, not
down).

It **refuses** rather than guessing on: a non-resident (`--non-resident`); a
house-property loss; any negative special-rate figure, because capital-loss set-off needs
Schedules CYLA/BFLA/CFL; s.115BBE unexplained credits, which carry a flat 25% surcharge;
s.80CCD(2) without the basic-plus-DA salary the percentage cap applies to; and land or
building acquired before 23 July 2024 without the indexed gain — that last one needs both
figures because the second proviso to s.112(1)(a) charges the *lower* of 12.5% unindexed
and 20% indexed. It does not compute 234A/B/C, s.89 relief, AMT or foreign tax credit;
those still need you.

For fees, pass `--filing-date` **and** `--filing-section` — s.234F and s.234-I are mutually
exclusive on any one set of facts, and a person below the basic exemption limit filing only
to claim a refund owes no 234F at all (add `--must-file` if a seventh-proviso or Rule 12AB
trigger applies).

An adversarial review of this engine found surcharge marginal relief silently zeroing
surcharge above every threshold, and basic-exemption absorption picking the wrong head when
two gains shared a rate. Both are now golden cases. **Re-run the golden file after any
change to a number.**

`evals/golden/cases.json` holds the cases in data form, including the refusals. Add cases
there rather than in Python:

```
python3 scripts/compute_tax.py --golden evals/golden/cases.json
python3 scripts/compute_tax.py --salary 1660000 --tds 121950 --summary
```

Keep the output. It is your checksum at every later step. If the portal disagrees with
it, one of you is wrong and you need to know which before you proceed.

The engine caught a hand-computed expectation that was wrong by ₹10,400 during its own
development. That is the reason it exists.

## Phase 5 — Fill the portal

Read `references/portal-traps.md` first. It is the highest-value file here.

| Read this | When |
|---|---|
| `references/forms-itr1-itr3-itr4.md` | The return is not ITR-2. ITR-1 and ITR-4 have no Select Schedule screen at all; ITR-3 makes Balance Sheet and P&L mandatory even with no books |
| `references/schedule-sections.md` | Deciding which section code or dropdown value a figure belongs to. **Match on the label text, never the row number** — numbering moves between forms and between years |
| `references/online-utility-walkthrough.md` | Filing through the online utility rather than the offline JSON one: the screen chain, Confirm-per-schedule, Add Details vs Add Another, paying and entering the challan |
| `references/error-messages.md` | Anything is blocking upload. **Ask for the error text verbatim before theorising** — the message usually names a field that is not where the fix is |
| `references/json-audit.md` | Reading the draft JSON back: schema paths, the fields worth grepping, and the digest check that catches a stale download |
| `references/post-filing.md` | After e-verify: rectification against revised return, defective returns, ITR-U, intimations, demands, refund failures, and the windows that close silently |

Due dates diverge **by income category and audit liability, not by form number**.
Business or professional income with no s.44AB audit gets 31 August 2026, audit cases get
31 October, everyone else gets 31 July.

Picking the wrong row is the most common way a correct computation still produces a wrong
return: a listed ETF filed under unquoted shares, online-game winnings on the 115BB row,
a PF withdrawal under 17(1).

### Never reconstruct a portal screen you have not seen

Portal structure is the one thing you cannot reason your way to. Row numbers move between
forms and between years — ITR-2 puts "other assets" at A5, ITR-3 at A6; Schedule SI is
under Income on ITR-2 and untagged on ITR-3. A plausible-sounding field number sends the
filer to the wrong block, and they will not know.

Classify every field you name as one of:

| | |
|---|---|
| **FILL** | the user types a value here |
| **VERIFY** | the portal pre-fills it from AIS/26AS — check it, do not assume |
| **AUTO** | computed from another schedule, read-only |
| **SKIP** | not applicable to this return |

And where confidence is below about 90% — a screen nobody in this skill has recorded, a
row number you are inferring from an adjacent form — say so and **ask for a screenshot**.
*"I don't know this field"* is a first-class answer. Reconstructing it is not.

**Match on the label text, never the box number.** Labels are stable across years; numbers
are not.

The ITR-3 Select Schedule picker is the standing example: two attempts, one research pass
and one live filing, have failed to capture it. It stays marked `[UNVERIFIED]` rather than
being filled in with something reasonable.

**Order matters** — later schedules pull from earlier ones:

```
Part A-Gen  →  Part A-BS  →  Part A-P&L  →  Part A-OI  →  BP
     →  Salary  →  112A  →  CG  →  OS  →  IF
     →  CYLA  →  BFLA  →  CFL  →  UD  →  AMTC  →  SI
     →  Part B-TI  →  Tax Paid  →  Part B-TTI
```

Schedule 112A **before** Schedule CG. CG pulls the LTCG figure from 112A;
reversed, you re-enter it.

**Schedule CG's Table F is the exception — fill it LAST**, after CYLA, BFLA and CFL
are confirmed. It takes figures net of all set-off and must tie to BFLA row for row.
Filling it in document order, with gross quarterly figures, is the single most common
way an otherwise-correct ITR-2 fails validation.

Confirm each schedule as you go. Re-confirm CYLA / BFLA / Part B-TI / Part B-TTI
after *any* upstream edit — they cache.

## Phase 5b — The deliverable

Produce **one document, not several.** Iterating across a pile of files loses the reader.

A single self-contained HTML file with tabs:

- **Working paper** — the tie-out, the computation, resolved questions and open judgement
  calls. This is the defensible record of *why* each figure is what it is.
- **Walkthrough** — numbered steps, each with the screen it happens on, a table of exact
  field-to-value pairs, and the traps that bite on that screen. Tickable, with progress.
- Add tabs for the schedule map, other forms, or a trap library only when they earn their
  place.

Two things make it usable rather than merely complete:

**A detail toggle.** Simple mode shows one plain sentence per step — *"Open item 2, click
+ Add Another, choose 111A [for others], then type four numbers"* — and hides rule
numbers, JSON field names and conflicts. Detailed mode shows everything. Ask which they
want (Phase 0) and default to Simple.

**Visual differentiation by action type** — navigate, enter data, verify, pay. A filer
scanning for "what do I actually type here" should not have to read prose to find it.

Deliver it early and update it in place as facts change, rather than producing a new
document each round. Say what changed each time.

## Phase 6 — Pre-flight

Before Proceed to Verification:

- [ ] Every schedule reads **Confirmed**
- [ ] "Return filed under section" reads **139(1)** where any loss is being carried
      forward — s.139(3) denies the carry-forward on a belated return
- [ ] Total income matches your independent computation
- [ ] Refund/payable matches (allow ±₹10, s.288B rounding)
- [ ] Every TDS row in 26AS appears in Tax Paid, with a head of income mapped
- [ ] Sum of income offered ≥ gross amounts against claimed TDS rows
- [ ] Bank account for refund is validated and EVC-enabled
- [ ] Address is current
- [ ] No schedule contradicts Part A-Gen (see traps file)

Validation defect categories:

- **Category A** — blocks upload. Must fix.
- **Category B/D** — advisory. Read it, decide, usually proceed. Many fire for
  every filer of that form.

Download the JSON at this screen and read it. It is far faster to audit than the
80-page preview PDF, and it is the only way to see flags the UI hides.

**Beware stale downloads.** The portal reuses the filename. Compare
`CreationInfo.Digest` against the previous copy — identical digest means you are
reading an old file.

## Phase 7 — File and after

Submit → **e-verify within 30 days** (Aadhaar OTP is fastest). Unverified is
treated as never filed. Save the ITR-V, the final JSON and the acknowledgement.

Tell the user their revised-return window. For AY 2026-27 that is **31 March 2027**
(Finance Act 2026 moved it from 31 December), with a **s.234-I fee** of ₹1,000 where
total income is ≤ ₹5 lakh, ₹5,000 otherwise, on revisions filed **after 31 December
2026**. Belated filing u/s 139(4) is unchanged at 31 December. Anything you flagged as a
judgement call goes in that window.

**Filing is not the end.** Read `references/post-filing.md` and give the user the
calendar: e-verify within 30 days or the return becomes belated and the loss
carry-forward is lost; watch Pending Actions weekly for a 139(9) defect (15 days to
respond) or a 143(1)(a) proposed adjustment (30 days); re-check AIS in Oct–Nov because it
keeps updating after you file. Know the difference between a rectification and a revised
return before the user needs it — wrong data needs a revision, wrong processing needs a
rectification, and getting it backwards can burn the 139(5) window.

---

## Verify your own numbers

Every rate, limit, threshold and date this skill uses is **shape, not truth** — it goes
stale annually and mid-year amendments happen. Before delivering any computation, record
what you actually checked:

| Rule | Value used | Source URL | Checked on |
|---|---|---|---|
| e.g. new-regime slabs AY 2026-27 | 0/5/10/15/20/25/30 at 4/8/12/16/20/24L | incometax.gov.in/… | 2026-07-28 |

**A rule used but not recorded here is a defect.** This is not paperwork — it is the only
mechanism that converts "the model remembered a slab" into something a reader can falsify.
The reference files are a starting point for what to check, never the authority.

## Evidence tags

Every non-obvious claim in the reference files carries its provenance, because this domain
punishes confident wrongness and the portal is under-documented:

- **[observed]** — someone saw this on a live screen, or read it out of a filed JSON or
  preview PDF
- **[documented]** — it is in a notified form, a validation-rules PDF, a JSON schema or an
  official manual
- **[inferred]** — reasoned from something adjacent; plausible, not confirmed
- **[UNVERIFIED]** — asserted at some point and never confirmed; may be wrong

**Do not launder a memory into a fact.** Two claims in this skill were demoted after
re-examination — the A19(b) revert and the intraday business code — and both had been
stated with total confidence. When a source and a screen disagree, record the conflict
rather than picking a winner, and say what would resolve it.

## Working style

- Show the tie-out. "₹6,50,321 + ₹1,95,290 = ₹8,45,611 against AIS ₹8,45,610"
  buys more trust than any assertion.
- When the portal and your computation differ, find the cause before moving on.
- When a form limitation forces a reporting choice, say so explicitly, give the
  options with their consequences, and note that both may be defensible.
- Never pick the option that reduces tax on a factual question the user hasn't
  answered. "Exempt Income" is always sitting right there in the dropdown.
- Distinguish "this is settled law" from "this is what practitioners do" from
  "this is my read." The user is signing it.
