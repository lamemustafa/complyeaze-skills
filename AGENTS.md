# Working On This Repository

Guidance for AI agents contributing to ComplyEaze Skills. This is *not* the distribution
artifact — the skills themselves live in `skills/*/SKILL.md`.

## What This Repository Is

Agent skills for Indian tax and compliance, written to the
[Agent Skills](https://agentskills.io) open standard. Prose and prompts, not application
code. The value is accuracy about a system that changes without notice.

## Layout

```
skills/<skill-name>/SKILL.md         the router — under 500 lines
skills/<skill-name>/references/*.md  loaded on demand, one level deep
skills/<skill-name>/scripts/*.py     deterministic work, stdlib only
skills/<skill-name>/evals/           golden cases, output-quality evals, trigger queries
.claude-plugin/marketplace.json      Claude Code plugin install
.agents/skills/<skill-name>          symlink — Codex, Antigravity, Cursor, Copilot read here
```

`name` in frontmatter **must** equal the directory name. Claude Code derives the slash
command from the directory regardless of frontmatter.

## Rules That Are Not Negotiable

**Never commit real tax data.** No PAN, Aadhaar, GSTIN, TAN, taxpayer name, acknowledgement
number, challan identifier, bank account, tax amount, ITR JSON, AIS/TIS/26AS file, portal
HTML, or unredacted screenshot. Placeholder patterns only: `ABCDE1234F`,
`XXXXXXXXXX`, `₹1,00,000`.

**Tag every non-obvious claim.** `[observed]` (seen on a live screen or read out of a filed
JSON) · `[documented]` (notified form, validation-rules PDF, JSON schema, Act) ·
`[inferred]` · `[UNVERIFIED]`. Do not launder a memory into a fact. Where a source and a
live screen disagree, record the conflict and say what would resolve it.

`python3 .github/scripts/check_provenance.py` reports added lines that name a section,
Schedule, rule or rate without a tag. Run it before pushing. It is advisory, it reads
only your diff, and it cannot see a claim that names nothing statutory — it narrows the
pass below, it does not replace it.

## Before you push

`[observed 2026-08-01, 66 review threads across PRs #30-#37]` 68% of those findings
arrived after the first round, and 46% were on lines an earlier fix had just added.
Fixing a summary meant adding a sentence, which then needed a tag, a test and its
sibling path — three findings that did not exist before the fix. Check your own diff for
the five classes that produced almost all of them:

1. Every added claim naming a section, Schedule, rule or rate carries a provenance tag.
2. Every behaviour change reaches **both** output modes — `--summary` and JSON — and the
   **sibling branch** of any conditional touched.
3. Every threshold, date or rate introduced has a case in `evals/golden/cases.json` that
   would fail if it changed.
4. No real figure, in any formatting. Indian comma grouping hides one from a search for
   its digits, and a value *derived* from a real one appears in no list of what leaked.
5. A refusal is raised in the engine, never printed by one renderer — otherwise the other
   output mode returns a number for the case that was refused.

**Cite rates to a primary source.** Any figure in a `rates-*.md` file needs a section,
notification or Finance Act reference and the date it was checked.

**Do not reconstruct a portal screen nobody has seen.** Row numbers move between forms and
between years. If confidence is below about 90%, mark it `[UNVERIFIED]` and say a
screenshot is needed. The ITR-3 Select Schedule picker is the standing example.

**Arithmetic belongs in `scripts/`, judgement belongs in prose.** If an output is
verifiable and mechanical, script it and give it a golden test. If it needs interpretation,
write it. Never move a computation from `compute_tax.py` into SKILL.md prose.

Every script must be stdlib-only where possible, run offline, read nothing it was not
given, and **refuse rather than guess** when a case falls outside what it handles.

**A changed number needs a failing test first.** Any edit to a rate, threshold, deadline or
form-selection rule needs a case in `evals/golden/cases.json` that fails before the change
and passes after, with a `source` line naming the section, validation rule or observed
screen. Refusals are cases too — `{"outcome": "refuse", "must_mention": [...]}`.

**Know which Act you are in.** AY 2026-27 = FY 2025-26 = the Income-tax Act **1961**. The
Income-tax Act 2025 commences 1 April 2026 and its first tax year is 2026-27, so returns
under it are filed from 2027. The portal runs both modules concurrently. Never cite a 2025
Act section in AY 2026-27 material.

## Budgets

| | Limit | Why |
|---|---|---|
| `SKILL.md` | < 500 lines, < 5k tokens | Spec recommendation; loaded on every trigger |
| `description` | < 1024 chars | Spec limit; Codex shares 8,000 chars across *all* installed skills |
| reference files | one level deep | Spec: avoid nested reference chains |
| individual reference file | keep focused | it is loaded whole; a 25 KB file costs ~6k tokens on one lookup |

Front-load trigger keywords in the first sentence of `description` — Codex truncates.

## Commits

Conventional Commits. `type(scope): imperative summary`. Types: `build`, `chore`, `ci`,
`docs`, `feat`, `fix`, `perf`, `refactor`, `revert`, `test`. Scope is the skill name where
applicable. **PR titles follow the same rule and are enforced by CI.**

Releases are cut by Release Please from commit history — `.github/workflows/release.yml`
opens the release PR, and merging it creates the tag, the GitHub release and the changelog
entry. Never tag by hand. A `feat:` bumps minor, `fix:` bumps patch; breaking changes need
`!` and a footer. While at `0.x` every release is marked prerelease.

Version lives in three places and Release Please keeps them in sync: the manifest,
`metadata.version` in `SKILL.md` (marked `# x-release-please-version`), and both version
fields in `.claude-plugin/marketplace.json`.

## Before You Change Anything

- **A rate or threshold** — cite the primary source and update `last-verified` in
  frontmatter
- **A new assessment year** — new `rates-ay*.md`, do not edit the old one in place
- **The escalate-to-a-professional list, or any disclaimer** — open a design issue first
- **Anything touching filing procedure** — two approvals
