#!/usr/bin/env python3
"""Run the parser golden cases in evals/golden/cases.json.

    python3 .github/scripts/run_parser_golden.py

Why this exists
---------------
`compute_tax.py --golden` has covered every tax number since the engine was
written, and AGENTS.md requires a changed rate, threshold, deadline or
form-selection rule to arrive with a case in `evals/golden/cases.json`.

But the parsers decide tax questions too, and until now there was nowhere to
put a case about one. s.55(2)(ac) grandfathering is the example that forced
this: 31 January 2018 decides whether a broker's profit figure is the taxable
gain or a number that will move, `parse_capital_gains.py` acts on that date,
and `compute_tax.py` has no argument that could express it. The threshold was
real, the rule applied, and the mechanism did not exist.

The cases live in the same file as the tax ones, under `parser_cases`, so the
rule stays literally true: a threshold gets a case in cases.json whichever side
of the toolchain implements it. `compute_tax.py --golden` reads only `cases`
and ignores this key.

Case shape
----------
    {
      "id":     "unique-slug",
      "script": "parse_capital_gains.py",
      "source": "why this is the right answer, with its provenance tag",
      "files":  {"statement.csv": "inline content, invented, identifier-free"},
      "args":   ["--rows"],
      "expect": {
        "exit_code": 0,
        "paths":   {"buckets.112A.gain": 117400.0},
        "absent":  ["needs_confirmation.mf_unknown.quarterly"],
        "present": ["needs_confirmation.mf_unknown.quarterly_withheld"],
        "stdout_contains": ["fair market value"]
      }
    }

Inline file content keeps a case readable next to its assertion and keeps the
fixture directory for things that have to be binary. Nothing here writes
outside a temporary directory, and no case may carry a real identifier — the
same scan_pii.py that guards the rest of the tree reads this file too.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILL = os.path.join(ROOT, "skills", "itr-filing-copilot")
SCRIPTS = os.path.join(SKILL, "scripts")
GOLDEN = os.path.join(SKILL, "evals", "golden", "cases.json")
MISSING = object()
PROVENANCE_TAG = re.compile(r"\[(?:observed|documented|inferred|UNVERIFIED)\]")


def has_exact_provenance_tag(source: object) -> bool:
    """Whether a source can be classified by the repository tag vocabulary."""
    return isinstance(source, str) and bool(PROVENANCE_TAG.search(source))


def json_values_match(got: object, wanted: object) -> bool:
    """Compare both value and JSON type; downstream readers rely on schema."""
    return type(got) is type(wanted) and got == wanted


def value_at(document, path: str):
    """Walk a dotted path. Returns the sentinel when any step is missing."""
    node = document
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return MISSING
        node = node[part]
    return node


def run_case(case: dict) -> list[str]:
    """Return the failures for one case, empty when it passes."""
    failures: list[str] = []
    expect = case.get("expect", {})
    with tempfile.TemporaryDirectory() as work:
        paths = []
        for name, content in (case.get("files") or {}).items():
            written = os.path.join(work, name)
            os.makedirs(os.path.dirname(written), exist_ok=True)
            with open(written, "w", encoding="utf-8") as fh:
                fh.write(content)
            paths.append(written)

        proc = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, case["script"]),
             *paths, *(case.get("args") or [])],
            capture_output=True, text=True)

        wanted_code = expect.get("exit_code", 0)
        if proc.returncode != wanted_code:
            failures.append(f"exit {proc.returncode}, expected {wanted_code}")

        for needle in expect.get("stdout_contains", []):
            if needle not in proc.stdout and needle not in proc.stderr:
                failures.append(f"output does not contain {needle!r}")

        if not (expect.get("paths") or expect.get("absent")
                or expect.get("present")):
            return failures
        try:
            document = json.loads(proc.stdout or proc.stderr)
        except json.JSONDecodeError:
            failures.append("output was not JSON, so no path could be checked")
            return failures

        for path, wanted in (expect.get("paths") or {}).items():
            got = value_at(document, path)
            if got is MISSING:
                failures.append(f"{path} is absent, expected {wanted!r}")
            elif not json_values_match(got, wanted):
                failures.append(f"{path} is {got!r}, expected {wanted!r}")
        for path in expect.get("absent", []):
            if value_at(document, path) is not MISSING:
                failures.append(f"{path} is present and must not be")
        for path in expect.get("present", []):
            if value_at(document, path) is MISSING:
                failures.append(f"{path} is absent and must not be")
    return failures


def main() -> int:
    with open(GOLDEN, encoding="utf-8") as fh:
        document = json.load(fh)
    cases = document.get("parser_cases") or []
    if not cases:
        print("no parser cases in cases.json", file=sys.stderr)
        return 1

    failed = 0
    seen: set[str] = set()
    for case in cases:
        cid = case["id"]
        if cid in seen:
            print(f"FAIL  {cid}: duplicate id")
            failed += 1
            continue
        seen.add(cid)
        # A source without a recognised, exact provenance tag is as hard to
        # classify as no source. Qualifiers belong after the tag, not inside it.
        source = case.get("source")
        if not has_exact_provenance_tag(source):
            print(f"FAIL  {cid}: source needs an exact provenance tag "
                  "([observed], [documented], [inferred], or [UNVERIFIED])")
            failed += 1
            continue
        problems = run_case(case)
        if problems:
            failed += 1
            print(f"FAIL  {cid}")
            for problem in problems:
                print(f"      {problem}")
        else:
            print(f"PASS  {cid}")

    print(f"\n{len(cases) - failed}/{len(cases)} parser golden cases pass")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
