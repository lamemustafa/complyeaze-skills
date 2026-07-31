#!/usr/bin/env python3
"""
Match the savings interest AIS was told about against the statements you hold.

Standard library only. Reads nothing but the files you name. No network.

    python3 open_ais.py AIS.pdf --pan ABCDE1234F --dob 01/01/1990 --print-password \\
        | python3 reconcile_interest.py --ais AIS.pdf --password-stdin \\
              kotak.pdf dcb.pdf --financial-year 2025-26

The gap this closes
-------------------
A return's Schedule OS was short by ₹921 and nobody could say why. TIS gave one
number for savings interest, the statements added to another, and the difference
was a bare figure with no name on it. Two things were true and neither was
visible: **AIS reports savings interest one block per bank**, so it already knew
which banks had reported and how much each one said, and **the statements only
covered some of those banks**.

That is what this does. It puts the two lists side by side and names every row
that appears on one and not the other. It does not decide which figure is right.

Three answers come out, and they mean different things
------------------------------------------------------
**A bank in both.** The two figures should agree. Where they do not, the
script does not choose either one. [inferred] Check the statement period and
the 31 March boundary. [documented] If the AIS item is wrong, submit AIS
feedback; if filing on the statement figure, keep the statement, feedback
acknowledgement and reconciliation working paper.

**A bank in AIS with no statement.** This is where an unexplained shortfall
almost always lives. The department has been told about that account; the return
has not. Get the statement.

**A bank with a statement that AIS never mentions.** Not an error and not a
licence. SFT reporting has thresholds and gaps, and interest a bank never
reported is still taxable. Report it.

What it will not do
-------------------
It will not add the two lists together, pick a winner, or quietly prefer the
larger number. Where a reporter's printed name cannot be matched to any bank you
supplied, it says the name is unmatched rather than assigning it to the nearest
one — the whole point of the exercise is to find the account nobody thought of,
and a fuzzy match hides exactly that.

No account number is printed. AIS carries one for every block and this reads
them only to redact them.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parse_bank_statement import parse as parse_statement  # noqa: E402
from parse_tax_docs import parse_ais  # noqa: E402
from pdf_crypt import CryptError, resolve_password  # noqa: E402
from read_pdf import PdfError, extract_pages  # noqa: E402
from redact import safe_name  # noqa: E402

# How a bank prints its own name in an AIS information source, against the short
# name the statement reader derives from an IFSC prefix. Longest alias first, so
# "SOUTH INDIAN BANK" is not matched by "INDIAN BANK".
ALIASES = {
    "SBI": ("STATEBANKOFINDIA", "SBI"),
    "ICICI": ("ICICIBANKLIMITED", "ICICIBANK", "ICICI"),
    "HDFC": ("HDFCBANKLIMITED", "HDFCBANK", "HDFC"),
    "Kotak": ("KOTAKMAHINDRABANKLIMITED", "KOTAKMAHINDRA", "KOTAK"),
    "DCB": ("DCBBANKLIMITED", "DCBBANK", "DCB"),
    "Axis": ("AXISBANKLIMITED", "AXISBANK"),
    "IndusInd": ("INDUSINDBANK", "INDUSIND"),
    "Yes": ("YESBANKLIMITED", "YESBANK"),
    "IDFC First": ("IDFCFIRSTBANK", "IDFCFIRST"),
    "Bank of Baroda": ("BANKOFBARODA",),
    "PNB": ("PUNJABNATIONALBANK", "PNB"),
    "Canara": ("CANARABANK",),
    "Union Bank": ("UNIONBANKOFINDIA",),
    "Federal": ("THEFEDERALBANKLIMITED", "FEDERALBANK"),
    "Indian Overseas": ("INDIANOVERSEASBANK",),
    "Bank of Maharashtra": ("BANKOFMAHARASHTRA",),
    "Central Bank": ("CENTRALBANKOFINDIA",),
    "Indian Bank": ("INDIANBANK",),
    "Punjab & Sind": ("PUNJABSINDBANK", "PUNJABANDSINDBANK"),
    "UCO": ("UCOBANK",),
    "Bank of India": ("BANKOFINDIA",),
    "AU Small Finance": ("AUSMALLFINANCEBANK", "AUBANK"),
    "RBL": ("RBLBANKLIMITED", "RBLBANK"),
    "Karnataka": ("KARNATAKABANK",),
    "South Indian": ("SOUTHINDIANBANK",),
    "Tamilnad Mercantile": ("TAMILNADMERCANTILEBANK",),
    "CSB": ("CSBBANK",),
    "DBS": ("DBSBANKINDIA", "DBSBANK"),
    "Standard Chartered": ("STANDARDCHARTEREDBANK", "STANDARDCHARTERED"),
    "Citi": ("CITIBANK",),
    "HSBC": ("HSBCLIMITED", "HSBC"),
}
# Longest first so a shorter alias never wins over a longer one that also fits.
ALIAS_ORDER = sorted(
    ((alias, bank) for bank, names in ALIASES.items() for alias in names),
    key=lambda pair: -len(pair[0]))


class Refusal(Exception):
    """There is not enough here to reconcile anything."""


def distinct_statement_paths(paths: list[str]) -> list[str]:
    """Refuse two spellings of the same statement before parsing either one."""
    seen: dict[str, str] = {}
    for path in paths:
        resolved = os.path.realpath(path)
        if resolved in seen:
            raise Refusal(
                f"{safe_name(path)} was supplied more than once: both inputs "
                "resolve to the same file. Pass each statement once.")
        seen[resolved] = path

    # Distinct real paths are kept even when their bytes happen to match. Two
    # accounts can legitimately export identical-looking statements; hashing
    # their contents would guess that separate source records are duplicates.
    return paths


def require_selected_year(accounts: list[dict], financial_year: str | None) -> None:
    """AIS is year-bound, so a cross-year statement needs an explicit year."""
    if financial_year is not None:
        return
    for account in accounts:
        years = account["interest_credited"]["by_financial_year"]
        if len(years) > 1:
            raise Refusal(
                f"{account['file']} has interest in more than one financial "
                f"year ({', '.join(years)}). Pass --financial-year YYYY-YY; "
                "reconciliation refuses rather than summing income from "
                "different returns.")


def squash(text: str) -> str:
    return re.sub(r"[^A-Za-z]", "", text or "").upper()


def bank_from_reporter(source: str) -> str | None:
    """The short bank name an AIS information source names, or None.

    None is a real answer. On a live AIS one savings block was reported by
    "CPRC CHENNAI", which is the department's own processing centre and not a
    bank at all. Guessing which of the taxpayer's accounts that belonged to
    would have hidden a real question behind a plausible match."""
    flat = squash(source)
    for alias, bank in ALIAS_ORDER:
        if alias in flat:
            return bank
    return None


def reconcile(ais_reporters: list[dict], accounts: list[dict],
              deposit_total: float = 0.0, deposit_unread: int = 0) -> dict:
    """Both sides are aggregated per bank before anything is compared.

    AIS reports one block per *account*, and a taxpayer with two accounts at one
    bank gets two blocks from it. Comparing each block against the bank's whole
    statement total reported that bank twice, each row disagreeing, while the
    totals in fact tied — an alarm on a return that was correct."""
    matched, ais_only, statement_only = [], [], []

    def money(value) -> float:
        # A block with no amount is a block AIS printed and this could not read.
        # Treating it as zero would quietly shrink the AIS side.
        return 0.0 if value is None else float(value)

    ais_by_bank: dict[str | None, list[dict]] = {}
    for reporter in ais_reporters:
        bank = bank_from_reporter(reporter["reported_by"] or "")
        ais_by_bank.setdefault(bank, []).append(reporter)

    unreadable = [r for r in ais_reporters if r.get("amount") is None]

    by_bank: dict[str, list[dict]] = {}
    for account in accounts:
        by_bank.setdefault(account["bank"], []).append(account)
    seen_banks: set[str] = set()

    for bank, blocks in ais_by_bank.items():
        reported = round(sum(money(b["amount"]) for b in blocks), 2)
        held = by_bank.get(bank or "", [])
        if not held:
            ais_only.append({
                "bank": bank,
                "accounts_reported": len(blocks),
                "reported_by": sorted({b["reported_by"] for b in blocks}),
                "ais_amount": reported,
                "why": ("no statement was supplied for this bank"
                        if bank else
                        "the reporting source is not a bank name this script "
                        "recognises, so no statement could be matched to it"),
            })
            continue
        seen_banks.add(bank)
        statement_total = round(
            sum(a["interest_credited"]["total"] for a in held), 2)
        matched.append({
            "bank": bank,
            "accounts_reported": len(blocks),
            "ais_amount": reported,
            "statement_amount": statement_total,
            "statements": [a["file"] for a in held],
            "difference": round(reported - statement_total, 2),
            "agrees": abs(reported - statement_total) <= 0.01,
        })

    for bank, held in by_bank.items():
        if bank in seen_banks:
            continue
        statement_only.append({
            "bank": bank,
            "statements": [a["file"] for a in held],
            "statement_amount": round(
                sum(a["interest_credited"]["total"] for a in held), 2),
        })

    ais_total = round(sum(money(r["amount"]) for r in ais_reporters), 2)
    statement_total = round(
        sum(a["interest_credited"]["total"] for a in accounts), 2)
    return {
        "matched": matched,
        "reported_to_ais_with_no_statement": ais_only,
        "in_a_statement_but_not_reported_to_ais": statement_only,
        "ais_total": ais_total,
        "statement_total": statement_total,
        "difference": round(ais_total - statement_total, 2),
        "ais_blocks_with_no_readable_amount": len(unreadable),
        "ais_term_deposit_total_not_compared": deposit_total,
    }


def report(result: dict) -> tuple[list[str], list[str]]:
    checks, flags = [], []

    deposit_unread = result.get("ais_term_deposit_blocks_with_unread_amount") or 0
    if deposit_unread:
        flags.append(
            f"[observed] {deposit_unread} term-deposit block(s) in AIS have an "
            "amount this reader could not extract, so the deposit figure below "
            "is a floor and the real difference may be larger.")
    deposit = result.get("ais_term_deposit_total_not_compared") or 0
    if deposit or deposit_unread:
        flags.append(
            f"[documented] AIS reports savings and term-deposit interest under "
            f"separate codes. [observed] {deposit:,.2f} of term-deposit "
            "interest is NOT part of the comparison below — the "
            "AIS side here is savings interest only. [inferred] A bank that credits a "
            "deposit's interest into the savings account puts it into the "
            "statement's interest total, so a statement can appear to exceed "
            "AIS by roughly this amount without either being wrong. Check "
            "where the deposit interest was credited before treating a "
            "difference of about this size as a missing account; this script "
            "cannot see which account received it.")

    for row in result["matched"]:
        if row["agrees"]:
            checks.append(
                f"{row['bank']}: AIS and the statement agree at "
                f"{row['ais_amount']:,.2f}.")
        else:
            flags.append(
                f"{row['bank']}: AIS was told {row['ais_amount']:,.2f}; the "
                f"statement credits {row['statement_amount']:,.2f}, a difference "
                f"of {abs(row['difference']):,.2f}. [inferred] This reconciliation "
                "does not decide which figure is correct. First check the "
                "statement period and the 31 March boundary. [documented] If "
                "the AIS figure is wrong, submit AIS feedback on the relevant "
                "SFT-016 information item. [inferred] If filing on the statement "
                "figure, keep the complete statement, the AIS feedback "
                "acknowledgement, and a working-paper reconciliation. "
                "[documented] A mismatch may draw a proposed s.143(1)(a) "
                "adjustment; preserve the evidence and respond rather than "
                "declaring income that was not earned.")

    if result["ais_blocks_with_no_readable_amount"]:
        flags.append(
            f"{result['ais_blocks_with_no_readable_amount']} savings block(s) in "
            "AIS carry no amount this reader could extract, and they count as "
            "zero above. The AIS total is therefore a floor. Run "
            "parse_tax_docs.py --text on the AIS and open an issue with the "
            "block's shape, no amounts.")

    missing = result["reported_to_ais_with_no_statement"]
    if missing:
        total = sum(r["ais_amount"] for r in missing)
        account_count = sum(r["accounts_reported"] for r in missing)
        named = ", ".join(
            f"{r['bank'] or 'an unrecognised source'} {r['ais_amount']:,.2f}"
            + (f" across {r['accounts_reported']} accounts"
               if r["accounts_reported"] > 1 else "")
            for r in missing)
        flags.append(
            f"{account_count} account(s) reported {total:,.2f} of interest to the "
            f"department that no statement here accounts for: {named}. This is "
            "where an unexplained shortfall in Schedule OS almost always lives. "
            "The department has been told about these accounts; the return has "
            "not. Get the statements.")

    extra = result["in_a_statement_but_not_reported_to_ais"]
    if extra:
        total = sum(r["statement_amount"] for r in extra)
        flags.append(
            f"{len(extra)} bank(s) credited {total:,.2f} of interest that AIS "
            "never mentions: "
            + ", ".join(f"{r['bank']} {r['statement_amount']:,.2f}" for r in extra)
            + ". That is not an error and not a licence. SFT reporting has "
              "thresholds and gaps, and interest a bank never reported is still "
              "taxable. Report it.")

    if result["difference"]:
        checks.append(
            f"AIS totals {result['ais_total']:,.2f} against "
            f"{result['statement_total']:,.2f} across the statements — a "
            f"difference of {result['difference']:,.2f}. Every rupee of it is "
            "named above; nothing here is a rounding remainder.")
    else:
        checks.append(
            f"AIS and the statements agree in total at "
            f"{result['ais_total']:,.2f}.")

    return checks, flags


def summarise(out: dict) -> str:
    """Print the two totals, their difference, coverage and every flag."""
    money = lambda value: f"₹{value:,.2f}"
    period = out["financial_year"] or "all statement periods"
    missing_accounts = sum(
        item["accounts_reported"]
        for item in out["reported_to_ais_with_no_statement"])
    lines = [
        f"Interest reconciliation: {period}",
        f"AIS total: {money(out['ais_total'])}",
        f"Statement total: {money(out['statement_total'])}",
        f"Difference (AIS minus statements): {money(out['difference'])}",
        f"Banks matched: {len(out['matched'])}",
        ("AIS accounts without statements: "
         f"{missing_accounts}"),
        ("Statement banks absent from AIS: "
         f"{len(out['in_a_statement_but_not_reported_to_ais'])}"),
    ]
    if out["flags"]:
        lines.extend(["", "Flags", *out["flags"]])
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("statements", nargs="+", help="bank statement PDFs")
    ap.add_argument("--ais", required=True, help="the AIS PDF")
    ap.add_argument("--password", help="for an encrypted AIS: lowercase PAN "
                                       "followed by ddmmyyyy")
    ap.add_argument("--password-stdin", action="store_true",
                    help="read the AIS password from standard input instead, so "
                         "it never appears in argv or in shell history")
    ap.add_argument("--statement-password",
                    help="if the statements share a password")
    ap.add_argument("--financial-year", metavar="YYYY-YY",
                    help="count only interest credited in this financial year")
    ap.add_argument("--json", metavar="PATH")
    ap.add_argument("--summary", action="store_true",
                    help="print the key figures and every flag as plain lines")
    a = ap.parse_args(argv)

    try:
        statement_paths = distinct_statement_paths(a.statements)
        ais = parse_ais(extract_pages(
            a.ais, resolve_password(a.password, a.password_stdin)))
        # [observed 2026-07-31] AIS reports savings and term-deposit interest
        # under separate codes, and this joins the savings side only. A bank
        # that credits a deposit's interest into the same savings account puts
        # it into the statement's interest total, so a bank can appear to
        # over-report by exactly the deposit. The deposit figure is carried
        # through and named rather than being netted off, because whether the
        # deposit was credited to this account is a fact about the account that
        # this script cannot see.
        deposits = ais.get("term_deposit_interest_by_reporter") or {}
        deposit_unread = deposits.get("blocks_with_unread_amount") or 0
        reporters = (ais.get("savings_bank_interest_by_reporter") or {}).get(
            "reporters", [])
        if not reporters:
            raise Refusal(
                f"{safe_name(a.ais)} carries no SFT-016 savings-interest "
                "block, so there is nothing on the AIS side to reconcile "
                "against. Either no bank reported for this year, or this is not "
                "an AIS — run parse_tax_docs.py on it and check what it was "
                "recognised as.")
        accounts = [parse_statement(path, 50000, a.statement_password,
                                    a.financial_year)
                    for path in statement_paths]
        require_selected_year(accounts, a.financial_year)
    except (PdfError, Refusal, CryptError) as e:
        print(json.dumps({"refused": str(e)}, indent=2), file=sys.stderr)
        return 2

    unreadable = [x["file"] for x in accounts if not x["transaction_rows_read"]]
    result = reconcile(reporters, accounts, deposits.get("total") or 0.0,
                       deposit_unread)
    checks, flags = report(result)

    if unreadable:
        flags.append(
            f"{len(unreadable)} statement(s) yielded no transaction rows at all "
            f"({', '.join(unreadable)}). Their interest reads as zero, which "
            "will make their bank look under-reported here. Treat them as "
            "unreadable, never as accounts with no interest.")
    torn = [x["file"] for x in accounts
            if x["balance_integrity"].get("checked")
            and not x["balance_integrity"]["reconciles"]]
    if torn:
        flags.append(
            f"{len(torn)} statement(s) do not reconcile from their opening "
            f"balance to their closing one ({', '.join(torn)}), so rows were "
            "missed in them. Their interest figure is a floor, and any shortfall "
            "shown above may be theirs rather than a missing account.")

    out = {
        "financial_year": a.financial_year,
        "ais_file": safe_name(a.ais),
        "statements": [{"file": x["file"], "bank": x["bank"],
                        "interest": x["interest_credited"]["total"]}
                       for x in accounts],
        **result,
        "checks": checks,
        "flags": flags,
        "disclaimer": "Read from the files as given. It names what appears on "
                      "one side and not the other; it does not decide which "
                      "figure is right, and it never adds the two lists "
                      "together. No account number is reproduced.",
    }
    if a.summary:
        print(summarise(out))
    else:
        print(json.dumps(out, indent=2, ensure_ascii=False))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
