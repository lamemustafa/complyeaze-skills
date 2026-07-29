# Changelog

## [0.1.1](https://github.com/lamemustafa/complyeaze-skills/compare/complyeaze-skills-v0.1.0...complyeaze-skills-v0.1.1) (2026-07-29)


### Features

* ComplyEaze skills — ITR filing copilot for AY 2026-27 ([5aee50a](https://github.com/lamemustafa/complyeaze-skills/commit/5aee50ab8c923f077aed9e7d8c7d3524d21bbad6))

## 0.1.0 (2026-07-28)

Initial alpha release.

### Features

* **itr-filing-copilot:** ITR-1 / ITR-2 / ITR-3 / ITR-4 non-audit filing copilot for
  AY 2026-27, covering document reconciliation against AIS/TIS/26AS, form and schedule
  selection, field-by-field portal entry, CBDT validation rules, and post-filing
  rectification and revision
* **`scripts/compute_tax.py`** — deterministic stdlib-only tax engine for AY 2026-27 with
  golden cases and invariant checks, so the model never does the arithmetic. Reproduces a
  real filed ITR-2 to the paisa
* **`scripts/open_ais.py`** — derives the AIS/TIS password and decrypts
* Eight reference files loaded on demand: portal traps, schedule and section maps, per-form
  flows, the online utility walkthrough, verbatim error messages, JSON audit checks,
  post-filing procedures, and AY 2026-27 rates

### Documentation

* Verified against two complete live filings (ITR-2 and ITR-3) on the AY 2026-27 portal,
  28–29 July 2026
* Every claim tagged `[observed]` / `[documented]` / `[inferred]` / `[UNVERIFIED]`
