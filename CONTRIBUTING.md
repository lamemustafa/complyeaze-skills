# Contributing To ComplyEaze Skills

The most valuable contribution here is not code. It is **"I saw this on a live screen."**

Portal behaviour is undocumented, changes without notice, and differs between forms and
assessment years. No amount of research substitutes for one person reporting what actually
happened. This document exists to make that contribution safe to publish.

## Before Opening An Issue

**Never post real tax data in a public space.** Not in an issue, a pull request, a comment,
or a screenshot.

PAN · Aadhaar · GSTIN · TAN · taxpayer or employer names · acknowledgement numbers ·
challan identifiers (CIN, BSR code, serial number) · bank account numbers or IFSC · demat
or client IDs · tax amounts · ITR JSON exports · prefill JSON · AIS, TIS or Form 26AS files
· portal HTML · network captures · OTPs · session cookies · unredacted screenshots ·
`SWCreatedBy` codes.

If your report cannot be understood without one of these, email
**contact@complyeaze.com** instead of opening an issue.

Use placeholders: `ABCDE1234F` for a PAN, `XXXXXXXXXX` for any identifier, round numbers
like `₹1,00,000` for amounts.

## How To Report A Portal Observation

Use the **Portal observation** issue template. It asks for:

1. **Assessment year and form** — "ITR-2, AY 2026-27"
2. **The screen**, by its portal label — "Schedule Capital Gains → A(I) → item 5"
3. **The literal string**, quoted exactly, with identifiers replaced by `XXXXXXXXXX`.
   Verbatim error text is the single hardest thing to obtain and the most useful. It is how
   a stuck filer finds the fix by searching
4. **What you did immediately before** it appeared
5. **Blocking or cosmetic** — did it prevent upload, or was it advisory
6. **Date observed and browser**
7. **Redacted screenshots only** — crop to the error banner or the field label. Never a
   full page

## Evidence Tiers

Every claim in this repository carries its provenance, because this domain punishes
confident wrongness and the portal is under-documented.

| Tag | Means |
|---|---|
| `[observed]` | Someone saw this on a live screen, or read it out of a filed JSON or preview PDF |
| `[documented]` | It is in a notified form, a CBDT validation-rules PDF, a JSON schema, an official manual, or the Act |
| `[inferred]` | Reasoned from something adjacent. Plausible, not confirmed |
| `[UNVERIFIED]` | Asserted at some point and never confirmed. May be wrong |

**Do not launder a memory into a fact.** Two claims in this skill were demoted after
re-examination — both had been stated with total confidence. When a source and a screen
disagree, record the conflict and say what would resolve it, rather than picking a winner.

An `[observed]` claim that a second contributor reproduces is worth saying so. A single
sighting is still worth reporting — just tag it honestly.

## Rates, Thresholds And Deadlines

Any figure in a `rates-*.md` file must cite a **primary source** — a section of the Act, a
CBDT notification or circular, or a Finance Act clause — and record the date it was checked.

A rule used but not recorded is treated as a defect. The reference files are *shape, not
truth*: they go stale annually, and mid-year amendments happen.

**A new assessment year gets a new file.** Do not edit `rates-ay2026-27.md` to describe
AY 2027-28.

## Skill Authoring Rules

- `SKILL.md` under **500 lines** and roughly **5,000 tokens**
- `description` under **1024 characters**, with trigger phrases front-loaded. Codex shares
  an **8,000-character budget across every installed skill** and truncates from the end
- `name` in frontmatter **must equal** the directory name
- Reference files **one level deep** from `SKILL.md`. No nested reference chains
- Deterministic work belongs in `scripts/`; judgement belongs in prose
- Scripts stay **stdlib-only**. No dependencies, no network, no disk reads beyond
  explicitly passed paths
- Every skill needs a symlink at `.agents/skills/<name>` — that is the directory Codex,
  Antigravity, Cursor and Copilot read. CI fails without it
- `metadata.version` carries a `# x-release-please-version` marker so releases bump it

## Run The Checks Before You Open A PR

Everything runs locally with no dependencies except PyYAML for the template check:

```bash
python3 .github/scripts/validate_skills.py
python3 .github/scripts/scan_pii.py
python3 skills/itr-filing-copilot/scripts/compute_tax.py --self-test
python3 skills/itr-filing-copilot/scripts/compute_tax.py \
    --golden skills/itr-filing-copilot/evals/golden/cases.json
npx skills-ref validate ./skills/itr-filing-copilot   # optional, spec conformance
```

CI runs the same set plus YAML/JSON parse checks and the refusal tests.

## Changing A Number

Any change to a rate, threshold, deadline or form-selection rule needs **a golden case
that fails before the change and passes after**. Add it to
`skills/itr-filing-copilot/evals/golden/cases.json` with a `source` line naming the
section, validation rule or observed screen it comes from.

This is not ceremony. A wrong number in this repo costs a stranger money, and prose alone
does not stop a regression. See `skills/itr-filing-copilot/evals/README.md` for the three
eval tiers and what each is for.

**Fixtures must be synthetic.** No real PAN, name, acknowledgement number or ITR JSON in
any eval file — round any figure that originates from a real return and strip every
identifier. CI scans the eval directory along with everything else.

## What Needs A Design Issue First

Open an issue and get agreement before a pull request for:

- A new form, a new assessment year, or a new jurisdiction
- Any change to the **escalate to a qualified professional** list
- Any change to **disclaimer or trademark** wording
- Anything that would make the skill touch the portal, handle credentials, or generate an
  uploadable ITR JSON — these are deliberate refusal boundaries, documented in
  [SECURITY.md](SECURITY.md)

## Sign-Off

Contributions are licensed under Apache-2.0. Sign off each commit with the
[Developer Certificate of Origin](https://developercertificate.org/):

```
git commit -s -m "fix(itr-filing-copilot): correct Schedule CG row number for ITR-3"
```

Two approvals are required for changes to rates, filing procedure, or the refusal
boundaries.

## Conventional Commits

`type(scope): imperative summary` — `build`, `chore`, `ci`, `docs`, `feat`, `fix`, `perf`,
`refactor`, `revert`, `test`. Releases and the changelog are generated from commit history,
so this is load-bearing rather than cosmetic.

**Pull request titles follow the same rule** and are checked by CI, because the PR title
is what lands on `master` when a PR is squashed. Append `!` for a breaking change:
`feat(itr-filing-copilot)!: drop AY 2025-26 rate tables`.

Releases are cut by Release Please from those commits. Do not tag by hand — the bot opens
a release PR, and merging it creates the tag, the GitHub release and the changelog entry.
While the project is at `0.x` every release is marked as a prerelease.
