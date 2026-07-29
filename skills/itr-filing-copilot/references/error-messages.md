# Error messages, verbatim

Portal error text, recorded exactly as rendered, with where it fires and what actually
cleared it. This is the hardest material to obtain and the most useful — the wording is not
published anywhere, and searching for it is how a stuck filer finds the fix.

All entries `[observed]` on live AY 2026-27 filings unless marked otherwise.

---

## Category A — blocks upload

Screen header:

> **Internal Validation** · ITR3
> *Category of Defect A - You will not be allowed to upload the return, kindly correct the
> below errors in order to proceed further.*
> *3 Error(s) found*

### A19(b) not set — fires twice, one fix

| Field | Error text |
|---|---|
| `A19(b). Do you have income from business or profession for current Assessment Year?` | *"Please select Yes for 'Do you have income from business or profession for current AY' if you have any income from Business or Profession."* |
| `48. Income from specified business (46 – 47)` | *"Please select option as 'Yes' at Sl.no.A19(b) of Part A General as there is Business income / loss"* |

**Fix:** set A19(b) = Yes in Part A-General. One change clears both.

**The trap:** the second error is filed under a **Schedule BP** field number while the fix is
in **Part A-General**. Chasing "item 48" puts you on the wrong screen.

**It also appears inline, before any validation run** — as a red callout directly under
item 48 while editing Schedule BP section C. The form warns you in place if you look.

### TDS-2 head of income not selected

| Field | Error text |
|---|---|
| `Head of Income (Col 12)` | *"Please select the drop down of head of income for which corresponding income offered in schedule TDS2"* |

**Fix:** select any value in the Head of Income dropdown on the TDS-2 row.

**Selecting a value is all the portal checks.** In one filing, choosing *Income from Other
Sources* while an invented ₹5,43,210 receipt was still sitting in Schedule S **passed validation and
produced a full preview PDF**. Moving the amount to Schedule OS afterwards was a judgement
call about internal consistency against a later s.139(9) defect — **not** something the
portal required. The mismatched state validated cleanly.

That is the whole reason to audit the JSON: the portal does not check that the income is
where the TDS row says it is.

---

## Category B/D — advisory, uploads anyway

Screen header:

> **Upload Level Validation** · ITR3
> *Category of Defect B/D - You will be allowed to upload the return. There is a possible
> defect present in the return or some of the deduction/claim may not be allowed.*
> *1 Error(s) found*

### Dividend consistency, BP vs OS

| Error Description | Suggestions |
|---|---|
| *"If you are required to prepare/maintain books of account and dividend income is reported in Profit & Loss Account, please ensure consistency between amount of dividend income reduced in Sch. BP and dividend income reported in Sch OS. Please ignore if not applicable."* | *"Kindly ensure that dividend income mentioned in schedule OS should be equal to dividend income reduced from Schedule BP."* |

**Fix:** none needed in a no-books case with no dividend credited to the P&L — both figures
are zero, so the consistency it wants is already satisfied. The text ends *"Please ignore if
not applicable."* Proceeded past it; the return filed and e-verified without incident.

---

## Inline field messages

### Schedule OS item 1e, Nature field

> *"Maximum 50 characters are required"*

Fired on a 57-character description. **The wording is backwards** — it means *maximum*, not
minimum. Shortening to 46 characters cleared it.

### Schedule OS item 1a(i), dividend

> *"If the benefit of quarterly computation of interest u/s234C is sought, same may be
> claimed by making necessary modifications in Table 10 'Information about accrual/receipt
> of income from Other Sources'"*

Persistent advisory, not an error. Nothing to fix. It is telling you that entering a dividend
total without filling Table 10 forfeits quarterly 234C relief.

---

## Documented but not yet seen in the wild

From the CBDT validation-rules PDFs — the rule text, not necessarily the rendered message:

| Context | Rule text |
|---|---|
| Table F vs BFLA, ITR-2 | *"In Schedule CG, Table F Sl. No. 5 the breakup of all the quarters is not equal to the value from item 3vii of schedule BFLA"* — item 3vii is not visibly labelled anywhere in BFLA |
| CFL vs BFLA | *"The amount of adjustment mentioned in CFL is not equal to amount of adjustment in BFLA."* — the classic stale-cache failure after an upstream edit |
| ITR-4 financial particulars | *"Gross receipts/turnover are mentioned in schedule BP but Financial Particulars such as Sundry creditors, Inventories, Sundry debtors, cash in hand is not filled"* |
| ITR-3 dividend, Category A | *"In Schedule OS/ Schedule EI, the amount of dividend income mentioned is cannot be more than the dividend income reduced from Schedule BP"* |
| s.139(9) defect, PGBP | *"Income from 'Profits and Gains from Business or Profession' is greater than 1.2 lakhs but particulars as in 'Balance sheet/Profit & Loss Account' are not filled"* |
| s.139(9) defect, TDS | *"credit for TDS is being claimed, the corresponding receipts are not offered in the respective income schedules"* |

---

## How to use this file

When a filer is stuck, **ask for the error text verbatim** before theorising. The message
usually names a field that is not where the fix is, so the wording matters more than the
field reference.

When you hit a message that is not here, **record it** — field name, exact text, screen,
and what actually cleared it. That is the highest-value contribution anyone can make to this
skill.
