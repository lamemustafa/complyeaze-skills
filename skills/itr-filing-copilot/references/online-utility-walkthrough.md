# The online utility — what you actually click

Mechanics of the ITR-2 / ITR-3 online flow on incometax.gov.in. Companion to
`portal-traps.md` (field-level failures) and `schedule-sections.md` (which section a
figure belongs to). This file is about navigation and the shape of the interaction.

Verified against the ITD user manual and FAQs for AY 2026-27 where marked; items marked
**unverified** need eyes on a live screen before you rely on them.

---

## The chain

```
Login  →  e-File › Income Tax Returns › File Income Tax Return
  →  Assessment Year + Original/Revised          → Continue
  →  Filing mode: Online                          → Continue
       (a saved draft offers "Resume Filing" vs "Start New Filing";
        starting new DISCARDS the draft)
  →  Status: Individual / HUF / Other             → Continue
  →  "I know which ITR Form I need to file"       → Proceed with ITR
  →  Document checklist                           → Let's Get Started
  →  Reason for filing                            → Continue
  →  "Are you opting for new Regime: Yes/No"      → Continue
  →  SELECT SCHEDULE  (see schedule-sections.md)  → Continue
  →  RETURN SUMMARY  ← the hub; everything below opens from here
  →  Part B-TTI: Pay Now / Pay Later
  →  Place + declaration                          → Proceed to Preview
  →  Preview Return                               → Proceed to Validation
  →  Validation                                   → Proceed to Verification
  →  e-Verify Now / Later / ITR-V by post
```

Read the regime question carefully. The wording flips between years and between "are you
opting for the new regime" and "are you opting out u/s 115BAC(6)". Answer the sentence in
front of you, not the one you remember.

## Return Summary is the hub

Every schedule ticked at Select Schedule appears here, with running totals that update as
schedules are confirmed. Click a schedule name → it opens as a **full page**, not a modal
→ fill → **Confirm** at the bottom → you are returned here. **Back** returns without
committing.

**The unit of commit is the schedule.** The manual repeats *"Click Confirm at the end of
each section"* for every section. Confirm validates that schedule's internal arithmetic,
writes it to the draft, and pushes its totals into Part B-TI/TTI.

There is no reliable global save. **Confirm often — that is the save.** A partly filled
return resurfaces later as *Resume Filing*.

**Unverified:** the exact icon/colour distinguishing confirmed from in-progress from
untouched on Return Summary. Also unverified: whether a literal *Save Draft* button
exists on the current screens.

Reopening a confirmed schedule and changing anything requires pressing **Confirm** again
or the change does not propagate.

## Inside a schedule: the three-tier button pattern

1. **Expand an accordion** — one per asset class or block. There is an **Expand All**
   control at the top of long schedules.
2. **Add Details** — appears inside a sub-item when it is empty. Opens the row form.
3. **Add Another** — adds a second row once the first exists. Rows get **Edit** and
   **Delete** icons.

Nested adds are real: the outer accordion holds the asset class, *Add Details* opens the
sub-item, and inside a sub-item like 112A or a property sale a further *Add* creates each
individual row. Property sales need one row **per property**, with buyer name / PAN /
address nested inside each row.

**Confirm sits at the bottom of the whole schedule page**, not per accordion.

Schedule CG throws a pop-up on entry — it is the reminder to report figures net of
loss. Click OK.

## Schedule 112A — manual vs CSV

Manual row entry is stricter-proof than CSV. **Prefer manual for a small number of rows.**

Buttons on the 112A screen: **Download Template**, **Upload CSV**, **Need Help** (opens
`112A_115AD_CSV_Instructions.pdf` on static.incometax.gov.in). The template itself ships
with the utility rather than as a separate download.

CSV columns 1a–14. The ones that matter:

| Col | Field | Rule |
|---|---|---|
| 1a | Share/unit acquired | `BE` = on or before 31 Jan 2018 · `AE` = after |
| 2 | ISIN | first two chars `IN`. No ISIN → `INNOTAVAILAB`. If 1a = `AE` → `INNOTREQUIRD` |
| 3 | Name | alphanumeric only. If 1a = `AE` → `CONSOLIDATED` |
| 4 | Quantity | **blank if 1a = `AE`** |
| 5 | Sale price per unit | **blank if 1a = `AE`** |
| 6 | Full value of consideration | `BE`: col 4 × col 5. `AE`: the actual total |
| 12 | Expenditure on transfer | rule 88: col 13 total deductions = col 7 + col 12 |

**Quantity 0 and price 0 were accepted** on a filed AY 2026-27 return [observed] — earlier
guidance to substitute a real quantity and a derived average price is a fallback, not the
expected path.

**Consolidated single row** for everything acquired after 31 Jan 2018 (no grandfathering
to compute): `1a = AE`, ISIN `INNOTREQUIRD`, name `CONSOLIDATED`, quantity and price
**blank**, consideration and cost as totals. Validation rule 173 enforces the blanks:
*"Value at Column no. 4,5,10 & 11 cannot be greater than zero in case drop down is
selected as 'After 31st January 2018'."*

Grandfathered (`BE`) holdings still need one row per scrip — FMV on 31 Jan 2018 is
scrip-specific.

CSV failure modes: any edit to the header row rejects the whole file · trailing blank
rows break the parse · dates DD/MM/YYYY · amounts in rupees not lakhs · ISIN exactly 12
characters, case-sensitive.

## The Table F ↔ BFLA mismatch

The most common hard block on ITR-2. Covered in `schedule-sections.md`; the mechanical
rule is: **fill Table F last, from BFLA's final column, net of all set-off.** If the net
is a loss or nil, leave it blank.

Don't click the error hyperlinks on this family of errors — they jump to the wrong place.
Navigate manually, and log out and back in before re-validating; the validator caches
stale state.

## Two validation stages, on different URLs

`Proceed To Verification` runs **Internal Validation** first, then **Upload Level Validation**.
They are separate screens on separate routes. Clearing the first does not mean you are done.
[observed]

```
/foreturns-ay26/fo-itr-shared/fo-internal-validation      ← Category A, blocks
/foreturns-ay26/fo-itr<n>-ay2026/fo-upload-level-validation ← Category B/D, advisory
```

**The button row is the reliable blocking signal — more reliable than the header text.**
[observed]

| Screen | Buttons offered |
|---|---|
| Internal Validation (Category A) | `< Back` · `Download JSON` |
| Upload Level Validation (Category B/D) | `< Back` · `Download JSON` · **`Proceed To Verification`** |

If `Proceed To Verification` is absent, you are blocked. If it is present, the errors on screen
are advisory whatever they sound like.

**The two error tables have different columns**, which is why B/D advisories are so much harder
to action: [observed]

| Screen | Columns |
|---|---|
| Category A | `Sl. Number` · **`FieldName`** · `Error Description` |
| Category B/D | `Sl. No` · `Error Description` · **`Suggestions`** — **no FieldName at all** |

**The cells render as plain text — no hyperlinks were observed.** [observed] Earlier guidance in
this skill to "not click the error hyperlinks because they jump to the wrong place" is
unsupported; there may be nothing to click. Navigate manually either way.

**Errors are filed under the field that *detects* them, not the field that *fixes* them.**
One Category A error was listed against `48. Income from specified business (46 – 47)` — a
Schedule BP field — while the fix was A19(b) in Part A-General, a different Part entirely.
Anyone chasing "item 48" is on the wrong screen. [observed]

## Validation categories

The AY 2026-27 ITR-2 validation rules document defines two:

- **Category A** — *"Return will not be allowed to be uploaded. Error message will be
  displayed."* Hard block.
- **Category D** — *"Return data will be allowed to be uploaded but the taxpayer … will
  be informed of a possibility of some of the deduction or claim not to be allowed or
  entertained unless the return is accompanied by the respective claim forms or
  particulars."* Warning; filing proceeds.

**Category B is legacy terminology** and does not appear in the AY 2026-27 ITR-2 rules.
Treat A as blocking and D as advisory.

## Paying self-assessment tax

Part B-TTI offers **Pay Now** or **Pay Later**. Pay Later carries the warning about being
treated as an assessee in default, plus interest. Pay Now redirects to **e-Pay Tax** →
pay → **Return to Filing**.

**Minor Head 300 — Self Assessment Tax**, correct assessment year. The challan goes into
Taxes Paid → *Advance Tax and Self Assessment Tax*: BSR code, challan serial number, date
of deposit, amount split across tax / surcharge / cess / 234A / 234B / 234C.

Auto-population takes 2–3 working days and a freshly paid challan does not appear on
every screen at the same moment. **Enter it manually** rather than waiting.

## Known utility bugs worth checking around

- **BFLA / CFL carry-forwards reported as zero in the final return, without warning** —
  online-utility-specific; the Excel utility is unaffected. No official statement.
  **Read the preview PDF's CFL page before submitting**, not just the on-screen schedule.
- **Table F rejects negative values** and then throws the tally error anyway. Enter 0 for
  loss quarters and make the positives sum to the BFLA figure.
- **Brought-forward losses do not auto-populate.** Key them in from the prior year's
  acknowledgement.
- **Save hangs** on some builds; remedies offered are clearing cache, incognito, or
  switching to the offline JSON utility.
- Prefilled capital-gains cost basis is frequently wrong and gets accepted uncritically.
  Every prefilled field is editable and your edit wins.

## AY 2026-27 changes to the flow

- **The 23-July-2024 before/after split is gone** from Schedule CG and Schedule 112A.
  Most AY 2025-26 forum advice about that split is now obsolete — including threads
  discussing a 112A column `1(b)`.
- New **secondary address** question in Part A-Gen: *"Is the secondary address same as
  primary address."* A required click on the first data screen.
- TDS schedules now require the **section code** under which tax was deducted.
- 80G now demands transaction reference number and bank IFSC; 80GGC demands the political
  party's name and PAN.
- **s.234-I fee on late revised returns — confirmed `[documented]`.** Inserted into the
  1961 Act by the Finance Act 2026, clause 12. ₹1,000 where total income ≤ ₹5 lakh,
  ₹5,000 otherwise, on a s.139(5) revision filed **after 31 December 2026**. The utility
  encodes it directly — ITR-1 validation rules 324/328 and ITR-2 rules 694/695 read
  *"…if ITR is filed after 31/12/2026 and filing section is 139(5)…"*.

  Note the drafting defect in the gazetted text: it charges the fee for filings *"beyond
  nine months but before twelve months from the end of the relevant **assessment
  year**"*, which is unreachable, since s.139(5) closes the window at the end of the
  assessment year. "Previous year" is plainly meant — the twin provision in the
  Income-tax Act 2025 (s.428(b)) runs the clock from the end of the tax year. **Follow
  the utility, not the literal text**, and see `post-filing.md`.

## Verification

*"It is mandatory to verify your return."* e-Verify Now (Aadhaar OTP, net banking, bank
or demat EVC, DSC), e-Verify Later within 30 days, or signed ITR-V to CPC Bengaluru
within 30 days. An unverified return is treated as never filed — which also takes any
loss carry-forward with it.

Save the ITR-V, the acknowledgement and the final JSON.
