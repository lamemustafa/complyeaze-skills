#!/usr/bin/env python3
"""
Deterministic income-tax computation for a RESIDENT individual, AY 2026-27
(FY 2025-26, governed by the Income-tax Act 1961).

The model must NOT do this arithmetic. Call this script, read the JSON it prints,
and use those figures. If a case falls outside what this handles, the script
refuses rather than guessing — that refusal is the point.

Usage:
    python3 compute_tax.py --help
    python3 compute_tax.py --salary 1660000 --savings-interest 4100 \
        --refund-interest 529 --winnings-115bbj 6 --tds 121950
    python3 compute_tax.py --self-test
    python3 compute_tax.py --golden ../evals/golden/cases.json

Stdlib only. No network. Reads nothing from disk except an explicit --golden file.

Every rate below carries the section it comes from. Before relying on any of
them, check the section text at incometaxindia.gov.in. Rates change every year;
this file is pinned to AY 2026-27 and to nothing else.
"""
from __future__ import annotations
import argparse, json, os, sys
from datetime import date
from decimal import Decimal as D, ROUND_HALF_UP

AY = "2026-27"
PY = "2025-26"
GOVERNING_ACT = "Income-tax Act, 1961"

# --- AY 2026-27, verified 2026-07-28 against incometaxindia.gov.in bare text,
#     the Finance Act 2025/2026 and the CBDT AY 2026-27 validation rules. ---

# s.115BAC(1A) — the default regime.
NEW_SLABS = [(400000, "0"), (800000, "0.05"), (1200000, "0.10"),
             (1600000, "0.15"), (2000000, "0.20"), (2400000, "0.25"), (None, "0.30")]
NEW_BEL = D(400000)

# Old regime, Finance Act 2025 First Schedule Paragraph A. The first slab is
# age-banded; s.115BAC(1A) has no age banding at all.
OLD_BEL_BY_AGE = {"below60": D(250000), "60to79": D(300000), "80plus": D(500000)}

STD_DED_NEW, STD_DED_OLD = D(75000), D(50000)        # s.16(ia)

# s.87A, first proviso as substituted by Finance Act 2025 w.e.f. AY 2026-27.
REBATE_87A_NEW, REBATE_87A_NEW_CEILING = D(60000), D(1200000)
REBATE_87A_OLD, REBATE_87A_OLD_CEILING = D(12500), D(500000)

CESS = D("0.04")                                     # Health & education cess
ADVANCE_TAX_THRESHOLD = D(10000)                     # s.208

SPECIAL_RATES = {                                    # section -> rate
    "111A":   D("0.20"),    # STCG equity / equity MF, STT paid
    "112A":   D("0.125"),   # LTCG same, above the 112A exemption
    "112":    D("0.125"),   # LTCG other assets, no indexation
    "112_LB": D("0.125"),   # LTCG land/building — dual computation, see below
    "115BB":  D("0.30"),    # lottery, crossword, gambling
    "115BBJ": D("0.30"),    # winnings from online games
    "115BBH": D("0.30"),    # virtual digital assets
    "115BBE": D("0.60"),    # unexplained credits / investments
}
LTCG_112A_EXEMPT = D(125000)                         # s.112A(1) proviso
LTCG_112_LB_OLD_RATE = D("0.20")                     # pre-FA(No.2) 2024 rate

# Only these carry a proviso letting an unabsorbed basic exemption soak up the
# gain: first proviso to s.111A(1), proviso to s.112A(2), first proviso to
# s.112(1)(a). Residents only. Nothing similar exists for 115BB/BBJ/BBH/BBE.
BEL_ABSORBABLE = ("111A", "112", "112_LB", "112A")

# s.87A under the OLD regime: s.112A(6) is the only express bar. There is no
# equivalent in s.111A — see ITAT Ahmedabad, Jayshreeben Palsana (Aug 2025).
# Everything else is excluded here conservatively; see rebate_87A_basis in the
# output and references/rates-ay2026-27.md for the open risk.
OLD_REBATE_ELIGIBLE_SPECIAL = ("111A",)

SURCHARGE_BANDS = [(D(50000000), D("0.37")), (D(20000000), D("0.25")),
                   (D(10000000), D("0.15")), (D(5000000), D("0.10"))]
SURCHARGE_CAP_NEW = D("0.25")   # s.115BAC(1A) — no 37% band exists
SURCHARGE_CAP_CG  = D("0.15")   # First Schedule proviso: dividend + 111A/112/112A

# s.80CCD(2) — 14% for government employers; 10% for others, lifted to 14%
# under s.115BAC(1A) by the proviso inserted by Act 15 of 2024.
NPS_80CCD2 = {("new", "govt"): D("0.14"), ("new", "other"): D("0.14"),
              ("old", "govt"): D("0.14"), ("old", "other"): D("0.10")}

# s.57(iia) family pension: 33 1/3% capped at 25,000 (new) / 15,000 (old).
FAMILY_PENSION_FRAC = D(1) / D(3)
FAMILY_PENSION_CAP = {"new": D(25000), "old": D(15000)}

# Filing dates for AY 2026-27. Explanation 2 to s.139(1) as substituted by the
# Finance Act 2026 — note the NEW 31 August slot, keyed on audit liability and
# NOT on which ITR form is used.
DUE_DATES = {
    "no-business":        date(2026, 7, 31),   # Expl. 2(d)
    "business-no-audit":  date(2026, 8, 31),   # Expl. 2(c) — new, FA 2026
    "audit-44ab":         date(2026, 10, 31),  # Expl. 2(b)
    "transfer-pricing":   date(2026, 11, 30),  # Expl. 2(a), s.92E
}
BELATED_LAST = date(2026, 12, 31)              # s.139(4)
REVISED_LAST = date(2027, 3, 31)               # s.139(5) as substituted, FA 2026
# [documented] An updated return u/s 139(8A) may be furnished only from the end
# of the relevant assessment year, so for AY 2026-27 ITR-U opens the day after
# the s.139(5) window closes. A 139(8A) return dated before this is not a return
# that exists.
UPDATED_FIRST = date(2027, 4, 1)               # s.139(8A)
FEE_234I_FROM = date(2027, 1, 1)               # ITR validation rules 694/695
FEE_234F = (D(5000), D(1000), D(500000))       # s.234F: normal, reduced, threshold
FEE_234I = (D(5000), D(1000), D(500000))       # s.234-I, FA 2026 cl.12


def r10(x: D) -> D:
    """s.288A / s.288B — round to the NEAREST multiple of ten (half up)."""
    return (x / 10).quantize(D(1), rounding=ROUND_HALF_UP) * 10


def p2(x: D) -> D:
    return x.quantize(D("0.01"), rounding=ROUND_HALF_UP)


def slab_tax(income: D, slabs) -> D:
    tax, prev = D(0), D(0)
    for cap, rate in slabs:
        upper = D(cap) if cap is not None else income
        if income > prev:
            tax += (min(income, upper) - prev) * D(rate)
            prev = upper
        else:
            break
    return tax


def old_slabs(age_band: str):
    bel = OLD_BEL_BY_AGE[age_band]
    rest = [(500000, "0.05"), (1000000, "0.20"), (None, "0.30")]
    if bel >= D(500000):            # 80+: the 5% band disappears entirely
        return [(500000, "0"), (1000000, "0.20"), (None, "0.30")]
    return [(int(bel), "0")] + rest


class Refusal(Exception):
    """Raised when the case is outside what this engine will compute."""


def special_tax(special: dict[str, D], lb: dict | None) -> tuple[D, dict]:
    """Tax on special-rate income. `special` holds post-BEL-absorption amounts."""
    total, detail = D(0), {}
    for sec, amt in special.items():
        if sec not in SPECIAL_RATES:
            raise Refusal(f"unknown special-rate section {sec!r}; "
                          f"known: {sorted(SPECIAL_RATES)}")
        if sec == "112_LB":
            # Second proviso to s.112(1)(a), inserted by Finance (No.2) Act 2024.
            # Resident individual/HUF, land or building acquired before
            # 23-07-2024 and transferred on or after that date: the excess of
            # the 12.5%-without-indexation tax over the 20%-with-indexation tax
            # is IGNORED. It is a tax comparison, not a re-computation of gain —
            # the unindexed gain is what enters total income either way, and an
            # indexed LOSS gives no benefit beyond capping the tax.
            t_new = amt * SPECIAL_RATES["112_LB"]
            t_old = max(D(0), D(lb["indexed_gain"])) * LTCG_112_LB_OLD_RATE
            t = min(t_new, t_old)
            detail[sec] = {
                "income": str(amt), "taxable": str(amt),
                "tax_12.5pc_no_indexation": str(p2(t_new)),
                "tax_20pc_with_indexation": str(p2(t_old)),
                "indexed_gain": str(lb["indexed_gain"]),
                "applied": "20% with indexation" if t_old < t_new
                           else "12.5% without indexation",
                "basis": "second proviso to s.112(1)(a) — resident individual/HUF only",
                "tax": str(p2(t)),
            }
        else:
            taxable = amt
            if sec == "112A":
                taxable = max(D(0), amt - LTCG_112A_EXEMPT)
            t = taxable * SPECIAL_RATES[sec]
            detail[sec] = {"income": str(amt), "taxable": str(taxable),
                           "rate": str(SPECIAL_RATES[sec]), "tax": str(p2(t))}
        total += t
    return total, detail


def absorb_basic_exemption(special: dict[str, D], slab_base: D, bel: D) -> tuple[dict, dict]:
    """First proviso to s.111A(1) / proviso to s.112A(2) / first proviso to
    s.112(1)(a): a resident whose other income falls short of the basic
    exemption limit may set that shortfall against these gains."""
    shortfall = max(D(0), bel - slab_base)
    if shortfall == 0 or not special:
        return special, {"shortfall": "0", "absorbed": {}}
    # The provisos do not prescribe an order across heads. Absorb against the
    # highest-taxed eligible gain first — the reading most favourable to the
    # assessee. Within a rate tier, absorb into 112A LAST: it already carries a
    # free 1,25,000 exemption, so soaking the shortfall into it wastes up to
    # that much of the shortfall. Sorting on a tuple keeps this deterministic
    # rather than dependent on dict insertion order.
    order = sorted((s for s in special if s in BEL_ABSORBABLE),
                   key=lambda s: (SPECIAL_RATES[s], s != "112A"), reverse=True)
    out, absorbed, left = dict(special), {}, shortfall
    for sec in order:
        if left <= 0:
            break
        take = min(left, out[sec])
        if take > 0:
            out[sec] -= take
            absorbed[sec] = str(take)
            left -= take
    return out, {"shortfall": str(shortfall), "absorbed": absorbed,
                 "note": "residents only; applied to the highest-taxed eligible "
                         "gain first and to 112A last within a rate tier, since "
                         "112A already carries its own exemption; "
                         "115BB/115BBJ/115BBH are not eligible"}


def surcharge_band(total_income: D, regime: str) -> tuple[D, D | None]:
    """Applicable surcharge rate and the threshold it sits above."""
    for threshold, r in SURCHARGE_BANDS:
        if total_income > threshold:
            # s.115BAC(1A) has no 37% band — it caps at 25%.
            return (min(r, SURCHARGE_CAP_NEW) if regime == "new" else r), threshold
    return D(0), None


def gross_surcharge(rate: D, tax_capped: D, tax_full: D) -> D:
    """Surcharge before marginal relief. Tax on dividends and on 111A/112/112A
    gains bears at most 15% (First Schedule proviso); the rest bears the full
    rate."""
    return tax_full * rate + tax_capped * min(rate, SURCHARGE_CAP_CG)


def surcharge(total_income: D, tax_capped: D, tax_full: D, regime: str,
              tax_at) -> tuple[D, dict]:
    """Surcharge with the 15% cap and marginal relief.

    `tax_at(income)` must return the tax (before surcharge and cess) that would
    arise on a hypothetical total income, holding special-rate income constant
    and shrinking slab income — the standard assumption, since the marginal
    rupee at a surcharge threshold is ordinary income.

    Marginal relief has to be computed from a *recomputed* tax at the threshold.
    Deriving it arithmetically from the actual tax (tax_total - excess) is
    algebraically self-cancelling and silently zeroes the surcharge.
    """
    rate, band = surcharge_band(total_income, regime)
    if rate == 0:
        return D(0), {"rate": "0"}

    sur = gross_surcharge(rate, tax_capped, tax_full)
    info = {"rate": str(rate), "capped_rate_on_dividend_and_cg":
            str(min(rate, SURCHARGE_CAP_CG)), "band_threshold": str(band)}

    tax_total = tax_capped + tax_full
    excess_income = total_income - band
    tax_band = tax_at(band)
    rate_band, _ = surcharge_band(band, regime)     # the band below, or nil
    if tax_total > 0:
        cap_band = tax_band * tax_capped / tax_total
    else:
        cap_band = D(0)
    sur_band = gross_surcharge(rate_band, cap_band, tax_band - cap_band)

    ceiling = tax_band + sur_band + excess_income
    if tax_total + sur > ceiling:
        relieved = max(D(0), ceiling - tax_total)
        info["marginal_relief"] = str(p2(sur - relieved))
        info["tax_at_threshold"] = str(p2(tax_band + sur_band))
        info["note"] = ("marginal relief applied at the surcharge threshold; "
                        "verify against the portal's own computation")
        sur = relieved
    return sur, info


def compute(regime: str, salary: D, other_slab: D, special: dict[str, D],
            house_property: D, chapter_via: D, *, age_band: str = "below60",
            nps_80ccd2: D = D(0), nps_salary: D = D(0), employer: str = "other",
            family_pension: D = D(0), lb: dict | None = None,
            dividends: D = D(0), stcg_slab: D = D(0)) -> dict:
    # A broker reports a short-term loss as a negative figure, and it arrives
    # here through --stcg-slab, which is added to slab income — where the
    # negative special-rate check below never sees it. Left alone it would
    # quietly reduce taxable income, which is capital-loss set-off performed
    # without the ordering, the intra-head restriction or the schedules.
    if stcg_slab < 0:
        raise Refusal(
            f"negative slab-rate short-term capital gain ({stcg_slab}) — a "
            "capital LOSS. [documented] s.70 sets the order in which a loss is "
            "set off within a head and s.71 across heads; s.74 restricts a "
            "long-term capital loss to long-term gains and allows an 8-year "
            "carry-forward. [documented] Schedules CYLA, BFLA and CFL are "
            "where a return records that set-off and carry-forward. "
            "[observed, this engine] None of that is modelled here, so netting "
            "the loss into slab income would apply a set-off nobody checked. "
            "Compute it on the portal and verify against your own working.")
    if "112_LB" in special and (lb is None or "indexed_gain" not in lb):
        raise Refusal(
            "LTCG on land/building acquired before 23-07-2024 needs BOTH the "
            "unindexed gain and the indexed gain — the second proviso to "
            "s.112(1)(a) charges the LOWER of 12.5% without indexation and 20% "
            "with indexation. Pass --ltcg-112-landbuilding-indexed-gain. "
            "Without the indexed figure this engine would overtax the sale.")

    negative = sorted(s for s, v in special.items() if v < 0)
    if negative:
        raise Refusal(
            f"negative special-rate income {negative} — capital LOSS set-off and "
            "carry-forward under s.70/71/74 is outside this engine. Losses have "
            "an ordering, an intra-head restriction (long-term against long-term "
            "only) and an 8-year carry-forward that needs Schedules CYLA, BFLA "
            "and CFL. Compute it on the portal and verify against your own "
            "working.")

    if "115BBE" in special:
        raise Refusal(
            "s.115BBE unexplained credits/investments: 60% tax plus a FLAT 25% "
            "surcharge irrespective of total income, no deduction, no set-off, "
            "and s.271AAC penalty exposure. This engine does not model that "
            "surcharge. Get a qualified professional.")

    if nps_80ccd2 > 0 and nps_salary <= 0:
        raise Refusal(
            "s.80CCD(2) is capped at a percentage of SALARY, which the "
            "Explanation defines as basic pay plus dearness allowance where the "
            "terms of employment so provide — not gross salary u/s 17(1). Pass "
            "--nps-80ccd2-salary. Defaulting to gross salary would overstate the "
            "cap and understate the tax.")

    std = STD_DED_NEW if regime == "new" else STD_DED_OLD
    salary_income = max(D(0), salary - std) if salary else D(0)

    # s.57(iia) family pension — allowed under BOTH regimes.
    fp_ded = min(family_pension * FAMILY_PENSION_FRAC,
                 FAMILY_PENSION_CAP[regime]) if family_pension else D(0)
    fp_income = max(D(0), family_pension - fp_ded)

    special_total = sum(special.values(), D(0))
    gti = salary_income + house_property + other_slab + fp_income + special_total

    # s.80CCD(2) survives the new regime; the percentage cap is on salary
    # (basic + DA), and differs by regime and employer type.
    cap_pct = NPS_80CCD2[(regime, employer)]
    ded_80ccd2 = min(nps_80ccd2, cap_pct * nps_salary) if nps_80ccd2 else D(0)
    claimed = ded_80ccd2 + (chapter_via if regime == "old" else D(0))

    # Chapter VI-A cannot be set against special-rate income —
    # s.111A(2), s.112A(5), s.112(2).
    deduction_room = max(D(0), gti - special_total)
    deductions = min(claimed, deduction_room)
    total_income = max(D(0), gti - deductions)

    slab_base = max(D(0), total_income - special_total)
    bel = NEW_BEL if regime == "new" else OLD_BEL_BY_AGE[age_band]
    special_after, bel_info = absorb_basic_exemption(special, slab_base, bel)

    # The pre-amendment computation the second proviso compares against sits
    # inside s.112(1)(a) and so carries the FIRST proviso too — any basic
    # exemption absorbed from the unindexed gain reduces the indexed gain by the
    # same amount. Failing to do this makes the 20% limb look artificially
    # expensive and picks the wrong side of the comparison.
    if lb is not None and "112_LB" in bel_info.get("absorbed", {}):
        lb = dict(lb)
        lb["indexed_gain"] = max(
            D(0), D(lb["indexed_gain"]) - D(bel_info["absorbed"]["112_LB"]))

    slabs = NEW_SLABS if regime == "new" else old_slabs(age_band)
    t_slab = slab_tax(slab_base, slabs)
    t_spec, spec_detail = special_tax(special_after, lb)
    tax_before_rebate = t_slab + t_spec

    # --- s.87A, regime-conditional -------------------------------------------
    if regime == "new":
        # Second proviso inserted by Finance Act 2025 w.e.f. AY 2026-27: the
        # rebate cannot exceed tax at the s.115BAC(1A) rates, so it reaches
        # slab tax only — never 111A, 112A, 112 or any 115BB* income.
        rebate_base = t_slab
        basis = ("new regime: capped at tax on slab income by the second proviso "
                 "to s.87A (Finance Act 2025) — no rebate against 111A/112A/112")
        ceiling, max_rebate = REBATE_87A_NEW_CEILING, REBATE_87A_NEW
    else:
        # Old regime: s.112A(6) is the ONLY express bar. s.111A carries no
        # equivalent restriction, so the rebate is allowable against 111A tax.
        rebate_base = t_slab + sum(
            D(spec_detail[s]["tax"]) for s in OLD_REBATE_ELIGIBLE_SPECIAL
            if s in spec_detail)
        basis = ("old regime: allowed against slab tax and s.111A tax (no bar in "
                 "s.111A); barred against 112A by s.112A(6). Other special-rate "
                 "sections excluded conservatively — UNVERIFIED whether the "
                 "portal utility agrees; check the portal's own figure")
        ceiling, max_rebate = REBATE_87A_OLD_CEILING, REBATE_87A_OLD

    rebate = min(rebate_base, max_rebate) if total_income <= ceiling else D(0)

    # Marginal relief on the rebate — new regime only, first proviso clause (b).
    if regime == "new" and total_income > ceiling:
        excess = total_income - ceiling
        if tax_before_rebate > excess:
            rebate = max(rebate, min(tax_before_rebate - excess, t_slab))

    tax_after_rebate = max(D(0), tax_before_rebate - rebate)

    # Surcharge: split the tax base into the 15%-capped slice (dividends plus
    # 111A/112/112A tax) and the rest.
    capped_secs = ("111A", "112A", "112", "112_LB")
    t_capped = sum((D(spec_detail[s]["tax"]) for s in capped_secs if s in spec_detail), D(0))
    if dividends > 0 and slab_base > 0:
        t_capped += t_slab * min(dividends, slab_base) / slab_base
    t_full = max(D(0), tax_before_rebate - t_capped)
    if rebate > 0:                                   # rebate only bites below 50L
        t_full = max(D(0), t_full - rebate)

    def tax_at(hypothetical_total_income: D) -> D:
        """Tax before surcharge on a hypothetical total income, holding
        special-rate income constant and shrinking slab income."""
        return slab_tax(max(D(0), hypothetical_total_income - special_total),
                        slabs) + t_spec

    sur, sur_info = surcharge(total_income, t_capped, t_full, regime, tax_at)

    cess = (tax_after_rebate + sur) * CESS
    total_tax = tax_after_rebate + sur + cess

    return {
        "regime": regime,
        "age_band": age_band,
        "basic_exemption_limit": str(bel),
        "salary_gross": str(salary),
        "standard_deduction": str(std),
        "income_from_salary": str(salary_income),
        "family_pension_gross": str(family_pension),
        "family_pension_deduction_57iia": str(p2(fp_ded)),
        "income_house_property": str(house_property),
        "income_other_slab": str(other_slab),
        "capital_gains_at_slab_rates": str(stcg_slab),
        "income_special_rate": str(special_total),
        "gross_total_income": str(gti),
        "deduction_80CCD2": str(p2(ded_80ccd2)),
        "deduction_80CCD2_cap_pct": str(cap_pct),
        "chapter_via_deductions": str(p2(deductions)),
        "total_income": str(total_income),
        "total_income_rounded_288A": str(r10(total_income)),
        "basic_exemption_absorption": bel_info,
        "tax_on_slab_income": str(p2(t_slab)),
        "tax_at_special_rates": str(p2(t_spec)),
        "special_rate_detail": spec_detail,
        "rebate_87A": str(p2(rebate)),
        "rebate_87A_basis": basis,
        "surcharge": str(p2(sur)),
        "surcharge_detail": sur_info,
        "cess_4pc": str(p2(cess)),
        "total_tax_and_cess": str(p2(total_tax)),
        "total_tax_rounded_288B": str(r10(total_tax)),
    }


def late_fees(total_income: D, filing_date: date | None, category: str,
              section: str, bel: D, must_file: bool) -> dict:
    """s.234F (late return) and s.234-I (late revised return). Deterministic —
    unlike 234A/B/C, which this engine deliberately does not compute.

    The two fees are mutually exclusive on any given set of facts, so the
    filing sub-section has to be known before either can be charged.
    """
    if filing_date is None:
        return {"note": "pass --filing-date (and --filing-section) to compute "
                        "s.234F / s.234-I"}
    due = DUE_DATES[category]
    out = {"filing_section": section,
           "due_date_s139_1": due.isoformat(),
           "belated_last_date_s139_4": BELATED_LAST.isoformat(),
           "revised_last_date_s139_5": REVISED_LAST.isoformat(),
           "filing_date": filing_date.isoformat(),
           "fee_234F": "0", "fee_234I": "0"}

    def tiered(fees):
        normal, reduced, threshold = fees
        return str(reduced if total_income <= threshold else normal)

    # s.234F bites only on a person "required to furnish a return under s.139".
    # Someone below the basic exemption limit filing purely to claim a refund
    # owes nothing — unless a seventh-proviso or Rule 12AB trigger applies, which
    # this engine cannot see.
    liable = must_file or total_income > bel
    if not liable:
        out["fee_234F_basis"] = (
            "nil — s.234F applies only to a person required to furnish a return. "
            "Total income is at or below the basic exemption limit. If a seventh-"
            "proviso or Rule 12AB trigger applies (current-account deposits over "
            "1 crore, foreign travel over 2 lakh, electricity over 1 lakh, "
            "turnover over 60 lakh, professional receipts over 10 lakh, TDS+TCS "
            "of 25,000/50,000, savings deposits of 50 lakh, or any foreign "
            "asset), pass --must-file and re-run")
    elif section == "139(5)":
        # A revised return carries no 234F — the original was timely. It carries
        # s.234-I instead, and only from 1 January 2027.
        out["fee_234F_basis"] = ("[documented] nil — a revised return u/s 139(5) "
                                 "does not attract 234F")
        if filing_date > REVISED_LAST:
            out["error"] = ("past 31-03-2027 — a revised return is no longer "
                            "possible. Only an updated return u/s 139(8A) remains")
        elif filing_date >= FEE_234I_FROM:
            out["fee_234I"] = tiered(FEE_234I)
            out["fee_234I_basis"] = (
                "[documented] s.234-I, inserted by the Finance Act 2026 — charged "
                "on a s.139(5) "
                "revised return filed on or after 01-01-2027. The gazetted text "
                "says 'assessment year' where 'previous year' is plainly meant; "
                "[documented] the ITR validation rules key it to 31-12-2026, and "
                "the utility follows the intended reading. [inferred] This engine "
                "follows the validation rules rather than the literal text, "
                "because that is what the portal will accept — but the conflict "
                "is unresolved and the figure is not beyond challenge")
        else:
            out["fee_234I_basis"] = "nil — revised on or before 31-12-2026"
    elif filing_date <= due:
        out["fee_234F_basis"] = "[documented] nil — filed within the s.139(1) due date"
    elif filing_date <= BELATED_LAST:
        out["fee_234F"] = tiered(FEE_234F)
        out["fee_234F_basis"] = "[documented] belated return u/s 139(4)"
    else:
        out["fee_234F"] = tiered(FEE_234F)
        out["fee_234F_basis"] = (
            "[documented] after 31-12-2026 neither an original nor a belated "
            "return can be "
            "filed. This is an updated return u/s 139(8A): the 234F fee is paid "
            "as part of s.140B along with additional tax of 25/50/60/70 per cent "
            "by band, which this engine does not compute")

    out["not_computed"] = "s.234A / 234B / 234C interest — read them off the portal"
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--salary", type=str, default="0",
                    help="salary chargeable under the head Salaries — s.17(1) plus "
                         "perquisites u/s 17(2) plus profits in lieu u/s 17(3), "
                         "LESS any allowances exempt u/s 10 such as HRA or LTA, and "
                         "BEFORE the s.16(ia) standard deduction, which this engine "
                         "applies itself. [documented] s.15 to s.17 with the "
                         "notified Form 16 Part B: the row to take is 'Total amount "
                         "of salary received from current employer', NOT the 'Gross "
                         "Salary' total printed above it — the two differ by the "
                         "exempt allowances, and this engine has no argument for "
                         "those, so passing the gross total overstates salary "
                         "income for anyone claiming them. With more than one "
                         "employer in the year, SUM that row across every Form 16 "
                         "and ignore the 'Reported total amount of salary received "
                         "from other employer(s)' line, which restates another "
                         "certificate's figure and would double-count it")
    ap.add_argument("--house-property", type=str, default="0",
                    help="income (or negative, loss) from house property")
    ap.add_argument("--family-pension", type=str, default="0",
                    help="gross family pension; s.57(iia) deduction applied")
    ap.add_argument("--savings-interest", type=str, default="0")
    ap.add_argument("--fd-interest", type=str, default="0")
    ap.add_argument("--refund-interest", type=str, default="0", help="s.244A refund interest")
    ap.add_argument("--dividends", type=str, default="0",
                    help="slab-rate, but surcharge on it is capped at 15%%")
    ap.add_argument("--other-slab-income", type=str, default="0")
    ap.add_argument("--presumptive-44ada-receipts", type=str, default="0",
                    help="gross professional receipts; 50%% is presumed as "
                         "profit and taxed at slab")
    ap.add_argument("--presumptive-44ada-profit", type=str, default=None,
                    help="declare more than the 50%% presumption; declaring "
                         "less is refused, because it is not s.44ADA")
    ap.add_argument("--cash-receipts-within-5pc", action="store_true",
                    help="cash receipts are 5%% or less of turnover, which "
                         "raises the s.44ADA ceiling from 50 to 75 lakh")
    ap.add_argument("--stcg-slab", type=str, default="0",
                    help="STCG on an asset outside s.111A — a debt or gold ETF, "
                         "unlisted shares held short, physical gold, an "
                         "unlisted debenture. Taxed at slab, like other income, "
                         "but it is a capital gain and Schedule CG has to "
                         "carry it, so it is reported separately from "
                         "--other-slab-income")
    ap.add_argument("--stcg-111a", type=str, default="0", help="equity/equity MF, STT paid")
    ap.add_argument("--ltcg-112a", type=str, default="0", help="first 1,25,000 exempt")
    ap.add_argument("--ltcg-112", type=str, default="0",
                    help="LTCG other assets at 12.5%%, no indexation option")
    ap.add_argument("--ltcg-112-landbuilding", type=str, default="0",
                    help="UNINDEXED gain on land/building acquired before 23-07-2024")
    ap.add_argument("--ltcg-112-landbuilding-indexed-gain", type=str, default=None,
                    help="the same sale computed WITH indexation; required with the above")
    ap.add_argument("--winnings-115bb", type=str, default="0", help="lottery, gambling")
    ap.add_argument("--winnings-115bbj", type=str, default="0", help="online games")
    ap.add_argument("--vda-115bbh", type=str, default="0")
    ap.add_argument("--chapter-via", type=str, default="0",
                    help="old regime only, EXCLUDING 80CCD(2)")
    ap.add_argument("--nps-80ccd2", type=str, default="0",
                    help="employer NPS contribution; allowed under BOTH regimes")
    ap.add_argument("--nps-80ccd2-salary", type=str, default="0",
                    help="salary (basic+DA) for the 80CCD(2) percentage cap")
    ap.add_argument("--employer", choices=["govt", "other"], default="other")
    ap.add_argument("--age-band", choices=["below60", "60to79", "80plus"],
                    default="below60", help="old regime only; s.115BAC has no age banding")
    ap.add_argument("--tds", type=str, default="0")
    ap.add_argument("--advance-tax", type=str, default="0")
    ap.add_argument("--self-assessment-tax", type=str, default="0")
    ap.add_argument("--filing-date", type=str, default=None, help="YYYY-MM-DD")
    ap.add_argument("--due-date-category", choices=sorted(DUE_DATES),
                    default=None, help="defaults to business-no-audit when "
                                       "presumptive professional receipts are "
                                       "present, otherwise no-business")
    ap.add_argument("--filing-section", choices=["139(1)", "139(4)", "139(5)", "139(8A)"],
                    default="139(1)", help="which sub-section the return is filed under; "
                                           "234F and 234-I are mutually exclusive")
    ap.add_argument("--must-file", action="store_true",
                    help="a seventh-proviso or Rule 12AB trigger applies, so a return "
                         "is mandatory even below the basic exemption limit")
    ap.add_argument("--regime", choices=["new", "old", "both"], default="both")
    ap.add_argument("--non-resident", action="store_true",
                    help="refuses: residency changes 87A, the s.112 option, "
                         "basic-exemption absorption and surcharge")
    ap.add_argument("--summary", action="store_true",
                    help="a few lines instead of the full JSON")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--business-income", choices=["yes", "no"], default=None,
                    help="whether ANY business or professional income exists — "
                         "44AD/44AE, intraday, F&O, partner remuneration and so "
                         "on. Decides whether Form 10-IEA is needed for the old "
                         "regime. Without it the engine declines to say, because "
                         "it has no argument for those heads")
    ap.add_argument("--golden", type=str, default=None,
                    help="path to evals/golden/cases.json")
    a = ap.parse_args(argv)

    if a.self_test:
        return self_test()
    if a.golden:
        return run_golden(a.golden)

    if a.non_resident:
        print(json.dumps({"refused": "This engine computes for RESIDENT "
              "individuals only. A non-resident gets no s.87A rebate, no basic-"
              "exemption absorption against 111A/112A, and no 20%-with-indexation "
              "option under the second proviso to s.112(1)(a) (that proviso sits "
              "inside clause (a), which is confined to residents). Different "
              "surcharge carve-outs apply under s.115A/115AB/115AC/115ACA/115E. "
              "Use a qualified professional."}, indent=2), file=sys.stderr)
        return 2

    n = lambda s: D(str(s).replace(",", "").replace("_", ""))
    dividends = n(a.dividends)
    presumptive_receipts = n(a.presumptive_44ada_receipts)
    has_business_income = _business_income_state(
        a.business_income, presumptive_receipts)
    try:
        presumptive = presumptive_44ada(
            presumptive_receipts,
            None if a.presumptive_44ada_profit is None
            else n(a.presumptive_44ada_profit),
            a.cash_receipts_within_5pc)
        due_date_category = resolve_due_date_category(
            a.due_date_category, has_business_income)
    except Refusal as e:
        print(json.dumps({"refused": str(e)}, indent=2), file=sys.stderr)
        return 2
    # s.111A reaches STT-paid equity only. A short-term gain on anything else
    # is taxed at slab like ordinary income, but it is still a capital gain:
    # Schedule CG has to carry it, and folding it into --other-slab-income got
    # the tax right while making the engine's output useless as a cross-check
    # against that schedule.
    stcg_slab = n(a.stcg_slab)
    other_slab = (n(a.savings_interest) + n(a.fd_interest) + n(a.refund_interest)
                  + dividends + n(a.other_slab_income) + stcg_slab + presumptive)
    special = {k: v for k, v in {
        "111A": n(a.stcg_111a), "112A": n(a.ltcg_112a), "112": n(a.ltcg_112),
        "112_LB": n(a.ltcg_112_landbuilding),
        "115BB": n(a.winnings_115bb), "115BBJ": n(a.winnings_115bbj),
        "115BBH": n(a.vda_115bbh),
    }.items() if v != 0}
    lb = ({"indexed_gain": n(a.ltcg_112_landbuilding_indexed_gain)}
          if a.ltcg_112_landbuilding_indexed_gain is not None else None)

    hp = n(a.house_property)
    if hp < 0:
        print(json.dumps({"refused": "house-property LOSS set-off is not handled. "
              "Set-off order and the 2,00,000 in-year cap under s.71(3A) need "
              "Schedule CYLA; under s.115BAC(2)(ii) the loss cannot be set off "
              "against any other head at all. Compute it on the portal and verify "
              "against your own working."}, indent=2), file=sys.stderr)
        return 2

    filing_date = date.fromisoformat(a.filing_date) if a.filing_date else None
    taxes_paid = n(a.tds) + n(a.advance_tax) + n(a.self_assessment_tax)
    out = {"assessment_year": AY, "previous_year": PY,
           "governing_act": GOVERNING_ACT,
           "computed_by": "compute_tax.py",
           "residential_status": "resident",
           **({"presumptive_44ADA": {
               "gross_receipts": str(presumptive_receipts),
               "profit_taxed_at_slab": str(presumptive),
               "note": "[documented] Presumed at 50% and taxed at slab. This "
                       "engine does not "
                       "decide whether the profession is one s.44AA(1) notifies, "
                       "and s.44ADA is unavailable to a firm's partner for "
                       "remuneration. Form selection is reported per regime "
                       "after total income is computed; unobserved eligibility "
                       "conditions are not guessed."}}
              if presumptive else {}),
           "caveat": "Verify every rate against a primary source before relying "
                     "on this. Does not compute 234A/B/C interest, s.89 relief, "
                     "AMT, foreign tax credit, or house-property loss set-off."}

    regimes = ["new", "old"] if a.regime == "both" else [a.regime]
    try:
        for reg in regimes:
            r = compute(reg, n(a.salary), other_slab, special, hp, n(a.chapter_via),
                        age_band=a.age_band, nps_80ccd2=n(a.nps_80ccd2),
                        nps_salary=n(a.nps_80ccd2_salary), employer=a.employer,
                        family_pension=n(a.family_pension), lb=lb,
                        dividends=dividends, stcg_slab=stcg_slab)
            if presumptive_receipts > 0:
                r["return_form_guidance"] = return_form_guidance(
                    D(r["total_income_rounded_288A"]), stcg_slab)
            settle(r, taxes_paid, tds=n(a.tds), filing_date=filing_date,
                   due_date_category=due_date_category,
                   filing_section=a.filing_section, must_file=a.must_file)
            out[reg] = r
    except Refusal as e:
        print(json.dumps({"refused": str(e)}, indent=2), file=sys.stderr)
        return 2

    regime_choice = regime_choice_guidance(has_business_income)
    out["regime_election"] = regime_choice
    if len(regimes) == 2:
        dn, do = D(out["new"]["total_tax_rounded_288B"]), D(out["old"]["total_tax_rounded_288B"])
        out["recommendation"] = {
            "cheaper_regime": "new" if dn <= do else "old",
            "saving": str(abs(dn - do)),
            **regime_choice,
        }
    if a.summary:
        print(summarise(out))
    else:
        print(json.dumps(out, indent=2))
    return 0


def summarise(out: dict) -> str:
    regimes_shown = [r for r in ("new", "old") if r in out]
    """The half-dozen figures somebody actually reads, in plain lines.

    The JSON carries every intermediate step because a figure nobody can trace
    is a figure nobody should file. But a filer comparing two regimes wants six
    numbers, and making them find those in two hundred lines of JSON is how
    transcription errors get made."""
    money = lambda v: f"{D(str(v)):,.0f}"
    lines = [f"AY {out['assessment_year']} (FY {out['previous_year']}) — "
             f"resident individual, {out['governing_act']}"]
    if "presumptive_44ADA" in out:
        p = out["presumptive_44ADA"]
        lines.append(f"s.44ADA: {money(p['gross_receipts'])} of receipts, "
                     f"{money(p['profit_taxed_at_slab'])} presumed as profit")
    for regime in ("new", "old"):
        if regime not in out:
            continue
        r = out[regime]
        lines.append("")
        lines.append(f"  {regime} regime")
        lines.append(f"    total income (s.288A)        {money(r['total_income_rounded_288A']):>14}")
        lines.append(f"    tax, surcharge and cess      {money(r['total_tax_rounded_288B']):>14}")
        # The fee is read before the payable line, because a return with no tax
        # to pay can still carry one and "nothing to pay" must not be printed
        # over it. The keys are the engine's own — `fee_234F`, not `s234F`.
        fees = r.get("late_fees") or {}
        fee_234F = D(str(fees.get("fee_234F", 0) or 0))
        fee_234I = D(str(fees.get("fee_234I", 0) or 0))
        if "taxes_paid" in r:
            lines.append(f"    taxes already paid           {money(r['taxes_paid']):>14}")
            if D(r["net_payable"]) > 0:
                lines.append(f"    NET PAYABLE (s.288B)         {money(r['net_payable']):>14}")
            elif D(r["refund_due"]) > 0:
                lines.append(f"    refund due (s.288B)          {money(r['refund_due']):>14}")
            elif fee_234F > 0 or fee_234I > 0:
                lines.append("    no tax to pay — but a late fee is due, below")
            else:
                lines.append("    nothing to pay, nothing to refund")
        if fee_234F > 0:
            lines.append(f"    late filing fee s.234F       {money(fees['fee_234F']):>14}"
                         f"  ({fees.get('fee_234F_basis', 'late return')})")
        if fee_234I > 0:
            lines.append(f"    late fee s.234I              {money(fees['fee_234I']):>14}")
            # The 234I basis records a drafting conflict and which reading this
            # engine follows. A bare figure in summary mode would present a
            # contested number as settled.
            if basis := fees.get("fee_234I_basis"):
                lines.append(f"      s.234I basis: {basis}")
        if (fee_234F > 0 or fee_234I > 0) and "taxes_paid" in r:
            # Part B-TTI settles tax and fee together, so the fee is not a
            # footnote to the payable line — it changes it. A refund of 10,000
            # against a 5,000 fee is a 5,000 refund, and where the fee exceeds
            # the credits the return moves from refund to payable entirely.
            # `net_payable` in the JSON is the pre-fee figure and stays that way;
            # this is the settlement a filer actually transfers.
            settlement = (D(r["net_payable"]) - D(r["refund_due"])
                          + fee_234F + fee_234I)
            # An updated return pays the fee as part of s.140B, together with
            # additional tax of 25/50/60/70 per cent by band that this engine
            # does not compute. A settlement printed without it is not a smaller
            # number than the truth, it is a different kind of number — so it is
            # labelled a subtotal and never "TO PAY".
            incomplete = "s.140B" in (fees.get("fee_234F_basis") or "")
            if incomplete:
                lines.append(f"    subtotal, tax and fee only   {money(settlement):>14}")
                lines.append("    NOT the amount to pay — an updated return u/s "
                             "139(8A) also carries s.140B additional tax of "
                             "25/50/60/70 per cent by band, which this engine "
                             "does not compute")
            elif settlement > 0:
                # s.234A/B/C interest is not computed here either, so even the
                # ordinary case is a floor rather than a transferable figure.
                lines.append(f"    subtotal, tax and fee only   {money(settlement):>14}")
                lines.append("    before s.234A/234B/234C interest, which this "
                             "engine does not compute — read it off the portal "
                             "before paying")
            elif settlement < 0:
                lines.append(f"    refund, before interest      {money(-settlement):>14}")
                lines.append("    s.234A/234B/234C interest is NOT computed here "
                             "and reduces a refund as readily as it raises a "
                             "payment — this is not the final figure")
            else:
                lines.append("    tax and fee cover the credits exactly, before "
                             "s.234A/234B/234C interest, which this engine does "
                             "not compute")
        if r.get("advance_tax_was_due_s208"):
            lines.append("    advance tax was due u/s 208 — s.234B and s.234C "
                         "interest is NOT computed here")
        form = r.get("return_form_guidance")
        if form:
            if form["recommended_form"]:
                lines.append(f"    return form                    {form['recommended_form']:>14} "
                             "(ITR-4 unavailable above 50 lakh total income)")
            else:
                lines.append("    return form              undetermined — confirm director, "
                             "unlisted-share and foreign-asset/income status")
    rec = out.get("recommendation")
    if rec:
        lines.append("")
        lines.append(f"  cheaper: {rec['cheaper_regime']} regime, by "
                     f"{money(rec['saving'])}")
        # The recommendation compares TAX. A late fee is tiered on total income,
        # so two regimes can sit on opposite sides of the 5,00,000 threshold and
        # carry different fees on identical tax — which can reverse the ordering
        # the line above just gave. Rather than silently re-rank the regimes on a
        # figure the JSON does not carry, say that the comparison excludes fees
        # and show them whenever they differ.
        fees_by_regime = {
            regime: (D(str((out[regime].get("late_fees") or {}).get("fee_234F", 0) or 0))
                     + D(str((out[regime].get("late_fees") or {}).get("fee_234I", 0) or 0)))
            for regime in ("new", "old") if regime in out}
        if len(set(fees_by_regime.values())) > 1:
            shown = ", ".join(f"{r} {money(f)}" for r, f in fees_by_regime.items())
            lines.append(f"  that compares TAX only. [documented] The late fee is "
                         f"tiered on total income, and the two regimes reach "
                         f"different totals — {shown}. [inferred] The difference "
                         f"can outweigh the tax saving above, so compare the two "
                         f"settlement lines rather than this one.")
    # The election is printed for every run, not only a two-regime comparison:
    # someone asking for the old regime alone is exactly who needs the deadline.
    election = out.get("regime_election")
    if election:
        if not rec:
            lines.append("")
        lines.append("  " + election["old_regime_election"])
    # A global note, not a regime's: it describes the head of income, which is
    # the same whichever regime is chosen. Rendered after both blocks it read
    # as though it belonged to the one printed last.
    for reg in regimes_shown:
        gains = out[reg].get("capital_gains_at_slab_rates")
        if gains and D(gains) != 0:
            lines.append("")
            lines.append(f"  of which capital gains taxed at slab: "
                         f"{money(gains)} — [documented] a capital gain goes on "
                         f"Schedule CG however it is taxed, so this does not "
                         f"belong in Other Sources")
            break
    lines.append("")
    lines.append("  " + out["caveat"])
    return "\n".join(lines)


# ---------------------------------------------------------------- golden tests
# s.44ADA: 50% of gross receipts, ceiling 50 lakh, or 75 lakh where cash
# receipts are 5% or less. Sourced to references/forms-itr1-itr3-itr4.md,
# "Presumptive rates and ceilings".
PRESUMPTIVE_44ADA_RATE = D("0.50")
PRESUMPTIVE_44ADA_CEILING = D("5000000")
PRESUMPTIVE_44ADA_CEILING_LOW_CASH = D("7500000")
ITR4_TOTAL_INCOME_LIMIT = D("5000000")


def resolve_due_date_category(requested: str | None,
                              has_business_income: bool) -> str:
    """Use the facts the engine has, while preserving explicit user input."""
    if has_business_income is True and requested == "no-business":
        raise Refusal(
            "--due-date-category no-business conflicts with the presumptive "
            "professional receipts supplied. Explanation 2(c) to s.139(1) "
            "places a business or professional filer not liable to audit in "
            "business-no-audit. Remove the explicit category to derive that "
            "date, or pass the applicable audit category if one applies.")
    if requested is not None:
        return requested
    if has_business_income is None:
        raise Refusal(
            "the due date cannot be chosen without knowing whether there is "
            "any business or professional income: with it and no s.44AB audit "
            "the s.139(1) date is 31 August 2026, without it 31 July 2026, and "
            "the difference decides s.234F and whether a loss can be carried "
            "forward. This engine has no argument for 44AD, 44AE, intraday, "
            "F&O or partner remuneration, so an empty presumptive figure is not "
            "evidence of absence. Pass --business-income yes or no, or name the "
            "period directly with --due-date-category.")
    return "business-no-audit" if has_business_income else "no-business"


def _business_income_state(declared, presumptive_receipts):
    """True, False, or None when it has not been established.

    Presumptive receipts prove presence. Their absence proves nothing, because
    every other kind of business income reaches this engine, if at all, through
    --other-slab-income."""
    if presumptive_receipts > 0:
        return True
    if declared in ("yes", True):
        return True
    if declared in ("no", False):
        return False
    return None


def regime_choice_guidance(has_business_income) -> dict:
    """Explain the old-regime election without asserting Form 10-IEA broadly.

    `has_business_income` is True, False, or None for "not established here".

    The test is the *income*, never the form number. An ITR-3 filer with no
    current business or professional income elects in the return like anyone
    else, and 44AD, 44AE, intraday, F&O and partner remuneration are business
    income that this engine has no argument for — routed through
    --other-slab-income they are invisible to it. Inferring their absence from
    an empty --presumptive-44ada-receipts told a filer no Form 10-IEA was
    needed, which can cost them the old regime for the year. When it has not
    been established, this says so instead."""
    if has_business_income is None:
        return {
            "business_or_professional_income_present": None,
            "form_10IEA_required": None,
            "old_regime_election": (
                "[documented] Whether Form 10-IEA is required turns on whether "
                "there is any business or professional income, not on which ITR "
                "number is filed: with it, the form must be filed before the "
                "due date and the choice becomes sticky; without it, the old "
                "regime is chosen in the return itself as an annual choice. "
                "This engine was not told which applies — it has no argument "
                "for 44AD, 44AE, intraday, F&O or partner remuneration, so an "
                "empty presumptive figure is not evidence of absence. Pass "
                "--business-income yes or no. Either way the election expires "
                "with the s.139(1) due date, because a belated return is "
                "locked into the new regime."),
        }
    if has_business_income:
        return {
            "business_or_professional_income_present": True,
            "form_10IEA_required": True,
            "old_regime_election": (
                "[documented] The old regime requires Form 10-IEA filed before "
                "the s.139(1) due date, because business or professional income "
                "is present — the test is the income, not the ITR number. The "
                "choice then becomes sticky for future years."),
        }
    return {
        "business_or_professional_income_present": False,
        "form_10IEA_required": False,
        "old_regime_election": (
            "[documented] Form 10-IEA is not required, because there is no "
            "business or professional income — the test is the income, not the "
            "ITR number. Choose the old regime in the return itself, as a free "
            "annual choice. It still expires with the s.139(1) due date: a "
            "belated return is locked into the new regime."),
    }


def return_form_guidance(total_income: D, schedule_cg_income: D = D(0)) -> dict:
    """Check the ITR-4 fact known here and name the facts not available here."""
    within_limit = total_income <= ITR4_TOTAL_INCOME_LIMIT
    # ITR-4 has no Schedule CG. A capital gain that has to be reported there
    # rules the form out regardless of the presumptive position or the income
    # limit, and this is a fact the engine now knows rather than one it has to
    # ask the filer about.
    if schedule_cg_income:
        return {
            "status": "ITR-4 unavailable",
            "recommended_form": "ITR-3",
            "itr4_total_income_limit_satisfied": within_limit,
            "basis": ("[documented] ITR-4 carries no Schedule CG, and a "
                      "capital gain taxed at slab still has to be reported "
                      "there. With presumptive business or professional "
                      "income alongside it, the return is ITR-3."),
            "conditions_engine_cannot_check": [],
        }
    confirmations = [
        "the filer is not a company director",
        "the filer did not hold unlisted shares at any time",
        "the filer has no foreign assets or foreign income",
    ]
    if not within_limit:
        status = "ITR-4 unavailable"
        recommended = "ITR-3"
        basis = ("[documented] Total income exceeds the 50 lakh ITR-4 limit; "
                 "business or professional income must therefore be filed in "
                 "ITR-3 for this resident individual.")
    else:
        status = "undetermined — filer confirmation required"
        recommended = None
        basis = ("[documented] Total income is within the 50 lakh ITR-4 limit, "
                 "but the engine cannot observe every eligibility condition.")
    return {
        "status": status,
        "recommended_form": recommended,
        "itr4_total_income_limit_satisfied": within_limit,
        "basis": basis,
        "conditions_engine_cannot_check": confirmations,
    }


def presumptive_44ada(receipts, declared=None, cash_within_5pc: bool = False):
    """Profit presumed under s.44ADA, or a refusal saying why not.

    The engine will not decide eligibility. It applies the rate and the ceiling
    and refuses everything else: whether the activity is a notified profession
    under s.44AA(1), whether the cash-receipts condition actually holds, and
    whether declaring below the presumption is worth the s.44AA books and audit
    that follow. Those are the parts that cost money to get wrong."""
    if receipts < 0:
        raise Refusal(
            f"negative gross receipts of {receipts:,.0f} are invalid. A sign "
            "error must not silently remove presumptive professional income; "
            "correct the receipts and re-run.")
    if receipts == 0:
        if declared is not None and declared != 0:
            raise Refusal(
                f"a presumptive profit of {declared:,.0f} was declared with no "
                "gross receipts. s.44ADA presumes a profit *from* receipts, so "
                "there is nothing for it to be 50% of. Give the receipts, or "
                "put the figure in --other-slab-income if it is not "
                "presumptive income at all.")
        return D(0)
    ceiling = (PRESUMPTIVE_44ADA_CEILING_LOW_CASH if cash_within_5pc
               else PRESUMPTIVE_44ADA_CEILING)
    if receipts > ceiling:
        raise Refusal(
            f"gross receipts of {receipts:,.0f} exceed the s.44ADA ceiling of "
            f"{ceiling:,.0f}"
            + ("" if cash_within_5pc else
               " — the ceiling rises to 75,00,000 only where cash receipts are "
               "5% or less of turnover, which this engine cannot verify from "
               "the figures. Pass --cash-receipts-within-5pc if the books show "
               "it")
            + ". Above the ceiling the presumptive scheme is unavailable and "
              "the return needs actual profit and loss under ITR-3.")
    presumed = receipts * PRESUMPTIVE_44ADA_RATE
    if declared is None:
        return presumed
    if declared < presumed:
        raise Refusal(
            f"a declared profit of {declared:,.0f} is below the 50% presumption "
            f"of {presumed:,.0f}. That is allowed, but it is not s.44ADA: it "
            "makes books mandatory under s.44AA and brings s.44AB audit into "
            "play once total income exceeds the basic exemption limit. This "
            "engine will not compute a figure that carries those consequences "
            "silently — file on actual profit under ITR-3.")
    return declared


ARG_TO_KEY = (("111A", "stcg_111a"), ("112A", "ltcg_112a"), ("112", "ltcg_112"),
              ("112_LB", "ltcg_112_landbuilding"), ("115BB", "winnings_115bb"),
              ("115BBJ", "winnings_115bbj"), ("115BBH", "vda_115bbh"))
SLAB_KEYS = ("savings_interest", "fd_interest", "refund_interest",
             "dividends", "other_slab_income", "stcg_slab")


def settle(result: dict, taxes_paid, tds=None, filing_date=None,
           due_date_category="no-business", filing_section="139(1)",
           must_file=False) -> dict:
    """Taxes paid against tax due, and what is left either way.

    Lifted out of main() so a golden case can pin it. The net payable on a real
    return is the last number anybody looks at and the only one they remember,
    and it was the one figure in this engine no test could reach."""
    net = D(result["total_tax_rounded_288B"]) - taxes_paid
    result["taxes_paid"] = str(taxes_paid)
    result["net_payable"] = str(r10(net)) if net > 0 else "0"
    result["refund_due"] = "0" if net > 0 else str(r10(-net))
    # s.209(1)(d) reduces the advance-tax estimate by TDS/TCS only. Netting off
    # advance tax or self-assessment tax already paid would make the flag read
    # False exactly for the taxpayers who complied.
    result["advance_tax_was_due_s208"] = bool(
        D(result["total_tax_rounded_288B"]) - (taxes_paid if tds is None else tds)
        >= ADVANCE_TAX_THRESHOLD)
    result["late_fees"] = late_fees(D(result["total_income"]), filing_date,
                                    due_date_category, filing_section,
                                    D(result["basic_exemption_limit"]), must_file)
    # [documented] The proviso to s.139(8A) bars an updated return that results
    # in a refund or increases one. Refuse here rather than in the summary
    # renderer: a caller reading the JSON would otherwise get exit 0 and a
    # refund_due it is not entitled to claim, and the whole point of the engine
    # refusing is that a refusal survives whichever output mode is asked for.
    fees = result["late_fees"]
    # [documented] After 31-12-2026 neither an original nor a belated return can
    # be filed for AY 2026-27, so a return dated later under any section other
    # than 139(5) is an updated return. Read that from the DATE AND SECTION, not
    # from whether a fee basis mentioning s.140B happened to be produced: a
    # filer at or below the basic exemption limit takes late_fees()'s
    # non-liable branch, generates no such basis, and would slip the guard.
    # The section, when the filer states it, is the direct evidence; the date is
    # the inference to fall back on. Reading the section only as an EXCLUSION —
    # which is what this did — meant an explicit `--filing-section 139(8A)` with
    # an in-window date, or with no date at all, walked straight past a guard
    # named for that very section.
    is_updated = (filing_section == "139(8A)"
                  or (filing_date is not None and filing_date > BELATED_LAST
                      and filing_section != "139(5)"))
    if (filing_section == "139(8A)" and filing_date is not None
            and filing_date < UPDATED_FIRST):
        # Refuse the contradiction itself. Falling through would refuse the same
        # input for claiming a refund, which is a conclusion about a return that
        # cannot be furnished on that date at all — right outcome, wrong reason,
        # and the reason is what a filer acts on.
        raise Refusal(
            f"a return u/s 139(8A) dated {filing_date.isoformat()} is not a "
            "return that exists. [documented] An updated return may be "
            f"furnished only from {UPDATED_FIRST.isoformat()} for AY 2026-27, "
            f"because s.139(5) runs to {REVISED_LAST.isoformat()} and s.139(8A) "
            "opens after it. [inferred] Either the section is wrong for this "
            "date — 139(1), 139(4) and 139(5) each have their own window — or "
            "the date is wrong for this section.")
    if is_updated and filing_date is None:
        # Without a date late_fees() computes nothing, so the fee reads as zero
        # and a small pre-fee refund looks like a barred refund claim. It may
        # not be one: a s.234F fee can absorb the refund entirely. Refuse for
        # the reason that is true — the date is missing — rather than for a
        # conclusion the missing date makes unreachable.
        raise Refusal(
            "an updated return u/s 139(8A) was stated with no filing date. "
            "[documented] The s.234F fee and the s.140B additional tax both "
            "turn on when the return is filed, and the proviso to s.139(8A) "
            "bars an updated return that results in a refund — so whether "
            "there is a valid return here cannot be decided until the fee is "
            "known. [inferred] Pass --filing-date. A pre-fee refund is not "
            "evidence of a barred refund: the fee can absorb it.")
    if is_updated:
        settlement = (D(result.get("net_payable", 0)) - D(result.get("refund_due", 0))
                      + D(str(fees.get("fee_234F", 0) or 0))
                      + D(str(fees.get("fee_234I", 0) or 0)))
        if settlement < 0:
            raise Refusal(
                f"credits exceed tax and fee by {-settlement:,.0f}, so this "
                "would be an updated return claiming a refund. [documented] The "
                "proviso to s.139(8A) bars an updated return that results in a "
                "refund or increases one, so there is no valid return to "
                "compute here. [documented] After 31-12-2026 neither an "
                "original nor a belated return can be filed for AY 2026-27. "
                "[inferred] Check the filing date and the section; a refund "
                "claim after that point needs a s.119(2)(b) condonation order "
                "rather than a return.")
    return result


def _run_case(kw: dict, regime: str = "new") -> dict:
    n = lambda s: D(str(s).replace(",", ""))
    special = {k: n(kw.get(arg, 0)) for k, arg in ARG_TO_KEY if n(kw.get(arg, 0)) != 0}
    other = sum((n(kw.get(k, 0)) for k in SLAB_KEYS), D(0))
    lb = ({"indexed_gain": n(kw["ltcg_112_landbuilding_indexed_gain"])}
          if "ltcg_112_landbuilding_indexed_gain" in kw else None)
    presumptive_receipts = n(kw.get("presumptive_44ada_receipts", 0))
    has_business_income = _business_income_state(
        kw.get("business_income"), presumptive_receipts)
    other += presumptive_44ada(
        presumptive_receipts,
        n(kw["presumptive_44ada_profit"]) if "presumptive_44ada_profit" in kw else None,
        bool(kw.get("cash_receipts_within_5pc", False)))
    due_date_category = (
        resolve_due_date_category(kw.get("due_date_category"),
                                  has_business_income)
        if kw.get("filing_date") or kw.get("due_date_category")
        else "no-business")
    result = compute(regime, n(kw.get("salary", 0)), other, special,
                   n(kw.get("house_property", 0)), n(kw.get("chapter_via", 0)),
                   age_band=kw.get("age_band", "below60"),
                   nps_80ccd2=n(kw.get("nps_80ccd2", 0)),
                   nps_salary=n(kw.get("nps_80ccd2_salary", 0)),
                   employer=kw.get("employer", "other"),
                   family_pension=n(kw.get("family_pension", 0)),
                   lb=lb, dividends=n(kw.get("dividends", 0)),
                   stcg_slab=n(kw.get("stcg_slab", 0)))
    if presumptive_receipts > 0:
        result["return_form_guidance"] = return_form_guidance(
            D(result["total_income_rounded_288A"]), n(kw.get("stcg_slab", 0)))
    # The election guidance is part of what a golden case must be able to pin,
    # so it travels with the computation rather than only with the CLI output.
    result.update(regime_choice_guidance(has_business_income))
    filing_inputs = ("tds", "advance_tax", "self_assessment_tax", "filing_date",
                     "due_date_category", "filing_section", "must_file")
    if any(k in kw for k in filing_inputs):
        settle(result,
               n(kw.get("tds", 0)) + n(kw.get("advance_tax", 0))
               + n(kw.get("self_assessment_tax", 0)),
               tds=n(kw.get("tds", 0)),
               filing_date=(date.fromisoformat(kw["filing_date"])
                            if kw.get("filing_date") else None),
               due_date_category=due_date_category,
               filing_section=kw.get("filing_section", "139(1)"),
               must_file=bool(kw.get("must_file", False)))
    return result


CASES = [
    # (label, kwargs, regime, field, expected)
    ("synthetic ITR-2: salary 16.6L + 4,629 interest + Rs 6 u/s 115BBJ",
     dict(salary="1660000", savings_interest="4100", refund_interest="529",
          winnings_115bbj="6"), "new", "total_tax_rounded_288B", "123180"),
    ("salary only, at the 87A ceiling — 12,00,000 total income",
     dict(salary="1275000"), "new", "total_tax_rounded_288B", "0"),
    ("salary only, just above the ceiling — marginal relief bites",
     dict(salary="1285000"), "new", "total_tax_rounded_288B", "10400"),
    ("no income", dict(), "new", "total_tax_rounded_288B", "0"),
    ("112A exemption: 1,25,000 LTCG is fully exempt",
     dict(ltcg_112a="125000"), "new", "total_tax_rounded_288B", "0"),
    ("112A above the exemption: 2,25,000 -> 1,00,000 at 12.5%",
     dict(salary="1200000", ltcg_112a="225000"), "new", "total_tax_rounded_288B", "67600"),
    ("new regime: 87A never reaches special-rate income",
     dict(salary="500000", winnings_115bbj="100000"), "new",
     "total_tax_rounded_288B", "31200"),
    # --- corrections verified 2026-07-28 ------------------------------------
    ("old regime: 87A DOES reach s.111A tax (no bar in s.111A)",
     dict(salary="300000", stcg_111a="200000", chapter_via="0"), "old",
     "rebate_87A", "12500.00"),
    ("old regime: 87A does NOT reach s.112A tax (s.112A(6))",
     dict(salary="300000", ltcg_112a="325000"), "old", "rebate_87A", "0.00"),
    ("s.112 land/building: 20% indexed beats 12.5% unindexed",
     dict(salary="1000000", ltcg_112_landbuilding="1000000",
          ltcg_112_landbuilding_indexed_gain="400000"), "new",
     "tax_at_special_rates", "80000.00"),
    ("s.112 land/building: 12.5% unindexed wins when indexation adds little",
     dict(salary="1000000", ltcg_112_landbuilding="1000000",
          ltcg_112_landbuilding_indexed_gain="900000"), "new",
     "tax_at_special_rates", "125000.00"),
    ("basic exemption absorbed against 111A when other income is nil",
     dict(stcg_111a="500000"), "new", "total_tax_rounded_288B", "20800"),
    ("80CCD(2) survives the new regime: 14% of salary",
     dict(salary="1500000", nps_80ccd2="210000", nps_80ccd2_salary="1500000"),
     "new", "chapter_via_deductions", "210000.00"),
    ("80CCD(2) old regime, private employer: capped at 10%",
     dict(salary="1500000", nps_80ccd2="210000", nps_80ccd2_salary="1500000"),
     "old", "deduction_80CCD2", "150000.00"),
    ("family pension: s.57(iia) capped at 25,000 under the new regime",
     dict(family_pension="300000"), "new", "family_pension_deduction_57iia", "25000.00"),
    ("old regime, 80+: basic exemption is 5,00,000",
     dict(salary="550000", age_band="80plus"), "old", "total_tax_rounded_288B", "0"),
    # --- surcharge, added after an adversarial review found relief self-cancelling
    ("surcharge marginal relief at 50L: 1,11,000 gross becomes 70,000",
     dict(salary="5175000"), "new", "surcharge", "70000.00"),
    ("surcharge marginal relief at 50L: total tax",
     dict(salary="5175000"), "new", "total_tax_rounded_288B", "1227200"),
    ("surcharge well above a threshold is not relieved at all",
     dict(salary="8075000"), "new", "surcharge", "198000.00"),
    ("basic exemption is absorbed into 112 before 112A, which has its own exemption",
     dict(ltcg_112a="400000", ltcg_112="400000"), "new",
     "total_tax_rounded_288B", "35750"),
    ("s.112 land/building: the absorbed exemption reduces the indexed gain too",
     dict(ltcg_112_landbuilding="1000000",
          ltcg_112_landbuilding_indexed_gain="500000"), "new",
     "total_tax_rounded_288B", "20800"),
]


def self_test() -> int:
    failed = []
    for label, kw, regime, field, expected in CASES:
        got = _run_case(kw, regime)
        actual = str(got[field])
        ok = actual == expected
        print(f"{'PASS' if ok else 'FAIL'}  [{regime}] {label}")
        if not ok:
            print(f"      {field}: expected {expected}, got {actual}")
            failed.append(label)

    # Refusals. Each of these silently produced a wrong figure at some point.
    REFUSALS = [
        ("s.112 land/building without the indexed gain",
         dict(ltcg_112_landbuilding="1000000")),
        ("a negative special-rate amount (capital loss set-off)",
         dict(stcg_111a="-200000", salary="3075000")),
        ("s.115BBE unexplained credits, which carry a flat 25% surcharge",
         dict(other_slab_income="0", salary="1000000")),
        ("s.80CCD(2) without the basic+DA salary the cap is a percentage of",
         dict(salary="1500000", nps_80ccd2="210000")),
        ("negative s.44ADA gross receipts",
         dict(presumptive_44ada_receipts="-123456")),
    ]
    for label, kw in REFUSALS:
        if "115BBE" in label:
            try:
                compute("new", D(0), D(0), {"115BBE": D(3000000)}, D(0), D(0))
                failed.append(f"engine did not refuse {label}")
                print(f"FAIL  refuses {label}")
                continue
            except Refusal:
                print(f"PASS  refuses {label}")
                continue
        try:
            _run_case(kw)
            failed.append(f"engine did not refuse {label}")
            print(f"FAIL  refuses {label}")
        except Refusal:
            print(f"PASS  refuses {label}")

    no_business_choice = regime_choice_guidance(False)
    if (no_business_choice["business_or_professional_income_present"] is not False
            or no_business_choice["form_10IEA_required"] is not False
            or "return itself" not in no_business_choice["old_regime_election"]
            or "annual choice" not in no_business_choice["old_regime_election"]):
        failed.append("salary-only regime guidance asserted Form 10-IEA")
        print("FAIL  salary-only old-regime choice stays inside the return")
    else:
        print("PASS  salary-only old-regime choice stays inside the return")

    business_choice = regime_choice_guidance(True)
    if (business_choice["business_or_professional_income_present"] is not True
            or business_choice["form_10IEA_required"] is not True
            or "Form 10-IEA" not in business_choice["old_regime_election"]):
        failed.append("business-income regime guidance omitted Form 10-IEA")
        print("FAIL  business-income old-regime choice requires Form 10-IEA")
    else:
        print("PASS  business-income old-regime choice requires Form 10-IEA")

    # Invariant: in the new regime, more income never means less total tax. The
    # sweep runs past every surcharge threshold — an earlier version stopped at
    # 30L and missed a defect that zeroed surcharge above 50L.
    prev, broke = D(-1), False
    for inc in range(0, 600_000_000, 500_000):
        tt = D(compute("new", D(inc), D(0), {}, D(0), D(0))["total_tax_and_cess"])
        if tt < prev:
            failed.append(f"monotonicity broken at salary {inc}")
            broke = True
            break
        prev = tt
    if not broke:
        print("PASS  monotonic: more salary never yields less tax (0 to 60cr, step 5L)")

    # Invariant: surcharge marginal relief never leaves the taxpayer better off
    # for crossing a threshold, and never wipes surcharge out entirely.
    for band in (D(5000000), D(10000000), D(20000000), D(50000000)):
        below = D(compute("new", band + STD_DED_NEW, D(0), {}, D(0), D(0))["total_tax_and_cess"])
        above = D(compute("new", band + STD_DED_NEW + D(500000), D(0), {},
                          D(0), D(0))["total_tax_and_cess"])
        if above < below:
            failed.append(f"tax falls when crossing the {band} surcharge threshold")
            break
    else:
        print("PASS  crossing a surcharge threshold never reduces total tax")

    # Invariant: cess is exactly 4% of tax after rebate and surcharge.
    r = compute("new", D(2500000), D(0), {"111A": D(100000)}, D(0), D(0))
    lhs = D(r["cess_4pc"])
    rhs = p2((D(r["tax_on_slab_income"]) + D(r["tax_at_special_rates"])
              - D(r["rebate_87A"]) + D(r["surcharge"])) * CESS)
    if lhs != rhs:
        failed.append(f"cess not 4%: {lhs} vs {rhs}")
    else:
        print("PASS  cess is exactly 4% of (tax - rebate + surcharge)")

    # Invariant: new-regime surcharge never exceeds 25%.
    r = compute("new", D(80_000_000), D(0), {}, D(0), D(0))
    if D(r["surcharge_detail"]["rate"]) > SURCHARGE_CAP_NEW:
        failed.append("new-regime surcharge exceeded 25%")
    else:
        print("PASS  new-regime surcharge caps at 25% (no 37% band)")

    print()
    if failed:
        print(f"{len(failed)} FAILURE(S):")
        for f in failed:
            print("  -", f)
        return 1
    print(f"All {len(CASES)} golden cases, {len(REFUSALS)} refusals, "
          "2 regime-choice checks and 3 invariants pass.")
    return 0


def run_golden(path: str) -> int:
    """Run the data-driven case file so contributors can add cases without
    touching Python. See evals/golden/README.md."""
    if not os.path.exists(path):
        print(f"golden file not found: {path}", file=sys.stderr)
        return 2
    with open(path) as fh:
        doc = json.load(fh)
    if doc.get("assessment_year") != AY:
        print(f"golden file is for AY {doc.get('assessment_year')}, engine is AY {AY}",
              file=sys.stderr)
        return 2
    failed = 0
    for case in doc["cases"]:
        cid, regime = case["id"], case.get("regime", "new")
        if case.get("expect", {}).get("outcome") == "refuse":
            try:
                _run_case(case["input"], regime)
                print(f"FAIL  {cid}: expected a refusal, got a computation")
                failed += 1
            except Refusal as e:
                miss = [m for m in case["expect"].get("must_mention", [])
                        if m.lower() not in str(e).lower()]
                if miss:
                    print(f"FAIL  {cid}: refusal did not mention {miss}")
                    failed += 1
                else:
                    print(f"PASS  {cid} (refused, as required)")
            continue
        got = _run_case(case["input"], regime)

        def value_at_path(path):
            value = got
            for part in path.split("."):
                if not isinstance(value, dict) or part not in value:
                    return None
                value = value[part]
            return value

        bad = [(k, v, str(value_at_path(k))) for k, v in case["expect"].items()
               if k not in ("outcome", "must_mention", "form",
                            "schedules_required", "schedules_forbidden")
               and str(value_at_path(k)) != str(v)]
        if bad:
            failed += 1
            print(f"FAIL  {cid}")
            for k, want, actual in bad:
                print(f"      {k}: expected {want}, got {actual}")
        else:
            print(f"PASS  {cid}")
    print()
    print(f"{len(doc['cases']) - failed}/{len(doc['cases'])} golden cases pass.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
