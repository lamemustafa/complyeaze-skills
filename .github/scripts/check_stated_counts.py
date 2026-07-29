#!/usr/bin/env python3
"""Refuse to ship documentation that has drifted away from the tree.

Prose in this repository states counts — "ten scripts", "the eight files under
references/" — and those counts rot the moment anything is added. Every one of
the following was true in the tree at the moment this file was written:

    docs/how-it-works.md   said eight files under references/   there were nine
    SKILL.md               said four scripts read the documents  five did
    README.md              said ten scripts                      correct, because
                                                                 it had just been
                                                                 edited by hand

A reader who catches a repository saying nine when it means eight stops
believing the parts they cannot check, and this project asks to be believed
about surcharge relief and s.288B rounding. So the counts are derived, and a
claim that disagrees with the tree fails the build.

Two other things are checked here, for the same reason:

  * **Coverage.** Every script must be documented and every reference file must
    be reachable from SKILL.md. A script nobody documented is a script nobody
    reviews.
  * **Version agreement.** The plugin manifest, the release-please manifest and
    the skill's own frontmatter all carry a version. Release Please updates the
    ones it is told about; a fourth place nobody wired up drifts silently.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

WORDS = {n: i for i, n in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve "
    "thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}


def read(*parts) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def listing(*parts, suffix=".py") -> list[str]:
    directory = os.path.join(ROOT, *parts)
    return sorted(f for f in os.listdir(directory) if f.endswith(suffix))


def as_number(word: str):
    word = word.strip().lower()
    if word.isdigit():
        return int(word)
    return WORDS.get(word)


def required_marketplace_versions(plugin: dict, manifest_version: str):
    """Read both required marketplace paths and compare each to the manifest."""
    versions: dict[str, str] = {}
    problems: list[str] = []
    metadata = plugin.get("metadata")
    metadata_version = metadata.get("version") if isinstance(metadata, dict) else None
    plugins = plugin.get("plugins")
    plugin_version = (plugins[0].get("version")
                      if isinstance(plugins, list) and plugins
                      and isinstance(plugins[0], dict) else None)

    for path, value in (("metadata.version", metadata_version),
                        ("plugins[0].version", plugin_version)):
        label = f".claude-plugin/marketplace.json {path}"
        if not isinstance(value, str) or not value:
            problems.append(f"{label} is missing")
            continue
        versions[label] = value
        if value != manifest_version:
            problems.append(
                f"{label} = {value}, but .release-please-manifest.json = "
                f"{manifest_version}")
    return versions, problems


def main() -> int:
    problems: list[str] = []
    checked = 0

    scripts = listing("skills", "itr-filing-copilot", "scripts")
    references = listing("skills", "itr-filing-copilot", "references", suffix=".md")
    ci_scripts = listing(".github", "scripts")

    # -- stated counts -----------------------------------------------------
    claims = [
        ("README.md", r"(\w+) scripts, no dependencies at all",
         len(scripts), "scripts under skills/itr-filing-copilot/scripts/"),
        ("docs/scripts.md", r"eye\.\s*(\w+)\s+scripts do that",
         len(scripts), "scripts under skills/itr-filing-copilot/scripts/"),
        ("docs/how-it-works.md", r"The (\w+) files under `references/`",
         len(references), "files under skills/itr-filing-copilot/references/"),
    ]
    for path, pattern, actual, what in claims:
        text = read(path)
        found = re.search(pattern, text)
        if not found:
            problems.append(
                f"{path}: the sentence matching /{pattern}/ is gone. Either the "
                "prose was rewritten and this check needs updating, or the claim "
                "was quietly deleted rather than corrected.")
            continue
        checked += 1
        stated = as_number(found.group(1))
        if stated != actual:
            problems.append(
                f"{path}: says {found.group(1)!r} {what}; there are {actual}.")

    # -- coverage ----------------------------------------------------------
    scripts_doc = read("docs", "scripts.md")
    for name in scripts:
        checked += 1
        if name not in scripts_doc:
            problems.append(
                f"docs/scripts.md does not mention {name}. A script nobody "
                "documented is a script nobody reviews.")

    skill = read("skills", "itr-filing-copilot", "SKILL.md")
    for name in references:
        checked += 1
        if name not in skill:
            problems.append(
                f"SKILL.md never points at references/{name}, so nothing loads "
                "it. Either link it or delete it.")

    how = read("docs", "how-it-works.md")
    for name in ci_scripts:
        checked += 1
        if name not in how:
            problems.append(
                f"docs/how-it-works.md does not mention .github/scripts/{name}, "
                "so the list of what CI runs is incomplete.")

    # Every check CI runs should be one a contributor can run locally, and
    # how-it-works.md is where we tell them how.
    workflow = read(".github", "workflows", "ci.yml")
    for name in ci_scripts:
        checked += 1
        if name not in workflow:
            problems.append(
                f".github/workflows/ci.yml never runs {name}. A check that does "
                "not run is not a check.")

    # -- version agreement -------------------------------------------------
    versions = {}
    manifest = json.loads(read(".release-please-manifest.json"))
    versions[".release-please-manifest.json"] = manifest.get(".")
    plugin = json.loads(read(".claude-plugin", "marketplace.json"))
    marketplace_versions, marketplace_problems = required_marketplace_versions(
        plugin, versions[".release-please-manifest.json"])
    versions.update(marketplace_versions)
    problems.extend(marketplace_problems)
    frontmatter = re.search(r'version:\s*"([^"]+)"', skill)
    if frontmatter:
        versions["SKILL.md frontmatter"] = frontmatter.group(1)
    readme = re.search(r"\*\*v(\d+\.\d+\.\d+)", read("README.md"))
    if readme:
        versions["README.md"] = readme.group(1)
    checked += 1
    if len(set(versions.values())) > 1:
        problems.append(
            "the version is stated differently in different places: "
            + ", ".join(f"{k} = {v}" for k, v in sorted(versions.items()))
            + ". Release Please updates only the places it is told about.")

    if problems:
        print("Documentation disagrees with the tree:")
        for problem in problems:
            print("  -", problem)
        print("\nFix the prose, not this check. A count nobody maintains is "
              "worse than no count.")
        return 1

    print(f"{checked} stated counts, coverage claims and version strings agree "
          f"with the tree ({len(scripts)} scripts, {len(references)} references, "
          f"{len(ci_scripts)} CI checks, version "
          f"{versions.get('.release-please-manifest.json')}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
