# Portal traps

Field-level failures observed on incometax.gov.in. Each entry: symptom → cause →
fix. Verify against the CBDT validation rules for the relevant form and AY:
`incometax.gov.in/iec/foportal/downloads` → "Validation Rules".

---

## Part A-General

### A19(b) resets and blocks Schedule BP

**Symptom** — Category A errors: *"Please select Yes for 'Do you have income
from business or profession for current AY'"* and *"Please select option as
'Yes' at Sl.no.A19(b) of Part A General as there is Business income / loss."*

**Cause** — A19(b) is `No` while Schedule BP carries any business or speculative
figure, even ₹-6. CBDT validation rules 39/40/46 for ITR-3.

**Fix** — Part A-Gen → A19(b) → **Yes**. A sub-question about the regime appears
(the `(I)` branch); pick the option that keeps the default new regime unless
Form 10-IEA has actually been filed.

**It may revert. [UNVERIFIED]** The claim that editing and re-saving Part A-Gen knocks A19(b)
back to No has never been directly observed by anyone who wrote it down — it was asserted from
memory and could not be confirmed on re-examination. What *is* observed on one filed ITR-3:
A19(b) not-Yes at the outset, the filer reporting BP validated, the same Category A errors
firing again at final validation, and `IncFrmBusOrProf: "Y"` in the filed JSON. That is equally
consistent with a revert and with the first fix never having saved.

The operational advice holds either way: **re-check A19(b) immediately before Proceed to
Verification**, and confirm it in the downloaded JSON rather than on screen.

### Seventh proviso to 139(1)

Prefill sets this `Y` with the TDS amount when aggregate TDS/TCS ≥ ₹25,000
(Rule 12AB). If total income already exceeds the basic exemption limit the filer
is caught by the main limb of 139(1) anyway, so `N` is defensible — but diverging
from prefill without reason invites questions. Low stakes; be deliberate.

### Flags that must not contradict schedules

`HeldUnlistedEqShrPrYrFlg = N` while Schedule CG reports consideration for
**unquoted shares** is a self-contradiction. See the residual-row trap below.

---

## Schedule Salary

### Deleting an entry leaves an empty schedule

Removing the only salary row zeroes the schedule but may leave it listed.
Harmless. Confirm the *income* is now zero in Part B-TI item 1.

### Nature of salary for a taxable PF withdrawal

Goes under **17(3) — profits in lieu of salary**, clause (ii) ("any payment…
from a provident or other fund"). Not 17(1) (there is no employment), not
17(3)(i) (termination compensation).

---

## Schedule TDS-2 — the head-of-income trap

**Symptom** — Category A error: *"Please select the drop down of head of income
for which corresponding income offered in schedule TDS2."* The dropdown offers
House Property / Business and Profession / Capital Gains / Other Sources /
Exempt Income / Not Applicable (194N). **There is no Salary option.**

**Cause** — s.192A (PF withdrawal) TDS is filed by EPFO in Form 26Q, so the
portal prefills it into TDS-2, which structurally cannot point at Salary.

**Consequences**

- Do **not** hand-add the row to Schedule TDS-1. CPC matches TDS-1 against
  Form 24Q; an unmatched claim can get the entire credit disallowed.
- Do **not** pick *Exempt Income* to make it go away — that is a factual claim
  about the 5-year rule.
- Either keep the income in Salary and accept a label mismatch, or move it to
  Other Sources so the return is internally consistent. Under the new regime
  with the s.87A rebate in play, both produce the same tax; the difference is
  only the ₹75,000 standard deduction, which the rebate absorbs.

Whichever you choose, **the gross amount must be offered somewhere.** The
s.139(9) defect is *"credit for TDS is being claimed, the corresponding receipts
are not offered in the respective income schedules."*

---

## Schedule 112A

- Consolidated entry is accepted: ISIN `INNOTREQUIRD`, name `CONSOLIDATED`,
  quantity `0`, price `0`, with the totals populated.
- Answer **"After 31st January, 2018"** unless holdings genuinely predate it —
  this greys out the FMV/grandfathering columns.
- If quantity `0` is rejected, use real total quantity and a derived average
  price that multiplies back to the sale value.
- Upload CSV is stricter than manual entry. Prefer manual for one row.

## Schedule CG

### The "other assets" row is A5 in ITR-2 and A6 in ITR-3

**Symptom** — a listed ETF or debt fund entered in the wrong row, or a row number that
does not exist on the screen in front of you.

**Cause** — the two forms number section A differently. **ITR-2**: A1 land/building,
A2 equity-with-STT (111A), A3 and A4 non-resident, **A5 "From sale of assets other than
at A1 or A2 or A3 or A4 above"**, A6 deemed STCG. **ITR-3** carries an extra slump-sale
row, which pushes "other assets" down to **A6**.

**Fix** — read the on-screen note. *"Sub-items 3 and 4 are not applicable for residents"*
tells you the non-resident rows are 3 and 4, so the residual row is the next one. Confirm
against the current AY's validation rules; the composition of the applicable-rate bucket
(`A1e + A3b + A5e + A6 + A7c` in ITR-2 AY 2026-27) identifies the row unambiguously.

### The residual row puts consideration under "unquoted shares" by default

**Symptom** — the JSON shows `FullValueConsdRecvUnqshr` and `FullValueConsdSec50CA`
populated for a listed ETF.

**Cause** — sub-item (a)(i) is the unquoted-shares block; (a)(ii) is everything else. The
cursor lands on the first field you see. In ITR-2 that is A5(a)(i)(a); in ITR-3, 6a(i)a.

**Fix** — zero (a)(i)(a) and (a)(i)(b), put the amount in **(a)(ii)**. Otherwise the
return claims an unquoted-share sale, invokes s.50CA fair-value substitution — the
validation rule forces (a)(i)(c) to the higher of (a)(i)(a) and (a)(i)(b) — and
contradicts `HeldUnlistedEqShrPrYrFlg = N`.

The same (ia/ib/ic/ii/iii) structure repeats in the non-resident and long-term residual
blocks. The trap is not unique to one row.

### Accrual table (section F) with loss-making quarters

The quarter columns must sum to the head total and will not take negatives. When
real quarters net negative, load the annual net into the **last** applicable
bucket and say why. Safe whenever total tax is below the ₹10,000 advance-tax
threshold in s.208 — 234C is nil on any allocation. Where a category's quarters
are all positive (often the debt-fund bucket), report them as they happened.

### Rate rows change every year

AY 2026-27: STCG 111A **20%**, LTCG 112A **12.5%** with a ₹1,25,000 exemption.
The AY 2025-26 before/after-23-July split is gone. Don't carry last year's rows
forward.

---

## Schedule OS

- Free-text "Nature" on the 1e breakup is capped at **50 characters**. The error
  reads *"Maximum 50 characters are required"* — it means maximum, not minimum.
- Item 1e's named sub-rows (family pension, s.89A, 56(2)(xii)/(xiii)) are fixed.
  The generic row is behind the **last** "+ Add Another".
- Item **2c "Accumulated balance of recognised provident fund taxable u/s 111"**
  is not a convenient label for a taxable PF withdrawal. It is the s.111 /
  Rule 9 machinery, where tax is the *aggregate additional tax across each
  earlier year* had the fund been unrecognised. For someone who was in the 30%
  bracket in those years it is dramatically more expensive than slab rates.
  Only use it deliberately.
- Quarterly dividend breakup drives 234C. Row 3(a) maps to item 1a(i).

## Schedules that appear on their own

Adding business income makes **Part A-OI**, **Schedule UD** and the 80-IA/IB/IE
family appear. None are mandatory without a 44AB audit. Confirm them empty
rather than leaving them on "Provide your confirmation" — unconfirmed schedules
can block Proceed to Verification.

**Schedule VI-A disappears** once the new regime is locked in. Expected, not a
deletion.

---

## Category B/D advisories that are usually noise

> *"If you are required to prepare/maintain books of account and dividend income
> is reported in Profit & Loss Account, please ensure consistency between amount
> of dividend income reduced in Sch. BP and dividend income reported in Sch OS."*

Fires for essentially every ITR-3 filer. Not applicable in a no-accounts case
where no dividend was credited to the P&L — both figures are zero. The text ends
"Please ignore if not applicable."

---

## Speculative business (intraday)

- Turnover = aggregate of positive **and** negative differences (ICAI Guidance Note), not
  sell value. Brokers report this correctly; use their figure.
- **Nature of business code — UNRESOLVED CONFLICT. Do not state a code with confidence.**

  | Source | Says |
  |---|---|
  | `NatOfBus` enum, ITR-3 JSON schema AY 2026-27 [documented] | `21009` = "Speculative trading" · `21010` = "Futures and Options trading" · `21011` = "Buying and selling shares" |
  | A **filed** AY 2026-27 ITR-3 JSON [observed] | `Code: "21011", Description: "Intraday trading in listed equity shares"` — the description string is the **portal's own**, paired with 21011 |

  Either the online form mislabels 21011, or the wrong code was selected against a
  coincidentally plausible description. **Nobody has reported seeing the dropdown itself.**

  Operationally: **verify the `Code` in the downloaded JSON, never the `Description`.** The
  description renders from the code, so a wrong code shows a wrong-but-convincing label. If
  you can see the dropdown, record what it actually offers — that resolves this.
- **Where it goes in ITR-3, no-books case:** Part A-P&L item **65** (65i turnover, 65ii gross
  profit, 65iii expenditure, 65iv net) → Schedule BP item **2a** (rule 119) → **B39**
  (rule 280) → **B42** = B39 + B40 − B41 (rule 266) → a loss goes to Schedule CFL (rule 238).

  **"CFL 6xix" is a conflation of two different printed strings** — check which one you mean.
  BP item 42 prints *"if loss, take the figure to **6ix** of schedule CFL"*. Part B-TI item 18
  prints *"total of row **xix** of Schedule CFL"*. Both verbatim from a filed return's preview.
- **s.73 nuance, usually told wrong.** Speculative *income* **does** appear in Schedule CYLA
  (rule 562) — it can absorb house-property and other-source losses. What never appears is a
  speculative *loss*: s.73(1) bars inter-head set-off, so intra-head set-off happens in
  **BP Table E** and the residue goes straight to CFL 6xix, bypassing CYLA.
- Carried 4 years, and only if filed by the due date.
- **New for AY 2026-27: Trading Account items 12a–12d** — 12a intraday turnover, 12b intraday
  income, 12c F&O turnover, 12d F&O income (rules 77/78/79). These sit in the *books*
  path. In a no-books case rule 119 contemplates 12b = 0, but there is **no no-books
  equivalent for F&O turnover** — F&O falls into P&L 64(i) with no turnover disclosure.
  Practitioners warn that leaving 12a–12d blank risks a s.139(9) defect. A genuine form
  limitation; flag it rather than silently picking a side.

## Due dates diverge by INCOME CATEGORY, not by form — AY 2026-27

The Finance Act 2026 substituted Explanation 2 to s.139(1) with effect from 1 March 2026
and added a new 31 August slot:

| Category | Due date | Basis |
|---|---|---|
| No business or professional income | **31 July 2026** | Expl. 2(d) |
| Business or profession, accounts **not** liable to audit u/s 44AB | **31 August 2026** | Expl. 2(c) |
| Accounts liable to audit u/s 44AB; companies; working partner of an audited firm | **31 October 2026** | Expl. 2(b) |
| s.92E transfer-pricing report required | **30 November 2026** | Expl. 2(a) |

**Reason from the income and the audit test, never from the form number.** ITR-3 is the
form most non-audit business filers use, so "ITR-3 → 31 August" is right most of the time
and wrong exactly when it matters: an audit-liable ITR-3 filer gets 31 October, and an
ITR-2 filer gets 31 July however large their income.

The notified ITR-3's own due-date dropdown at A19(ai) offers **31st August / 31st October /
30th November** — 31 July is not an option, which is the cleanest confirmation available.

Consequence: a salaried filer who picks up ₹6 of intraday moves from a 31 July deadline to a
31 August one, and both the Form 10-IEA deadline and the s.80 loss-carry-forward deadline move
with it. Still treat `ItrFilingDueDate` in the prefill JSON as authoritative for the actual
case in front of you.

## Paying the challan

### The bank's own maintenance window

**SBI net banking refuses transactions between 11:00 PM and 00:15 AM IST.** [observed]

> *"Your Transaction cannot be processed during the period between 11.00 PM and 00.15 AM.
> Kindly try after 00.15 AM"*

You only see it after leaving the portal and reaching the bank. Other banks have their own
windows. **Do not wait it out** — e-Pay Tax also offers NEFT/RTGS, payment gateway (UPI, debit
card, another bank's net banking) and over-the-counter. Switch route.

Late-night filing on the last few days before the due date is exactly when this bites.

### Part B-TTI keeps saying "Pay Now" after you have paid

**Symptom** — the challan is paid and the receipt is in hand, but Part B-TTI still shows a
balance payable and a `Pay Now` button.

**Cause** — paying does not put the challan in the return. `ScheduleIT.TotalTaxPayments`
stays `0` and `PartB_TTI.TaxPaid.TaxesPaid.SelfAssessmentTax` stays `0` until you enter it
by hand. Auto-population takes **2–3 working days**, which you do not have near the due
date. [observed]

**Fix** — Return Summary → **Tax Paid** → *Advance Tax and Self Assessment Tax* →
**+ Add Another** → four fields off the challan receipt:

| Field | From the receipt |
|---|---|
| BSR Code | `BSR code` — 7 digits |
| Challan Serial Number | `Challan No` — 5 digits, **not** the CIN |
| Date of Deposit | `Date of Deposit` |
| Amount | put the whole amount under **Tax**; surcharge, cess, interest, penalty stay 0 |

Then **re-open Part B-TTI and Confirm it again.** It caches and will not refresh on its own —
this is the same staleness that bites CYLA and BFLA after any upstream edit.

**Do not enter the CIN in the challan-number field.** The CIN (e.g.
`2607280090XXXXNNNN`) is the composite identifier; the portal wants the 5-digit `Challan No`.

### The few rupees left over after paying

**Symptom** — in this synthetic illustration, liability ₹1,23,184, taxes paid
₹1,23,180, and the filer sees a ₹4 gap and assumes the payment was short.

**Cause** — **s.288B rounds the amount payable to the nearest ₹10**, and the observed
portal behaviour applied it twice: once to the amount it told the filer to pay and again
to the residue (₹4 → ₹0). The amounts above are invented; the double-rounding behaviour
is [observed].

**Nothing to do.** Item 16 "Amount Payable" correctly reads ₹0. CPC applies the same
rounding, and CBDT instructions bar enforcing demands below ₹100. Reassure and move on —
paying the extra ₹4 would create an unmatched challan, not a cleaner return.

The same rounding runs the other way on refunds: a computed ₹66,243 files as ₹66,240.

### Getting logged out mid-payment

The e-Pay Tax detour can end with the ITR session timed out. **Nothing confirmed is lost.**
Log back in → e-File → Income Tax Returns → File Income Tax Return → **Resume Filing**.
**Never "Start New Filing"** — that discards the draft.

You can also file first and pay after; the return simply carries the payable. Paying first is
better where the due date is close, so the challan sits in Taxes Paid and the return files as
nil-due.

## Session hygiene

- 15-minute idle timeout, reset on each save. Don't leave a schedule half-filled.
- Confirmed schedules survive a timeout; the in-progress one does not.
- The preview PDF regenerates on each run — page count changing is a useful
  signal that an edit landed.
