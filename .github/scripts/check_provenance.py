#!/usr/bin/env python3
"""Flag added text that states a tax rule without saying how it is known.

    python3 .github/scripts/check_provenance.py              # warn, exit 0
    python3 .github/scripts/check_provenance.py --strict      # fail on a hit
    python3 .github/scripts/check_provenance.py --base <ref>  # against a ref

Why this exists
---------------
AGENTS.md requires every non-obvious claim to carry `[observed]`,
`[documented]`, `[inferred]` or `[UNVERIFIED]`. Nothing enforced it, so the
rule was enforced by review instead — and review sees a diff.

`[observed 2026-08-01, 66 review threads across PRs #30-#37]` Seventeen of those
findings were a missing provenance tag, sixteen of them on prose a *fix* had just
added: a summary line, a refusal, a resolver's explanation. Each cost a round.
Twelve were in scripts, four in references. Measured against the exact strings
review flagged, the pattern below catches roughly two thirds of them, in a second,
before the push.

How it picks the base
---------------------
The merge base with master, so a branch that is simply behind is not credited
with master's own changes. `[observed 2026-08-01]` A CI checkout is shallow — it
has the base commit and none of its ancestry — so `merge-base` fails there and a
three-dot diff fails with it. The fallback compares the two trees directly,
which needs no ancestry, and a failure at that point is raised rather than
reported as a clean result.

Why it is diff-scoped
---------------------
`[observed 2026-08-01]` A scan of the whole tree finds around a hundred untagged
statutory claims already in it. A blocking gate over all of them would fail on
master and be turned off within a day. Checking only added lines makes the rule
mean what it has meant in practice — new claims carry their provenance — without
pretending the backlog does not exist. Backfilling it is worth doing; this does
not wait for that.

What it cannot do
-----------------
It finds claims that *name* something statutory or quote a rate. A sentence like
"the late fee is tiered on total income" states a rule and matches nothing here.
Three of the seventeen were of that kind. This narrows the pre-push pass; it does
not replace it.

It also asks two questions before flagging, because a bare mention is not an
assertion: does the text carry a verb of legal effect (`applies`, `is charged`,
`is deemed`, `cannot`), or is it a table row where the columns supply the verb?
`late filing fee s.234F` is a label and `check("s.234F" in out, ...)` is a test;
neither states a rule, and demanding a tag on them is the noise that gets a
check switched off.

`[observed 2026-08-01]` Measured against the four most recent merged commits,
which review has already passed: 9 hits across the four. Two are a command
invocation and a code statement carrying a comment; the rest are genuine
untagged claims in user-facing strings — including one that tells a filer an
updated return "also carries s.140B additional tax of 25/50/60/70 per cent by
band" with no provenance at all. Both this reviewer and its author missed those.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

# A statutory reference in the forms this repository actually writes.
STATUTE = re.compile(
    r"\bs\.\s?\d"                        # s.50AA, s. 139
    r"|\bsection\s\d"                    # section 203
    r"|\bu/s\b"                          # u/s 139(4)
    r"|\bSchedule\s[A-Z]"                # Schedule OS, Schedule CG
    r"|\brule\s\d"                       # rule 120
    r"|\b\d{2,3}[A-Z]{1,3}\b"            # 111A, 112A, 115BAC, 234F
    r"|\bTable\s[A-Z]\b"                 # Table F
    r"|\bFinance\s\(?No\.?\s?\d?\)?\s?Act|\bFinance\sAct"
    r"|\d\s?%|\d\s?per\s?cent",         # 12.5%, 20 per cent
    re.I)
TAG = re.compile(r"\[(?:observed|documented|inferred|UNVERIFIED)\b")
# Naming a section is not asserting anything about it. `late filing fee s.234F`
# is a label and `check("s.234F" in out, ...)` is a test; neither states a rule,
# and tagging them would be noise that gets the whole check switched off. A
# claim says what the law DOES, so it carries a verb of that kind — or it is a
# table row, where the verb is implied by the columns.
CLAIM_VERB = re.compile(
    r"\b(?:is|are|was|were|be|becomes?|means?|applies|applied|apply|"
    r"charged?|taxed?|deemed?|requires?|required|gives?|bars?|barred|"
    r"provides?|allows?|allowed|treats?|treated|counts?|falls?|attracts?|"
    r"must|cannot|does not|do not|no longer|only where|only when)\b", re.I)
TABLE_ROW = re.compile(r"^\s*\|")
# Below this a fragment is a label or a key, not a claim. The floor is low on
# purpose: a two-cell rate-table row naming a section and a percentage is a
# complete statutory claim, normalises to about a dozen characters, and a rate
# table is exactly where an untagged one hides.
MIN_CLAIM_CHARS = 12
CHECKED_SUFFIXES = (".py", ".md")
# Paths whose added lines are prose or user-facing strings. Workflow and config
# files quote sections in passing without asserting anything; docs/ and the root
# markdown carry guidance a reader acts on, so they are checked too.
CHECKED_PREFIXES = ("skills/", ".github/scripts/", "docs/")

# A line that begins a new statement or paragraph ends the previous claim.
# Without this a wholly new file arrives as ONE run of added lines, and a single
# tag anywhere in it would vouch for every untagged claim below it.
BOUNDARY = re.compile(
    r"^\s*(?:def |class |return |raise |yield |import |from )"
    r"|^\s*(?:if |elif |else|for |while |with |try|except|finally)"
    r"|^\s*[\w.\[\]]+\s*=[^=]"
    r"|^\s*\w[\w.]*\(")
# Markdown splits on the blank line between paragraphs — except that a list or
# a table attaches to the paragraph introducing it. A `[documented]` sentence
# above a rate table governs the table, and demanding the tag on every row is
# noise that gets a check switched off; but two separate paragraphs are two
# separate claims, so one tag cannot vouch for the file.
MD_BOUNDARY = re.compile(r"^\s*$|^#{1,6}\s")
MD_CONTINUATION = re.compile(r"^\s*(?:[-*]\s|\d+\.\s|\|)")


def changed_blocks(base: str) -> list[tuple[str, int, list[str]]]:
    """Added lines from the diff, split into claim-sized blocks.

    A block is the unit a tag belongs to. In Python that is a statement: a
    message is assembled from adjacent string literals, so a tag on any of them
    covers the message. In Markdown it is a paragraph, together with any list or
    table immediately below it — a `[documented]` sentence introducing a rate
    table governs the table, and demanding the tag on every row would be noise.
    Two separate paragraphs are two claims, so one tag cannot vouch for a file.
    """
    # Prefer the merge base, so a branch behind master is not credited with
    # master's own changes. But a CI checkout is shallow: it has the base commit
    # and no ancestry, so `merge-base` fails and a three-dot diff fails with it.
    # Fall back to comparing the two trees directly, which needs no ancestry.
    merge_base = subprocess.run(["git", "merge-base", base, "HEAD"],
                                capture_output=True, text=True)
    left = merge_base.stdout.strip() if merge_base.returncode == 0 else base
    proc = subprocess.run(["git", "diff", "--unified=0", left, "HEAD"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        # Empty stdout from a failed diff is not an empty diff. Reporting it as
        # "everything is tagged" is exactly a gate passing while proving nothing.
        raise SystemExit(f"could not diff against {base!r}: "
                         f"{proc.stderr.strip() or 'git diff failed'}")

    blocks: list[tuple[str, int, list[str]]] = []
    path: str | None = None
    lineno = start_line = 0
    run: list[str] = []
    blank_run = False          # a Markdown blank line is pending

    def flush():
        nonlocal blank_run
        if path and any(line.strip() for line in run):
            blocks.append((path, start_line, list(run)))
        run.clear()
        blank_run = False

    for line in proc.stdout.splitlines():
        if line.startswith("+++ b/"):
            flush()
            path = line[6:]
            continue
        if line.startswith("@@"):
            flush()
            m = re.search(r"\+(\d+)", line)
            lineno = int(m.group(1)) if m else 0
            continue
        if not line.startswith("+") or line.startswith("+++"):
            flush()
            continue

        body = line[1:]
        if (path or "").endswith(".md"):
            if MD_BOUNDARY.match(body):
                # Hold the paragraph open: what follows decides whether the
                # blank line ended the claim or merely preceded its table.
                blank_run = True
                lineno += 1
                continue
            if blank_run and not MD_CONTINUATION.match(body):
                flush()
            blank_run = False
        elif run and BOUNDARY.match(body):
            flush()

        if not run:
            start_line = lineno
        run.append(body)
        lineno += 1
    flush()
    return blocks


def is_checked(path: str) -> bool:
    if not path.endswith(CHECKED_SUFFIXES):
        return False
    # Root markdown — README.md, AGENTS.md — is guidance too.
    return path.startswith(CHECKED_PREFIXES) or "/" not in path


def claim_of(block: list[str]) -> str:
    """The prose in a run of added lines, with code punctuation removed.

    Python strings arrive wrapped in quotes and joined by implicit
    concatenation; stripping the quoting is what lets a statute on one line and
    a tag on the next count as one claim."""
    text = " ".join(block)
    text = re.sub(r"^\s*[#*\->|]+", " ", text)       # comment and list markers
    text = text.replace("\\n", " ").replace('"', " ").replace("'", " ")
    # An identifier is not a claim. `fee_234F` and `fee_234F_basis` carry a
    # section number and assert nothing; the sentence they render is a separate
    # string, and that is where the tag belongs. Dropping snake_case tokens
    # keeps the plumbing that assembles a message from being read as one.
    text = re.sub(r"\b\w*_\w+\b", " ", text)
    text = re.sub(r"[-=]{4,}", " ", text)            # section dividers
    return re.sub(r"\s+", " ", text).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=None,
                    help="ref to diff against; default is the merge base with "
                         "origin/master, falling back to master")
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero on a hit")
    a = ap.parse_args()

    base = a.base
    if base is None:
        for candidate in ("origin/master", "master"):
            got = subprocess.run(["git", "merge-base", candidate, "HEAD"],
                                 capture_output=True, text=True)
            if got.returncode == 0:
                base = got.stdout.strip()
                break
    if not base:
        # Silence here is indistinguishable from a clean result. In CI a shallow
        # checkout makes every merge-base fail, so this is the likely path.
        raise SystemExit(
            "no base to diff against. In CI, check out with fetch-depth: 0 or "
            "pass --base explicitly; the check has examined nothing.")

    hits = []
    for path, lineno, block in changed_blocks(base):
        if not is_checked(path):
            continue
        # A compiled pattern quotes section numbers in order to match them. It
        # asserts nothing about the law and cannot carry a tag sensibly.
        if any("re.compile(" in line for line in block):
            continue
        if block[0].lstrip().startswith(("check(", "assert ")):
            continue
        claim = claim_of(block)
        if len(claim) < MIN_CLAIM_CHARS:
            continue
        if not STATUTE.search(claim) or TAG.search(claim):
            continue
        if not (CLAIM_VERB.search(claim) or TABLE_ROW.match(block[0])):
            continue
        hits.append((path, lineno, claim))

    if not hits:
        print("Every added statutory claim carries a provenance tag.")
        return 0

    print(f"{len(hits)} added claim(s) name a section, Schedule, rule or rate "
          f"with no provenance tag:\n")
    for path, lineno, claim in hits:
        print(f"  {path}:{lineno}")
        print(f"    {claim[:150]}{'…' if len(claim) > 150 else ''}\n")
    print("Add [observed] / [documented] / [inferred] / [UNVERIFIED]. A tag "
          "anywhere in the same string or paragraph counts.\n"
          "If the line is a quotation of someone else's text rather than a "
          "claim, tag the sentence that adopts it.")
    return 1 if a.strict else 0


if __name__ == "__main__":
    sys.exit(main())
