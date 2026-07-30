# Changelog

## [0.1.5](https://github.com/lamemustafa/complyeaze-skills/compare/complyeaze-skills-v0.1.4...complyeaze-skills-v0.1.5) (2026-07-30)


### Fixes

* **capital-gains:** stop reporting figures from a layout that was never recognised ([#17](https://github.com/lamemustafa/complyeaze-skills/issues/17)) ([b5a7e93](https://github.com/lamemustafa/complyeaze-skills/commit/b5a7e933f04f9e0e4ac9494308c44b856d555918))
* **portal-json:** stop reporting a return as reconciled when its income was never read ([#15](https://github.com/lamemustafa/complyeaze-skills/issues/15)) ([dee36f8](https://github.com/lamemustafa/complyeaze-skills/commit/dee36f87368ea1f29cc85752f53d9960566dcb67))

## [0.1.4](https://github.com/lamemustafa/complyeaze-skills/compare/complyeaze-skills-v0.1.3...complyeaze-skills-v0.1.4) (2026-07-30)


### Features

* **parsers:** give the parsers the --summary that compute_tax already has ([#12](https://github.com/lamemustafa/complyeaze-skills/issues/12)) ([f89a9f7](https://github.com/lamemustafa/complyeaze-skills/commit/f89a9f712878425e22c0641d304c4496b97a33a8))

## [0.1.3](https://github.com/lamemustafa/complyeaze-skills/compare/complyeaze-skills-v0.1.2...complyeaze-skills-v0.1.3) (2026-07-30)


### Documentation

* record the gaps that need documents nobody has ([#10](https://github.com/lamemustafa/complyeaze-skills/issues/10)) ([cf1e2b5](https://github.com/lamemustafa/complyeaze-skills/commit/cf1e2b5844c4ab40ba4a6e83731d1bb40f687129))

## [0.1.2](https://github.com/lamemustafa/complyeaze-skills/compare/complyeaze-skills-v0.1.1...complyeaze-skills-v0.1.2) (2026-07-30)


### Features

* **read-pdf:** open the portal's Java-serialized downloads ([#9](https://github.com/lamemustafa/complyeaze-skills/issues/9)) ([0fff30f](https://github.com/lamemustafa/complyeaze-skills/commit/0fff30f2a59b95bf8bf247ead60f79ca3b303169))


### Fixes

* **read-pdf:** refuse a document that extracted to almost nothing ([#6](https://github.com/lamemustafa/complyeaze-skills/issues/6)) ([f5d262e](https://github.com/lamemustafa/complyeaze-skills/commit/f5d262eb3a77426399bc599433b77fc544335e7a))
* **release:** keep the README version in step with the manifest ([#7](https://github.com/lamemustafa/complyeaze-skills/issues/7)) ([60d2c4d](https://github.com/lamemustafa/complyeaze-skills/commit/60d2c4d92fbe5c2b2d751b3fc293b60e6a94678a))

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
