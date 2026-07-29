# Authoring standard

This repository will hold skills for several compliance domains — income tax
first, then GST, TDS returns, ROC and MCA filings, PF and ESI. Most of the
decisions that make that painful are cheap now and expensive later, so they are
written down here.

Read this before adding a skill. `CONTRIBUTING.md` covers how to contribute;
this covers what a skill in this repository has to look like.

## Naming

`<subject>-<action>`, always carrying a verb or a verb-shaped noun.

| Good | Why |
|---|---|
| `itr-filing-copilot` | names the artefact and the job |
| `gstr-3b-filing` | names the specific return |
| `tds-return-24q` | names the form |
| `roc-annual-filing` | names the event |

| Avoid | Why |
|---|---|
| `gst` | a domain word taken as a skill name blocks every future GST skill and collides with any other GST skill a user has installed |
| `tax-helper` | triggers on everything, helps with nothing |
| `gst-utils` | nothing about it says when to use it |

Reserve bare domain words for directories and documentation, never for a skill.

## The description is the product

It is the only part loaded before the skill triggers, and it carries the entire
burden of getting invoked. Three rules, in order of how much they matter:

1. **Put the trigger vocabulary first.** Codex shares a character budget across
   every installed skill and truncates from the end. CI warns if the first 232
   characters carry no `use when` clause.
2. **Name the domain noun explicitly** — GST, TDS, ITR, ROC, PF. A user with
   four compliance skills installed needs the router to have something to route
   on.
3. **Say what it does not cover.** `Do NOT use for…` in the description does
   more work than any amount of scope-limiting prose in the body.

Never compress the *procedure* into the description. A description that reads
"reconcile, then compute, then file" invites the model to do those three things
from the description alone and never open the file.

## Structure

```
skills/<name>/
  SKILL.md              the router: under 500 lines, loaded when the skill triggers
  references/*.md       loaded on demand, one level deep, each named in SKILL.md
  scripts/*.py          deterministic work
  evals/
    golden/cases.json   exact expected outputs, no model involved
    evals.json          output-quality evals
    trigger_queries.json  does the description fire when it should
    fixtures/           synthetic input files
```

`SKILL.md` decides and routes. It should not contain anything a reader needs
only sometimes — that belongs in `references/`, named with the condition that
sends you there. "Read `references/error-messages.md` when something blocks
upload" beats "see references for more detail".

## Scripts

Standard library only, and offline. Someone following a filing walkthrough
should never have to debug a pip install before they can read their own data.
Where a format seems to need a dependency, look again: `.xlsx` is a zip of XML,
and `read_tabular.py` reads it in about a hundred and fifty lines.

Three rules that are not negotiable:

- **Arithmetic belongs in a script, judgement belongs in prose.** Never move a
  computation out of a script and into SKILL.md text.
- **Refuse rather than guess.** A script that hits a case it does not model must
  exit non-zero with a message naming what is missing and why it matters.
  `compute_tax.py` refuses on a non-resident; `parse_capital_gains.py` refuses
  to decide whether a fund is equity-oriented. Those refusals are the feature.
- **Every number that changes needs a failing test first.** A rate, threshold,
  deadline or classification rule changes only alongside a case in
  `evals/golden/cases.json` that fails before the change and passes after,
  carrying a `source` line naming the section, validation rule or observed
  screen.

## Facts and provenance

Every rate, limit, threshold and date is shape, not truth. It goes stale
annually and mid-year amendments happen.

Tag every non-obvious claim:

| Tag | Means |
|---|---|
| `[observed]` | Someone saw this on a live screen, or read it out of a filed JSON or preview PDF |
| `[documented]` | It is in a notified form, a validation-rules PDF, a JSON schema, an official manual, or the Act |
| `[inferred]` | Reasoned from something adjacent. Plausible, not confirmed |
| `[UNVERIFIED]` | Asserted at some point and never confirmed. May be wrong |

Where a published source and a live screen disagree, record the conflict and say
what would resolve it. Do not pick a winner, and do not launder a memory into a
fact.

A new period gets a new file. `rates-ay2026-27.md` is never edited to describe
AY 2027-28, and a GST skill's `rates-2026.md` is never edited into 2027.

## The disclaimer

`shared/disclaimer.md` is canonical. Every SKILL.md opens with it as a markdown
quote block, copied verbatim, because a skill directory has to work when it is
copied somewhere on its own and a relative link would resolve to nothing. CI
checks the copies against the canonical text.

## Versioning

Per-skill `metadata.version` carrying the `# x-release-please-version` marker,
plus a period pin: `assessment-year` for annual filings, `period` for the
monthly and quarterly ones, and `last-verified` as a date. Release Please keeps
the version in step with the tag; the period pin is what tells a reader whether
the file has gone stale.

## Growing past one skill

Two things break first, and CI checks both:

- **Name collisions.** No two skills may share a name, and any two descriptions
  that read too much alike will make the model pick between them at random.
- **Router gap.** Once there are more than about three domains, a user asking
  "what do I need to file this month" is not addressing any one skill. That is
  when a `compliance-calendar` skill earns its place: a description that fires
  on undirected deadline questions, and a body that is a routing table from due
  date to the skill that handles it. Do not build it before then.
