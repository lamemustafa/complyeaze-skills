#!/usr/bin/env python3
"""
Read the two JSON files the income-tax portal gives a filer, and reconcile them.

Standard library only. Reads nothing but the files you name. No network.

    python3 parse_portal_json.py PREFILL.json
    python3 parse_portal_json.py ECZPK7003J_upload_2026-27.json
    python3 parse_portal_json.py PREFILL.json FILED.json      # and cross-check

Two different documents, both called "the JSON"
-----------------------------------------------
**The prefill** is what "Download Pre-filled JSON" gives you before you start.
It is the department's own view of you: the bank accounts it holds, the TDS rows
from Form 26AS, the AIS-derived figures it calls `insights`, the regime forms on
record, and — under `lastFiledITR` — the carry-forwards from last year. It is
the only machine-readable statement of what the portal will put in the form
before you touch it, and every disagreement between it and your own documents is
a disagreement you have to settle before filing, not after.

**The filed return** is what the utility uploads and what you get back from
"Download JSON" afterwards. It carries the whole computation, and two schedules
in it are the only record of things a *later* year needs: `ScheduleCFL`, the
losses carried forward, and `ScheduleUD`, the unabsorbed depreciation. Nobody
reconstructs those from a PDF a year later.

Why a script rather than reading it
-----------------------------------
Because the totals in it are checkable, and the portal's own validation does not
check all of them. Every schedule that carries a total also carries the rows the
total is made of, so each one is an arithmetic identity that either holds or
does not. This checks them and reports the ones that do not, and it computes
nothing it was not given.

What it will not do
-------------------
It does not decide anything. It does not choose a regime, decide a residential
status, or say whether a carry-forward is allowable. Where the file is silent it
says so rather than assuming a zero — an absent `ScheduleCFL` and a
`ScheduleCFL` full of zeroes are different facts, and only one of them means
there is nothing to carry.

It prints no identifier. Not the PAN, not the Aadhaar number, not an account
number, not the mobile number or the email address — the whole point of these
files is that they are full of them. Where two files need to be compared, the
comparison happens inside the script and only the answer comes out.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from redact import safe_name  # noqa: E402

IFSC_BANKS = {
    "HDFC": "HDFC", "ICIC": "ICICI", "SBIN": "SBI", "KKBK": "Kotak",
    "DCBL": "DCB", "UTIB": "Axis", "INDB": "IndusInd", "YESB": "Yes",
    "IDFB": "IDFC First", "BARB": "Bank of Baroda", "PUNB": "PNB",
    "CNRB": "Canara", "UBIN": "Union Bank", "FDRL": "Federal",
    "IOBA": "Indian Overseas", "MAHB": "Bank of Maharashtra",
    "CBIN": "Central Bank", "IDIB": "Indian Bank", "PSIB": "Punjab & Sind",
    "UCBA": "UCO", "BKID": "Bank of India", "AUBL": "AU Small Finance",
    "RATN": "RBL", "KARB": "Karnataka", "SIBL": "South Indian",
    "TMBL": "Tamilnad Mercantile", "CSBK": "CSB", "DBSS": "DBS",
    "SCBL": "Standard Chartered", "CITI": "Citi", "HSBC": "HSBC",
}

# The heads ScheduleCFL carries forward, and what each one is allowed to be set
# off against later. The right-hand side is guidance for the filer, not a rule
# this script applies to anything.
CFL_HEADS = {
    "TotalHPPTILossCF": ("house property",
                         "8 years, against house-property income only"),
    "BusLossOthThanSpecLossCF": ("business, other than speculation",
                                 "8 years, against business income only"),
    "LossFrmSpecBusCF": ("speculation business",
                         "4 years, against speculation profit only"),
    "LossFrmSpecifiedBusCF": ("specified business u/s 35AD",
                              "indefinite, against specified-business profit only"),
    "TotalSTCGPTILossCF": ("short-term capital loss",
                           "8 years, against any capital gain"),
    "TotalLTCGPTILossCF": ("long-term capital loss",
                           "8 years, against long-term capital gain only"),
    "OthSrcLossRaceHorseCF": ("owning and maintaining race horses",
                              "4 years, against the same activity only"),
}


# Every schedule this script actually looks at. Anything else in a return is
# reported as unchecked rather than passed over, because a script that says
# nothing about ScheduleBP reads exactly like a script that found nothing wrong
# with it. ITR-4's presumptive block is the case in point: no ITR-4 has been put
# through this, so its key names are unknown and are not going to be guessed.
SCHEDULES_READ = {
    "form_itr1", "form_itr2", "form_itr3", "form_itr4", "creationinfo",
    "parta_gen1", "partb_tti", "scheduletds1", "scheduletds2", "scheduletds3",
    "scheduletcs", "scheduleit", "schedulesi", "schedulecfl", "scheduleud",
    "itr3scheduleud", "itr4scheduleud", "scheduleamtc", "verification",
}


class Refusal(Exception):
    """The file is not one this script can read."""


def dig(obj, *path, default=None):
    """Walk a path of keys, returning `default` the moment one is missing.

    Case is not consistent across these files: the prefill writes
    `personalInfo`, the filed return writes `PersonalInfo`, and `ifsccode`
    against `IFSCCode`. Each step matches case-insensitively."""
    cur = obj
    for key in path:
        if not isinstance(cur, dict):
            return default
        if key in cur:
            cur = cur[key]
            continue
        lowered = {k.lower(): k for k in cur}
        if key.lower() in lowered:
            cur = cur[lowered[key.lower()]]
        else:
            return default
    return default if cur is None else cur


def num(value) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", ""))
        except ValueError:
            return None
    return None


def total(value) -> float:
    """A missing figure is zero *for arithmetic*, but `present` records whether
    it was actually there — the difference matters for reporting."""
    return num(value) or 0.0


def normalise_ay(value) -> str | None:
    """The portal writes the assessment year as `2026` in one place and
    `2026-27` in another. Both mean AY 2026-27, covering FY 2025-26."""
    if not isinstance(value, (str, int)):
        return None
    text = str(value).strip()
    if re.fullmatch(r"\d{4}", text):
        return f"{text}-{str(int(text) + 1)[2:]}"
    if re.fullmatch(r"\d{4}-\d{2}", text):
        return text
    if re.fullmatch(r"\d{4}-\d{4}", text):
        return f"{text[:4]}-{text[-2:]}"
    return None


def round_288b(amount: float) -> int:
    """s.288B: tax payable and refund due are rounded to the nearest ten rupees.

    This is not cosmetic. A return whose computed balance is 66,243 states a
    refund of 66,240, and a check for equality flags every honest return ever
    filed. `[observed]` on five real returns across AY 2021-22 to AY 2026-27:
    66,243 to 66,240, 7,137 to 7,140, 35,312 to 35,310 and 4 to 0 — each one
    the nearest multiple of ten, with five rounding up."""
    sign = -1 if amount < 0 else 1
    return sign * int((abs(amount) + 5) // 10 * 10)


def bank_of(ifsc: str | None) -> str | None:
    if not ifsc or len(ifsc) < 4:
        return None
    return IFSC_BANKS.get(ifsc[:4].upper()) or f"unrecognised IFSC prefix {ifsc[:4]}"


# --------------------------------------------------------------------------
# detection
# --------------------------------------------------------------------------

# Forms this script reads, and forms it recognises only in order to refuse them.
FORMS = ("ITR1", "ITR2", "ITR3", "ITR4")
OUT_OF_SCOPE = {
    "ITR5": "a firm, LLP, AOP or BOI",
    "ITR6": "a company",
    "ITR7": "a trust or institution claiming exemption",
}


def detect(doc: dict) -> tuple[str, str | None]:
    if isinstance(doc.get("ITR"), dict):
        for form in FORMS:
            if form in doc["ITR"]:
                return "filed return", form
        for form, who in OUT_OF_SCOPE.items():
            if form in doc["ITR"]:
                raise Refusal(
                    f"this is an {form[:3]}-{form[3:]}, the return of {who}. This "
                    "skill covers resident individuals filing ITR-1 to ITR-4. "
                    "Reading it would produce figures that look right and belong "
                    "to a computation this project does not implement.")
        keys = list(doc["ITR"])
        raise Refusal(
            f"the file has an ITR wrapper but holds {keys}, which is not a form "
            "this script knows. ITR-1 to ITR-4 are read.")
    if "personalInfo" in doc or "lastFiledITR" in doc or "insights" in doc:
        return "prefill", None
    raise Refusal(
        "this is neither a prefill nor a filed return. A prefill has a "
        "personalInfo block; a filed return has an ITR wrapper around ITR1, "
        "ITR2, ITR3 or ITR4. If the portal called it a JSON and it is neither, "
        "say what screen it came from in an issue — do not make the parser "
        "guess.")


def json_type_name(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    return type(value).__name__


def require_object(obj: dict, *path: str) -> dict:
    value = dig(obj, *path)
    label = ".".join(path)
    if value is None:
        raise Refusal(
            f"the filed return is missing the required {label} object. "
            "No liability or payment figure can be checked without it.")
    if not isinstance(value, dict):
        raise Refusal(
            f"the filed return's required {label} block is a "
            f"{json_type_name(value)}, not an object. No liability or payment "
            "figure can be checked from that schema.")
    return value


# --------------------------------------------------------------------------
# shared readers
# --------------------------------------------------------------------------

def read_banks(entries: list) -> list[dict]:
    out = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        ifsc = dig(entry, "IFSCCode") or dig(entry, "ifsccode") or ""
        refund = str(dig(entry, "UseForRefund") or dig(entry, "useForRefund")
                     or "").lower()
        out.append({
            "bank": bank_of(ifsc) or (dig(entry, "BankName")
                                      or dig(entry, "bankName") or "unnamed"),
            "ifsc_prefix": ifsc[:4].upper() if ifsc else None,
            "account_type": dig(entry, "AccountType") or dig(entry, "accountType"),
            "nominated_for_refund": refund == "true",
        })
    return out


def read_cfl(cfl: dict) -> dict:
    """ScheduleCFL, as the next year's return needs it."""
    if not isinstance(cfl, dict) or not cfl:
        return {"present": False}
    out = {"present": True, "carried_forward": {}, "current_year_loss": {},
           "brought_forward_from_earlier_years": {}}
    blocks = [("TotalLossCFSummary", "carried_forward"),
              ("CurrentAYloss", "current_year_loss"),
              ("TotalOfBFLossesEarlierYrs", "brought_forward_from_earlier_years")]
    for key, label in blocks:
        detail = dig(cfl, key, "LossSummaryDetail", default={})
        for field, (head, life) in CFL_HEADS.items():
            value = num(dig(detail, field))
            if value:
                out[label][head] = {"amount": value, "set_off_window": life}
    # The year-wise rows only exist when there is something to carry.
    rows = dig(cfl, "LossCFFromPrevYrToAY", default=[])
    if isinstance(rows, list) and rows:
        out["year_wise_rows"] = len(rows)
        out["years"] = sorted({str(dig(r, "LossCFFromPrevYrToAYDtl", "AssYr")
                                   or dig(r, "AssYr") or "?") for r in rows})
    return out


# --------------------------------------------------------------------------
# prefill
# --------------------------------------------------------------------------

def read_prefill(doc: dict) -> dict:
    checks, flags, refusals = [], [], []

    banks: list[dict] = []
    for group in dig(doc, "bankAccountDtls", default=[]) or []:
        banks += read_banks(dig(group, "addtnlBankDetails", default=[]))

    tds = []
    for row in dig(doc, "form26as", "tdsOnOthThanSals", "tdSonOthThanSal",
                   default=[]) or []:
        tds.append({
            "section": dig(row, "sectionCode"),
            "deductor": dig(row, "employerOrDeductorOrCollectDetl",
                            "employerOrDeductorOrCollecterName"),
            "gross_amount": num(dig(row, "grossAmount")),
            "tax_deducted": num(dig(row, "taxDeductCreditDtls",
                                    "taxDeductedOwnHands")),
            "tax_claimed": num(dig(row, "taxDeductCreditDtls",
                                   "taxClaimedOwnHands")),
        })

    salary_tds = []
    for row in dig(doc, "form26as", "tdsOnSalaries", "tdSonSalary",
                   default=[]) or []:
        salary_tds.append({
            "deductor": dig(row, "employerOrDeductorOrCollectDetl",
                            "employerOrDeductorOrCollecterName"),
            "income_charged": num(dig(row, "incChrgSal")),
            "tax_deducted": num(dig(row, "totalTDSSal")),
        })

    # Savings-bank interest is stated in as many as three places, and they are
    # three different sources: AIS, the employer's 24Q, and nothing at all from
    # the bank that did not report. They are not required to agree, and the
    # difference is the point.
    interest_views = {}
    for label, path in [
            ("AIS insights", ("insights", "intrstFrmSavingBank")),
            ("employer Form 24Q", ("form24q", "intrstFrmSavingBank")),
            ("Form 26AS block", ("form26as", "intrstFrmSavingBank"))]:
        value = num(dig(doc, *path))
        if value is not None:
            interest_views[label] = value

    dividend_views = {}
    for label, path in [
            ("AIS insights", ("insights", "scheduleOS", "incOthThanOwnRaceHorse",
                              "dividendGross")),
            ("Form 26AS block", ("form26as", "scheduleOS",
                                 "incOthThanOwnRaceHorse", "dividendGross"))]:
        value = num(dig(doc, *path))
        if value is not None:
            dividend_views[label] = value

    other_income = []
    for source in ("insights", "form26as"):
        for row in dig(doc, source, "incomeDeductionsOthersInc", default=[]) or []:
            other_income.append({"source": source,
                                 "nature": dig(row, "othSrcNatureDesc"),
                                 "amount": num(dig(row, "othSrcOthAmount"))})

    last = dig(doc, "lastFiledITR", default={}) or {}
    carry = {
        "schedule_cfl": read_cfl(dig(doc, "scheduleCFL", default={}) or {}),
        "unabsorbed_depreciation_rows": len(dig(last, "scheduleUD", default=[]) or []),
        "amt_credit_rows": len(dig(last, "scheduleAMTC", "scheduleAMTCDtls",
                                   default=[]) or []),
    }

    regime = {
        "residential_status": dig(doc, "personalInfo", "filingStatus",
                                  "residentialStatus"),
        "status": dig(doc, "personalInfo", "status"),
        "form_10IF_new_regime": dig(doc, "form10IF", "newTaxRegime"),
        "form_10IEA_on_record": bool(dig(doc, "Form10IEA")),
        "seventh_proviso_139": dig(doc, "filingStatus", "SeventhProvisio139"),
    }

    # -- checks
    nominated = [b for b in banks if b["nominated_for_refund"]]
    if banks:
        checks.append(
            f"{len(banks)} bank account(s) on record with the portal: "
            f"{', '.join(sorted({b['bank'] for b in banks}))}. Every one of them "
            "is an account the department knows about, so every one of them is "
            "an account whose interest it can look for. A savings account you "
            "did not collect a statement for is the usual reason a return "
            "under-reports Schedule OS.")
    if banks and not nominated:
        flags.append(
            "no account is nominated for refund. The portal will not let the "
            "return be filed with a refund due until one is, and validation "
            "reports it only at the last step.")
    elif len(nominated) > 1:
        checks.append(f"{len(nominated)} accounts are nominated for refund, "
                      "which is allowed; the department picks one.")

    if tds:
        checks.append(
            f"{len(tds)} non-salary TDS row(s) in the prefill, "
            f"section(s) {', '.join(sorted({str(t['section']) for t in tds}))}. "
            "Each one is income the department already knows you received. "
            "Claiming the credit without reporting the income underneath it is "
            "the single most common mismatch notice.")
        for row in tds:
            gross, deducted, claimed = (row["gross_amount"], row["tax_deducted"],
                                        row["tax_claimed"])
            if claimed is not None and deducted is not None and claimed > deducted:
                flags.append(
                    f"TDS row {row['section']}: {claimed:,.0f} claimed against "
                    f"{deducted:,.0f} deducted. Credit above what was deducted "
                    "will be disallowed at processing.")
            if gross is not None and gross == 0 and deducted:
                flags.append(
                    f"TDS row {row['section']}: tax deducted with a gross amount "
                    "of zero. The gross figure is what the income must be "
                    "reported at; find it in Form 26AS before filing.")

    if len(interest_views) > 1:
        values = set(interest_views.values())
        if len(values) > 1:
            flags.append(
                "savings-bank interest is stated differently by different "
                f"sources: {', '.join(f'{k} {v:,.0f}' for k, v in interest_views.items())}. "
                "They are not required to agree. AIS carries only what the banks "
                "reported, and the employer's 24Q carries only what you declared "
                "to the employer. Neither is a substitute for adding up the "
                "statements — and the statements are the only source that "
                "includes a bank which did not report at all.")
        else:
            checks.append(
                f"savings-bank interest agrees across {len(interest_views)} "
                f"prefill sources at {values.pop():,.0f}. Still check it against "
                "the statements: agreement between two portal views does not "
                "mean a bank is not missing from both.")

    if len(dividend_views) > 1 and len(set(dividend_views.values())) > 1:
        flags.append(
            "dividend is stated differently by the AIS insights block and the "
            f"Form 26AS block: {dividend_views}. AIS lists dividend twice by "
            "design — SFT-015 from the registrar and TDS-194 from the company's "
            "own TDS return, for the same money. Take the deduplicated figure, "
            "which is what TIS shows; adding both overstates the income.")

    cfl_state = carry["schedule_cfl"]
    if cfl_state.get("present") and not cfl_state.get("carried_forward"):
        checks.append(
            "the prefill has a ScheduleCFL block and it is empty. That is the "
            "portal saying it holds no brought-forward loss for you — which is "
            "not the same as there being none. A loss that a previous return "
            "failed to carry is simply absent here too, and this file will "
            "never tell you it was lost.")
    if not cfl_state["present"]:
        checks.append(
            "the prefill carries no ScheduleCFL. That means the portal is not "
            "offering any brought-forward loss, not that none exists — a loss "
            "that was never carried in a filed return is not offered here "
            "either. Check last year's return, not this file.")

    if regime["residential_status"] and regime["residential_status"] != "RES":
        refusals.append(
            f"residential status on record is '{regime['residential_status']}'. "
            "This skill covers resident individuals; a non-resident or RNOR "
            "return needs Schedule FSI, Schedule TR, Schedule FA and treaty "
            "relief, none of which is implemented.")

    return {
        "document": "prefill",
        "regime_and_status": regime,
        "bank_accounts": banks,
        "tds_non_salary": tds,
        "tds_salary": salary_tds,
        "savings_bank_interest_by_source": interest_views,
        "dividend_by_source": dividend_views,
        "other_income_rows": other_income,
        "carry_forward": carry,
        "checks": checks,
        "flags": flags,
        "refusals": refusals,
    }


# --------------------------------------------------------------------------
# filed return
# --------------------------------------------------------------------------

def _tds_block(itr: dict, key: str, rows_key: str, row_total_path,
              total_key: str, label: str, checks: list, flags: list) -> float:
    block = dig(itr, key, default={}) or {}
    rows = dig(block, rows_key, default=[]) or []
    stated = num(dig(block, total_key))
    if not rows and stated in (None, 0):
        # An empty schedule states a total of zero and carries no rows: that is
        # a schedule with nothing in it, and it is the common case. A schedule
        # that carries *neither* key is a schema this script does not know, and
        # reading that as "nothing to check" is how a whole schedule goes
        # unchecked in silence.
        present = {k.lower() for k in block}
        if block and rows_key.lower() not in present and total_key.lower() not in present:
            flags.append(
                f"{label}: the schedule is present but neither '{rows_key}' nor "
                f"'{total_key}' was found in it — it holds {sorted(block)[:6]}. "
                "Nothing in it was checked. Open an issue with the schema "
                "version rather than trusting the total.")
        return 0.0
    added = round(sum(total(dig(r, *row_total_path)) for r in rows), 2)
    if stated is None:
        flags.append(f"{label}: {len(rows)} row(s) but no stated total. "
                     "Nothing can be reconciled against it.")
        return added
    if abs(added - stated) > 1:
        flags.append(
            f"{label}: the rows add to {added:,.0f} but the schedule states "
            f"{stated:,.0f}. A difference of {abs(added - stated):,.0f} is a "
            "schedule that will not reconcile against Form 26AS at processing.")
    else:
        checks.append(f"{label}: {len(rows)} row(s) adding to {stated:,.0f}, "
                      "which ties to the schedule's own total.")
    return stated


def read_filed(doc: dict, form: str) -> dict:
    itr = doc["ITR"][form]
    checks, flags, refusals = [], [], []

    meta = dig(itr, f"Form_{form}", default={}) or {}
    assessment_year = dig(meta, "AssessmentYear")
    gen = dig(itr, "PartA_GEN1", default={}) or {}
    filing = dig(gen, "FilingStatus", default={}) or {}

    tti = require_object(itr, "PartB_TTI")
    comp = require_object(tti, "ComputationOfTaxLiability")
    paid = require_object(tti, "TaxPaid", "TaxesPaid")

    # -- prepaid tax, reconciled against the schedules it comes from
    tds1 = _tds_block(itr, "ScheduleTDS1", "TDSonSalary", ("TotalTDSSal",),
                      "TotalTDSonSalaries", "Schedule TDS1 (salary)",
                      checks, flags)
    tds2 = _tds_block(itr, "ScheduleTDS2", "TDSOthThanSalaryDtls",
                      ("TaxDeductCreditDtls", "TaxClaimedOwnHands"),
                      "TotalTDSonOthThanSals", "Schedule TDS2 (other than salary)",
                      checks, flags)
    # The total key is TotalTDS3OnOthThanSal, not the TotalTDS3Details this
    # script first guessed. Real returns from AY 2021-22 onward say so.
    tds3 = _tds_block(itr, "ScheduleTDS3", "TDS3Dtls",
                      ("TaxDeductCreditDtls", "TaxClaimedOwnHands"),
                      "TotalTDS3OnOthThanSal", "Schedule TDS3 (26QB/26QC)",
                      checks, flags)
    tcs = _tds_block(itr, "ScheduleTCS", "TCS", ("AmtTCSClaimedThisYear",),
                     "TotalSchTCS", "Schedule TCS", checks, flags)
    it_block = dig(itr, "ScheduleIT", default={}) or {}
    it_rows = dig(it_block, "TaxPayment", default=[]) or []
    it_total = num(dig(it_block, "TotalTaxPayments"))
    it_present = {k.lower() for k in it_block}
    if it_block and "taxpayment" not in it_present and "totaltaxpayments" not in it_present:
        flags.append(
            "Schedule IT (advance and self-assessment tax): the schedule is "
            "present but neither 'TaxPayment' nor 'TotalTaxPayments' was found "
            f"in it — it holds {sorted(it_block)[:6]}. No challan in it was "
            "checked. Open an issue with the schema version.")
    if it_rows:
        added = round(sum(total(dig(r, "Amt")) for r in it_rows), 2)
        if it_total is not None and abs(added - it_total) > 1:
            flags.append(f"Schedule IT: challans add to {added:,.0f} against a "
                         f"stated {it_total:,.0f}.")
        else:
            checks.append(f"Schedule IT: {len(it_rows)} challan(s) adding to "
                          f"{it_total if it_total is not None else added:,.0f}.")

    # Schedule IT holds the advance-tax and self-assessment challans, and
    # Part B-TTI states both again. Checking the challans only against Schedule
    # IT's own total left the pair unreconciled: a challan missing from the
    # schedule but claimed in Part B-TTI passed every check here.
    it_stated = it_total if it_total is not None else round(
        sum(total(dig(r, "Amt")) for r in it_rows), 2)
    tti_self_paid = round(total(dig(paid, "AdvanceTax"))
                          + total(dig(paid, "SelfAssessmentTax")), 2)
    # Only worth comparing when Schedule IT was understood. Where its schema is
    # unknown the flag above already says so, and saying it twice is noise.
    it_readable = not it_block or "taxpayment" in it_present or \
        "totaltaxpayments" in it_present
    if it_readable and (it_block or tti_self_paid):
        if abs(it_stated - tti_self_paid) > 1:
            flags.append(
                f"Part B-TTI claims {tti_self_paid:,.0f} of advance tax and "
                f"self-assessment tax, but Schedule IT accounts for "
                f"{it_stated:,.0f}. Every rupee of that has a challan behind it, "
                "and a claim with no challan in Schedule IT is disallowed at "
                "processing — the BSR code, date and serial number are what the "
                "department matches on.")
        elif tti_self_paid:
            checks.append(
                f"the advance tax and self-assessment tax in Part B-TTI "
                f"({tti_self_paid:,.0f}) is exactly what Schedule IT's challans "
                "account for.")

    stated_tds = total(dig(paid, "TDS"))
    schedule_tds = round(tds1 + tds2 + tds3, 2)
    if abs(stated_tds - schedule_tds) > 1:
        flags.append(
            f"Part B-TTI claims TDS of {stated_tds:,.0f} but Schedules TDS1, "
            f"TDS2 and TDS3 add to {schedule_tds:,.0f}. The utility fills this "
            "from the schedules, so a difference means one of them was edited "
            "after the other was computed.")
    else:
        checks.append(f"the TDS in Part B-TTI ({stated_tds:,.0f}) is exactly the "
                      "sum of the TDS schedules.")

    stated_tcs = total(dig(paid, "TCS"))
    if abs(stated_tcs - tcs) > 1:
        flags.append(
            f"Part B-TTI claims TCS of {stated_tcs:,.0f} but Schedule TCS adds "
            f"to {tcs:,.0f}. The utility fills this from the schedule, so a "
            "difference means one was edited after the other was computed.")
    else:
        checks.append(f"the TCS in Part B-TTI ({stated_tcs:,.0f}) is exactly the "
                      "Schedule TCS total.")

    components = round(total(dig(paid, "AdvanceTax")) + total(dig(paid, "TDS"))
                       + stated_tcs
                       + total(dig(paid, "SelfAssessmentTax")), 2)
    stated_paid = total(dig(paid, "TotalTaxesPaid"))
    if abs(components - stated_paid) > 1:
        flags.append(
            f"total taxes paid is stated as {stated_paid:,.0f} but advance tax, "
            f"TDS, TCS and self-assessment tax add to {components:,.0f}.")
    else:
        checks.append(f"total taxes paid ({stated_paid:,.0f}) is exactly its four "
                      "components.")

    # -- the liability chain
    net = total(dig(comp, "NetTaxLiability"))
    interest_paid = total(dig(comp, "IntrstPay", "TotalIntrstPay"))
    aggregate = total(dig(comp, "AggregateTaxInterestLiability"))
    if abs(net + interest_paid - aggregate) > 1:
        flags.append(
            f"aggregate liability {aggregate:,.0f} is not net tax {net:,.0f} plus "
            f"interest and fee {interest_paid:,.0f}.")
    else:
        checks.append(f"aggregate liability ({aggregate:,.0f}) is net tax plus "
                      "s.234 interest and fee.")

    refund = total(dig(tti, "Refund", "RefundDue"))
    payable = total(dig(tti, "TaxPaid", "BalTaxPayable"))
    balance = round(stated_paid - aggregate, 2)
    if refund and payable:
        flags.append(
            f"the return shows both a refund of {refund:,.0f} and a balance "
            f"payable of {payable:,.0f}. Only one of them can be right.")
    elif balance == 0 and (refund or payable):
        # Taxes paid equal the liability exactly, so there is nothing either
        # way. An earlier version fell through to the success branch here and
        # reported a return claiming a refund out of nowhere as reconciled.
        flags.append(
            f"taxes paid of {stated_paid:,.0f} exactly equal the liability, so "
            f"there is nothing to pay and nothing to refund — yet the return "
            f"states "
            + (f"a refund of {refund:,.0f}" if refund
               else f"{payable:,.0f} payable") + ".")
    elif balance > 0 and refund != round_288b(balance):
        flags.append(
            f"taxes paid exceed the liability by {balance:,.0f}, which rounds "
            f"under s.288B to {round_288b(balance):,.0f}, but the refund due is "
            f"stated as {refund:,.0f}.")
    elif balance < 0 and payable != round_288b(-balance):
        flags.append(
            f"the liability exceeds taxes paid by {-balance:,.0f}, which rounds "
            f"under s.288B to {round_288b(-balance):,.0f}, but the balance "
            f"payable is stated as {payable:,.0f}.")
    else:
        checks.append(
            f"taxes paid {stated_paid:,.0f} against a liability of "
            f"{aggregate:,.0f} gives "
            + (f"a refund of {refund:,.0f}." if refund
               else f"{payable:,.0f} payable." if payable
               else "nothing to pay and nothing to refund."))

    if refund:
        raw_accounts = dig(tti, "Refund", "BankAccountDtls",
                           "AddtnlBankDetails", default=[]) or []
        accounts = read_banks(raw_accounts)
        # UseForRefund does not exist in every schema version. On an AY 2024-25
        # ITR-2 no row carries it at all, and reading its absence as "not
        # nominated" reports a defect on a return that was filed and refunded.
        has_flag = any(
            "useforrefund" in {k.lower() for k in row}
            for row in raw_accounts if isinstance(row, dict))
        nominated = [a for a in accounts if a["nominated_for_refund"]]
        if not accounts:
            flags.append(
                f"a refund of {refund:,.0f} is claimed and the return names no "
                "bank account at all to receive it.")
        elif not has_flag:
            checks.append(
                f"{len(accounts)} bank account(s) are named for the refund of "
                f"{refund:,.0f}. This schema version carries no UseForRefund "
                "flag, so which one was nominated cannot be read from the file "
                "— the department picks one.")
        elif not nominated:
            flags.append(
                f"a refund of {refund:,.0f} is claimed but none of the "
                f"{len(accounts)} bank account(s) in the return is nominated to "
                "receive it.")
        else:
            checks.append(f"the refund is nominated to a {nominated[0]['bank']} "
                          "account.")

    # -- special rates
    si_rows = dig(itr, "ScheduleSI", "SplCodeRateTax", default=[]) or []
    live_si = [r for r in si_rows if total(dig(r, "SplRateInc"))]
    si_income = round(sum(total(dig(r, "SplRateInc")) for r in si_rows), 2)
    si_tax = round(sum(total(dig(r, "SplRateIncTax")) for r in si_rows), 2)
    stated_si = num(dig(itr, "ScheduleSI", "TotSplRateInc"))
    if live_si and stated_si is None:
        flags.append(
            f"Schedule SI: {len(live_si)} live row(s) but no stated total "
            "TotSplRateInc. Nothing can be reconciled against it.")
    elif si_rows and stated_si is not None and abs(si_income - stated_si) > 1:
        flags.append(f"Schedule SI rows add to {si_income:,.0f} against a stated "
                     f"{stated_si:,.0f}.")
    elif live_si:
        checks.append(
            f"Schedule SI: {len(live_si)} section(s) at special rates — "
            f"{', '.join(str(dig(r, 'SecCode')) for r in live_si)} — "
            f"{si_income:,.0f} of income bearing {si_tax:,.0f} of tax, which "
            "ties to the schedule's own total.")

    # -- what a later year needs out of this return
    cfl = read_cfl(dig(itr, "ScheduleCFL", default={}) or {})
    ud_key = f"{form}ScheduleUD" if f"{form}ScheduleUD" in itr else "ScheduleUD"
    ud = dig(itr, ud_key, default={}) or {}
    depreciation_cf = num(dig(ud, "TotDepritBalCFNY"))
    allowance_cf = num(dig(ud, "TotalBalCFNY"))
    amt_cf = num(dig(itr, "ScheduleAMTC", "TotBalAMTCreditCF"))

    carried = cfl.get("carried_forward") or {}
    if carried:
        checks.append(
            "this return carries losses forward: "
            + "; ".join(f"{head} {v['amount']:,.0f} ({v['set_off_window']})"
                        for head, v in carried.items())
            + ". Next year's return has to state them again in ScheduleCFL, "
              "year by year — they do not carry themselves. s.80 read with "
              "s.139(3) makes the carry-forward depend on the return that "
              "*created* the loss having been filed by the s.139(1) due date; "
              "that is the condition with teeth. A later year that simply omits "
              "the brought-forward figure is not automatically fatal to the "
              "loss, but it does forgo the set-off for that year and leaves you "
              "arguing from records nobody kept. `[documented]` on the sections; "
              "the practical consequence of an omitted year is `[inferred]`.")
    elif cfl["present"]:
        checks.append("ScheduleCFL is present and carries nothing forward.")
    else:
        checks.append("this return has no ScheduleCFL, so there is nothing to "
                      "carry to a later year from it.")

    if depreciation_cf:
        checks.append(
            f"unabsorbed depreciation carried forward: {depreciation_cf:,.0f}. "
            "Unlike a business loss it has no time limit and does not need the "
            "return to have been filed on time, but it does need to be stated in "
            "each later return's ScheduleUD.")
    if allowance_cf:
        checks.append(f"unabsorbed allowance u/s 35(4) carried forward: "
                      f"{allowance_cf:,.0f}.")
    if amt_cf:
        checks.append(
            f"AMT credit carried forward u/s 115JD: {amt_cf:,.0f}, available for "
            "15 assessment years. It is only usable in a year where regular tax "
            "exceeds AMT, and it is lost if the return stops carrying it.")

    # -- the Tax Year trap
    ay = normalise_ay(assessment_year)
    if ay:
        start = int(ay[:4])
        checks.append(
            f"this return is for assessment year {ay}, which is financial year "
            f"{start - 1}-{str(start)[2:]} under the Income-tax Act 1961. Form "
            f"168 on the same portal is headed by *Tax Year* under the "
            f"Income-tax Act 2025, and the two number differently: a Form 168 "
            f"headed Tax Year {ay} covers financial year {start}-"
            f"{str(start + 1)[2:]}, a year later than this return. The portal "
            "runs both modules at once and the figures look plausible in the "
            "wrong box.")
    elif assessment_year:
        flags.append(f"the assessment year reads '{assessment_year}', which is "
                     "not a form this script recognises. Check it by eye.")

    unchecked = sorted(k for k in itr if k.lower() not in SCHEDULES_READ)
    if unchecked:
        checks.append(
            f"{len(unchecked)} schedule(s) in this return were not looked at: "
            + ", ".join(unchecked)
            + ". Nothing above says anything about them, which is not the same "
              "as saying they are right. The presumptive blocks in particular — "
              "s.44AD, s.44ADA and s.44AE on an ITR-4 — are not read at all: no "
              "ITR-4 has been put through this script, so their key names are "
              "unknown and are not being guessed at. Send one and they can be "
              "added.")

    residential = dig(filing, "ResidentialStatus")
    if residential and residential != "RES":
        refusals.append(
            f"residential status is '{residential}'. This skill covers resident "
            "individuals only.")

    # ITR-2 and ITR-3 are filed by HUFs as well as individuals, and ITR-4 by
    # HUFs and by firms other than LLPs. The form alone does not establish that
    # a return is an individual's, and this script was reading all of them as
    # though it did.
    status = dig(gen, "PersonalInfo", "Status")
    if status and status.upper() != "I":
        refusals.append(
            f"the filer status on this return is '{status}', not 'I' for "
            "individual. "
            + {"H": "An HUF return has its own rules — no s.87A rebate, a "
                    "different Schedule AL threshold, and s.64(2) clubbing on "
                    "converted property.",
               "F": "A firm is taxed at a flat rate with no slabs, no rebate "
                    "and no regime choice."}.get(status.upper(),
                    "This skill covers resident individuals.")
            + " Nothing above accounts for that, so treat the figures as "
              "unchecked rather than as a clean return.")

    return {
        "document": "filed return",
        "form": form,
        "assessment_year": assessment_year,
        "schema_version": dig(meta, "SchemaVer"),
        "form_version": dig(meta, "FormVer"),
        "prepared_by": dig(itr, "CreationInfo", "SWCreatedBy"),
        "filing_status": {
            "residential_status": residential,
            "section_filed_under": dig(filing, "ReturnFileSec"),
            "new_regime": dig(filing, "NewTaxRegime"),
            "opted_out_of_new_regime": dig(filing, "OptOutNewTaxRegime"),
            "due_date_on_record": dig(filing, "ItrFilingDueDate"),
        },
        "taxes_paid": {
            "advance_tax": total(dig(paid, "AdvanceTax")),
            "tds": stated_tds,
            "tcs": stated_tcs,
            "self_assessment_tax": total(dig(paid, "SelfAssessmentTax")),
            "total": stated_paid,
        },
        "liability": {
            "net_tax": net,
            "interest_and_fee_234": interest_paid,
            "aggregate": aggregate,
            "refund_due": refund,
            "balance_payable": payable,
        },
        "schedules_not_checked": unchecked,
        "carry_forward": {
            "schedule_cfl": cfl,
            "unabsorbed_depreciation": depreciation_cf,
            "unabsorbed_allowance_35_4": allowance_cf,
            "amt_credit_115JD": amt_cf,
        },
        "checks": checks,
        "flags": flags,
        "refusals": refusals,
    }


# --------------------------------------------------------------------------
# cross-file
# --------------------------------------------------------------------------

def _pan(doc: dict) -> str | None:
    """Used only to compare two files. Never returned."""
    return (dig(doc, "personalInfo", "pan")
            or next((dig(doc, "ITR", form, "PartA_GEN1", "PersonalInfo", "PAN")
                     for form in FORMS
                     if dig(doc, "ITR", form) is not None), None))


def cross_check(loaded: list[tuple[str, dict, dict]]) -> dict:
    checks, flags = [], []
    pans = {}
    unidentified = []
    for name, raw, _ in loaded:
        pan = _pan(raw)
        if pan:
            pans.setdefault(pan, []).append(name)
        else:
            unidentified.append(name)
    if unidentified:
        # Silence is not agreement. With one file carrying a PAN and another
        # carrying none, `pans` still had exactly one key and this reported
        # that every file belonged to the same taxpayer.
        flags.append(
            f"{len(unidentified)} of {len(loaded)} file(s) carry no PAN this "
            f"script could read ({', '.join(unidentified)}), so they cannot be "
            "confirmed to belong to the same taxpayer as the rest. Everything "
            "reconciled across them below assumes they do.")
    if len(pans) > 1:
        flags.append(
            f"these {len(loaded)} files belong to {len(pans)} different "
            "taxpayers. Nothing below reconciles across them, and filing one "
            "person's figures on another's return is the failure mode this "
            "check exists for. The PANs are deliberately not printed.")
    elif len(pans) == 1 and len(loaded) > 1 and not unidentified:
        checks.append(f"all {len(loaded)} files belong to the same taxpayer.")
    elif len(pans) == 1 and len(loaded) > 1:
        checks.append(
            f"{len(pans[next(iter(pans))])} of {len(loaded)} files carry the "
            "same PAN; the rest carry none and are taken on trust.")

    prefills = [r for _, _, r in loaded if r["document"] == "prefill"]
    filed = [r for _, _, r in loaded if r["document"] == "filed return"]
    if prefills and filed:
        pre, ret = prefills[0], filed[0]
        pre_tds = round(sum(t["tax_claimed"] or 0 for t in pre["tds_non_salary"])
                        + sum(t["tax_deducted"] or 0 for t in pre["tds_salary"]), 2)
        ret_tds = ret["taxes_paid"]["tds"]
        if pre_tds and abs(pre_tds - ret_tds) > 1:
            flags.append(
                f"the prefill offers {pre_tds:,.0f} of TDS and the return claims "
                f"{ret_tds:,.0f}. A return claiming more than Form 26AS carries "
                "will have the excess disallowed; claiming less is money left "
                "behind. Either can be right — a row belonging to a different "
                "year is the usual reason — but it has to be the one you meant.")
        elif pre_tds:
            checks.append(f"the TDS claimed in the return ({ret_tds:,.0f}) is "
                          "exactly what the prefill offered.")

        interest = pre["savings_bank_interest_by_source"]
        if interest:
            flags.append(
                "the prefill states savings-bank interest of "
                + ", ".join(f"{v:,.0f} ({k})" for k, v in interest.items())
                + ". Reconcile it against the statements with "
                  "parse_bank_statement.py before accepting either figure — "
                  "this script cannot see Schedule OS row by row.")
    return {"checks": checks, "flags": flags}


# --------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--json", metavar="PATH", help="write the full result to a file")
    a = ap.parse_args(argv)

    loaded = []
    for path in a.files:
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, json.JSONDecodeError) as e:
            print(json.dumps({"refused": f"{safe_name(path)}: {e}"},
                             indent=2), file=sys.stderr)
            return 2
        try:
            if not isinstance(raw, dict):
                raise Refusal(
                    f"the JSON root is a {json_type_name(raw)}, not an object. "
                    "A portal prefill or filed return must have a JSON object "
                    "at the root.")
            kind, form = detect(raw)
            result = (read_prefill(raw) if kind == "prefill"
                      else read_filed(raw, form))
        except Refusal as e:
            print(json.dumps({"refused": str(e),
                              "file": safe_name(path)}, indent=2),
                  file=sys.stderr)
            return 2
        result["file"] = safe_name(path)
        loaded.append((safe_name(path), raw, result))

    cross = cross_check(loaded) if len(loaded) > 1 else {"checks": [], "flags": []}
    out = {
        "documents": [r for _, _, r in loaded],
        "checks": cross["checks"],
        "flags": cross["flags"],
        "disclaimer": (
            "Read from the files as given. No identifier is reproduced: not the "
            "PAN, the Aadhaar number, an account number, the mobile number or "
            "the email address, all of which these files carry. Nothing here is "
            "a computation of tax — it checks the totals in the file against the "
            "rows they are made of, and reports what a later year has to carry."),
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2, ensure_ascii=False)

    refused = [r for _, _, r in loaded if r["refusals"]]
    return 3 if refused else 0


if __name__ == "__main__":
    sys.exit(main())
