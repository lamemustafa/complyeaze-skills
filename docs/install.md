# Install

[← back to the README](../README.md)

<table>
<tr><td width="50%" valign="top">

**Any agent, one command**

```bash
npx skills add lamemustafa/complyeaze-skills
```

Detects what you have installed and places the skill at the right path for each.

</td><td width="50%" valign="top">

**Or clone it**

```bash
git clone https://github.com/lamemustafa/complyeaze-skills
```

The repository ships `.agents/skills/`, so Codex, Antigravity, Cursor and Copilot
pick the skill up from a clone with no further steps.

</td></tr>
</table>

### Claude Code

```
/plugin marketplace add lamemustafa/complyeaze-skills
```

<details>
<summary>Manual install</summary>

Copy `skills/itr-filing-copilot/` to `~/.claude/skills/` for yourself, or
`.claude/skills/` for one project. Claude Code watches both directories live, so
there is no restart.

</details>

### Claude.ai, Cowork and cloud sessions

These do not read `~/.claude/skills/` on your machine. They load skills enabled
for your account, so zip the folder and upload it under Settings, Capabilities,
Skills.

```bash
cd skills && zip -r itr-filing-copilot.zip itr-filing-copilot
```

### Codex, Antigravity, Cursor, Copilot

All four read `.agents/skills/`, which this repository ships, so a clone is enough
for a project-level install.

<details>
<summary>Global install paths</summary>

| Agent | Path | Invoke |
|---|---|---|
| OpenAI Codex | `~/.agents/skills/` | `$itr-filing-copilot` |
| Google Antigravity | `~/.gemini/config/skills/` | by description match |
| Cursor | `~/.cursor/skills/` | by description match |
| GitHub Copilot | `~/.copilot/skills/` | by description match |

`npx skills add` may use slightly different global directories than the vendor
docs above. Either works. Do not mix the two for the same agent.

</details>


