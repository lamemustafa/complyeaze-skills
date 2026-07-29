# ITR-1, ITR-3 and ITR-4 — flows, sections and traps

`schedule-sections.md` covers ITR-2 in depth. This file covers the other three, and the
structural differences that matter before you start filling anything.

**The Select Schedule screen exists only on ITR-2 and ITR-3.** ITR-1 and ITR-4 use fixed
section flows — there is nothing to tick, and nothing to forget to tick.

---

# ITR-1 (Sahaj)

Resident (ROR) individual, total income up to ₹50 lakh. **Due date 31 July 2026.**

## Flow — five fixed sections

```
Personal Information → Gross Total Income → Total Deductions
  → Tax Paid → Total Tax Liability
```

All mandatory, each ends with **Confirm**. "Exempt Income" and "Long Term Capital Gains
u/s 112A" are sub-sections **inside Gross Total Income** per the official manual — though
ITR-4's manual promotes both to top-level sections, so the live ITR-1 utility may differ.
Check on screen.

## New for AY 2026-27

- **Two house properties** (was one), with co-owner details for up to seven co-owners
  (name, PAN, Aadhaar, % share), up to three tenants, and a new **"rent which cannot be
  realised"** field.
- **Aadhaar Enrolment ID no longer accepted** — 12-digit Aadhaar only.
- Chapter VI-A now requires dropdown clause selection, plus loan amount / interest / bank /
  account number for 80E, 80EE, 80EEA, 80EEB.
- 80G wants the transaction reference number and the recipient's IFSC; 80GGC wants the
  political party's name **and PAN**.

**LTCG 112A up to ₹1.25 lakh is NOT new for AY 2026-27** — it arrived in AY 2025-26. Don't
present it as this year's change.

## The 112A block

Three rows in the **Exempt Income** section: (i) total sale consideration, (ii) total cost
of acquisition, (iii) long-term capital gains as per s.112A.

- **A-217**: (iii) may not exceed ₹1,25,000
- **A-218**: (iii) must equal (i) − (ii)
- **A-22 / A-292**: it flows into **Gross Total Income**

**The label lies.** It sits in a box called "exempt income" but it is not exempt from GTI.
Filers cannot work out why their GTI moved. It also drives the rebate ceiling.

## What forces you out of ITR-1

There is **no Schedule CG, CYLA, BFLA or CFL**, so anything involving a capital loss has
nowhere to go.

→ **ITR-2**: any STCG at all · any LTCG other than 112A ≤ ₹1.25L · a capital **loss** ·
brought-forward losses · more than two properties · income above ₹50 lakh · agricultural
income above ₹5,000 · director in a company · unlisted shares held at any time · foreign
assets or income · RNOR / non-resident · ESOP deferral · TDS u/s 194N · **any special-rate
income** — the notified ITR-1 has **no row for lottery, crossword or online-gaming
winnings** (115BB / 115BBJ).

→ **ITR-3**: any business or professional income, including intraday and F&O; partner in a
firm or LLP.

**The portal will not stop a wrong-form ITR-1.** Special-rate income only fires Category B
advisories (B-3 to B-8), which do not block upload. CPC catches it later. Eligibility is
your job, not the validator's.

## Traps

| Trap | Rule |
|---|---|
| **Self-occupied housing-loan interest is nil under the new regime**, not ₹2 lakh | A-162 |
| **One row per interest type.** FDs at four banks aggregate into a single "Interest from Deposits" row; a second row is a Category A block | A-50/51/55/56 |
| **Rebate ceiling is ₹12,70,590, not ₹12,00,000** — marginal relief tapers above ₹12L | A-191 |
| Co-owned = Yes forces your own share strictly **below** 100%; your own PAN cannot be the co-owner | A-332, A-300 |
| Standard deduction ₹75,000 new regime, ₹50,000 old | A-215, A-112 |
| Entertainment allowance u/s 16(ii) is Government/PSU only, capped at ₹5,000 or 1/5th of salary | A-58, A-57 |
| Agricultural income shown as exempt cannot exceed ₹5,000 | A-29 |
| **Belated filing locks you into the new regime**, and revising a belated return does not recover the old one | A-151, A-190, A-189 |

## Regime

Item **A20**, a free annual toggle. **Form 10-IEA is not required** — only ITR-3, ITR-4 and
ITR-5 filers with business income need it. Under the new regime only **80CCD(2)** (14% of
salary for a private, PSU or government employer) and **80CCH** survive; everything else in
Chapter VI-A is forced to zero by rule A-146. 80JJAA does not appear on ITR-1 at all.

---

# ITR-3

Business or professional income, including intraday and F&O. **Due date 31 August 2026 if
the accounts are not liable to audit u/s 44AB; 31 October 2026 if they are.** The trigger is
audit liability, not the form.

## What ITR-2 does not have

The JSON schema's `required` array marks these mandatory: `PartA_GEN1`, `PartA_GEN2`,
**`PARTA_BS`**, **`PARTA_PL`**, **`ITR3ScheduleBP`**, `ScheduleCYLA`, `ScheduleBFLA`,
`PartB-TI`, `PartB_TTI`, `Verification`.

**Balance sheet and P&L are not optional even with no books** — you fill the no-accounts
blocks. Note `ScheduleCFL` is *not* in the schema `required` list even though the ITR-2 UI
tags CFL "(Mandatory)"; treat the UI as authoritative and confirm it either way.

Adding business income also surfaces **Part A-OI**, **Schedule UD** and the 80-IA/IB/IC
family. None is mandatory absent a 44AB audit — **confirm them empty** rather than leaving
them unconfirmed, which can block Proceed to Verification.

## Observed on a filed AY 2026-27 ITR-3

**The Select Schedule picker for ITR-3 is still unseen. [UNVERIFIED]** Two independent
attempts — one research pass, one actual filing — produced nothing: "Select Schedule"
appeared only as a breadcrumb. **Do not reconstruct it.**

What *is* known: the picker exists, sits before Return Summary, and **Return Summary carries a
`+ Add More Schedules` button that reopens it** [observed]. That is how you add a schedule you
did not select at the gate — you do not have to restart.

### Return Summary as observed — one ITR-3 filing

Salary + capital gains + intraday + partner in an LLP, new regime. `(Mandatory)` tags exactly
as rendered. [observed]

| # | On-screen label | Tag | How it arrived |
|---|---|---|---|
| 1 | Part A - General Information | **(Mandatory)** | at start |
| 2 | Part A - Balance Sheet | **(Mandatory)** | at start |
| 3 | Part A - P & L | **(Mandatory)** | at start |
| 4 | Part A - OI (Other Information) | — | appeared after business income |
| 5 | Schedule Salary | — | **added manually** |
| 6 | Schedule BP | **(Mandatory)** | at start |
| 7–9 | Schedule CG · 112A · Other Sources | — | at start |
| 10–11 | Schedule CYLA · BFLA | **(Mandatory)** | at start |
| 12 | Schedule CFL | — | **added manually** |
| 13 | Schedule UD | — | appeared after business income |
| 14–16 | Schedule 80-IA · 80-IB · 80-IE | — | appeared **greyed out / disabled** |
| 17–19 | Schedule AMTC · SI · IF | — | at start |
| 20 | Part B - TI | **(Mandatory)** | at start |
| 21 | Tax Paid | — | at start |
| 22 | Part B - TTI | **(Mandatory)** | at start |

"At start" means present when the summary was first seen — whether prefill ticked them or they
are always-on is not distinguishable from this. [UNVERIFIED]

Divergences from the verified ITR-2 map, all [observed]:

| Schedule | ITR-2 | ITR-3 |
|---|---|---|
| Schedule SI | tagged **(Mandatory)**, under Income | **no tag** |
| Tax Paid | tagged **(Mandatory)** | **no tag** |
| Schedule CFL | tagged **(Mandatory)** | **no tag**, and had to be **added manually** |
| Schedule VI-A | tagged **(Mandatory)** | tagged Mandatory early, then **vanished** once the new regime settled |
| Schedule AMTC | pre-ticked, no tag | present, no tag — same |
| CYLA / BFLA | Mandatory | Mandatory — same |

**CFL not being mandatory on ITR-3, and not appearing until added, is the dangerous one.** A
speculative loss with no CFL schedule on the form is a carry-forward silently lost.

**Schedule 10AA does not exist as a schedule in ITR-3.** It appears only as Part B-TI
item 13. Do not go looking for it in the schedule list.

**Part A-BS was filed entirely zero** — no item 6, no cash balance — **with no defect
notice** [observed]. Earlier guidance in this file to "fill it even at zero" is prudent,
not mandatory; a s.139(9) defect on this is a reported risk, not a certainty.

### Capital gains row numbers shift by one versus ITR-2

The extra slump-sale row displaces everything below it. [observed / documented]

| Want | ITR-2 | **ITR-3** |
|---|---|---|
| Equity with STT, short term (s.111A) | A2 | **A3** |
| Other assets, short term | A5 | **A6** |
| Equity with STT, long term (s.112A) | B3 | **B4** |

Quoting an ITR-2 row number at an ITR-3 filer sends them to the wrong block. Check which form
you are on before citing any row.

**Schedule CG section A is A6 for "other assets" — confirmed, not inferred.** Item 10's
total prints verbatim as `(A1e+ A2c+ A3e+A4a+ A4b+ A5e+ A6g +A7+A8 - A9a+A(A))`, and item 6
reads *"From sale of assets other than at A1 or A2 or A3 or A4 **or A5** above"*. The extra
row versus ITR-2 is slump sale — Section B item 2 prints *"From Slump Sale"* and the JSON
carries `SlumpSaleInStcg`. (That slump sale specifically occupies A2 remains [inferred];
A1 and A2 were never on screen.)

**Schedule CYLA row v is "Speculative Income"** [observed] — direct confirmation that
speculative *income* passes through CYLA while the loss does not.

## No-accounts blocks

**Part A-BS item 6** — "In a case where regular books of account of business or profession
are not maintained": 6a sundry debtors · 6b sundry creditors · 6c stock-in-trade · 6d cash
balance. Fill it even at zero. The item 1–5 "sources = application" tie-out does not
constrain item 6.

**Part A-P&L**: item **64** is non-speculative no-books (64i business, 64ii profession,
64iii total); item **65** is speculative no-books — **a standalone block, not a sub-part of 64**. Items
61–63 are the presumptive blocks (44AD / 44ADA / 44AE).

**Item 65's sub-labels are in conflict between sources:**

| Source | 65i | 65ii | 65iii | 65iv |
|---|---|---|---|---|
| Notified form PDF [documented] | Turnover from speculative activity | Gross Profit | Expenditure, if any | Net income (65ii − 65iii) |
| Filed return preview, as read [observed/inferred] | sum of favourable and unfavourable differences | favourable differences | unfavourable differences | net |

If the second reading is right, **the form's own structure encodes the ICAI turnover
definition** — turnover is not something you compute externally and type in; the form asks
for the components and adds them. That is a materially better mental model, and worth
confirming against a live screen. Until then, enter figures that satisfy both readings:
65i = total absolute differences, 65iv = the net.

For a pure-intraday salaried filer, **65 is the only block you touch**.

The real-world failure here is a s.139(9) defect rather than a Category A block:
*"Income from 'Profits and Gains from Business or Profession' is greater than 1.2 lakhs but
particulars as in 'Balance sheet/Profit & Loss Account' are not filled."* That threshold is
the s.44AA(2) books trigger. Fill 6a–6d and the 65 block regardless.

## Part A-Gen A19(b)

> **A19(b)** Do you have income from business or profession for current Assessment Year?
> **(I)** If Yes — have you filed ITR 3/4 and filed Form 10-IEA within the due date for any
> **earlier** assessment year for choosing old tax regime?
> **(II)** If No — do you wish to opt for old tax regime for the current AY?

Sub-question (I) is a **history** question, not a current-year election. With business
income the old-regime election runs through Form 10-IEA separately (rules 44/45).

Rules 39/40/46 make this a **bidirectional Category A lock**: A19(b) must be Yes if Schedule
BP carries anything, **and** BP must be non-zero if A19(b) is answered at all. Answering it
"just in case" on a return with no business income is itself a failure.

The A19(b)-reverts-on-resave behaviour is a field observation, not a documented rule — cheap
to guard against, so re-check immediately before Proceed to Verification.

## Rule 303 — the ITR-3 eligibility gate

*"ITR 3 should not be filed in case there is no business income"*, with enumerated
exceptions. Note exception 4: **a brought-forward speculative loss alone justifies ITR-3**
in a year with no current business income.

## Turnover and audit

Intraday and F&O turnover is the aggregate of **absolute** differences, positive and
negative (ICAI Guidance Note) — not sell value, not net.

| Clause | Trigger |
|---|---|
| 44AB(a) | business turnover > ₹1 crore → audit; raised to **₹10 crore** if cash *receipts* **and** cash *payments* are each ≤ 5% |
| 44AB(b) | profession gross receipts > ₹50 lakh. Do not confuse this with the ₹75 lakh **44ADA** presumptive ceiling — they are different tests. If receipts fall between the two, get a CA to confirm whether audit is triggered |
| 44AB(e) | opted 44AD in any of the preceding 5 AYs then declared below 44AD(1) → audit if total income exceeds the basic exemption limit |

**The A20 cash-percentage questions are gated. [observed]** Sub-questions a2ii (cash
receipts) and a2iii (cash payments) only render if a2i is answered *"More than Rs. 1 crore
and up to Rs. 10 crores"*. A small filer never sees the 5% tests at all — so their absence
from the screen is not a bug, and their presence means you have already declared turnover
above ₹1 crore.

A fully banked trader is at 0% cash on both legs, so the ₹10 crore limit applies — which is
why a mid-six-figure F&O book usually triggers no audit. Note 44AB(a) needs **both** tests;
s.44AD's enhanced limit uses the cash-*receipts* test only.

**Options premium is an open practitioner divergence.** The pre-2022 ICAI position added
premium received on sale of options to turnover; the 2022 revision dropped it as a blanket
rule. Both are defensible and they differ by an order of magnitude. It only matters near a
threshold — but say which you used.

**44AD does not extend to speculative business.** Mainstream practitioner position, not an
explicit CBDT statement. And 44AD is unavailable where there is a loss to carry forward —
declaring below the presumptive rate is exactly what triggers the 44AD(4) lock-out. For an
F&O loss: ITR-3 with the no-accounts P&L, not ITR-4.

## Dividend consistency

Behind the familiar Category D advisory sit two Category A rules — **289** (dividend reduced
in BP plus dividend offered in OS cannot exceed dividend at Part A-P&L 14(iii)) and **301**
(BP 5c dividend income cannot exceed zero). In a no-accounts case all three figures are
zero and the advisory is genuinely inapplicable.

---

# ITR-4 (Sugam)

Resident individual / HUF / firm other than LLP, income up to ₹50 lakh, presumptive business
under 44AD / 44ADA / 44AE. **Due date 31 August 2026** (presumptive filers are by definition
not audit-liable on that income).

## Flow — seven fixed sections

```
Personal Information → Gross Total Income → Disclosures and Exempt Income
  → Long term Capital Gains u/s 112A → Total Deductions
  → Taxes Paid → Total Tax Liability
```

The 112A block here is called **Schedule EI / D20(a)**, not "Exempt Income". Same three
rows; rule A-265 caps it at ₹1,25,000, A-343 and A-46 push it into GTI.

## Presumptive rates and ceilings

| Section | Rate | Ceiling |
|---|---|---|
| 44AD | **6%** on banked receipts (E1a); **8%** on cash (E1b) and other modes (E1c) | ₹2 crore, or **₹3 crore** if cash ≤ 5% |
| 44ADA | **50%** of gross receipts | ₹50 lakh, or **₹75 lakh** if cash ≤ 5% |
| 44AE | ₹7,500/month up to 12 MT; ₹1,000 per MT per month above 12 MT | 10 goods carriages |

**E1c is counted both ways** — receipts "in any mode other than a and b" attract the 8% rate
but do **not** count toward the 5% cash test that unlocks the ₹3 crore ceiling.

## The tripwire

Declare below the presumptive rate and: s.44AD(5) makes books mandatory under s.44AA;
s.44AB(e) makes audit mandatory if total income exceeds the basic exemption limit; and
s.44AD(4) locks you out of 44AD for the **five following assessment years**. Result: ITR-3,
not ITR-4.

**None of this is enforced by the portal** — `44AD(4)` appears nowhere in the validation
rules. The lock-out is entirely on the filer.

**Unresolved:** whether the "basic exemption limit" in s.44AB(e) is ₹4,00,000 (new regime,
the default) or ₹2,50,000 (old). No official confirmation found. Escalate rather than state
a number.

## Financial particulars — the most common upload failure

**Rule A-139 (Category A):** *"Gross receipts/turnover are mentioned in schedule BP but
Financial Particulars such as Sundry creditors, Inventories, Sundry debtors, cash in hand is
not filled."*

Enter **0** where genuinely nil rather than leaving blank. Presumptive filers routinely skip
these and cannot work out why upload fails.

Assets and liabilities need **not** balance — rules A-3 and A-4 each check only that the
stated total equals the sum of its own components. There is no E17 = E25 rule.

New for AY 2026-27: an **"Investments"** line at **E18a**, and the year-end bank balance at
E21 is now mandatory.

## Regime — Form 10-IEA IS required

Item **A23**. To use the old regime you must file **Form 10-IEA on or before the due date**,
then quote its acknowledgement number and date in the return. Doing it in the other order
produces Category B-12/B-13 mismatches — which do **not** block upload, so the problem
surfaces at CPC when the return is recomputed at new-regime rates.

**One-time lifetime switch**: having opted out to the old regime, you get exactly one move
back to the new regime, ever.

**Firms other than LLP must leave A23 blank** (rule A-264).

## Other traps

- **Commission agents and brokers cannot use 44AD** (A-10) — a very common wrong filing for
  insurance and property agents
- Professionals cannot use 44AD; businesses cannot use 44ADA (A-10, A-15)
- Business code and income are linked **bidirectionally** — declare one without the other and
  upload fails (A-11/12, A-16/17, A-137/138)
- Duplicate goods-carriage registration numbers are blocked (A-213)
- The business code lives **inside Schedule BP**, not in a Part A "Nature of Business" table —
  entered separately under each of the 44AD, 44ADA and 44AE blocks
- Code numbers change; pull them from the utility dropdown or the instructions annexure
  rather than from memory
