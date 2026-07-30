<div align="center">

# ComplyEaze Skills

**Agent skills for Indian tax and compliance work.**

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![CI](https://github.com/lamemustafa/complyeaze-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/lamemustafa/complyeaze-skills/actions/workflows/ci.yml)
[![Agent Skills](https://img.shields.io/badge/Agent_Skills-open_standard-informational.svg)](https://agentskills.io)
[![Status](https://img.shields.io/badge/status-alpha-orange.svg)](#status)
[![AY](https://img.shields.io/badge/assessment_year-2026--27-brightgreen.svg)](#status)
[![Dependencies](https://img.shields.io/badge/dependencies-none-success.svg)](docs/scripts.md)

```bash
npx skills add lamemustafa/complyeaze-skills
```

**[Install](docs/install.md)** · **[The scripts](docs/scripts.md)** ·
**[How it works](docs/how-it-works.md)** · **[Writing](docs/broker-statements-state-gains-twice.md)** ·
**[Contributing](CONTRIBUTING.md)**

</div>

---

Filing an Indian income tax return is not hard because the tax is hard. It is
hard because your broker hands you a 400-row spreadsheet, the portal rejects
your upload with `common.errors.csv_row_skip`, and nothing tells you that the ₹6
of intraday profit you forgot about has just moved you from ITR-1 to ITR-3.

This repository is the knowledge for that, written as agent skills, with the
parts that must be exact done by scripts rather than by a language model.

Run against two live Zerodha workbooks, the parser's first output put every
capital-gains bucket at exactly twice the broker's own summary. That exposed the
workbook's two views of the same realised gains and led to exact de-duplication.
**[The whole story →](docs/broker-statements-state-gains-twice.md)**

> **General reference only, not tax advice.**
> [Disclaimer](docs/disclaimer.md). Not affiliated with, endorsed by or operated
> by the Income Tax Department, CBDT or the Government of India.

## What it solves

| Stuck on | Go to |
|---|---|
| Which ITR form applies, and whether intraday forces ITR-3 | [Form selection](skills/itr-filing-copilot/SKILL.md) |
| Reading a broker Tax P&L into Schedule CG | [`parse_capital_gains.py`](docs/scripts.md#parse_capital_gainspy) |
| "Please import the details in correct template" | [`check_112a_csv.py`](docs/scripts.md#check_112a_csvpy) |
| The ₹1,25,000 LTCG exemption across several brokers | [`parse_capital_gains.py`](docs/scripts.md#parse_capital_gainspy) |
| Reading AIS, TIS, 26AS, Form 168 or Form 16 | [`parse_tax_docs.py`](docs/scripts.md#parse_tax_docspy) |
| Whether your AIS detail adds up to your TIS | [`parse_tax_docs.py`](docs/scripts.md#parse_tax_docspy) ties them category by category |
| Savings interest, and credits that need explaining | [`parse_bank_statement.py`](docs/scripts.md#parse_bank_statementpy) |
| Your AIS PDF asking for a password | [`open_ais.py`](skills/itr-filing-copilot/scripts/open_ais.py) — no plaintext copy is written |
| Savings interest that will not add up to AIS | [`reconcile_interest.py`](docs/scripts.md#reconcile_interestpy) names the account nobody has a statement for |
| The accounts, TDS and carry-forwards the portal holds | [`parse_portal_json.py`](docs/scripts.md#parse_portal_jsonpy) reads the prefill and any filed return |
| AIS showing no capital gains when you traded all year | [Phase 0 intake](skills/itr-filing-copilot/SKILL.md) |
| Old regime against new, with capital gains in the mix | [`compute_tax.py`](docs/scripts.md#compute_taxpy) |
| Which schedules to tick, and in what order | [Schedule map](skills/itr-filing-copilot/references/schedule-sections.md) |
| A validation error naming a field that is fine | [Error library](skills/itr-filing-copilot/references/error-messages.md) |
| Part B-TTI still saying Pay Now after you paid | [Portal traps](skills/itr-filing-copilot/references/portal-traps.md) |
| Rectification against revised return | [Post-filing](skills/itr-filing-copilot/references/post-filing.md) |

## Skills

| Skill | Does | Fires on |
|---|---|---|
| **`itr-filing-copilot`** | Reconciles AIS, TIS and 26AS against your own documents, picks the form and schedules, walks the portal field by field, covers rectification and revision | "file my ITR", income tax return, Form 16, AIS, TIS, 26AS, capital gains statement, broker tax P&L, Schedule CG |

GST, TDS, ROC and PF skills will land here.
[`shared/AUTHORING.md`](shared/AUTHORING.md) is the standard they are built to.

## Quick start

```bash
npx skills add lamemustafa/complyeaze-skills
```

Then say what you actually want:

> I need to file my ITR for AY 2026-27. Salary and some Zerodha trades.

The skill runs its own intake and reconciles before it computes anything.
Other hosts, manual paths and global directories are in
**[Install](docs/install.md)**.

The scripts also work on their own, without an agent:

```bash
$ python3 skills/itr-filing-copilot/scripts/parse_capital_gains.py "Tax P&L.xlsx"

  speculative  rows= 2 gain=      120.00  Schedule BP — speculative business
  111A         rows= 2 gain=    6,150.00  CG A2 / A3
  112A         rows= 2 gain=  117,400.00  CG B3 (ITR-2), plus Schedule 112A
  dividend     rows= 2 gain=    2,300.00  Schedule OS
  fno          rows= 2 gain=   -9,200.00  Schedule BP — non-speculative business

  needs confirmation:
    mutual fund, equity-oriented or not? (1 row, 6,900.00)

  flags:
    Intraday or F&O activity is present, so this is business income and the
    return is ITR-3, not ITR-1/2, however small the amount.
```

Twelve scripts, no dependencies at all. Nothing to install, nothing that phones
home, nothing that reads a file you did not name.
**[What each one does →](docs/scripts.md)**

## What it hands back

One working paper with two reading levels. Simple is tickable steps and plain
sentences; Detailed adds the section numbers, the rounding, and the command
behind each figure.

| Simple | Detailed |
|---|---|
| Tickable steps and plain-language outcomes | The same steps with section references, rounding and the command behind each figure |

Blockers are called out inside the affected step before the user can continue,
with the missing evidence or unresolved tie-out named explicitly.

## Scope

|  | Covered | Not covered |
|---|---|---|
| **Who** | Resident individuals | Non-residents, HUF, firms, companies, deceased or representative filings |
| **Forms** | ITR-1, ITR-2, ITR-3, ITR-4, non-audit only | Audit cases u/s 44AB, ITR-5/6/7 |
| **Income** | Salary, capital gains, other sources, intraday and speculative, presumptive 44AD/44ADA/44AE, partner in a firm, PF withdrawal | F&O at meaningful turnover, foreign assets or income, ESOP deferral, businesses with real books |
| **Year** | AY 2026-27 (FY 2025-26), Income-tax Act 1961 | Every other year. Figures are year-specific and the skill refuses to guess |
| **Action** | Tells you what to type, and where the form lies | Never touches the portal, handles credentials, or submits anything |

Outside that, it says so and routes to a qualified professional. It is better at
saying "I don't know this screen, send me a screenshot" than most things are.

## Status

**v0.1.5, alpha.** <!-- x-release-please-version --> Reconciled and filed against the live portal for AY 2026-27
on 28–29 July 2026: one complete ITR-2 and one complete ITR-3, both filed and
e-verified. Separately, the tax engine's synthetic regression case preserves exact
s.288A and s.288B rounding checks without publishing figures from either return.

Open items, stated rather than papered over:

| Item | Status |
|---|---|
| ITR-3 *Select Schedule* picker | Never captured. Marked `[UNVERIFIED]` rather than reconstructed |
| s.87A against s.111A, old regime | Statute allows it; the AY 2026-27 utility's behaviour is unpublished |
| Intraday business code 21011 vs 21009 | Schema enum and a filed return disagree. Verify the code, never the description |
| Brokers other than Zerodha | Layout-agnostic, but only Zerodha has a fixture |
| Bank statement layouts | Three tested. One 58-page statement yielded 2 rows and says so |
| Document formats awaiting specimens | [Known gaps and today's refusal or partial-read behaviour](skills/itr-filing-copilot/references/known-gaps.md) |

## Writing

- [Your broker statement probably states your capital gains twice](docs/broker-statements-state-gains-twice.md)
  — what two real Zerodha workbooks turned up, and why the test suite missed it.

## Related work

| Project | Does well |
|---|---|
| [casparser](https://github.com/codereverser/casparser) | The mature CAMS and KFintech CAS parser |
| [folioman](https://github.com/codereverser/folioman) | The most careful Schedule 112A implementation anywhere |
| [form16-parser](https://github.com/INF800/form16-parser) | TRACES-generated Form 16 Part A and Part B |
| [itr-wala](https://github.com/karanb192/itr-wala), [itr-prep-skill](https://github.com/NidheeshJain/itr-prep-skill) | Other ITR agent skills, different emphases |

Maintain something in this space? Open an issue and I'll add a line.

## Contributing

Portal observations are the most valuable contribution here and the hardest to
get. One screenshot of a schedule picker, or one error string quoted exactly, is
worth more than a page of prose. [CONTRIBUTING.md](CONTRIBUTING.md) explains how.

**Most useful right now:** run
`parse_capital_gains.py --inspect` on a Tax P&L from any broker other than
Zerodha, or `parse_bank_statement.py --text` on a statement it reads badly, and
paste the structure into an issue. Sheet names and header rows only.

**Never post real tax data.** No PAN, Aadhaar, GSTIN, TAN, name,
acknowledgement number, challan identifier, bank account, tax amount, ITR JSON,
or unredacted screenshot. CI scans every pull request and fails the build.

Security reports go to [SECURITY.md](SECURITY.md), never a public issue.

---

<div align="center">

**[Disclaimer and licence](docs/disclaimer.md)** · Apache-2.0 · alpha ·
AY 2026-27 · resident individuals, non-audit

*Language models produce fluent, confident, wrong figures. Verify every number
against the primary source. You are legally responsible for every figure in the
filed return.*

</div>
