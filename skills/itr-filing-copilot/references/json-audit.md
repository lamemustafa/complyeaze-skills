# Auditing the draft JSON

At the verification screen, download the JSON and read it. It is far faster to audit than
the 80-page preview PDF, and it is the only way to see flags the UI hides.

**Nobody else does this.** Every published ITR assistant stops at "narrate the schedule, you
type." Reading the JSON back is where wrong-field errors actually surface.

## Where the schemas live

`incometax.gov.in/iec/foportal/downloads/income-tax-returns` — CBDT publishes raw JSON
Schema per form, per AY, alongside a **schema change document** that diffs versions.

| Artifact | Path pattern |
|---|---|
| ITR-2 schema | `/sites/default/files/<yyyy-mm>/ITR-2_<yyyy>_Main_V<n>.json` |
| ITR-3 schema | `/sites/default/files/<yyyy-mm>/ITR-3_<yyyy>_Main_V<n>.json` |
| Validation rules | `/sites/default/files/<yyyy-mm>/CBDT*_ITR <n>_Validation Rules_AY <yyyy-yy>*.pdf` |
| Schema change doc | `/sites/default/files/<yyyy-mm>/ITR <n>_Schema change document_*.pdf` |

Version-pin whatever you rely on. Utilities get re-cut mid-season (ITR-2 and ITR-3 were both
re-issued 17 July 2026), and the schema itself moves — the only ITR-2 change from V1.0 to
V1.1 for AY 2026-27 was two fields under `OthersIncDtlEI` (`SubCategory` enum updated,
`Description` added). Record the schema version and the date you checked it.

## Top-level shape

```
ITR → ITR2 → { CreationInfo, Form_ITR2, PartA_GEN1,
               ScheduleS, ScheduleHP, ScheduleCGFor23, Schedule112A,
               Schedule115AD, ScheduleVDA, ScheduleOS,
               ScheduleCYLA, ScheduleBFLA, ScheduleCFL,
               ScheduleVIA, ScheduleSI, ScheduleEI,
               ScheduleFA, ScheduleAL,
               PartB-TI, PartB_TTI,
               ScheduleIT, ScheduleTDS1, ScheduleTDS2, ScheduleTDS3, ScheduleTCS,
               Verification, TaxReturnPreparer, ScheduleESOP }
```

ITR-3 adds `PartA_GEN2`, `PARTA_BS`, `ManufacturingAccount`, `TradingAccount`, `PARTA_PL`,
`PARTA_OI`, `PARTA_QD`, `ITR3ScheduleBP`, `ScheduleDPM/DOA/DEP/DCG/ESR`, `ITR3ScheduleUD`,
`ScheduleICDS`, `ScheduleIF`, `ScheduleGST`, and an `AuditInfo` block carrying
`LiableSec44AAflg` and `IncDclrdUs`.

## Fields worth grepping for

| Path | Why |
|---|---|
| `CreationInfo.Digest` | 44-char checksum **or the literal `-`**. Compare against the previous copy — identical digest means you downloaded a stale file, because the portal reuses the filename. The `-` escape hatch is why hand-edited JSON uploads at all. |
| `CreationInfo.JSONCreationDate` | must be ≥ 1 April of the AY |
| `PartA_GEN1.FilingStatus.ReturnFileSec` | 11 = 139(1). **The loss-carry-forward field.** |
| `PartA_GEN1.FilingStatus.OptOutNewTaxRegime` | Y/N, default N |
| `PartA_GEN1.FilingStatus.SeventhProvisio139` | prefill sets Y when TDS/TCS ≥ ₹25,000 |
| `PartA_GEN1.FilingStatus.ResidentialStatus` | RES / NRI / NOR |
| `PartA_GEN1.FilingStatus.HeldUnlistedEqShrPrYrFlg` | must not contradict Schedule CG |
| `PartA_GEN1.FilingStatus.ItrFilingDueDate` | **the portal's own authoritative due date** — pattern-locked per form, and it has differed from what the calendars say |
| `ScheduleCGFor23.*.FullValueConsdRecvUnqshr` | populated for a listed ETF = the unquoted-shares trap fired |
| `ScheduleCGFor23.*.FullValueConsdSec50CA` | same tell — s.50CA substitution was invoked |
| `ScheduleCFL.*` | cross-check against `PartB-TI` losses carried forward (rule 486) |
| `ScheduleTDS2.*` head-of-income mapping | every claimed TDS row needs corresponding income offered somewhere |
| ITR-3: `PartA_GEN1.IncFrmBusOrProf` | the A19(b) flag that reverts |

## Turning the validation rules into a checklist

The rules PDFs are the underexploited asset — ITR-3 alone has 618+ sequentially numbered
Category A rules, each citing a schedule and Sl.No., and none of it is machine-readable
anywhere public. Even reading the twenty rules that touch the schedules you actually filled
catches more than a preview-PDF skim.

Defect categories, as CBDT defines them for AY 2026-27:

- **Category A** — *"Return will not be allowed to be uploaded. Error message will be
  displayed."*
- **Category D** — *"Return data will be allowed to be uploaded but the taxpayer … will be
  informed of a possibility of some of the deduction or claim not to be allowed or
  entertained unless the return is accompanied by the respective claim forms or
  particulars."*

**Category B is legacy** on ITR-2 for AY 2026-27 and does not appear in that rules document —
but it *does* appear in the ITR-1 and ITR-4 rules, where it matters a great deal: a
wrong-form ITR-1 with special-rate income, or an ITR-4 old-regime claim with no Form 10-IEA,
both fire Category B only. **They upload cleanly and fail at CPC months later.**

## The AIS decryption password

AIS and TIS **PDFs**: **lowercase PAN + date of birth as `ddmmyyyy`**, concatenated. Same
credential works on the encrypted AIS **JSON** download — a working open-source
implementation (`itr-prep-skill`, `scripts/decrypt_ais.py`) uses exactly that. Earlier
reports of an undocumented magic string in the key derivation appear to be wrong, or to
describe an older format. Try `pan+ddmmyyyy` first; it works.

## Prefill JSON is a different shape

The **prefill** download is not an ITR JSON. No `{"ITR": {"ITR3": …}}` envelope, no schedules —
it is a flat bag of pre-populated values. You cannot build a return from it, but it is the
fastest way to see what the department already has. [observed]

```
personalInfo.address                    ← often STALE; compare against AIS
personalInfo.aadhaarCardNo              ← base64-encoded, not plaintext
form26as.tdsOnOthThanSals.tdSonOthThanSal[]   ← where s.192A lands, with sectionCode
filingStatus.SeventhProvisio139
filingStatus.clauseiv7provisio139i[Dtls]
bankAccountDtls[].addtnlBankDetails[]
insights.* / form26as.*                 ← dividend and interest the dept. expects
scheduleCFL.CarryFwdLossDetail[]        ← empty means no brought-forward losses
```

In one case prefill, AIS and the broker each gave a **different dividend figure**.
Report all three and reconcile the source of each; do not silently prefer one. [observed]

## Checks that have caught real errors

**Cross-schedule contradiction** — `HeldUnlistedEqShrPrYrFlg == "N"` while
`ScheduleCGFor23.…SaleOnOtherAssets.FullValueConsdRecvUnqshr > 0`. The correct field for a
quoted asset is **`FullValueConsdOthUnqshr`**. [observed]

**TDS claimed vs income offered** — a TDS-2 row with `HeadOfIncome: "OS"` and a
non-zero `GrossAmount` while Schedule OS carried a different, deliberately invented test
amount, the receipt still sitting in `ScheduleS`. **Passes validation.** [observed]

**Business-income flag** — `PartA_GEN1.FilingStatus.IncFrmBusOrProf` must be `"Y"` whenever any
Schedule BP figure is non-zero. This is the A19(b) Category A error in JSON form; check it
**last**, immediately before upload.

**Speculative chain, all five should agree in magnitude:**
`PARTA_PL.TurnverFrmSpecActivity` → `GrossProfit` → `Expenditure` →
`NetIncomeFrmSpecActivity` → `ITR3ScheduleBP.SpecBusinessInc.NetPLFrmSpecBus` →
`ScheduleCFL…LossFrmSpecBusCF` → `PartB-TI.LossesOfCurrentYearCarriedFwd`.
`PARTA_PL.NoBooksOfAccPL.*` and Trading Account 12a–12d stay zero when item 65 is used.

**Audit block** — `PartA_GEN2.AuditInfo`: all `"N"` plus `TotalSalesExcOneCr: "Upto1CR"` is the
clean non-audit profile.

**Refund rounds to the nearest ₹10** (s.288B) — in one observed return the filed refund
was three rupees below the computed figure after rounding. [observed]

**Exactly one** `PartB_TTI.Refund.BankAccountDtls.AddtnlBankDetails[]` with
`UseForRefund == "true"`.

**Challan actually entered** — after paying self-assessment tax, check all three moved:
```
ScheduleIT.TotalTaxPayments                            > 0
PartB_TTI.TaxPaid.TaxesPaid.SelfAssessmentTax          > 0
PartB_TTI.TaxPaid.BalTaxPayable                        → 0
```
All three at zero with a paid challan in hand means the challan was never keyed in. The
portal will still let you file — as a return with tax payable. [observed]

`ScheduleIT.TaxPayment[]` carries `BSRCode`, `DateDep`, `SrlNoOfChaln`, `Amt` — check
`SrlNoOfChaln` is the **5-digit challan number**, not the CIN.

**A residue of under ₹10 between `AggregateTaxInterestLiability` and `TotalTaxesPaid` is
expected**, not an error — s.288B rounds the payable to the nearest ₹10 at both ends. A ₹4
gap files with `BalTaxPayable: 0`. [observed]

**Quarterly buckets match the actual date** — `ScheduleOS.IncFrmOnGames.DateRange` and the
dividend `DateRange` blocks drive 234C. A March receipt sitting in `Upto15Of6` is wrong even
where 234C is nil. [observed]

**`Form_ITR<n>.AssessmentYear` is the *starting* year** — `"2026"` for AY 2026-27, not `"2027"`.

**The preview PDF's page count is a free signal** — it shifted 81 → 80 pages when a salary
entry was deleted. A page count that does not move means your edit did not land. [observed]

## Prior art — an accurate map of a sparse landscape

Surveyed July 2026. **Roughly twenty repositories, nearly all created in the last eight
weeks of this filing season. The largest has 20 stars.** There is no incumbent, no shared
schema library, no canonical rules corpus. Star counts and dates as at 28 Jul 2026.

| Project | ★ | What it is | The one idea worth taking |
|---|---|---|---|
| `NidheeshJain/itr-prep-skill` | 20 | Prompt-and-reference skill, 10 numbered reference files, one AIS decryptor. Explicitly does not file | **The `rules_verification` block** — every rate used must appear as `{rule, value_used, source_url, checked_on}`, and a rule with no row is a defect. Self-distrust as a mechanism |
| `karanb192/itr-wala` | 8 | Deterministic 884-line engine, LLM never does arithmetic. 47 golden + 104 validator tests, CI | **A property-based fuzzer asserting law-implied invariants** — more income can never mean less tax; cess is exactly 4%. It caught a real 1-in-350,000 float bug. Also: reject PAN/Aadhaar-shaped strings in input — privacy as mechanism |
| `Nootus/OpenTax` | 10 | The **only** project emitting uploadable ITR JSON — ITR-1 only. Bundles the official CBDT schema | **`tax_validation_service.py`** — 1,877 lines transcribed from the offline utility's **VBA macros**, cited to function and line. The technique matters more than the code: the government's `.xlsm` is a machine-readable spec of rules that otherwise exist only as PDFs |
| `Sagargupta16/itr-agent` | 4 | The only MCP server. TypeScript, 12 read-only tools, AIS + 26AS parsers | **The versioned rule pack as JSON data**, not code — with the 87A old/new asymmetry declared as flags (`excludesSpecialRateIncome`, `allowAgainst111A`) rather than buried in branches. A new FY ships as a new file |
| `dkbholusaria/AayDocCapio` | 5 | Playwright bulk-downloader for 26AS/AIS/TIS/Form 168. 17,841 LOC. **AGPL** — read, don't vendor | Two operational facts: **launch real Chrome (`channel="chrome"`), not bundled Chromium — AIS downloads silently fail on Chromium**; and use a multi-level selector fallback chain, because the portal's labels move |
| `kumaradarsh1993/india-itr-portal-map` | 0 | 556-line field-level map of the live AY 2026-27 portal from 62 captures | **The FILL / VERIFY / AUTO / SKIP taxonomy**, plus ⚠ = *"not captured, <90% confidence — ask for a screenshot, do not guess"*. Encoding "I don't know this field" as a first-class value is how you stop an agent confabulating portal structure |
| `shivprime94/file-itr` | 8 | The first Indian ITR skill, 28 Jun 2026 | **`evals/evals.json`** — scenario evals with hand-derived expected output. The VDA case asserts a ₹30,000 loss cannot offset an ₹80,000 gain, which LLMs routinely get wrong |
| `bagdeabhishek/…foreign-assets-skill` | 0 | Schedule FA depth | **Generate a one-row test CSV before the full file** — the portal's "some rows were skipped" message tells you nothing |
| `siddhpant/extortion-tools` | 11 | Regime break-even, Schedule FSI/FA | Narrow and careful; consumes SBI TTBR archives rather than asking the user |

**SBI TT reference rates** have their own little sub-ecosystem — `anoopgarlapati/sbi-tt-rates-archive`
(updating daily), `jdecodes/sbi-tt-rates`, `aniketsaha2310/sbi-fx-ratekeeper`. Anyone touching
Schedule FA needs historical TTBR; consume one of these.

## ⚠ The one genuinely dangerous thing in this ecosystem

OpenTax hardcodes `SWCreatedBy` / `JSONCreatedBy` = `"SW90002526"` and a fixed 44-char
`Digest`. **`SW########` is a registered software-provider code issued by the department.**
Emitting one that is not yours stamps a private individual's return as another vendor's
output.

The schema constrains `Digest` with the pattern `"-|.{44}"` — **unanchored**, so any string
of length ≥44 or containing a hyphen validates. The department's own utility appears to
write a placeholder. That is *why* people get away with it, not permission to.

**Never forge a Digest and never emit someone else's SW code.** Audit the portal's JSON;
do not manufacture one.

## What is still genuinely absent

1. **A broker Tax P&L parser.** Nothing open-source reads a Zerodha, Groww or Upstox Tax
   P&L — the single most common Indian investor artifact. This is the largest void, and the
   highest-volume real need.
2. **F&O and intraday.** itr-wala refuses it, itr-agent has not modelled business P&L. Yet
   any F&O forces ITR-3, the hardest form. The population most in need is the least served.
3. **ITR-2 and ITR-3 uploadable JSON.** Only ITR-1 exists anywhere.
4. **A machine-readable validation-rules corpus.** CBDT publishes PDFs only. Nobody has
   systematically dumped the ITR-2/ITR-3 offline utility macros — a tractable, high-value
   project.
5. **A current Form 16 parser.** `rozeappletree/form16-parser` is the only one and it stops
   at FY 2024-25.

**Nobody has built portal automation that files.** Everyone converged on refusing it — there
is no public API and only the taxpayer or an authorised ERI may file. The best pattern anyone
has found is a **read-only CDP attach**: the user launches their own Chrome with
`--remote-debugging-port`, logs in themselves, and the tool only screenshots and reads to
verify on-screen figures. Never clicks, never fills, never near Submit or payment.

## The transition nobody has priced in

The **Income-tax Act 2025** takes effect 1 April 2026. From Tax Year 2026-27, "tax year"
replaces previous/assessment year, **Form 16 becomes Form 130** and **Form 26AS becomes
Form 168**. It does not affect AY 2026-27 returns — but every rate table, document name and
portal reference in this entire ecosystem is pinned to the 1961 Act. Handling the transition
cleanly, with correct vocabulary per year and a refusal to mix them, is where this skill can
be differentiated within twelve months.
