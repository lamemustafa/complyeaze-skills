# Evals

Three tiers, because "did the skill help?" and "is the number right?" are
different questions and only one of them needs a model.

| Tier | File | Asserts | Model? |
|---|---|---|---|
| **Golden** | `golden/cases.json` | Exact figures to the paisa, and that the engine **refuses** where it must | No |
| **Output quality** | `evals.json` | Form and schedule selection, that the engine was actually invoked, that evidence tags are present | Yes |
| **Trigger** | `trigger_queries.json` | The description fires on real asks and stays quiet on near-misses | Yes |

## Every fixture here is synthetic

**No file in this directory may contain real taxpayer data.** No PAN, Aadhaar,
GSTIN, TAN, name, acknowledgement number, challan identifier, bank account or
unredacted ITR JSON. Figures that originate from a real filed return are rounded
and stripped of every identifier before they land here. CI scans this directory
along with the rest of the repo and fails the build on a match.

## Tier 1 — golden cases

```bash
python3 ../scripts/compute_tax.py --golden golden/cases.json
```

Runs in CI on every push and pull request. No model, no network, no flakiness.

Each case is `input` → `expect`, where `expect` names output fields of the engine
and their exact string values. Add a case by editing the JSON — you should not
need to touch Python.

Two case classes matter more than the rest:

**Refusal cases.** `"expect": {"outcome": "refuse", "must_mention": [...]}`. For a
compliance skill, correctly declining is a first-class success condition. Without
these the skill drifts toward confident over-reach, which is the failure mode that
costs a taxpayer money.

**Cases that pin a contested reading.** `rebate-87a-old-regime-reaches-111a` records
a statutory position the portal utility may not share. Its `source` field says so.
When the utility's behaviour is finally observed, that case is where the change
lands — not scattered through prose.

## Tier 2 — output quality

`evals.json` follows the Agent Skills eval format: run each prompt **with** and
**without** the skill, in a clean context each time, and grade the `expectations`
against concrete evidence from the transcript.

Two rules that do most of the work:

- **Require evidence for a PASS.** Do not give the benefit of the doubt. A
  response that mentions the right section number without acting on it fails.
- **Drop expectations that pass in both configurations.** They inflate the score
  and measure nothing.

Prefer expectations that are checkable from tool-call metrics rather than from
prose — "a Bash call invoking `compute_tax.py` appears" is a real assertion about
the skill's core design claim. "The tax computation is correct" is not gradeable
by a judge without ground truth; that belongs in Tier 1.

## Tier 3 — trigger accuracy

`trigger_queries.json` tests the `description` field, not the body. Roughly half
the queries should trigger and half should not, and the negatives are deliberate
**near-misses** — "what is Form 16 and who issues it" mentions a document the
description lists but asks for a definition. If that fires, the description is
keyed on nouns instead of on intent.

Keep a held-out split when tuning the description, or you will simply overfit it
to this file.

## Adding a case

1. Write it in the relevant JSON file with a `source` line saying where the
   expected value comes from — a section, a validation rule, or an observed screen.
2. Confirm it fails before your change and passes after.
3. Scrub identifiers. Round figures that came from a real return.

## Fixtures

`fixtures/` holds the input files the parsers are tested against. All of them are
invented. Scrip names and ISINs are real because they are public market data;
the quantities, prices, dates and folios are not anybody's.

| Fixture | What it pins |
|---|---|
| `zerodha_tax_pnl_synthetic.xlsx` | An ordinary broker statement: intraday, short and long term equity, a liquid fund, dividends, F&O |
| `adversarial_layout_synthetic.xlsx` | Every layout that misclassified during review — a decoy Unrealised P&L column, scrips named SUMICHEM and TOTAL ENERGIES, a Subtotal row, an unrecognised heading, a heading sharing its row with a note, non-equity, unlisted, buyback, currency intraday, land |
| `broker_double_view_synthetic.xlsx` | The real Zerodha workbook shape: the same gains stated twice, an Open Positions sheet, a ledger, and a raw `Profit` column beside the grandfathered `Taxable Profit`. Reading it naively doubles the return |
| `tis_synthetic.pdf` | A TIS generated from invented totals by `build_tis_synthetic.py`, byte by byte so the PDF reader and document detector are covered without shipping anyone's statement |
| `schedule112a_valid.csv` | A CSV the portal accepts |
| `schedule112a_broken.csv` | Six rejections at once, including the retyped header |
| `schedule112a_loss.csv` | A capital loss, which an earlier version blocked as a forbidden minus sign and told the user to delete |
| `schedule112a_blank14.csv` | A blank derived column, which an earlier version passed while reporting the total as zero |
| `schedule112a_ae_col9.csv` | Column 9 on an AE row, which an earlier version used to inflate the cost by ₹6,48,000 |

Every one of those fixtures exists because the code once got it wrong. When you
change classification behaviour, add the case that fails first.
