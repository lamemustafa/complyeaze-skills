# After the return is filed

The skill used to stop at e-verify. Most of what goes wrong for a taxpayer happens after
that, and almost all of it is silent — a notice in a portal tab nobody opens, a refund that
fails on an IFSC that changed in a bank merger, a carry-forward lost because verification
slipped past thirty days.

Tags: `[PRIMARY]` = incometax.gov.in / the Act / Finance Bill · `[SEC]` = corroborated
secondary · `[INFER]` · `[UNVERIFIED]`.

---

## The calendar — AY 2026-27

| Window | Deadline | Consequence of missing it |
|---|---|---|
| **e-verification** | **30 days** from transmission | Verified late → **the verification date becomes the filing date**. A timely return becomes belated: s.234F fee, s.234A interest, **loss carry-forward gone** |
| Belated return u/s 139(4) | **31 Dec 2026** — *unchanged* | Only ITR-U or condonation remain |
| **Revised return u/s 139(5)** | **31 Mar 2027** — **changed this year** | — |
| Revised return **free of fee** | **31 Dec 2026** | **s.234-I fee** applies after |
| Updated return u/s 139(8A) | 31 Mar 2031 (48 months) | — |
| Rectification u/s 154 | 4 years from end of the FY in which the **order** was passed | — |
| Condonation u/s 119(2)(b) | 5 years from end of the AY | — |
| Intimation u/s 143(1) may issue until | 31 Dec 2027 | After that the return stands as filed |
| Scrutiny notice u/s 143(2) may issue until | ~30 Jun 2027 `[SEC]` | Only 147/148 reassessment remains |

### s.139(5) moved, and acquired a fee — the correction to make everywhere

Finance Act 2026 (assent 30 Mar 2026), **Clause 5**, replaced *"three months prior to the
end of the relevant assessment year"* with *"at any time before the end of the relevant
assessment year"* — **31 December 2026 → 31 March 2027**. `[PRIMARY, Finance Bill 2026]`

**Clause 12 inserts s.234-I**, a fee on revising late: `[PRIMARY]`

| Revised return filed | Fee |
|---|---|
| on or before **31 Dec 2026** | nil |
| **1 Jan – 31 Mar 2027** | **₹1,000** if total income ≤ ₹5,00,000 · **₹5,000** otherwise |
| after 31 Mar 2027 | not permitted — ITR-U only |

**Belated returns were NOT extended.** The memorandum extends only the revised-return limit.
139(4) stays 31 Dec 2026.

The *"or before the completion of the assessment, whichever is earlier"* limb survives — an
intimation u/s 143(1) is generally **not** an assessment, so revision stays open after it,
but that is settled practice rather than portal-verified. `[SEC]`

`[UNVERIFIED]` The exact enacted wording of s.234-I reads "from the end of the relevant
assessment year", which is internally inconsistent with the amended 139(5). The intended
trigger is 9/12 months from the end of the **previous year**. Verify against the gazetted
Act before hard-coding. Also unverified: whether the utility auto-computes 234-I and blocks
submission if unpaid.

---

## Rectification or revised return? — decide this first

> **Is the return data wrong** — income, deduction, regime, form, personal particulars?
> → **revised return** (or ITR-U if the window has closed).
> **Is the return right but the processing wrong?** → **rectification u/s 154**.

Getting this backwards is the most expensive post-filing mistake: a rectification filed
where a revision was needed completes with "no change", and the 139(5) window may close
while you wait.

### Rectification cannot `[PRIMARY]`

Claim a new exemption or deduction · change income figures or heads · change personal
particulars · change the ITR form · introduce a new source of income · claim credit that is
not in Form 26AS · **change the tax regime** · change the refund bank account (that is
*Refund Reissue*) · be withdrawn once submitted · be filed while an earlier rectification is
still pending.

### Rectification mechanics

**Services → Rectification → New Request** → AY / order → request type. Requires an
**intimation u/s 143(1) or a s.154 order to already exist** — you cannot rectify an
unprocessed return.

| Request type (exact label) | Use when |
|---|---|
| **Reprocess the Return** | Data is right, CPC mis-processed it. No editing; CPC re-runs. |
| **Tax Credit Mismatch Correction** | Edit TDS / TCS / IT challan schedules. **Only credits present in 26AS survive.** |
| **Return Data Correction (Online)** | Edit specific schedules in the browser. |
| **Return Data Correction (Offline)** | Re-generate the whole return in the offline utility, upload JSON — **same ITR form as originally filed**. |
| **Additional Information for 234C Interest** | Supply PGBP / 115BBDA / 115B breakup for 234C recomputation. |
| Status Correction · Exemption Section Correction | ITR-5/7 only, historic AYs |

There is **no menu item called "Only Reprocess"** — the label is *Reprocess the Return*.

Attachments: PDF only, 5 MB per file, 50 MB zipped. **CPC does not accept paper s.154
applications.**

**s.154(7):** four years from the end of the FY in which **the order** was passed — not from
the AY. **s.154(8):** the authority must dispose of it within six months from the end of the
month of receipt; cite this in a grievance if it stalls.

**"Rectification rights transferred to AO"** — CPC has migrated the record. The ordinary flow
errors out. Route: **Services → Rectification → Request to AO Seeking Rectification**.

**Rectify the live order.** After a revised return is processed, the operative order is the
*revised* return's intimation. Rectifying the original achieves nothing.

---

## Defective return u/s 139(9)

**Pending Actions → e-Proceedings** → the notice for the AY → **Submit Response**.
**15 days** from receipt. Adjournment may be requested from the AO but is discretionary.

**Agree** → prepare the corrected **full** return in the offline utility (same form, same AY),
upload the JSON quoting the original acknowledgement number and the notice DIN. It is filed
*in response to the notice*, not as a fresh 139(1)/139(5). **Disagree** → written explanation.
Either way, e-verify. A submitted response is generally not editable.

**If you do not respond, the return is treated as invalid *ab initio*** — s.234F, s.234A,
loss carry-forward gone, no refund.

`[UNVERIFIED]` Sources conflict on whether filing a fresh/revised return counts as a
response. **Always respond through e-Proceedings**, and separately revise if the data needs
changing. Responding costs nothing.

**Do not use a hard-coded defect-code table.** No authoritative list for AY 2026-27 exists;
the code set changes between years. **Parse the code and text out of the notice PDF.**

Recurring defect categories `[PRIMARY FAQ + SEC]`: TDS credit claimed without offering the
income (Rule 37BA) · gross receipts below 26AS/AIS · **self-assessment tax computed but not
paid** (Explanation (aa)) · Balance Sheet / P&L blank with business income · audit report not
filed or not linked · presumptive income below the statutory minimum · name mismatch against
the PAN database · wrong ITR form · missing bank details · PAN inoperative.

---

## Updated return u/s 139(8A) — ITR-U

48 months from the end of the AY (Finance Act 2025). **AY 2026-27 → 31 Mar 2031**, and it
should open once the 139(5) window closes on 1 Apr 2027. `[INFER]`

Additional tax u/s 140B on (additional tax + interest): **25%** within 12 months · **50%**
to 24 · **60%** to 36 · **70%** to 48. **+10%** where furnished pursuant to a s.148 notice
(new via Finance Act 2026).

**Cannot** be used to: file a loss return · reduce tax determined earlier · **create or
increase a refund** · file a second ITR-U for the same AY · where assessment or reassessment
is pending or complete · after search u/s 132, requisition u/s 132A or survey u/s 133A ·
where PMLA / Black Money / Benami / DTAA information has been communicated · where
prosecution has begun · after a s.148A notice issued beyond 36 months.

**New via Finance Act 2026:** ITR-U **is** now permitted where it *reduces* a claimed loss.
Where that reduction flows into later years, consequential ITR-Us are required for those
years too.

Tax must be **paid before filing** — the portal will not accept an ITR-U with a balance
payable.

---

## Intimation u/s 143(1)

May issue until **9 months from the end of the FY in which the return was furnished** —
31 Dec 2027 for a return filed in FY 2026-27.

Download: **View Filed Returns → Download Intimation Order**. **PDF password = lowercase PAN
+ DOB as `ddmmyyyy`** — same scheme as AIS.

Two columns: *"As provided by taxpayer"* vs *"As computed under section 143(1)"*.
**Read bottom-up** — find the net figure, then walk up to the first line where the columns
diverge. That line is the entire dispute.

The six permissible adjustments: arithmetical error · incorrect claim apparent from the
return · loss disallowed where the loss-year return was late · disallowance indicated in the
audit report · **s.10AA / Chapter VI-A Part C deduction disallowed where the return was
late** · income in 26AS/16/16A not included.

**No adjustment without a pre-adjustment notice and 30 days to respond** — it arrives in
**Pending Actions → e-Proceedings** as *"Adjustment u/s 143(1)(a)"*. Silence for 30 days
means the adjustment is made.

### Outstanding demand

**Pending Actions → Response to Outstanding Demand.**

⚠ **"Demand is Correct" is irreversible** — *"Once you submit the response as Demand is
correct, then you cannot Disagree with Demand later on."* `[PRIMARY]`

Disagreeing requires one of eleven prescribed reasons (Instruction 01/2023), each with an
*"Amount not payable"* figure. Partial disagreement is allowed.

### s.245 set-off against an earlier demand

Prior intimation is mandatory. **Response window is 21 days**, reduced from 30 by Instruction
06/2022. **Silence reads as consent.** Always respond, even to agree in part.

---

## Refund

Typically **4–5 weeks from e-verification**; nothing starts until verification is done.
Check **View Filed Returns** or **Services → Know Your Refund Status**.

**Refund failure causes** `[PRIMARY]`: account not validated, or validated but **not
nominated for refund** — the toggle is separate · PAN not linked to the account · name
mismatch · account closed, dormant or frozen · **IFSC changed after a bank merger** · account
type ineligible (only Savings, Current, Cash Credit, Overdraft and NRO can be validated —
**loan and PPF accounts cannot**) · PAN inoperative.

**Refund Reissue:** Services → Refund Reissue → *+ Create Refund Reissue Request*. You cannot
raise one before the refund has actually failed.

**Interest u/s 244A** — 0.5% per month, simple. Return filed **on time** → interest runs from
**1 April of the AY**; filed late → only from the **date of filing**. That is a real,
quantifiable cost of filing late. No interest where the refund is under 10% of the tax
determined. Refund interest is **taxable as Other Sources in the year of receipt** — it will
appear in next year's AIS, from CPRC.

---

## Condonation of delay u/s 119(2)(b)

For a refund or loss carry-forward after the 139(4)/139(5) windows have shut, or where
e-verification lapsed. **Services → Condonation Request.**

Limits per AY (Circular 11/2024): ≤ ₹1 crore → Pr.CIT/CIT · ₹1–3 crore → CCIT · > ₹3 crore →
Pr.CCIT · ITR-V delay → Commissioner, CPC. **No application beyond 5 years from the end of
the AY.** Disposal within 6 months. **No interest is payable** on a refund allowed this way.

---

## Discard ITR

**e-File → Income Tax Returns → e-Verify Return → Discard.** Only for **unverified** returns,
AY 2023-24 onward. **Irreversible** — treated as never filed. Cannot be used once the ITR-V
has been posted.

Discarding a timely original and re-filing after the due date makes the new return **belated**.

`[UNVERIFIED]` Whether the discard window for AY 2026-27 now tracks the extended 139(5) to
31 Mar 2027 or stays at 31 Dec 2026.

---

## The weeks after filing — what to actually check

| When | What |
|---|---|
| Day 0–30 | **e-verify**, and confirm the status reads *Successfully e-Verified*. Nothing else matters until this is done |
| Day 0–30 | Bank account **Validated** *and* **Nominated for refund**. Re-check IFSC if the bank has merged |
| Weekly, Aug–Dec | **Pending Actions → e-Proceedings** — a 139(9) defect (15 days) or a 143(1)(a) proposed adjustment (30 days) arrives with no other warning |
| Oct–Nov 2026 | **Re-check AIS/TIS.** It keeps updating after you file — late TDS returns, revised SFT. A new entry there is the commonest cause of a later adjustment or an e-Campaign notice |
| On any demand | Respond within the window. Never leave it silent; s.245 will consume the next refund |
| By 31 Dec 2026 | Last date for a belated return, and for a **fee-free** revision |

**AIS feedback:** AIS tile → select the row → *Optional / Feedback*. Five options: information
is correct · not fully correct · relates to another PAN or year · duplicate · denied. Download
the **Consolidated Feedback File** as the audit trail.

**Compliance Portal e-Campaign** (Pending Actions → Compliance Portal): *Significant
Transactions*, *High Value Transactions*, *Non-filing of Return*, *e-Verification Scheme*.
No stated deadline, but non-response is a common trigger for reopening u/s 148A.

**Grievance (e-Nivaran):** Grievances → Submit Grievance. Minimum 100 characters. Use where a
return is unprocessed well beyond norm, a refund has not arrived after *Refund issued*, or a
rectification has sat past the s.154(8) six-month limit.
