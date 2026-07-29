# Changelog

## [0.1.1](https://github.com/lamemustafa/complyeaze-skills/compare/complyeaze-skills-v0.1.0...complyeaze-skills-v0.1.1) (2026-07-29)


### Maintenance

* **deps:** Bump actions/checkout from 4.4.0 to 7.0.1 ([#1](https://github.com/lamemustafa/complyeaze-skills/issues/1)) ([bdc3f34](https://github.com/lamemustafa/complyeaze-skills/commit/bdc3f348093a6b032102e864c5f39587904225ff))
* **deps:** Bump actions/setup-python from 5.6.0 to 7.0.0 ([#3](https://github.com/lamemustafa/complyeaze-skills/issues/3)) ([11b89fa](https://github.com/lamemustafa/complyeaze-skills/commit/11b89fa6a04f344465d555d3d1a78359191d9d1a))
* **deps:** Bump googleapis/release-please-action from 4.4.1 to 5.0.0 ([#2](https://github.com/lamemustafa/complyeaze-skills/issues/2)) ([71ade14](https://github.com/lamemustafa/complyeaze-skills/commit/71ade14d778269e6539ead0b343620b01d27b6f4))

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
