# Security Policy

## Reporting

**Do not open a public issue for a security report.**

Email **security@complyeaze.com** with a description, reproduction steps, and impact.
Expect an acknowledgement within five working days.

## What Is In Scope

These skills are Markdown instructions consumed by AI agents. The realistic threat surface:

- **Prompt injection** — content in a reference file that could steer an agent toward
  harmful or unintended action
- **Data exfiltration paths** — any instruction that would cause an agent to transmit a
  user's tax documents, credentials, or personal data anywhere
- **Dangerous guidance** — instructions that would cause an agent to forge a filing
  identity, automate submission of a legal document, or handle portal credentials
- **Supply chain** — anything in this repository that executes

## Deliberate Refusal Boundaries

These are design decisions, not gaps. Do not file them as vulnerabilities, and do not
submit pull requests that remove them:

- **No filing automation.** There is no public API to submit an ITR; only the taxpayer or
  an authorised e-return intermediary may file. These skills never click Submit.
- **No credential handling.** The skills never ask for, store, or transmit portal
  credentials, OTPs, or session cookies.
- **No forged filing identity.** `CreationInfo.SWCreatedBy` / `JSONCreatedBy` in an ITR
  JSON are registered software-provider codes issued by the department. The skill
  explicitly refuses to emit one that is not the user's, and refuses to fabricate a
  `Digest`.

## Never In A Public Report

PAN · Aadhaar · GSTIN · TAN · taxpayer names · acknowledgement numbers · challan
identifiers (CIN, BSR, serial) · bank account or IFSC · tax amounts · ITR JSON exports ·
prefill JSON · AIS, TIS or 26AS files · portal HTML or network captures · unredacted
screenshots.

If a report needs any of these to be understood, email it — do not post it.
