#!/usr/bin/env python3
"""Validate skills against the Agent Skills spec and this repo's own budgets.

Spec: https://agentskills.io/specification
"""
import sys, glob, os, re, json

FAIL = []
WARN = []

# Codex shares a single character budget across the descriptions of every
# installed skill — documented at 8,000 chars, observed lower. A long
# description is not rejected, but its tail may be truncated away in a crowded
# install, so anything load-bearing has to sit early.
CODEX_SAFE_PREFIX = 232

descriptions = {}


def check(cond, msg):
    if not cond:
        FAIL.append(msg)


def warn(cond, msg):
    if not cond:
        WARN.append(msg)


for skill_md in sorted(glob.glob("skills/*/SKILL.md")):
    d = os.path.basename(os.path.dirname(skill_md))
    body = open(skill_md, encoding="utf-8").read()

    check(body.startswith("---\n"), f"{d}: no YAML frontmatter")
    end = body.find("\n---", 4)
    check(end > 0, f"{d}: frontmatter not terminated")
    fm, rest = body[4:end], body[end + 4:]

    name = re.search(r"^name:\s*(\S+)\s*$", fm, re.M)
    check(bool(name), f"{d}: no name")
    if name:
        n = name.group(1)
        check(n == d, f"{d}: name '{n}' != directory name")
        check(bool(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", n)),
              f"{d}: name must be lowercase alphanumeric with single hyphens")
        check(1 <= len(n) <= 64, f"{d}: name length out of range")

    desc = re.search(r"^description:\s*(.+)$", fm, re.M)
    check(bool(desc), f"{d}: no description")
    if desc:
        text = desc.group(1).strip()
        descriptions[d] = text
        check(1 <= len(text) <= 1024,
              f"{d}: description {len(text)} chars, must be 1-1024")
        # The trigger vocabulary is what makes a skill fire. It has to survive
        # truncation, so it belongs in the first sentence or two.
        warn("use when" in text[:CODEX_SAFE_PREFIX].lower(),
             f"{d}: no trigger clause in the first {CODEX_SAFE_PREFIX} chars of "
             f"the description — Codex may truncate it away")

    # A skill that does not say which assessment year it is pinned to becomes a
    # liability the year after it ships.
    check(bool(re.search(r"^\s+version:\s*\"", fm, re.M)), f"{d}: no metadata.version")
    check("x-release-please-version" in fm,
          f"{d}: metadata.version has no '# x-release-please-version' marker, so "
          f"releases will leave it stale")

    lines = rest.count("\n")
    check(lines < 500, f"{d}: SKILL.md body {lines} lines, budget is 500")
    warn(lines < 450, f"{d}: SKILL.md body {lines} lines — close to the 500 budget; "
                      f"move detail into references/")

    # References must be one level deep. Deep chains defeat progressive disclosure.
    for ref in glob.glob(f"skills/{d}/references/**/*", recursive=True):
        depth = ref.replace(f"skills/{d}/", "").count("/")
        check(depth <= 1, f"{d}: {ref} is nested deeper than one level")

    # A reference file that SKILL.md never names will never be loaded.
    for ref in sorted(glob.glob(f"skills/{d}/references/*.md")):
        base = os.path.basename(ref)
        warn(base in rest, f"{d}: references/{base} is never mentioned in SKILL.md")

    # Golden cases must parse and must be pinned to the same AY as the skill.
    golden = f"skills/{d}/evals/golden/cases.json"
    if os.path.exists(golden):
        try:
            doc = json.load(open(golden, encoding="utf-8"))
            check(bool(doc.get("cases")), f"{d}: golden case file has no cases")
            ay = re.search(r'assessment-year:\s*"([^"]+)"', fm)
            if ay:
                check(doc.get("assessment_year") == ay.group(1),
                      f"{d}: golden cases are AY {doc.get('assessment_year')}, "
                      f"skill is AY {ay.group(1)}")
        except json.JSONDecodeError as e:
            FAIL.append(f"{d}: evals/golden/cases.json is not valid JSON: {e}")
    else:
        WARN.append(f"{d}: no evals/golden/cases.json")

    print(f"  {d}: name ok, description {len(descriptions.get(d, ''))} chars, "
          f"body {lines} lines, "
          f"{len(glob.glob(f'skills/{d}/references/*.md'))} references, "
          f"{len(glob.glob(f'skills/{d}/scripts/*'))} scripts")

# Every skill must be reachable by the hosts that read .agents/skills/ —
# Codex, Antigravity, Cursor and Copilot all do.
for skill_md in sorted(glob.glob("skills/*/SKILL.md")):
    d = os.path.basename(os.path.dirname(skill_md))
    link = f".agents/skills/{d}"
    check(os.path.exists(link),
          f"{d}: missing .agents/skills/{d} — Codex, Antigravity, Cursor and "
          f"Copilot read that directory")
    if os.path.islink(link):
        target = os.path.join(os.path.dirname(link), os.readlink(link))
        check(os.path.exists(target), f"{d}: .agents/skills/{d} is a broken symlink")

# Every skill must open with the canonical disclaimer. It is duplicated rather
# than linked because a skill directory has to work when copied somewhere on its
# own, and duplication without a check is how it drifts.
canon_path = "shared/disclaimer.md"
if os.path.exists(canon_path):
    canon = open(canon_path, encoding="utf-8").read().split("-->", 1)[-1]
    canon_words = re.findall(r"[a-z0-9]+", canon.lower())
    for skill_md in sorted(glob.glob("skills/*/SKILL.md")):
        d = os.path.basename(os.path.dirname(skill_md))
        body_words = re.findall(r"[a-z0-9]+",
                                open(skill_md, encoding="utf-8").read().lower())
        joined = " ".join(body_words)
        check(" ".join(canon_words) in joined,
              f"{d}: SKILL.md does not open with the canonical disclaimer from "
              f"{canon_path}. Copy it verbatim as a quote block; bold and other "
              f"markdown around the words is fine.")
else:
    WARN.append(f"{canon_path} is missing — the disclaimer has no canonical copy")

# Two skills that share a name, or read too much alike, make the model pick at
# random. This is the check that matters most as the repo grows past one domain.
names = sorted(descriptions)
for i, a_name in enumerate(names):
    for b_name in names[i + 1:]:
        a = set(re.findall(r"[a-z]{4,}", descriptions[a_name].lower()))
        b = set(re.findall(r"[a-z]{4,}", descriptions[b_name].lower()))
        if not a or not b:
            continue
        overlap = len(a & b) / len(a | b)
        warn(overlap < 0.6,
             f"{a_name} and {b_name}: descriptions are {overlap:.0%} alike. The "
             f"model will not reliably pick between them — give each one a domain "
             f"noun and a distinct trigger vocabulary. See shared/AUTHORING.md")

# The whole-repo description budget, which is what a crowded Codex install sees.
total = sum(len(v) for v in descriptions.values())
print(f"\n  descriptions total {total} chars across {len(descriptions)} skill(s)")
warn(total <= 8000, f"skill descriptions total {total} chars — Codex budgets ~8,000 "
                    f"across ALL installed skills, so this repo alone will crowd it")

if WARN:
    print("\nWARNINGS:")
    for w in WARN:
        print("  -", w)

if FAIL:
    print("\nFAILED:")
    for f in FAIL:
        print("  -", f)
    sys.exit(1)
print("\nAll skills valid.")
