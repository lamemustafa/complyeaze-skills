# Which schedules to tick, and which section to select in each

Two different problems, both on incometax.gov.in. Part 1 is the **Select Schedule**
gate that the online utility puts in front of the form. Part 2 is the section code or
dropdown value each figure belongs to once you are inside a schedule.

**Row numbering and code lists move between assessment years** — verify against the
current AY's form and the CBDT validation rules before relying on a number here.
Labels are more stable than numbers; match on the label text.

---

# Part 1 — The Select Schedule screen

`e-File → Income Tax Return → Select Status → Select ITR Form → Select Schedule`

The utility groups every schedule into five tabs — **General, Income, Deduction, Tax,
Others** — and the badge on each tab is the count *selected*, not the count available.
Mandatory schedules arrive pre-ticked and cannot be unticked; they are still displayed,
labelled "(Mandatory)".

Do not assume a schedule lives in the tab its name suggests. On ITR-2 for AY 2026-27
the **Others** tab holds CYLA, BFLA, CFL, FA, AMT, AMTC and AL — the loss set-off
schedules are there, not under Income or Tax.

Under-selecting is the failure mode. A schedule you leave off is not on the form at
all, and the omission is silent — there is no validation error for income you never
told the utility you had.

## ITR-2, AY 2026-27 — observed on the live utility

Prefill ticks **13**: General 1 + Income 4 + Deduction 1 + Tax 3 + Others 4.

**Do not assume a schedule sits in the tab its name suggests.** Schedule **SI** is under
**Income**, not Tax. **CYLA, BFLA and CFL** are under **Others**, not Income. **Part B-TI
and Part B-TTI** are under **Tax**.

| Tab | Schedule | State | Tick when |
|---|---|---|---|
| General | **Part A-Gen** | Mandatory | always |
| General | Schedule 5A | off | spouse governed by the Portuguese Civil Code (Goa, Daman, Diu) |
| Income | Schedule Salary | prefill | any salary or pension |
| Income | Schedule House Property | off | any property, including a let-out at a loss |
| Income | Schedule Capital Gains | prefill | any transfer — **including a year that nets to a loss** |
| Income | Schedule 112A | off | long-term equity / equity MF with STT paid |
| Income | Schedule 115AD(1)(iii) proviso | off | non-residents only |
| Income | Schedule VDA | off | any virtual digital asset transfer |
| Income | Schedule Other Sources | prefill | interest, dividends, gifts, winnings, family pension |
| Income | Schedule SPI | off | spouse or minor child income clubbed u/s 64 |
| Income | **Schedule SI** | **Mandatory** | always — even with no special-rate income |
| Income | Schedule EI | off | agricultural income, s.10 exemptions, exempt PF/PPF interest, share of firm profit |
| Income | Schedule PTI | off | pass-through income from a business trust or investment fund |
| Deduction | **Schedule VI-A** | **Mandatory** | always. Empty under the new regime — only 80CCD(2), 80CCH(2), 80JJAA survive |
| Deduction | 80G · 80GGA · 80D · 80U · 80DD · 80GGC · 80C | off | old regime only |
| Tax | **Part B-TI** | **Mandatory** | computed |
| Tax | **Part B-TTI** | **Mandatory** | computed |
| Tax | **Tax Paid** | **Mandatory** | TDS, TCS, advance and self-assessment tax |
| Tax | Tax deferred on ESOP | off | s.17(2)(vi) perquisite from an eligible start-up u/s 80-IAC |
| Others | **Schedule CYLA** | **Mandatory** | current-year loss set-off |
| Others | **Schedule BFLA** | **Mandatory** | brought-forward loss set-off — does **not** auto-populate |
| Others | **Schedule CFL** | **Mandatory** | losses carried forward |
| Others | Schedule FA | off | any foreign asset, account or signing authority — Black Money Act exposure |
| Others | Schedule AMT | off | old regime **and** a Ch.VI-A Part C or s.10AA claim. **Rule 430: blank under the new regime** |
| Others | Schedule AMTC | pre-ticked, **not** mandatory | untick or leave empty — both harmless. **May vanish from Return Summary on its own** once the new regime settles [observed], same as Schedule VI-A on ITR-3. Expected: AMT and its credit only exist under the old regime |
| Others | Schedule AL | off | **total income above ₹1 crore** (rule 456) |

**A gift from a relative is not "exempt income"** and does not belong in Schedule EI — it
is outside the charge entirely and is not reported anywhere on the return.

**ITR-1 and ITR-4 have no Select Schedule screen at all** — they use fixed section flows.
See `forms-itr1-itr3-itr4.md`.

## Threshold and applicability rules worth quoting

- **Rule 456** — "Schedule AL should be filled if total Income is greater than 1 crore."
  The threshold was raised from ₹50 lakh to ₹1 crore **with effect from AY 2025-26**,
  not AY 2026-27 — it is simply unchanged this year. Do not carry the ₹50 lakh figure
  forward from older guidance; the on-screen text reads "₹1 Crore".
- **Rule 430** — "If new tax regime is selected, Schedule AMT should be blank."
  AMT under s.115JC only bites where Chapter VI-A Part C or s.10AA deductions are
  claimed, which the new regime disallows. If the utility pre-populates a zero into
  Schedule 10AA or 80GG it can switch AMT on spuriously — clear those entries rather
  than filling AMT.
- **Rule 486** — "Losses of current year to be carried forward at Part B TI should be
  equal to Total of Current Year Losses of Schedule CFL."
- **Rule 368** — "If no special Income is shown, then tax at special rates should not be
  computed." The converse also holds: special income shown means Schedule SI must
  reconcile (Rule 376).

Rule numbers are AY-specific. Pull the current file from
`incometax.gov.in/iec/foportal/downloads` → "Validation Rules" before relying on one.

## Session hygiene on this screen

Session timer is 15 minutes and resets on each save. Pick the full set in one pass —
re-entering Select Schedule after data has been keyed can reset flags in Part A-Gen.

---

# Part 2 — Which section to select inside each schedule

---

## Part A-General

**Return filed under section** — the single highest-consequence dropdown on the form.

| Value | When | Cost of getting it wrong |
|---|---|---|
| 139(1) | on or before the due date | — |
| 139(4) | belated | **kills carry-forward** of capital, speculative and business losses (s.80 read with s.139(3)); house-property loss and unabsorbed depreciation survive |
| 139(5) | revised | inherits the original's date for s.139(3) purposes |
| 139(8A) | updated | additional tax 25–70%; cannot be used to increase a loss or a refund |
| 119(2)(b) | condonation granted | needs an order first |

Other flags:

- **Residential status** — RES / NRI / RNOR. Drives Schedule FA/FSI/TR and the
  s.111A/112A basic-exemption-adjustment provisos.
- **Nature of employment** — Central Government / State Government / Public Sector
  Undertaking / Pensioners / Others / Not applicable. A private company is **Others**.
  s.16(ii) entertainment allowance is government-only.
- **Opting out of the new regime u/s 115BAC(6)** — `No` keeps the default new regime.
  `Yes` requires **Form 10-IEA filed before the due date**; with business income the
  choice becomes sticky.
- **Seventh proviso to 139(1)**, **unlisted equity shares held**, **director in a
  company** — see portal-traps.md; these must not contradict the schedules.

---

## Schedule Salary

| Component | Section |
|---|---|
| Salary | 17(1) |
| Perquisites | 17(2) — per Form 12BA |
| Profits in lieu of salary | 17(3)(i) termination compensation · **17(3)(ii)** payment from a provident or other fund |
| Standard deduction | 16(ia) |
| Entertainment allowance | 16(ii) — government employees only |
| Professional tax | 16(iii) |

s.10 exemption rows: 10(5) LTA · 10(10) gratuity · 10(10A) commuted pension ·
10(10AA) leave encashment · 10(10C) VRS · 10(13A) HRA · 10(14) special allowances.
**Under the new regime only 10(10), 10(10A), 10(10AA), 10(10C), transport allowance
for the specially-abled and genuine job-related travel survive.** HRA and LTA do not.

A taxable PF withdrawal goes under **17(3)(ii)** — not 17(1) (there is no employment)
and not 17(3)(i) (that is termination compensation).

---

## Schedule CG — short-term, section A  *(ITR-2)*

**Verified against the notified ITR-2 form and CBDT validation rules for AY 2026-27.**
The row that catches people is A5 — see the ITR-3 warning at the end of this block.

| Item | Label (abbreviated) | Rate bucket |
|---|---|---|
| **A1** | From sale of land or building or both | applicable rate |
| **A2** | Equity share / equity-oriented MF / business trust unit, **STT paid — s.111A** | **20%** |
| A3 | NON-RESIDENT, not an FII — shares or debentures of an Indian company | a → 20%, b → applicable |
| A4 | NON-RESIDENT — securities sold by an FII, s.115AD | 30% |
| **A5** | **From sale of assets other than at A1 or A2 or A3 or A4 above** | applicable rate |
| A6 | Amount **deemed** to be short-term capital gains | applicable rate |
| A7 | Pass-through income/loss in the nature of STCG | split a/b/c |
| A8 | STCG in A1–A7 not chargeable, or chargeable at special rates, per DTAA | DTAA |
| A(A) | Capital loss on buy-back of shares — rate dropdown | 20 / 30 / applicable |
| A9 | Total short-term capital gain | — |

The on-screen note *"Sub-items 3 and 4 are not applicable for residents"* is the fastest
way to confirm this numbering on a live screen: A3 and A4 are the non-resident rows, so
the residual row for a resident is **A5**.

### Opening a CG sub-item

The row does not exist until you create it. The control reads **"Do you want to add more
breakup values? + Add Another"** — that phrasing makes it look optional; it is how you add
the *first* row. Once a row exists you get **Edit** and **Delete** instead.

The row form opens with a **dropdown before any amount field**. On A2 it is
**Section \*** → `111A [for others]` or `115AD(1)(b)(ii) proviso [for FII]`. Picking the FII
option routes the figure to the 30% bucket in table E instead of 20%. Every field marked
`*` is mandatory — a blank cost-of-improvement blocks the save; type `0`.

Save the row from inside the sub-form before navigating away. Leaving the page mid-form
loses it silently, and the parent list will still show the accordion as if nothing is wrong.

### A5 internal structure — the unquoted-shares trap

| Field | Label | Fill with |
|---|---|---|
| A5(a)(i)(a) | Full value of consideration in respect of **unquoted shares** | **0** unless genuinely unquoted shares |
| A5(a)(i)(b) | Fair market value of unquoted shares | **0** |
| A5(a)(i)(c) | Consideration adopted per **s.50CA** — auto | 0 |
| **A5(a)(ii)** | **Full value of consideration for assets other than unquoted shares** | **← ETFs, gold, debt funds, bonds go here** |
| A5(a)(iii) | Total (ic + ii) — auto | |
| A5(b)(i) | Cost of acquisition without indexation | |
| A5(b)(ii) | Cost of improvement | |
| **A5(b)(iii)** | **Expenditure wholly and exclusively in connection with transfer** | |
| A5(b)(iv) | Total (bi + bii + biii) — auto | |
| A5(c) | Balance (aiii − biv) — auto | |
| A5(d) | Loss disallowed u/s 94(7) / 94(8) | |
| A5(e) | STCG on assets other than A1–A4 — auto | |

The cursor lands on A5(a)(i) first. Putting a listed ETF there claims an unquoted-share
sale, triggers **rule 120** (*"A5(a)(ic) should be higher of A5(a)(ia) or A5(a)(ib)"*),
invokes s.50CA fair-value substitution, and contradicts `HeldUnlistedEqShrPrYrFlg = N`
in Part A-Gen. The same (ia/ib/ic/ii/iii) structure repeats at **A4(a)**, **B5(a)** and
**B8(a)** — the trap is not unique to A5.

### s.50AA classification, AY 2026-27

`[documented]` s.50AA deems certain gains SHORT term however long the asset was held —
slab rate, row A5. It reaches three different things through separate limbs, and only
the first is the mutual-fund test most guidance describes:

| Asset | Test |
|---|---|
| a **specified mutual fund** unit | the three conditions below |
| a **market-linked debenture** | no composition or acquisition-date test — s.50AA applies on its own terms |
| an **unlisted bond or debenture** | transferred, redeemed or maturing **on or after 23 July 2024**; no composition test |

Sending a debenture through the mutual-fund conditions below would find them unmet and
route it to the ordinary holding-period analysis, which is the wrong answer. **The three
conditions are the specified-mutual-fund limb only**, and each of them is a way out of
that limb.

**1. The unit must have been acquired on or after 1 April 2023.** `[documented]` s.50AA
reaches only units acquired on or after that date. A unit bought earlier follows the
ordinary holding-period rules and can produce a long-term gain whatever the fund holds.
**Ask for the acquisition date before giving a row** — this is the condition most often
skipped, because the fund's own composition looks like the whole question.

**2. The fund must meet the substituted definition, either limb.** `[documented]` As
substituted by the **Finance (No. 2) Act 2024** and effective for AY 2026-27, a
specified mutual fund is one that invests

- **more than 65% of its total proceeds in debt and money-market instruments**, or
- **at least 65% of its total proceeds in units of a fund of the first kind** — the
  fund-of-funds limb, which is easy to miss and catches a fund that holds no debt
  directly at all.

`[documented]` The percentage is computed on the **annual average of the daily closing**
figures — closing only, not an average of opening and closing, and not a single date.
For a fund sitting near the 65% line that difference decides the section.

`[documented]` The pre-amendment test was a different one — a fund investing **not more
than 35%** of its proceeds in the equity shares of domestic companies, so a fund at
exactly 35% was caught — and most commentary written before 2025 still describes that
version.

**3. Gold ETFs fail the first limb.** `[documented]` Gold is neither debt nor a
money-market instrument. `[inferred]` Check the second limb before concluding: a gold
*fund of funds* holding units of a debt fund could still be caught. Liquid and debt
ETFs meet the first limb directly.

**Where s.50AA does not apply, check the holding period before taking a row.**
`[UNVERIFIED]` Three sources give three answers for these units, and the whole
disagreement turns on one phrase.

- **12 months** — practitioner consensus, and how at least one broker's own tax
  statement classifies them. The argument: the Finance (No. 2) Act 2024 rationalised
  holding periods to two, and a **listed** ETF unit is a security listed on a
  recognised Indian exchange. If that Act removed the "other than a unit" carve-out,
  then for a listed ETF this is not disputed at all and the next entry is the
  superseded reading.
- **24 months** — on the pre-amendment wording of s.2(42A), "a security **(other than
  a unit)** listed on a recognised stock exchange", which puts a unit outside the
  12-month limb whatever it is listed on.
- **36 months** — AMFI's published table, which appears to be a stale FY 2024-25 row.

`[inferred]` A listed unit and an unlisted one need not answer the same way, and the
argument above is about a listed one. **Read the current text of s.2(42A)**, not any of
these summaries or this line. On a real return this split decided whether the gain was
long-term or short-term.

### ⚠️ ITR-3 numbering differs

ITR-3 carries an extra **slump sale** row, which pushes "other assets" to **A6** with the
unquoted-shares split at 6a(i) and other assets at **6a(ii)**. Same trap, different number.
Confirm which form you are on before quoting a row number.

## Schedule CG — long-term, section B  *(ITR-2)*

| Item | Label (abbreviated) | Notes |
|---|---|---|
| B1 | Land or building | carries the second-proviso 12.5%-vs-20%-indexed comparison for residents |
| B2 | Listed securities (other than a unit) or zero-coupon bonds — s.112 | |
| **B3** | **Equity share / equity-oriented fund / business trust unit, STT paid — s.112A** | B3a is pulled from **Schedule 112A col. 14** |
| B4–B7 | NON-RESIDENT rows: unlisted shares · 112(1)(c) / 115AC / 115AD · FII 112A via 115AD(1)(iii) · 115F foreign exchange asset | |
| B8 | From sale of assets where B1 to B7 are not applicable | has the 50CA split |
| B9 | Amount deemed to be long-term capital gains | |
| B10 | Pass-through income/loss in the nature of LTCG | |
| B11 | LTCG in B1–B10 not chargeable, or at special rates, per DTAA | |
| B(A) | Capital loss on buy-back of shares — long term 12.5% | |
| B12 | Total long-term capital gain | |

The resident 112A row is **B3**, *before* the non-resident block — matching the on-screen
note *"Sub-items 4, 5, 6, & 7 are not applicable for residents"*.

**Fill Schedule 112A before Schedule CG.** B3 pulls from it; reversed, you re-enter it.

There is **no separate LTCG-at-20% bucket** anywhere in table E, table F or BFLA for
AY 2026-27. Pre-23-July-2024 indexation on immovable property is delivered as a
*tax-capping adjustment* (B1ei / B1eii / B1h), while B1g itself feeds the 12.5% bucket.

## Expenditure on transfer — s.48(i)

Always sub-field **b(iii)**, inside the *Deductions under section 48* group, in every
block with a full computation: **A1, A2, A4, A5** short-term and **B1, B2, B5, B8**
long-term. Pattern: bi cost of acquisition → bii cost of improvement → **biii expenditure
on transfer** → biv total → c balance.

Blocks with no expenditure field, because the figure arrives computed: A3, B4, B7, and
**B3 / B6** (where the expenditure sits in **column 12 of Schedule 112A** and
Schedule 115AD(1)(iii) respectively).

Deductible: brokerage · exchange transaction charges · stamp duty · SEBI turnover fee ·
IPFT · GST on those · DP charges on sale.
**Not deductible: STT** (express bar in the proviso to s.48). Demat AMC and
delayed-payment charges are account maintenance, not transfer costs.

Allocate per-scrip charges directly to the block that scrip belongs to; pro-rate common
charges on consideration. Brokers report charges in a single undifferentiated table —
the split is yours to make and to document.

## Table E — set-off of current year capital losses

A matrix, and **horizontally scrollable** — the visible area shows two or three of eight
columns. Scroll right before concluding a figure is missing; this is the single most
common "my loss disappeared" false alarm.

**On screen the rows are numbered 1–5 with nested rate sub-rows.** The formula text still
uses the notified form's roman numerals, so the two do not match. There is no row 9.

| On screen | Formula name | What |
|---|---|---|
| Row 1 | i | Capital Loss to be Set Off — fill only if negative |
| Row 2 | ii–v | Short Term Capital Gain → 20% · 30% · Applicable Rate · Covered By DTAA |
| Row 3 | vi–vii | Long Term Capital Gain → 12.50% · Covered By DTAA |
| Row 4 | viii | Total loss set off (ii+iii+iv+v+vi+vii) |
| Row 5 | ix | Loss remaining after set off (i − viii) |

**Columns** — 1 capital gain of current year (positive only) · 2 STCL 20% · 3 STCL 30% ·
4 STCL applicable rate · 5 STCL DTAA · 6 LTCL 12.5% · 7 LTCL DTAA ·
8 gains remaining, `8 = 1 − 2 − 3 − 4 − 5 − 6 − 7`.

`C1 = 8ii + 8iii + 8iv + 8v + 8vi + 8vii` — column 8 of the six rate rows.

The table is auto-populated. At the bottom sits **"Do you want to edit the detail
auto-populated above?"** — leave it on **No** and let the schedule feed itself.

**There is no combined total anywhere in table E, and that is correct.** [observed] Losses stay
in their rate columns because a 20% loss can never be merged with a slab-rate loss. Row 4
"Total loss set off" is the total *absorbed* — zero when there are no gains, which reads like a
missing total but is not. Row 5 "Loss remaining after set off" is per column.

**The head total lives in the section header.** Collapse table E and read
`A(I). Short-term Capital Gains` at the top of Schedule CG — it shows the signed total across
all rate buckets. That is the check that both rows landed.

Which A/B row feeds which category:

| Table E row | Fed by |
|---|---|
| Ei2 — STCG 20% | A2e + A3a + A7a + A(A)@20% |
| Ei3 — STCG 30% | A4e + A7b + A(A)@30% |
| Ei4 — STCG applicable | **A1e + A3b + A5e + A6 + A7c** + A(A)@applicable |
| Ei5 — STCG DTAA | A8b |
| Ei6 — LTCG 12.5% | B1g + B2e + B3c + B4c + B5e + B6c + B7c + B8e + B9 + B10a1 + B10a2 + B(A) |
| Ei7 — LTCG DTAA | B11b |

**A5 lands in the applicable-rate bucket, not the 20% bucket.** Only A2 is 20%. If you
entered both A2 and A5 and only see one loss, the other is in an off-screen column.

## Table F — accrual of capital gain by quarter

Seven rows × five quarter columns: `Upto 15/6` · `16/6–15/9` · `16/9–15/12` ·
`16/12–15/3` · `16/3–31/3`.

Rows: 1 STCG @20% · 2 STCG @30% · 3 STCG at applicable rates · 4 STCG at DTAA rates ·
5 LTCG @12.5% · 6 LTCG at DTAA rates · 7 VDA @30%.

**Fill table F LAST — after CYLA, BFLA and CFL are confirmed.** It is the single largest
source of validation failures on this form. Table F wants figures **net of current-year
and brought-forward set-off**, and each row must equal the corresponding BFLA figure:
row 1 → BFLA 3(iii), row 2 → 3(iv), row 3 → 3(v), row 4 → 3(vi), row 5 → 3(vii),
row 6 → 3(viii), row 7 → C2.

Typical error text:

> *"In Schedule CG, Table F Sl. No. 5 the breakup of all the quarters is not equal to the
> value from item 3vii of schedule BFLA"*

The item labels in that message do not visibly exist in Schedule BFLA, which makes it
unactionable by inspection — the fix is always the same: read BFLA's final column and
enter only that. **If the net is a loss or nil, leave table F blank / zero.** The table
does not accept negatives.

Table F drives 234C only. Where total tax is under the ₹10,000 s.208 threshold, 234C is
nil on any allocation — so where real quarters net negative but the head is positive,
loading the annual net into the last applicable bucket is safe. Keep the true quarterly
working on file separately.

## Schedule OS

Item 1 — income chargeable at normal rates:

| Row | Contents |
|---|---|
| 1a | Dividends, gross (quarterly breakup below drives 234C; row 3(a) maps to 1a(i)) |
| 1b | Interest, gross → **bi** savings bank · **bii** term deposits · **biii** income-tax refund (s.244A) · **biv** pass-through · **bv** on enhanced compensation · **bvi** others |
| 1c | Rental from machinery, plant or furniture |
| 1d | Income of the nature referred to in **s.56(2)(x)** |
| 1e | Any other — named sub-rows for family pension, s.89A, 56(2)(xii)/(xiii) are fixed; the **generic row sits behind the last "+ Add Another"**, and its free-text nature field is capped at **50 characters** ("Maximum 50 characters are required" means maximum) |

Item 2 — income chargeable at special rates:

| Section | Covers | Rate |
|---|---|---|
| 115BB | lotteries, crossword puzzles, races, card games, gambling | 30% |
| **115BBJ** | **winnings from online games** | 30% |
| 115BBE | unexplained cash credits / investments | 60% + surcharge |
| 115BBH | virtual digital assets | 30% |
| 111 (item 2c) | accumulated balance of a recognised PF taxable u/s 111 | see below |

**115BBJ was carved out of 115BB by Finance Act 2023.** Online-game winnings do not go
on the 115BB row, and the corresponding TDS section is 194BA, not 194B.

Item **2c** is not a convenient label for a taxable PF withdrawal. It is the s.111 /
Rule 9 machinery, where tax is the aggregate additional tax across each earlier year had
the fund been unrecognised — usually far more expensive than slab rates. Only use it
deliberately.

s.56(2)(x): once aggregate money received without consideration from non-relatives
exceeds ₹50,000 in a year, **the whole amount is taxable, not the excess**. "Relative"
excludes cousins, nephews and nieces.

---

## Schedule SI — mirrors the special-rate rows

| Section | Rate AY 2026-27 |
|---|---|
| 111A | 20% |
| 112A | 12.5% on the excess over ₹1,25,000 |
| 112 | 12.5% |
| 115BB | 30% |
| 115BBJ | 30% |
| 115BBE | 60% plus surcharge |
| 115BBH | 30% |

**Whether the s.87A rebate reaches these rows depends on the regime — and this is
the most contested computation on the portal.**

- **New regime:** it does not. The second proviso to s.87A (Finance Act 2025, from
  AY 2026-27) caps the rebate at tax computed at s.115BAC(1A) rates, and special-rate
  tax does not arise at those rates. A filer under the ₹12,00,000 ceiling still pays
  full tax on every SI row.
- **Old regime:** s.112A(6) expressly bars it against 112A tax. **s.111A carries no
  such bar**, so on the statute the rebate is allowable against STCG tax. Whether the
  AY 2026-27 utility agrees is `[UNVERIFIED]` — the published validation rules are
  silent and the utility denied it from July 2024 onwards.

Compute it, then read the portal's own figure. If they differ, give the taxpayer both
numbers and say what the difference turns on. See `rates-ay2026-27.md`.

---

## Schedule TDS / Taxes Paid

| Schedule | Source | Form | Head-of-income dropdown |
|---|---|---|---|
| TDS-1 | salary, s.192 | 24Q | none — salary by construction |
| TDS-2 | other than salary | 26Q / 27Q | House Property · Business and Profession · Capital Gains · Other Sources · Exempt Income · Not Applicable (194N). **No Salary option.** |
| TDS-3 | 194IA / 194IB / 194M / 194S | 26QB/QC/QD/QE | — |
| TCS | collections | 27D | — |

Sections that land in TDS-2: 194 dividend · 194A interest · **192A PF withdrawal** ·
194B lottery · **194BA online games** · 194H commission · 194I rent · 194J professional ·
194K MF units · 194N cash withdrawal · 194S VDA.

The **192A trap**: EPFO files PF-withdrawal TDS in Form 26Q, so it prefills into TDS-2,
which structurally cannot point at Salary. Do not hand-add it to TDS-1 (CPC matches
TDS-1 against 24Q and an unmatched claim can lose the whole credit), and do not pick
*Exempt Income* to make it go away — that is a factual claim about the five-year rule.

Whichever row a TDS claim sits in, **the gross amount must be offered somewhere.** The
s.139(9) defect reads: "credit for TDS is being claimed, the corresponding receipts are
not offered in the respective income schedules."

Taxes Paid also carries: advance tax and self-assessment challans (BSR code, date,
serial), TCS, and — from FY 2023-24 — challan details visible only in AIS Part B3, not
in 26AS. **Check the challan's assessment year in AIS before claiming it**; a
self-assessment challan paid in September commonly belongs to the *previous* AY.

---

## Schedule CFL — losses and carry-forward periods

| Loss | Set off against | Years |
|---|---|---|
| House property | any head, ₹2,00,000 cap in-year | 8 |
| Short-term capital | STCG or LTCG | 8 |
| Long-term capital | LTCG only | 8 |
| Speculative — s.73 | speculative profit only; **never appears in CYLA** | 4 |
| Specified business — s.73A / 35AD | specified business only | unlimited |
| Non-speculative business | any head except salary | 8 |

Capital losses cannot be set off against salary or other sources. Every loss above
except house-property loss and unabsorbed depreciation requires a **139(1)** return.

---

## Chapter VI-A under the new regime

**Survive:** 80CCD(2) employer NPS · 80CCH(2) Agniveer Corpus Fund · 80JJAA additional
employee cost.

The 80CCD(2) cap is on salary (basic + DA) and differs by regime **and** employer:

| | New regime s.115BAC(1A) | Old regime |
|---|---|---|
| Central / State Government employer | 14% | 14% |
| Any other employer | **14%** | **10%** |

The 14% for private employers under the new regime comes from the proviso inserted by
Act 15 of 2024 (from AY 2025-26). Under the old regime s.80CCD(2)(b) still reads 10%.
The whole employer contribution also sits under the ₹7.5 lakh combined PF + NPS +
superannuation cap in s.17(2)(vii).

**Gone:** 80C · 80CCC · 80CCD(1) · 80CCD(1B) · 80D · 80DD · 80DDB · 80E · 80EE / 80EEA /
80EEB · 80G · 80GG · 80GGA · 80GGC · 80TTA · 80TTB · 80U.

Also allowed outside Chapter VI-A: s.24(b) interest on a **let-out** property with no
cap (self-occupied interest is not), and the ₹25,000 family-pension deduction.

Schedule VI-A disappears from the form once the regime is locked in. Expected, not a
deletion.

---

## Nature of business codes (ITR-3)

- **21011** — intraday / speculative trading in listed equity shares.

For F&O, commission agency and other segments, pull the code from the current year's
published list rather than reusing a remembered one — the list is revised and a stale
code is a Category A rejection.
