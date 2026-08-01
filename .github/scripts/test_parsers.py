#!/usr/bin/env python3
"""Run the parsers against the committed synthetic fixtures.

Every fixture is invented. Scrip names and ISINs are real because they are
public market data; the quantities, prices and dates are not anybody's.

Assertions here are deliberately exact. An earlier version of this file used
superset and fail-open tests, passed cleanly, and missed eight defects that each
produced a wrong tax figure — a section leaking into the previous bucket, real
scrip names deleted as total rows, subtotals counted as data, a decoy column
poisoning a whole bucket. Every case below reproduces one of those.
"""
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILL = os.path.join(ROOT, "skills", "itr-filing-copilot")
SCRIPTS = os.path.join(SKILL, "scripts")
FIXTURES = os.path.join(SKILL, "evals", "fixtures")

failures = []


def check(condition, message):
    print(f"{'PASS' if condition else 'FAIL'}  {message}")
    if not condition:
        failures.append(message)


def run(script, *args, expect_code=None):
    proc = subprocess.run([sys.executable, os.path.join(SCRIPTS, script), *args],
                          capture_output=True, text=True)
    if expect_code is not None and proc.returncode != expect_code:
        failures.append(f"{script} exited {proc.returncode}, expected {expect_code}")
        print(proc.stderr[:2000])
    return proc


def parse(*files, code=0):
    proc = run("parse_capital_gains.py", *files, "--rows", expect_code=code)
    return json.loads(proc.stdout or proc.stderr)


def load_ci_script(name):
    path = os.path.join(ROOT, ".github", "scripts", name)
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------- a normal broker statement
data = parse(os.path.join(FIXTURES, "zerodha_tax_pnl_synthetic.xlsx"))
buckets = {k: (v["rows"], v["gain"]) for k, v in data["buckets"].items()}

check(data["sources"][0]["detected"] == "zerodha", "broker detected from the workbook")
check(buckets == {"speculative": (2, 120.0), "111A": (2, 6150.0),
                  "112A": (2, 117400.0), "dividend": (2, 2300.0),
                  "fno": (2, -9200.0)},
      f"every bucket exact, nothing extra: {buckets}")
check(list(data["needs_confirmation"]) == ["mf_unknown"],
      "an unlabelled mutual fund is queried, not guessed")

# Schedule CG item F wants the five windows for every gain, and they are a fact
# about sale dates that does not wait on the classification question. Withholding
# them until it is answered forces hand arithmetic on the one output SKILL.md
# calls the most common way a correct ITR-2 fails validation.
check(all("quarterly" in e for e in data["needs_confirmation"].values()),
      "an unresolved bucket still carries its quarterly timing split")

# Table F wants figures net of set-off, equal to BFLA, and rejects negatives.
# What this parser knows is dates and gross figures, so what it emits is timing.
check(all("fill Table F last, from BFLA" in e.get("quarterly_basis", "")
          and "NET of current-year" in e.get("quarterly_basis", "")
          for name, e in list(data["buckets"].items())
                       + list(data["needs_confirmation"].items())
          if "quarterly" in e and name != "dividend"),
      "every published capital-gains split says it is gross timing, not Table F input")

# A dividend is Other Sources. Handing it the Table F and BFLA guidance tells a
# reader to run set-off machinery that has nothing to do with it.
_div = data["buckets"]["dividend"]
check("Schedule OS" in _div["quarterly_basis"]
      and "EX-DATE" in _div["quarterly_basis"]
      and "have nothing to do with it" in _div["quarterly_basis"],
      "the dividend split carries a Schedule OS basis, not Table F guidance")
# Schedule OS wants the quarter of receipt, and a dividend is received after its
# ex-date — so a row either side of a 15th is in the wrong window.
check("actual RECEIPT" in _div["quarterly_basis"]
      and "must be moved" in _div["quarterly_basis"],
      "the dividend basis says an ex-date is not the receipt date")
check(any("NET of current-year" in c and "GROSS" not in c
          for c in data["checks"]),
      "the checks correct the Table F claim rather than repeating it")

# ...but only where the answer changes the rate or the head. A buyback on or
# after 1 October 2024 turns its consideration into a deemed dividend and its
# capital result into a loss of the whole cost, so the broker's gain is not what
# Schedule CG will carry. Publishing a split of a figure about to change is a
# confident wrong working, which is worse than none.
_adv = parse(os.path.join(FIXTURES, "adversarial_layout_synthetic.xlsx"))
_needs = _adv["needs_confirmation"]
for _bucket in ("buyback", "landbuilding_unknown"):
    check("quarterly" not in _needs[_bucket]
          and "changes the amount" in _needs[_bucket].get("quarterly_withheld", ""),
          f"{_bucket} withholds its windows until the amount is settled")
    # Nothing here accepts the answer, so telling the reader to re-run is advice
    # that cannot work.
    check("re-running it will report the same bucket"
          in _needs[_bucket]["quarterly_withheld"],
          f"{_bucket} does not promise that re-running will change it")
# A named non-equity heading leaves only the s.50AA rate question open, and its
# windows are the s.234C answer Schedule BFLA cannot give. They publish, with a
# basis saying they are gross timing rather than an amount for any schedule.
check("quarterly" in _needs["nonequity_unknown"]
      and "quarterly_basis" in _needs["nonequity_unknown"],
      "a named non-equity heading publishes its windows with a timing basis")
check("quarterly" not in _needs["unlisted_unknown"],
      "unlisted shares withhold their windows until s.50CA consideration is settled")
check(all(tag in _needs["nonequity_unknown"]["why_it_matters"]
          for tag in ("[observed]", "[documented]", "[inferred]")),
      "the non-equity resolver tags each non-obvious claim")
_unlisted_summary = run("parse_capital_gains.py",
                        os.path.join(FIXTURES, "adversarial_layout_synthetic.xlsx"),
                        "--summary")
check("unlisted_unknown:" in _unlisted_summary.stdout
      and "Amount/timing withheld:" in _unlisted_summary.stdout
      and "not a Schedule CG amount yet" in _unlisted_summary.stdout,
      "summary retains the unlisted-share amount withholding condition")

# An unreadable gain does not make an independent amount-sensitive condition
# disappear. A preparer needs both reasons before deciding what to obtain.
_unlisted_unread_dir = tempfile.mkdtemp()
_unlisted_unread_path = os.path.join(_unlisted_unread_dir, "unlisted_unread.csv")
with open(_unlisted_unread_path, "w", encoding="utf-8") as fh:
    fh.write("Unlisted Equity Shares - Long Term\n"
             "Symbol,ISIN,Entry Date,Exit Date,Quantity,Sell Value,Profit\n"
             "PRIVATE,INE000000001,2020-02-01,2025-08-05,100,70000,\n")
_unlisted_unread = parse(_unlisted_unread_path)["needs_confirmation"]["unlisted_unknown"]
_unlisted_unread_reason = _unlisted_unread["quarterly_withheld"]
check("no readable gain" in _unlisted_unread_reason
      and "not a Schedule CG amount yet" in _unlisted_unread_reason,
      "unreadable gains retain independent s.50CA amount withholding")
shutil.rmtree(_unlisted_unread_dir, ignore_errors=True)

# A bare long-term heading establishes only holding period, not the asset. A
# land row beneath it can need the indexed/unindexed comparison, so its broker
# profit cannot become a timing split merely because the heading omitted land.
_bare_dir = tempfile.mkdtemp()
_bare_ltcg_path = os.path.join(_bare_dir, "bare_long_term_land.csv")
with open(_bare_ltcg_path, "w", encoding="utf-8") as fh:
    fh.write("Long Term\n"
             "Name,Purchase Date,Sale Date,Buy Value,Sell Value,Profit\n"
             "PLOT A,2019-04-05,2025-08-05,400000,700000,300000\n")
_bare_ltcg = parse(_bare_ltcg_path)["needs_confirmation"]["ltcg_unknown"]
check("quarterly" not in _bare_ltcg
      and "changes the amount" in _bare_ltcg.get("quarterly_withheld", ""),
      "a bare long-term heading withholds a potentially indexed land gain")
_bare_stcg_path = os.path.join(_bare_dir, "bare_short_term_buyback.csv")
with open(_bare_stcg_path, "w", encoding="utf-8") as fh:
    fh.write("Short Term\n"
             "Name,Purchase Date,Sale Date,Buy Value,Sell Value,Profit\n"
             "ACME BUYBACK,2025-04-05,2025-08-05,40000,70000,30000\n")
_bare_stcg = parse(_bare_stcg_path)["needs_confirmation"]["stcg_unknown"]
check("quarterly" not in _bare_stcg
      and "changes the amount" in _bare_stcg.get("quarterly_withheld", ""),
      "a bare short-term heading withholds a possible buyback gain")
_generic_non_equity_path = os.path.join(_bare_dir, "generic_non_equity_sgb.csv")
with open(_generic_non_equity_path, "w", encoding="utf-8") as fh:
    fh.write("Non Equity - Long Term\n"
             "Name,Purchase Date,Sale Date,Buy Value,Sell Value,Profit\n"
             "SGB 2032,2020-04-05,2025-08-05,40000,70000,30000\n")
# A bond that a broker actually sold says so in the heading, and the
# sovereign-gold-bond rules match before the generic non-equity ones — so the
# redemption question is asked where the evidence for it exists.
_named_sgb_path = os.path.join(_bare_dir, "non_equity_named_sgb.csv")
with open(_named_sgb_path, "w", encoding="utf-8") as fh:
    fh.write("Non Equity - Sovereign Gold Bond\n"
             "Name,Purchase Date,Sale Date,Buy Value,Sell Value,Profit\n"
             "SGB 2032,2020-04-05,2025-08-05,40000,70000,30000\n")
_named_sgb = parse(_named_sgb_path)["needs_confirmation"]
check(list(_named_sgb) == ["sgb_unknown"]
      and "quarterly" not in _named_sgb["sgb_unknown"],
      f"a heading naming the bond reaches the redemption question: {list(_named_sgb)}")
# The heading classifies the bucket and is never revisited, so an
# amount-sensitive instrument named in the ROW is the only evidence left — and
# it is evidence, so it is used rather than discarded.
_generic_non_equity = parse(_generic_non_equity_path)["needs_confirmation"]["nonequity_unknown"]
check("quarterly" not in _generic_non_equity
      and "s.47(viic)" in _generic_non_equity.get("quarterly_withheld", ""),
      "a bond named in the row withholds even under a generic heading")

# ...and an ordinary non-equity row under the same heading still publishes, so
# the evidence is what decides rather than the heading being blanket-suspect.
_plain_ne_path = os.path.join(_bare_dir, "plain_non_equity.csv")
with open(_plain_ne_path, "w", encoding="utf-8") as fh:
    fh.write("Non Equity - Long Term\n"
             "Name,Purchase Date,Sale Date,Buy Value,Sell Value,Profit\n"
             "LIQUIDBEES,2020-04-05,2025-08-05,40000,70000,30000\n")
check("quarterly" in parse(_plain_ne_path)["needs_confirmation"]["nonequity_unknown"],
      "an ordinary non-equity row under the same heading still publishes")
shutil.rmtree(_bare_dir, ignore_errors=True)

# The whole point of publishing these windows is that Schedule BFLA cannot say
# WHEN a gain arose and s.234C turns on exactly that. Successive rounds of
# "withhold this too" once grew the set to cover every unresolved bucket, which
# silently removed the output this parser exists to produce. The split is
# therefore pinned by intent, not just by behaviour: a question about the RATE
# publishes, a question about the AMOUNT withholds.
sys.path.insert(0, SCRIPTS)
from parse_capital_gains import QUARTERLY_NOT_PUBLISHABLE  # noqa: E402

check(QUARTERLY_NOT_PUBLISHABLE == {
          "buyback", "landbuilding_unknown", "foreign_unknown", "sgb_unknown",
          # a bare heading names no asset, so nothing is ruled out
          "stcg_unknown", "ltcg_unknown",
          # s.50CA can deem the consideration, so the figure moves
          "unlisted_unknown"},
      f"the withholding set is exactly the amount-open buckets: "
      f"{sorted(QUARTERLY_NOT_PUBLISHABLE)}")
for _rate_only in ("nonequity_unknown", "mf_unknown"):
    check(_rate_only not in QUARTERLY_NOT_PUBLISHABLE,
          f"{_rate_only} names its asset class and asks only about the rate, "
          f"so it publishes")

# s.55(2)(ac) grandfathers an equity acquisition made on or before 31 January
# 2018: the cost becomes the higher of actual cost and that day's fair market
# value. A raw Profit column does not carry that, so resolving the bucket as
# equity-oriented would move the figure — the same reason a buyback's split is
# withheld.
_gf_dir = tempfile.mkdtemp()
def _mf_csv(name, buy_date):
    path = os.path.join(_gf_dir, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("Mutual Funds - Long Term\n"
                 "Symbol,ISIN,Entry Date,Exit Date,Quantity,Buy Value,Sell Value,Profit\n"
                 f"AXISBLUE,INF846K01EW2,{buy_date},2025-08-05,100,40000,70000,30000\n")
    return path

RAW_H = ("Symbol,ISIN,Entry Date,Exit Date,Quantity,Buy Value,Sell Value,Profit")
TAX_H = ("Symbol,ISIN,Entry Date,Exit Date,Quantity,Buy Value,Sell Value,"
         "Taxable Profit")
MIXED_H = ("Symbol,ISIN,Entry Date,Exit Date,Quantity,Buy Value,Sell Value,"
           "Taxable Profit,Profit")
FMV_H = ("Symbol,ISIN,Entry Date,Exit Date,Quantity,Buy Value,Sell Value,"
         "FMV,Profit")


def _mf(name, header, buy_date):
    path = os.path.join(_gf_dir, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("Mutual Funds - Long Term\n" + header + "\n"
                 f"A,INF846K01EW2,{buy_date},2025-08-05,100,40000,70000,30000\n")
    return parse(path)["needs_confirmation"]["mf_unknown"]


# The cutoff is a date, so it is tested at the date. 31 January is inside the
# grandfathering; 1 February is not.
for _label, _entry, _want in (
        ("a pre-cutoff acquisition", _mf("pre.csv", RAW_H, "2017-06-05"), False),
        ("an acquisition on the cutoff itself", _mf("on.csv", RAW_H, "2018-01-31"), False),
        ("an acquisition the day after", _mf("after.csv", RAW_H, "2018-02-01"), True),
        # An absent date is not evidence of a post-cutoff acquisition.
        ("an unknown acquisition date", _mf("nodate.csv", RAW_H, ""), False),
        # A figure read from Taxable Profit already carries the adjustment, so
        # telling the reader to fetch that column would be circular.
        ("a gain already read from Taxable Profit",
         _mf("taxable.csv", TAX_H, "2017-06-05"), True)):
    check(("quarterly" in _entry) is _want,
          f"{_label}: split {'published' if _want else 'withheld'}")
check("31 January 2018 fair market value"
      in _mf("pre2.csv", RAW_H, "2017-06-05").get("quarterly_withheld", ""),
      "the withheld note names the fair market value it needs")

# An explicit 112A heading settles the asset class, not the grandfathered gain.
# The same raw-Profit/cutoff guard must apply before it publishes a split.
_direct_112a_raw = os.path.join(_gf_dir, "direct_112a_raw.csv")
with open(_direct_112a_raw, "w", encoding="utf-8") as fh:
    fh.write("Equity - Long Term\n" + RAW_H + "\n"
             "A,INE000000001,2017-06-05,2025-08-05,100,40000,70000,30000\n")
_direct_112a_entry = parse(_direct_112a_raw)["buckets"]["112A"]
check("quarterly" not in _direct_112a_entry
      and "grandfathering check" in _direct_112a_entry.get("quarterly_withheld", ""),
      "direct 112A raw Profit withholds a pre-cutoff split")
_direct_112a_summary = run("parse_capital_gains.py", _direct_112a_raw, "--summary")
check("112A:" in _direct_112a_summary.stdout
      and "Amount/timing withheld:" in _direct_112a_summary.stdout,
      "summary retains direct 112A grandfathering withholding")
_direct_112a_taxable = os.path.join(_gf_dir, "direct_112a_taxable.csv")
with open(_direct_112a_taxable, "w", encoding="utf-8") as fh:
    fh.write("Equity - Long Term\n" + TAX_H + "\n"
             "A,INE000000001,2017-06-05,2025-08-05,100,40000,70000,28000\n")
check("quarterly" in parse(_direct_112a_taxable)["buckets"]["112A"],
      "direct 112A Taxable Profit publishes its settled split")

# Header preference alone is not proof that Taxable Profit supplied this row:
# a blank adjusted cell must fall back to raw Profit and remain withheld.
_mixed_path = os.path.join(_gf_dir, "blank_taxable.csv")
with open(_mixed_path, "w", encoding="utf-8") as fh:
    fh.write("Mutual Funds - Long Term\n" + MIXED_H + "\n"
             "A,INF846K01EW2,2017-06-05,2025-08-05,100,40000,70000,,30000\n")
_mixed = parse(_mixed_path)["needs_confirmation"]["mf_unknown"]
check("quarterly" not in _mixed,
      "a blank Taxable Profit cell falling back to Profit remains withheld")

# An FMV column is input to the statutory calculation, not evidence that this
# parser or the broker used it to arrive at the raw Profit figure.
_fmv_path = os.path.join(_gf_dir, "fmv_raw_profit.csv")
with open(_fmv_path, "w", encoding="utf-8") as fh:
    fh.write("Mutual Funds - Long Term\n" + FMV_H + "\n"
             "A,INF846K01EW2,2017-06-05,2025-08-05,100,40000,70000,65000,30000\n")
_fmv = parse(_fmv_path)["needs_confirmation"]["mf_unknown"]
check("quarterly" not in _fmv,
      "an FMV cell beside raw Profit does not settle grandfathering")

# A bare short-term row cannot reach 112A, but it still has no established asset
# class. An absent acquisition date is irrelevant; the possible buyback or SGB
# treatment is enough to keep its raw broker gain out of a timing split.
_st_dir = tempfile.mkdtemp()
_st_csv = os.path.join(_st_dir, "short_term_unknown_date.csv")
with open(_st_csv, "w", encoding="utf-8") as fh:
    fh.write("Short Term\n" + RAW_H + "\n"
             "A,INF846K01EW2,,2025-08-05,100,40000,70000,30000\n")
_st = parse(_st_csv)["needs_confirmation"]["stcg_unknown"]
check("quarterly" not in _st and _st.get("quarterly_withheld"),
      "short-term rows are withheld for asset ambiguity, not grandfathering")
shutil.rmtree(_st_dir, ignore_errors=True)

_missing_date = _mf("missing_date_note.csv", RAW_H, "")
check("no readable acquisition date" in _missing_date.get("quarterly_withheld", "")
      and "were acquired on or before" not in _missing_date["quarterly_withheld"],
      "the grandfathering note does not present a missing date as a pre-cutoff date")

# A mutual-fund section can establish short-term treatment even with no readable
# acquisition date. It cannot reach 112A, so grandfathering is not a reason to
# suppress the timing split.
_mf_short_path = os.path.join(_gf_dir, "mutual_fund_short_term.csv")
with open(_mf_short_path, "w", encoding="utf-8") as fh:
    fh.write("Mutual Funds - Short Term\n" + RAW_H + "\n"
             "A,INF846K01EW2,,2025-08-05,100,40000,70000,30000\n")
_mf_short = parse(_mf_short_path)["needs_confirmation"]["mf_unknown"]
check("quarterly" in _mf_short
      and "grandfathering" not in _mf_short.get("quarterly_withheld", ""),
      "a short-term mutual-fund section does not trigger grandfathering")
_mf_short_summary = run("parse_capital_gains.py", _mf_short_path, "--summary")
check("mf_unknown:" in _mf_short_summary.stdout
      and "Timing — 16-Jun-2025 to 15-Sep-2025" in _mf_short_summary.stdout,
      "summary renders confirmation-bucket timing windows")

# When a bucket is confirmed only as far as its shared class, each section's
# published timing window must remain visible in --summary as well.
_mf_sections_path = os.path.join(_gf_dir, "mutual_fund_sections.csv")
with open(_mf_sections_path, "w", encoding="utf-8") as fh:
    fh.write("Mutual Funds - Long Term\n" + RAW_H + "\n"
             "LONG,INF846K01EW2,2018-02-01,2025-08-05,100,40000,70000,30000\n"
             "Mutual Funds - Short Term\n" + RAW_H + "\n"
             "SHORT,INF846K01EW3,2018-02-01,2025-09-02,100,40000,70000,5000\n")
_mf_sections = parse(_mf_sections_path)["needs_confirmation"]["mf_unknown"]
check("quarterly_by_section" in _mf_sections,
      "multi-section confirmation buckets retain their per-section windows")
_mf_sections_summary = run("parse_capital_gains.py", _mf_sections_path, "--summary")
check("Timing — Mutual Funds - Long Term, 16-Jun-2025 to 15-Sep-2025"
      in _mf_sections_summary.stdout
      and "Timing — Mutual Funds - Short Term, 16-Jun-2025 to 15-Sep-2025"
      in _mf_sections_summary.stdout,
      "summary renders published per-section timing windows")

# Withholding a non-final gain is not a reason to hide an independently known
# sale-date mismatch. The summary must flag the prior-year row even though it
# deliberately has no quarterly amount.
_gf_prior_path = os.path.join(_gf_dir, "precutoff_prior_year.csv")
with open(_gf_prior_path, "w", encoding="utf-8") as fh:
    fh.write("Mutual Funds - Long Term\n" + RAW_H + "\n"
             "A,INF846K01EW2,2017-06-05,2024-11-20,100,40000,70000,30000\n")
_gf_prior = parse(_gf_prior_path)["needs_confirmation"]["mf_unknown"]
check("quarterly" not in _gf_prior and _gf_prior.get("out_of_year", {}).get("rows") == 1,
      "a withheld grandfathering bucket retains its independent out-of-year warning")
_gf_prior_summary = run("parse_capital_gains.py", _gf_prior_path, "--summary")
check("Out-of-year rows" in _gf_prior_summary.stdout
      and "mf_unknown (needs confirmation)" in _gf_prior_summary.stdout,
      "summary surfaces an out-of-year date for a withheld bucket")

# Withheld means withheld everywhere: the per-section branch is independent and
# was still emitting the grandfathering-sensitive figure.
_two = os.path.join(_gf_dir, "two_sections.csv")
with open(_two, "w", encoding="utf-8") as fh:
    fh.write("Mutual Funds - Long Term\n" + RAW_H + "\n"
             "A,INF846K01EW2,2017-06-05,2025-08-05,100,40000,70000,30000\n"
             "Mutual Funds - Short Term\n" + RAW_H + "\n"
             "B,INF846K01EW2,2025-04-05,2025-08-05,100,40000,45000,5000\n")
_two_entry = parse(_two)["needs_confirmation"]["mf_unknown"]
check("quarterly" not in _two_entry and "quarterly_by_section" not in _two_entry,
      "grandfathering withholds the per-section split as well as the aggregate")
shutil.rmtree(_gf_dir, ignore_errors=True)

# safe_name() reduces a path to its basename, so two statements in different
# directories with the same file name would count as one source.
_same_dir = tempfile.mkdtemp()
_same = []
for _sub in ("one", "two"):
    os.makedirs(os.path.join(_same_dir, _sub), exist_ok=True)
    _path = os.path.join(_same_dir, _sub, "report.csv")
    with open(_path, "w", encoding="utf-8") as fh:
        fh.write("US Stocks - Long Term\n"
                 "Symbol,ISIN,Entry Date,Exit Date,Quantity,Buy Value,Sell Value,Profit\n"
                 "X,US0378331005,2023-04-18,2025-09-02,10,1500,2100,300\n")
    _same.append(_path)
_same_out = run("parse_capital_gains.py", *_same, "--summary")
check(_same_out.stdout.count("report.csv — detected") == 2,
      "two statements sharing a basename are counted as two sources")
shutil.rmtree(_same_dir, ignore_errors=True)

# The first window's test is `sold <= 15 June 2025`, which is also true of every
# date before the year began — so the wrong year's statement would report its
# whole gain inside the first instalment window.
_oy_dir = tempfile.mkdtemp()
_oy_csv = os.path.join(_oy_dir, "prior_year.csv")
with open(_oy_csv, "w", encoding="utf-8") as fh:
    fh.write("Non Equity - Long Term\n"
             "Symbol,ISIN,Entry Date,Exit Date,Quantity,Buy Value,Sell Value,Profit\n"
             "GOLDBEES,INF204KB17I5,2022-01-05,2024-11-20,10,4000,7000,3000\n")
_oy_entry = parse(_oy_csv)["needs_confirmation"]["nonequity_unknown"]
_oy = _oy_entry["out_of_year"]
check(_oy["gain"] == 3000.0
      and not any(w["rows"] for k, w in (_oy_entry.get("quarterly") or {}).items()
                  if k != "out_of_year"),
      "a sale before the financial year lands in no instalment window")
# The date mismatch is observed; "the statement is for another year" is not —
# a multi-year export or a misparsed date looks the same.
check("[inferred]" in _oy["note"],
      "the out-of-year diagnosis is tagged as an inference")
_oy_summary = run("parse_capital_gains.py", _oy_csv, "--summary")
check("FY 2025-26 (AY 2026-27)" in _oy_summary.stdout
      and "Out-of-year rows" in _oy_summary.stdout
      and "outside the FY timing scope" in _oy_summary.stdout,
      "the summary names its fixed year and surfaces out-of-year bucket amounts")
shutil.rmtree(_oy_dir, ignore_errors=True)

# Nothing here converts a currency, and the foreign resolver says foreign
# holdings are out of scope — so a foreign broker's gain would otherwise be
# published in its native currency as though it were a rupee filing figure.
_fx_dir = tempfile.mkdtemp()
_fx_csv = os.path.join(_fx_dir, "foreign_layout.csv")
with open(_fx_csv, "w", encoding="utf-8") as fh:
    fh.write("US Stocks - Long Term\n"
             "Symbol,ISIN,Entry Date,Exit Date,Quantity,Buy Value,Sell Value,Profit\n"
             "AAPL,US0378331005,2023-04-18,2025-09-02,10,1500,2200,700\n")
_fx = parse(_fx_csv)
# s.47(viic): redeeming a Sovereign Gold Bond with the RBI is not a transfer, so
# no capital gain arises at all — while selling the same bond on the exchange is
# an ordinary transfer. A broker statement does not say which happened, and the
# non-equity bucket's s.50AA question cannot resolve it.
_sgb_dir = tempfile.mkdtemp()
_sgb_csv = os.path.join(_sgb_dir, "sgb_layout.csv")
with open(_sgb_csv, "w", encoding="utf-8") as fh:
    fh.write("Sovereign Gold Bond\n"
             "Symbol,ISIN,Entry Date,Exit Date,Quantity,Buy Value,Sell Value,Profit\n"
             "SGBAUG28,IN0020280054,2020-08-05,2025-08-05,10,4000,7000,3000\n")
_sgb = parse(_sgb_csv)
check(list(_sgb["needs_confirmation"]) == ["sgb_unknown"]
      and "redeemed with the RBI" in _sgb["needs_confirmation"]["sgb_unknown"]["question"],
      "a sovereign gold bond asks its own question, not the s.50AA one")
check("quarterly" not in _sgb["needs_confirmation"]["sgb_unknown"],
      "a sovereign gold bond withholds its windows until redemption is settled")
check("47(viic)" in _sgb["needs_confirmation"]["sgb_unknown"]["why_it_matters"],
      "the sovereign gold bond rationale cites s.47(viic)")
shutil.rmtree(_sgb_dir, ignore_errors=True)

# Intraday and F&O are Schedule BP. Putting them in the item F shape invites a
# reader to file business income on a capital-gains schedule.
check(all("quarterly" not in e and "quarterly_by_section" not in e
          for name, e in data["buckets"].items()
          if name in ("speculative", "fno")),
      "business-income buckets carry no Schedule CG item F split")

# The abbreviated mode must not abbreviate the qualification on its figures.
_disc = run("parse_capital_gains.py",
            os.path.join(FIXTURES, "zerodha_tax_pnl_synthetic.xlsx"), "--summary")
check("Tie every figure back to AIS" in _disc.stdout,
      "the summary keeps the filing disclaimer")
check("Timing — 01-Apr-2025 to 15-Jun-2025:" in _disc.stdout
      and "Timing — 16-Jun-2025 to 15-Sep-2025:" in _disc.stdout,
      "summary renders published bucket timing windows")

# Mutually exclusive stdout modes are rejected, as the other CLIs do.
for _flag in ("--inspect", "--rows"):
    _conflict = run("parse_capital_gains.py",
                    os.path.join(FIXTURES, "zerodha_tax_pnl_synthetic.xlsx"),
                    "--summary", _flag, expect_code=2)
    check("two different stdout modes" in (_conflict.stdout + _conflict.stderr),
          f"--summary with {_flag} is refused rather than silently ignored")

check("quarterly" not in _fx["needs_confirmation"]["foreign_unknown"]
      and _fx["needs_confirmation"]["foreign_unknown"].get("quarterly_withheld"),
      "a foreign holding withholds its windows — the amount is not in rupees")

# Nothing here reads a currency per row, so even a single statement cannot be
# described as having one currency or summed as though it did.
_fx_summary = run("parse_capital_gains.py", _fx_csv, "--summary")
check("₹" not in _fx_summary.stdout.split("Flags")[0]
      and "not totalled" in _fx_summary.stdout
      and "currency per row" in _fx_summary.stdout,
      f"a foreign gain is not labelled or summed: "
      f"{_fx_summary.stdout.splitlines()[1] if len(_fx_summary.stdout.splitlines()) > 1 else ''}")

_mixed_fx_csv = os.path.join(_fx_dir, "mixed_currency_foreign.csv")
with open(_mixed_fx_csv, "w", encoding="utf-8") as fh:
    fh.write("US Stocks - Long Term\n"
             "Symbol,ISIN,Entry Date,Exit Date,Currency,Quantity,Buy Value,Sell Value,Profit\n"
             "AAPL,US0378331005,2023-04-18,2025-09-02,USD,10,1500,2100,600\n"
             "BP,GB0007980591,2023-04-18,2025-09-03,GBP,10,1500,1900,400\n")
_mixed_fx_summary = run("parse_capital_gains.py", _mixed_fx_csv, "--summary")
check("not totalled" in _mixed_fx_summary.stdout
      and "1,000.00" not in _mixed_fx_summary.stdout,
      "a consolidated foreign statement with USD and GBP rows is not summed")
_mixed_fx = parse(_mixed_fx_csv)["needs_confirmation"]["foreign_unknown"]
check(not {"gain", "sell_value", "buy_value"} & set(_mixed_fx),
      "full JSON omits foreign-currency aggregates as well as the summary")

_foreign_prior_csv = os.path.join(_fx_dir, "foreign_prior_year.csv")
with open(_foreign_prior_csv, "w", encoding="utf-8") as fh:
    fh.write("US Stocks - Long Term\n"
             "Symbol,ISIN,Entry Date,Exit Date,Quantity,Buy Value,Sell Value,Profit\n"
             "AAPL,US0378331005,2023-04-18,2024-11-20,10,1500,2200,700\n")
_foreign_prior_summary = run("parse_capital_gains.py", _foreign_prior_csv, "--summary")
check("Out-of-year rows" in _foreign_prior_summary.stdout
      and "not totalled" in _foreign_prior_summary.stdout
      and "₹" not in _foreign_prior_summary.stdout,
      "an out-of-year foreign warning never reintroduces a rupee total")
check("gain" not in parse(_foreign_prior_csv)["needs_confirmation"]
      ["foreign_unknown"]["out_of_year"],
      "full JSON omits an out-of-year foreign aggregate")

# A sale date establishes FY scope even where the broker omitted the gain.
_amountless_dir = tempfile.mkdtemp()
_amountless_csv = os.path.join(_amountless_dir, "amountless_prior_year.csv")
with open(_amountless_csv, "w", encoding="utf-8") as fh:
    fh.write("Equity - Long Term\n"
             "Symbol,ISIN,Entry Date,Exit Date,Quantity,Sell Value,Profit\n"
             "SYNTHETIC,INE000000001,2024-02-01,2024-11-20,100,70000,\n")
_amountless = parse(_amountless_csv)["buckets"]["112A"]
check("gain" not in _amountless
      and _amountless.get("gain_unreadable_rows") == 1
      and _amountless.get("out_of_year", {}).get("rows") == 1
      and "gain" not in _amountless["out_of_year"],
      "an unread gain keeps its out-of-year date without a false zero total")
_amountless_summary = run("parse_capital_gains.py", _amountless_csv, "--summary")
check("Out-of-year rows" in _amountless_summary.stdout
      and "amount not read" in _amountless_summary.stdout,
      "summary reports an amountless out-of-year row")
shutil.rmtree(_amountless_dir, ignore_errors=True)

# One unreadable row makes a dated quarterly total partial, even when another
# row's gain is available. Do not offer the partial amount for s.234C timing.
_partial_dir = tempfile.mkdtemp()
_partial_csv = os.path.join(_partial_dir, "partial_111a.csv")
with open(_partial_csv, "w", encoding="utf-8") as fh:
    fh.write("Equity - Short Term\n"
             "Symbol,ISIN,Entry Date,Exit Date,Quantity,Profit\n"
             "ONE,INE000000001,2024-02-01,2025-08-05,100,100\n"
             "TWO,INE000000002,2024-02-01,2025-08-05,100,\n"
             "Equity Short Term Profit,100\n")
_partial_result = parse(_partial_csv)
_partial_111a = _partial_result["buckets"]["111A"]
check("gain" not in _partial_111a
      and _partial_111a.get("gain_unreadable_rows") == 1
      and "quarterly" not in _partial_111a
      and "partial timing amount" in _partial_111a.get("quarterly_withheld", ""),
      "an unreadable 111A row withholds the otherwise partial quarterly split")
_partial_reconciliation = next(
    (f for f in _partial_result["flags"] if "Equity Short Term Profit" not in f
     and "under 111A" in f), "")
check("bucket total is withheld, not missing" in _partial_reconciliation
      and "no rows were parsed" not in _partial_reconciliation,
      "reconciliation distinguishes an unreadable gain from an absent bucket")
shutil.rmtree(_partial_dir, ignore_errors=True)

# A derived gain's caveat lives in the row's `flags`. The collector read a
# `warning` key that never exists, so it always found nothing and the summary
# showed only the tally, truncated at its first semicolon — hiding that no
# transfer cost was deducted.
_derived_dir = tempfile.mkdtemp()
_derived_csv = os.path.join(_derived_dir, "derived_gain.csv")
with open(_derived_csv, "w", encoding="utf-8") as fh:
    fh.write("Equity - Long Term\n"
             "Symbol,ISIN,Entry Date,Exit Date,Quantity,Buy Value,Sell Value\n"
             "INFY,INE009A01021,2023-04-18,2025-09-02,60,93000,101400\n")
_derived = run("parse_capital_gains.py", _derived_csv, "--summary")
check("Row warnings" in _derived.stdout
      and "transfer cost is not deducted" in _derived.stdout,
      "the summary surfaces the unabridged derived-gain caveat")

# ...and from a row past the three-row sample. Collecting after truncation saw
# only the first three, so a caveat on the fourth row onward disappeared.
_late_csv = os.path.join(_derived_dir, "late_derived.csv")
with open(_late_csv, "w", encoding="utf-8") as fh:
    fh.write("Equity - Long Term\n"
             "Symbol,ISIN,Entry Date,Exit Date,Quantity,Buy Value,Sell Value,Profit\n")
    for _i in range(5):
        fh.write(f"INFY,INE009A01021,2023-04-18,2025-09-0{_i % 9 + 1},"
                 "60,93000,101400,840\n")
    fh.write("INFY,INE009A01021,2023-04-18,2025-09-02,60,93000,101400\n")
_late = run("parse_capital_gains.py", _late_csv, "--summary")
check("transfer cost is not deducted" in _late.stdout,
      "a derived-gain caveat past the three-row sample still reaches the summary")
shutil.rmtree(_derived_dir, ignore_errors=True)

# Nothing here parses a currency, so a total across two foreign statements may
# be adding units that are not the same unit. The sum has no monetary meaning.
_multi_dir = tempfile.mkdtemp()
_multi = []
# Four rows in the first file, so the second file's only row sits past the
# three-row sample the JSON keeps.
for _name, _sym, _isin, _rows in (("usd.csv", "AAPL", "US0378331005", 4),
                                  ("gbp.csv", "BP", "GB0007980591", 1)):
    _path = os.path.join(_multi_dir, _name)
    with open(_path, "w", encoding="utf-8") as fh:
        fh.write("US Stocks - Long Term\n"
                 "Symbol,ISIN,Entry Date,Exit Date,Quantity,Buy Value,Sell Value,Profit\n")
        for _r in range(_rows):
            fh.write(f"{_sym},{_isin},2023-04-18,2025-09-0{_r + 1},"
                     "10,1500,2100,150\n")
    _multi.append(_path)
_multi_out = run("parse_capital_gains.py", *_multi, "--summary")
_fx_line = next((l for l in _multi_out.stdout.splitlines() if "foreign" in l), "")
check("not totalled" in _fx_line and "currency per row" in _fx_line,
      f"two foreign statements are not summed, even when the second file's rows "
      f"sit past the sample: {_fx_line[:80]}")
shutil.rmtree(_multi_dir, ignore_errors=True)

# A named non-equity bucket publishes, so it must carry the qualification that
# makes publishing honest: gross timing, not an amount for any schedule.
_ne_basis = _needs["nonequity_unknown"].get("quarterly_basis", "")
check("fill Table F last, from BFLA" in _ne_basis
      and "NET of current-year" in _ne_basis,
      "a published non-equity bucket carries its timing basis")

_parser_golden = load_ci_script("run_parser_golden.py")
check(_parser_golden.has_exact_provenance_tag(
          "[observed] Parser regression: checked in a synthetic fixture.")
      and not _parser_golden.has_exact_provenance_tag(
          "[observed, parser regression] malformed combined tag."),
      "parser golden cases require an exact provenance tag")
check(_parser_golden.json_values_match(30000.0, 30000.0)
      and not _parser_golden.json_values_match(30000.0, "30000.0"),
      "parser golden comparisons preserve JSON numeric types")

# A malformed, encrypted, unsupported or PDF input must honour --summary too.
_pdf_sum = run("parse_capital_gains.py", os.path.join(FIXTURES, "plain_synthetic.pdf"),
               "--summary", expect_code=2)
check(not _pdf_sum.stderr.lstrip().startswith("{") and "is a PDF" in _pdf_sum.stderr,
      "a parse-time refusal honours --summary instead of printing the object")
shutil.rmtree(_fx_dir, ignore_errors=True)

# --summary promises a few lines instead of the full JSON, and an unrecognised
# layout is the commonest time a reader wants them.
_unknown_dir = tempfile.mkdtemp()
_unknown_csv = os.path.join(_unknown_dir, "unknown_layout.csv")
with open(_unknown_csv, "w", encoding="utf-8") as fh:
    fh.write("alpha,beta\n1,2\n")
_unknown = run("parse_capital_gains.py", _unknown_csv, "--summary", expect_code=2)
check(not _unknown.stderr.lstrip().startswith("{")
      and "No rows were recognised" in _unknown.stderr,
      "an unrecognised layout refuses in summary form under --summary")
shutil.rmtree(_unknown_dir, ignore_errors=True)

# The PDF advice carries its provenance: a broker menu changes without notice.
_pdf2 = run("parse_capital_gains.py", os.path.join(FIXTURES, "plain_synthetic.pdf"),
            expect_code=2)
_pdf2_msg = json.loads(_pdf2.stdout or _pdf2.stderr).get("refused", "")
check("[observed" in _pdf2_msg and "[UNVERIFIED]" in _pdf2_msg
      and "[inferred]" in _pdf2_msg,
      "the PDF refusal tags the menu path and the conversion claim")
check("[observed] 2026-07-31" in _pdf2_msg,
      "the PDF refusal uses the exact observed provenance tag")

# A PDF is named as a PDF. Telling its owner to re-save it as .xlsx in a
# spreadsheet application is advice that cannot be followed.
_pdf_refusal = run("parse_capital_gains.py",
                   os.path.join(FIXTURES, "plain_synthetic.pdf"),
                   expect_code=2)
_pdf_message = (json.loads(_pdf_refusal.stdout or _pdf_refusal.stderr)
                .get("refused", ""))
check("is a PDF" in _pdf_message and "workbooks and CSV" in _pdf_message
      and "not a valid .xlsx" not in _pdf_message,
      f"a PDF passed to the capital-gains reader is named as one: {_pdf_message[:90]}")
check(len(data["flags"]) == 1 and "ITR-3" in data["flags"][0],
      "validated Zerodha keeps its existing single ITR-3 flag")
check(any("1,25,000" in c and "per PAN" in c for c in data["checks"]),
      "the 112A exemption is flagged as once per PAN")

dated = [r for r in data["buckets"]["111A"]["records"] if r.get("buy_date")]
check(len(dated) == data["buckets"]["111A"]["rows"], "every row parsed both dates")
check(all(r["buy_date"] < r["sell_date"] for r in dated), "dates parse as ISO, in order")

# ------------------------------------------------------- the adversarial file
adv = parse(os.path.join(FIXTURES, "adversarial_layout_synthetic.xlsx"))
b = {k: (v["rows"], v["gain"]) for k, v in adv["buckets"].items()}
needs = adv["needs_confirmation"]

check(b == {"111A": (3, 98000.0), "112A": (2, 500000.0),
            "fno": (1, 1000.0)},
      f"the adversarial broker buckets remain exact: {b}")
check({k: (v["rows"], v["gain"]) for k, v in needs.items()} == {
          "nonequity_unknown": (1, 12000.0),
          "unlisted_unknown": (1, 400000.0),
          "buyback": (1, 20000.0),
          "landbuilding_unknown": (1, 4000000.0),
      }, f"the adversarial confirmation buckets remain exact: {needs}")

check(b.get("111A") == (3, 98000.0),
      f"real scrips named SUMICHEM, Summit and TOTAL ENERGIES survive; the "
      f"Subtotal row does not: {b.get('111A')}")
check(b.get("112A") == (2, 500000.0),
      f"'Equity LTCG' and a heading sharing its row with a note both land in "
      f"112A, not in the section above: {b.get('112A')}")
check("111A" in b and b["111A"][1] == 98000.0,
      "a decoy Unrealised P&L column ahead of the real one is ignored")
check(needs.get("nonequity_unknown", {}).get("gain") == 12000.0,
      "'Non-Equity Mutual Funds - Long Term' is not read as equity")
check(needs.get("unlisted_unknown", {}).get("gain") == 400000.0,
      "unlisted shares are queried, not given the 112A exemption")
check(needs.get("buyback", {}).get("gain") == 20000.0,
      "a buyback is queried, not taxed as an ordinary capital gain")
check(needs.get("landbuilding_unknown", {}).get("gain") == 4000000.0,
      "land and building is queried so the indexation option is not skipped")
check(b.get("fno", (0, 0))[1] == 1000.0 and "speculative" not in b,
      "currency intraday is non-speculative business, not speculative")
check(any("buyback" in f.lower() for f in adv["flags"]), "the buyback is flagged")

# ------------------------------------------------- --inspect must not identify
# [observed 2026-07-31] A real broker workbook names its account holder in the
# header rows of every sheet — client ID, full name, PAN — and --inspect printed
# all three verbatim, once per sheet, while the parser's own `checks` output
# said "nothing here reproduces them". --inspect is what the refusal messages
# send people to run on an unrecognised layout, which is the moment they are
# most likely to paste the output into a bug report. No fixture carried an
# identity header row, so nothing could have caught it.
identity_dir = tempfile.mkdtemp()
identity_csv = os.path.join(identity_dir, "broker_with_identity.csv")
with open(identity_csv, "w", encoding="utf-8") as fh:
    fh.write(
        "Client ID,ZZ1234\n"
        "Client Name,SPECIMEN TAXPAYER\n"
        "PAN,ABCDE1234F\n"
        "Email,specimen@example.invalid\n"
        # `[inferred]` A registrar or a second broker may qualify its labels this
    # way; only the Zerodha workbook's Client ID / Client Name / PAN block was
    # observed. Matching one label too many costs a masked value; one too few
    # costs a taxpayer's name in a public issue.
        "Investor Name,SECOND SPECIMEN\n"
        "First Holder Name,THIRD SPECIMEN\n"
        "Registered Email ID,holder@example.invalid\n"
        "Equity - Short Term\n"
        "Symbol,ISIN,Entry Date,Exit Date,Quantity,Buy Value,Sell Value,Profit\n"
        "INFY,INE009A01021,2025-04-18,2025-09-02,60,93000,101400,8400\n")
inspected = run("parse_capital_gains.py", "--inspect", identity_csv).stdout
for secret in ("ZZ1234", "SPECIMEN TAXPAYER", "ABCDE1234F",
               "specimen@example.invalid", "SECOND SPECIMEN", "THIRD SPECIMEN",
               "holder@example.invalid"):
    check(secret not in inspected,
          f"--inspect does not reproduce {secret!r} from a header row")
# Redacting must not blind the mode: the labels and the structure are the whole
# point of running it.
check("Client Name" in inspected and "PAN" in inspected
      and "Investor Name" in inspected and "Registered Email ID" in inspected,
      "--inspect keeps the identity labels, dropping only their values")
check("Equity - Short Term" in inspected and "INE009A01021" in inspected,
      "--inspect still shows section headings and trade rows")

# A broker table may legitimately open with a Name column — "name" is in
# HEADER_RULES. Matching the label against the joined row text replaced every
# heading after it with a mask, which removes the exact structure someone runs
# --inspect to report.
name_first_csv = os.path.join(identity_dir, "name_first_header.csv")
with open(name_first_csv, "w", encoding="utf-8") as fh:
    fh.write(
        "Equity - Short Term\n"
        "Name,ISIN,Entry Date,Exit Date,Quantity,Buy Value,Sell Value,Profit\n"
        "INFY,INE009A01021,2025-04-18,2025-09-02,60,93000,101400,8400\n")
name_first = run("parse_capital_gains.py", "--inspect", name_first_csv).stdout
for column in ("ISIN", "Entry Date", "Quantity", "Buy Value", "Sell Value"):
    check(column in name_first,
          f"a header row beginning with Name keeps its {column!r} column")
check("INE009A01021" in name_first,
      "a data row under a Name-first header is still shown")

# Second review round: the label pass must reach identity stored in shapes the
# two-cell rule missed, without eating a header it cannot classify.
sys.path.insert(0, SCRIPTS)
from parse_capital_gains import safe_row_text, safe_sheet_name  # noqa: E402
from redact import MASK  # noqa: E402

for row, must_go, must_stay, why in [
    (["Client Name", "SPECIMEN TAXPAYER", "PAN", "ABCDE1234F"],
     "SPECIMEN TAXPAYER", "Client Name", "two key/value pairs share one row"),
    (["Client Name: SPECIMEN TAXPAYER"],
     "SPECIMEN TAXPAYER", "Client Name", "label and value inside one cell"),
    (["Name of Client", "SECRET TAXPAYER"],
     "SECRET TAXPAYER", "Name of Client", "the qualifier trails the noun"),
    (["Name of First Holder", "SECRET TWO"],
     "SECRET TWO", "Name of First Holder", "a long trailing qualifier"),
]:
    rendered = safe_row_text(row)
    check(must_go not in rendered and must_stay in rendered,
          f"--inspect masks the value when {why}: {rendered}")

# A compact header an unknown layout produces is exactly what --inspect exists
# to reveal, and map_header cannot classify it.
compact = safe_row_text(["Name", "Date", "Value"])
check("Date" in compact and "Value" in compact and MASK not in compact,
      f"a compact unrecognised Name-first header keeps its columns: {compact}")
wide_header = safe_row_text(["Name", "ISIN", "Entry Date", "Exit Date", "Quantity"])
check("ISIN" in wide_header and MASK not in wide_header,
      "a wide Name-first header keeps its columns")

# A two-column header has the same shape as a key/value pair, so the value side
# decides. Masking a column name destroys the layout this mode reports.
for header_row in (["Name", "Value"], ["Name", "Amount"], ["Name", "Date"]):
    rendered = safe_row_text(header_row)
    check(MASK not in rendered and header_row[1] in rendered,
          f"a two-column header {header_row} keeps its column: {rendered}")
check(MASK in safe_row_text(["Client Name", "SPECIMEN TAXPAYER"])
      and MASK in safe_row_text(["Client Name", "ZZ1234"]),
      "a two-cell key/value pair is still masked")

# Round three: identity escaping in shapes the label-position rule missed.
from parse_capital_gains import identity_columns  # noqa: E402

check(MASK in safe_row_text(["Client Name", "SECRET ONE", "Status", "Active"])
      and "SECRET ONE" not in safe_row_text(
          ["Client Name", "SECRET ONE", "Status", "Active"])
      and "Active" in safe_row_text(
          ["Client Name", "SECRET ONE", "Status", "Active"]),
      "an identity key masks its own value and leaves an unrelated pair alone")
_inline_row = safe_row_text(["Client Name: SECRET TWO", "PAN: ABCDE1234F"])
check("SECRET TWO" not in _inline_row and "ABCDE1234F" not in _inline_row
      and "Client Name" in _inline_row,
      f"inline Label: value is masked in every cell, not only a lone one: {_inline_row}")
for possessive in ("Father's Name", "Guardian's Name"):
    rendered = safe_row_text([possessive, "SECRET THREE"])
    check("SECRET THREE" not in rendered and possessive in rendered,
          f"a possessive qualifier is matched: {rendered}")

# Columnar metadata: labels on one row, values on the next.
_label_row = ["Client ID", "Client Name", "PAN"]
_value_row = ["ZZ1234", "SECRET FOUR", "ABCDE1234F"]
_cols = identity_columns(_label_row)
check(safe_row_text(_label_row) == "Client ID Client Name PAN",
      "a columnar label row keeps every heading")
_masked = safe_row_text(_value_row, _cols)
check("ZZ1234" not in _masked and "SECRET FOUR" not in _masked,
      f"values beneath an identity header row are masked: {_masked}")
check(identity_columns(["INFY", "INE009A01021", "60"]) == set(),
      "a data row does not declare identity columns for the row after it")

check(safe_sheet_name("Client Name: SPECIMEN TAXPAYER").endswith(MASK)
      and safe_sheet_name("PAN") == MASK
      and safe_sheet_name("Tradewise Exits") == "Tradewise Exits",
      "a worksheet name carrying a labelled identity is masked, an ordinary one is not")
shutil.rmtree(identity_dir, ignore_errors=True)

# ------------------------------- the real-broker workbook shape (synthetic copy)
# Everything below was found by running the parser on two real Zerodha Tax P&L
# files. Before these fixes it reported exactly double every figure, because the
# workbook states each gain twice.
dv = parse(os.path.join(FIXTURES, "broker_double_view_synthetic.xlsx"))
dvb = {k: (v["rows"], v["gain"]) for k, v in dv["buckets"].items()}

check(dvb == {"speculative": (1, 180.0), "111A": (2, 6150.0), "112A": (1, 31000.0)},
      f"a workbook that states its gains twice is counted once: {dvb}")
check(any("restates the same" in c for c in dv["checks"]),
      "the duplicate view is reported, not silently dropped")
check(dvb["112A"][1] == 31000.0,
      "the grandfathered Taxable Profit is used, not the raw Profit column "
      "printed to its left")
check(any("ties to the statement's own summary" in c for c in dv["checks"]),
      "each bucket is reconciled against the broker's own stated totals")
check(any("Open Positions" in c and "unrealised" in c for c in dv["checks"]),
      "open positions are excluded — unrealised profit is not income")
check(all("21750" not in json.dumps(v) for v in dv["buckets"].values()),
      "no unrealised figure reached a bucket")
check(any("PAN" in c for c in dv["checks"]),
      "the file is flagged as carrying identifiers before anyone posts it")

q = data["buckets"]["112A"].get("quarterly", {})
check(round(sum(v["gain"] for v in q.values()), 2) == data["buckets"]["112A"]["gain"],
      "the quarterly split for Schedule CG item F reconciles to the bucket total")
check(all("window" in v for v in q.values()),
      "each quarter carries the window the form asks for")

# The refusal path: nothing recognisable must exit 2, not invent a bucket.
# Written to a temporary directory, not into the fixtures tree — a test that
# creates and deletes files inside the repository fails on any checkout that is
# mounted read-only, and it did.
scratch = tempfile.mkdtemp(prefix="complyeaze-test-")
empty = os.path.join(scratch, "_empty.csv")
with open(empty, "w") as fh:
    fh.write("nothing,useful,here\n1,2,3\n")
proc = run("parse_capital_gains.py", empty, expect_code=2)
check("refused" in proc.stderr, "an unrecognised layout is refused, not guessed at")

# Generic column matching is deliberately useful for inspecting a broker shape
# that has not been validated yet, but detecting a brand is not evidence that
# its layout was checked. Keep every unvalidated detector needle in this table
# so adding a fifteenth brand is one row, not another hand-written test cycle.
unvalidated_layouts = (
    ("", "unknown"),
    ("Groww Tax P&L Statement", "groww"),
    ("Upstox Tax P&L Statement", "upstox"),
    ("Angel Tax P&L Statement", "angel-one"),
    ("INDmoney Tax P&L Statement", "indmoney"),
    ("Dhan Tax P&L Statement", "dhan"),
    ("ICICI Tax P&L Statement", "icici-direct"),
    ("Kotak Tax P&L Statement", "kotak"),
    ("HDFC Sec Tax P&L Statement", "hdfc-securities"),
    ("Paytm Tax P&L Statement", "paytm-money"),
    ("5paisa Tax P&L Statement", "5paisa"),
    ("CAMS Capital Gains Statement", "cams"),
    ("KFintech Capital Gains Statement", "kfintech"),
)
unvalidated_results = {}
unvalidated_paths = {}
for heading, detected in unvalidated_layouts:
    path = os.path.join(scratch, f"_unvalidated_{detected}.csv")
    with open(path, "w") as fh:
        fh.write((heading + "\n" if heading else "")
                 + "Equity Long Term\n"
                 + "Scrip,Sale Value,Cost of Acquisition,Fair Market Value\n"
                 + "SYNTHETIC EQUITY,100,200,120\n")
    result = parse(path)
    unvalidated_results[detected] = result
    unvalidated_paths[detected] = path
    check(result["sources"][0]["detected"] == detected,
          f"the detector retains the {detected} source label")
    layout_flag = next((f for f in result["flags"]
                        if f.startswith("UNVERIFIED LAYOUT")), "")
    check(bool(layout_flag),
          f"the unvalidated {detected} layout raises the primary safety flag")
    expected_status = (
        "could not be associated with a recognised broker brand"
        if detected == "unknown"
        else f"was recognised as {detected}, but no {detected} layout has been "
             "validated against a real specimen"
    )
    check(expected_status in layout_flag,
          f"the {detected} flag distinguishes brand detection from validation")
    result_checks = " ".join(result["checks"]).lower()
    check("heuristic" in result_checks and "not a verified total" in result_checks,
          f"the unvalidated {detected} total is described as heuristic")
    check("112a gains total" not in result_checks,
          f"the unvalidated {detected} layout asserts no verified 112A total")

unknown = unvalidated_results["unknown"]
unknown_checks = " ".join(unknown["checks"]).lower()
check("heuristic matches include a fair market value" in unknown_checks
      and "broker has already applied" not in unknown_checks,
      "an FMV match in an unvalidated layout is not called proven grandfathering")
check("heuristic matches produce a net loss" in unknown_checks
      and not any(c.startswith("Net loss in") for c in unknown["checks"]),
      "an unvalidated-layout loss is described as a heuristic match")
check(any(c.startswith("Heuristic matches in 111A") and "sale value" in c
          for c in adv["checks"]),
      "missing consideration in an unvalidated layout is described as a matched row")

mixed_layouts = parse(os.path.join(FIXTURES, "zerodha_tax_pnl_synthetic.xlsx"),
                      unvalidated_paths["groww"])
check(any(f.startswith("UNVERIFIED LAYOUT") for f in mixed_layouts["flags"])
      and "112a gains total" not in " ".join(mixed_layouts["checks"]).lower(),
      "one unvalidated brand makes a mixed Zerodha total heuristic")

named_unvalidated = os.path.join(scratch, "ABCDE1234F_Groww.csv")
shutil.copyfile(unvalidated_paths["groww"], named_unvalidated)
proc = run("parse_capital_gains.py", named_unvalidated, "--rows", expect_code=0)
check("ABCDE1234F" not in proc.stdout and scratch not in proc.stdout,
      "an unvalidated-layout flag redacts a PAN-like filename and its path")

# The same file twice must not silently double the totals.
dup = parse(os.path.join(FIXTURES, "zerodha_tax_pnl_synthetic.xlsx"),
            os.path.join(FIXTURES, "zerodha_tax_pnl_synthetic.xlsx"))
check(any("more than one of the files" in f for f in dup["flags"]),
      "the same statement passed twice is flagged, not silently doubled")

# --------------------------------------------------------- department documents
proc = run("parse_tax_docs.py", os.path.join(FIXTURES, "tis_synthetic.pdf"),
           expect_code=0)
tax_docs = json.loads(proc.stdout)
doc = tax_docs["documents"][0]
cats = doc["data"]["categories"]

check(doc["document"] == "TIS", "a TIS is recognised from its own title")
check(cats.get("PF withdrawal", {}).get("accepted_by_taxpayer") == 543210.0,
      "Indian digit grouping reads correctly out of a PDF (5,43,210)")
check(cats.get("Sale of securities and mutual-fund units", {})
      .get("accepted_by_taxpayer") == 876540.0,
      "a category whose label lost its word spacing still matches")
check(len(cats) == 5, f"every TIS category is found, not just the first: {len(cats)}")
check(any("broker Tax P&L is mandatory" in c for c in tax_docs["checks"]),
      "a reported sale of securities demands the broker statement")
check(any("AIS silence is not evidence" in f for f in tax_docs["flags"]),
      "the AIS-silence warning is unconditional")

sys.path.insert(0, SCRIPTS)
from read_pdf import extract_pages  # noqa: E402
page = extract_pages(os.path.join(FIXTURES, "tis_synthetic.pdf"))[0]
check("Financial Year" in page and "2025-26" in page,
      "the PDF reader keeps columns on one line")

# ------------------------------------------------- an employer-issued Form 16
# Everything below was found by running the parser on one real AY 2026-27
# employer certificate. It came back `"document": "UNKNOWN"` with an empty
# `data` block, so the strongest cross-check the skill has — Form 16 gross
# salary and TDS against the AIS TDS-192 figure — could not run at all, and a
# full return's worth of figures was transcribed by hand instead.
proc = run("parse_tax_docs.py",
           os.path.join(FIXTURES, "form16_employer_synthetic.pdf"),
           expect_code=0)
f16 = json.loads(proc.stdout)["documents"][0]
f16d = f16["data"]

check(f16["document"] == "FORM16B",
      f"a certificate headed 'Form 16' rather than 'FORM NO. 16' is recognised "
      f"and its Part B found nine pages in: {f16['document']}")
check(f16d.get("salary_17_1") == 699346.0
      and f16d.get("perquisites_17_2") == 5504.0,
      "the s.17(1) and s.17(2) split is read")
check(f16d.get("standard_deduction_16_ia") == 75000.0
      and f16d.get("gross_total_income") == 629850.0,
      "the s.16(ia) deduction and gross total income are read")
check(f16d.get("tax_on_total_income") == 11492.0
      and f16d.get("rebate_87a") == 11492.0,
      "tax on total income and the s.87A rebate are read")

# The line that says which regime the employer computed on. Its pattern carried
# "115BAC" in capitals and was matched against a lowercased line, so it fired on
# nothing and the regime was silently absent rather than reported as unread.
check(f16d.get("opted_out_of_new_regime") is False
      and "new" in (f16d.get("regime") or ""),
      f"the s.115BAC(1A) opt-out line is read: {f16d.get('regime')!r}")

# Part A against Part B, which is the identity the certificate exists to carry.
paid = round(sum(q["amount_paid"] for q in f16d.get("quarterly", [])), 2)
check(paid == 704850.0,
      f"the quarterly amounts paid sum to the Part B gross salary: {paid}")

# The certificate prints its assessment year as "2026-2027" on the cover sheet,
# pages ahead of the real financial year. A period pattern that stopped two
# digits in reported "2026-20" — not a period of any kind, and not flagged.
check(f16d is not None and f16.get("period") == "2025-26",
      f"a four-digit year pair does not become a two-digit period: "
      f"{f16.get('period')!r}")

# `period` is the FINANCIAL year, and an assessment year found under its own
# label is converted. The two-letter labels have to be real tokens: stripping
# punctuation makes "generated today:" end in "ay" and "certify" end in "fy",
# and an AY misread converts the year — so a statement dated "today" reported
# the wrong financial year entirely.
sys.path.insert(0, SCRIPTS)
from parse_tax_docs import identity as _identity  # noqa: E402

for _label, _text, _want in (
        ("a word ending in ay is not an AY label",
         "Statement generated today: 2025-26", "2025-26"),
        ("a word ending in fy is not an FY label",
         "we hereby certify 2025-26", "2025-26"),
        ("a real AY label still converts",
         "Assessment Year 2026-27", "2025-26"),
        ("a real FY label is taken as it stands",
         "Financial Year 2025-26", "2025-26"),
        # The reader exists for PDFs whose word spacing is lost, so the glued
        # spellings must keep working.
        ("a glued FY label", "FinancialYear2025-26", "2025-26"),
        ("a glued FY abbreviation", "FY2025-26", "2025-26"),
        ("an abbreviation in brackets", "FinancialYear(FY)2025-26", "2025-26"),
        ("a labelled FY wins over an AY on the same page",
         "Assessment Year 2026-27 ... Financial Year 2025-26", "2025-26")):
    check(_identity(_text).get("period") == _want,
          f"{_label}: {_identity(_text).get('period')!r}")

from parse_tax_docs import detect, identity  # noqa: E402
SALARY_LINE = ("Certificate under Section 203 of the Income-tax Act, 1961 for "
               "tax deducted at source on salary paid to an employee")
check(detect("Form 168 / Annual Tax Statement for Tax Year 2025-26") == "26AS",
      "Form 168 is not swallowed by the Form 16 title — 'form168' contains "
      "'form16' once the spaces are squashed")
check(detect("FORM NO. 16\n" + SALARY_LINE + "\nPART B (Annexure)") == "FORM16B"
      and detect("Form 16\n" + SALARY_LINE + "\nPART B (Annexure)") == "FORM16B",
      "both spellings of the title are recognised")

# The s.203 heading cannot prove a salary certificate, and it looks as though it
# should. The notified heading reads "...on salary paid to an employee under
# section 192 OR pension/interest income of specified senior citizen", so a real
# employer Form 16 carries "194P" and "specified senior citizen" as boilerplate,
# and a bank's s.194P certificate to a specified senior citizen carries the
# salary words. Only Part B separates them, so Part A alone stays UNKNOWN.
check(detect("Form 16\n" + SALARY_LINE
             + "\nQuarterly statement of TDS on pension and interest") == "UNKNOWN",
      "a Part A with no s.17 breakup is left UNKNOWN — from Part A alone a "
      "bank's s.194P certificate and an employer's are the same document")

# Form 16A and Form 16B certify TDS on something other than salary, and their
# titles contain the Form 16 title as a prefix. A next-character guard cannot
# separate them, because the extractor squashes spacing and the genuine
# certificate reads "...limitedform16form16details:". The subject does separate
# them: no s.192 salary line, no s.17 breakup, so no salary certificate.
check(detect("FORM NO. 16A\nCertificate under section 203 of the Income-tax "
             "Act, 1961 for tax deducted at source") == "UNKNOWN"
      and detect("Form 16B\nCertificate under section 203 for tax deducted at "
                 "source on sale of immovable property") == "UNKNOWN",
      "a non-salary Form 16A/16B is left UNKNOWN rather than run through the "
      "salary reconciliation")
check(detect("SPECIMEN EMPLOYER PRIVATE LIMITED Form 16 Form 16 Details : "
             + SALARY_LINE
             + " Salary as per provisions contained in section 17(1) 1.00")
      == "FORM16B",
      "the real certificate's own header, where squashing glues 'form16' to "
      "'form16details', is still recognised")

# Labels arrive punctuated. A suffix test that strips only whitespace leaves the
# colon or bracket in the way, every label falls through to `bare`, and the
# first pair on the page wins — which is the assessment year, a real financial
# year and the wrong one.
check(identity("Assessment Year: 2026-27 Financial Year: 2025-26")
      .get("period") == "2025-26"
      and identity("Assessment Year (AY) 2026-27 Financial Year (FY) 2025-26")
      .get("period") == "2025-26",
      "a punctuated year label is still classified, so the financial year wins")
check(identity("AssessmentYear2026-27").get("period") == "2025-26",
      "a labelled assessment year is converted to its financial year")

# An unread regime line must stay unread. `endswith("yes")` turned a label-only
# line — the answer on the next line, or the cell lost in extraction — into a
# confident False, which reports the NEW regime for a certificate that never
# said so. That is the failure this repository's refuse-don't-guess rule exists
# to prevent, and it is invisible: a wrong regime looks exactly like a right one.
from parse_tax_docs import parse_form16  # noqa: E402
label_only = parse_form16(["A Whether opting out of taxation u/s 115BAC(1A)?"])
check("opted_out_of_new_regime" not in label_only and "regime" not in label_only,
      f"a regime line with no answer on it is left unread, not read as No: "
      f"{label_only.get('regime')!r}")
check(parse_form16(["Whether opting out of taxation u/s 115BAC(1A)? No"])
      .get("opted_out_of_new_regime") is False
      and parse_form16(["Whether opting out of taxation u/s 115BAC(1A)? Yes"])
      .get("opted_out_of_new_regime") is True,
      "an explicit Yes and an explicit No are both still read")
old_regime = parse_form16(
    ["Whether opting out of taxation u/s 115BAC(1A)? Yes"]).get("regime", "")
check("opted out via Form 10-IEA" not in old_regime
      and "depends on whether there is business or professional income" in old_regime,
      f"the old-regime value states the condition instead of asserting the "
      f"mechanism: {old_regime!r}")

# Form 16 against the annual statement. The statement's total covers every
# deductor, so measuring one employer's certificate against it reported a
# shortfall for any filer with non-salary TDS — and told them to ask the
# employer to correct a certificate that was right. Two employers made it worse:
# `by_kind` kept one document per kind, so the second certificate vanished.
from parse_tax_docs import reconcile  # noqa: E402


def _f16(tan, tds, gross=500000.0, period="2025-26"):
    return {"document": "FORM16B", "period": period, "data": {
        "deductor_tan": tan, "tds_total": tds,
        "salary_17_1": gross, "perquisites_17_2": 0.0,
        "profits_in_lieu_17_3": 0.0,
        "regime": "new (test)"}}


def _26as(rows, period="2025-26"):
    return {"document": "26AS", "period": period, "data": {
        "form": "Form 26AS", "deductors": rows,
        "total_tds_deposited": round(
            sum(r.get("tds_deposited") or 0 for r in rows), 2)}}


two_jobs_and_a_bank = reconcile([
    _f16("AAAA00000A", 19500.0, 500000.0),
    _f16("BBBB11111B", 12000.0, 300000.0),
    _26as([
        {"part": "Part I", "tan": "AAAA00000A", "tds_deposited": 19500.0},
        {"part": "Part I", "tan": "BBBB11111B", "tds_deposited": 12000.0},
        # A bank's interest TDS. Real credit, nothing to do with salary.
        {"part": "Part II", "tan": "CCCC22222C", "tds_deposited": 47000.0}])])

check(not any("ask the employer to correct" in f
              for f in two_jobs_and_a_bank["flags"]),
      f"non-salary TDS in the annual statement does not fake a Form 16 "
      f"discrepancy: {two_jobs_and_a_bank['flags']}")
check(sum("cannot confirm that row is the s.192 salary credit" in c
          for c in two_jobs_and_a_bank["checks"]) == 2,
      f"each certificate is matched against its own deductor's rows: "
      f"{two_jobs_and_a_bank['checks']}")
check(any("500,000.00 gross salary" in c for c in two_jobs_and_a_bank["checks"])
      and any("300,000.00 gross salary" in c
              for c in two_jobs_and_a_bank["checks"]),
      "every certificate's gross salary is reported, not just the first")

# Nothing is summed. Every way of getting a multi-certificate total wrong is
# live and undetectable from the documents — a partial s.17 extraction, the same
# file supplied twice, two financial years, and the fact that s.17(1)+(2)+(3) is
# struck before the s.10 exemptions. No two-employer specimen has ever been put
# through this project, so the total is declined rather than guessed.
check(not any("800,000" in c for c in two_jobs_and_a_bank["checks"]),
      "no gross-salary total is offered across certificates")
check(any("no total is offered here" in f and "s.10 exemptions" in f
          for f in two_jobs_and_a_bank["flags"]),
      f"declining the total says why, and what to add up instead: "
      f"{two_jobs_and_a_bank['flags']}")

# Aggregating hid this: 19,500 and 12,000 against rows of 12,000 and 19,500 ties
# on the sum while neither employer ties at all.
swapped = reconcile([
    _f16("AAAA00000A", 19500.0), _f16("BBBB11111B", 12000.0),
    _26as([
        {"part": "Part I", "tan": "AAAA00000A", "tds_deposited": 12000.0},
        {"part": "Part I", "tan": "BBBB11111B", "tds_deposited": 19500.0}])])
check(sum("cannot say which is right" in f for f in swapped["flags"]) == 2
      and not any("agrees with" in c for c in swapped["checks"]),
      f"two offsetting per-employer errors are both reported, not cancelled: "
      f"{swapped['flags']}")

# A TAN on the certificate that appears nowhere in the statement is the case
# that actually costs money: the deductor's return is what creates the credit,
# so this needs a different action from an arithmetic difference.
unfiled = reconcile([
    _f16("AAAA00000A", 19500.0),
    _26as([{"part": "Part II", "tan": "CCCC22222C",
            "tds_deposited": 47000.0}])])
check(any("appears nowhere in Form 26AS" in f and "rule 37BA" in f
          for f in unfiled["flags"]),
      f"a deductor TAN missing from the statement is named, with the basis "
      f"for why it is not creditable: {unfiled['flags']}")

# A certificate that cannot be matched must say so rather than fall back to a
# comparison against something else.
untanned = reconcile([
    {"document": "FORM16B", "period": "2025-26", "data": {"tds_total": 19500.0}},
    _26as([{"part": "Part I", "tan": "AAAA00000A",
            "tds_deposited": 19500.0}])])
check(any("no readable deductor TAN" in f for f in untanned["flags"]),
      f"a certificate with no TAN declines the comparison: {untanned['flags']}")

# Warning and then continuing is the same guess with a disclaimer on it. Every
# branch that cannot verify its pairing has to stop, because the instruction the
# loop ends in — claim this figure, go back to your employer — is unsafe on an
# unverified pairing and a caveat further up does not retract it.
NO_ADVICE = ("Claim the", "ask the employer to correct")

unread_year = reconcile([
    _f16("AAAA00000A", 19500.0, period=None),
    _26as([{"part": "Part I", "tan": "AAAA00000A", "tds_deposited": 47000.0}])])
check(any("cannot be confirmed that the two cover the same year" in f
          for f in unread_year["flags"])
      and not any(p in c for c in unread_year["checks"] for p in NO_ADVICE)
      and not any(p in f for f in unread_year["flags"] for p in NO_ADVICE),
      f"an unread financial year stops the comparison rather than warning and "
      f"proceeding: {unread_year['flags']}")

mismatched_year = reconcile([
    _f16("AAAA00000A", 19500.0, period="2024-25"),
    _26as([{"part": "Part I", "tan": "AAAA00000A", "tds_deposited": 47000.0}])])
check(any("not comparable" in f for f in mismatched_year["flags"]),
      f"two different years are refused outright: {mismatched_year['flags']}")

# One row for a TAN is unambiguous. More than one is not — this reader keeps no
# section, so it cannot say which rows are the s.192 salary credit.
mixed_tan = reconcile([
    _f16("AAAA00000A", 19500.0),
    _26as([{"part": "Part I", "tan": "AAAA00000A", "tds_deposited": 19500.0},
           {"part": "Part I", "tan": "AAAA00000A", "tds_deposited": 6000.0}])])
check(any("cannot tell which of them are the s.192 salary credit" in f
          for f in mixed_tan["flags"])
      and not any(p in c for c in mixed_tan["checks"] for p in NO_ADVICE)
      and not any(p in f for f in mixed_tan["flags"] for p in NO_ADVICE),
      f"a TAN with more than one row declines instead of comparing with a "
      f"caveat: {mixed_tan['flags']}")

# An employer that deducted nothing has no credit to appear, so no row is
# expected. This is the ordinary shape for anyone whose tax is covered by the
# s.87A rebate, and diagnosing an unfiled TDS return there invents a compliance
# problem out of a correct pair of documents.
nil_tds = reconcile([
    _f16("AAAA00000A", 0.0),
    _26as([{"part": "Part II", "tan": "CCCC22222C", "tds_deposited": 500.0}])])
check(not any("appears nowhere" in f for f in nil_tds["flags"])
      and any("no credit to appear anywhere" in c for c in nil_tds["checks"]),
      f"a nil-TDS certificate with no matching row is consistent, not a "
      f"compliance failure: {nil_tds['flags']}")

# Where they disagree the parser must not pick a winner. It matches on TAN and
# keeps no section, so it cannot know whether the certificate is wrong, the row
# is wrong, or the row is a different payment entirely.
disagree = reconcile([
    _f16("AAAA00000A", 19500.0),
    _26as([{"part": "Part I", "tan": "AAAA00000A", "tds_deposited": 12000.0}])])
check(any("cannot say which is right" in f and "Do not file either figure" in f
          for f in disagree["flags"])
      and not any("Claim the" in f for f in disagree["flags"]),
      f"a disagreement is reported without instructing which figure to file: "
      f"{disagree['flags']}")

# The period boundary is a digit boundary, not a word boundary: this reader
# exists for PDFs whose word spacing is lost, and there \b never matches.
check(identity("FinancialYear2025-26").get("period") == "2025-26"
      and identity("Tax Year 2026-27").get("period") == "2026-27",
      "a year glued to its own label is still read")
check("period" not in identity("Assessment Year 2026-2027"),
      "a four-digit year pair does not become a two-digit period")

# --------------------------------------------------------------- Schedule 112A
def csv_check(name, code):
    proc = run("check_112a_csv.py", os.path.join(FIXTURES, name), "--json",
               expect_code=code)
    doc = json.loads(proc.stdout)
    return doc, " ".join(f["message"] for f in doc["findings"])


valid, _ = csv_check("schedule112a_valid.csv", 0)
check(valid["ok"] and valid["blockers"] == 0, "a correct Schedule 112A CSV passes")
check(valid["column_14_total"] == "117400", "column 14 totals across rows")

broken, messages = csv_check("schedule112a_broken.csv", 1)
check(not broken["ok"], "a broken Schedule 112A CSV fails")
check("forbidden character" in messages, "a hyphen in a scrip name is caught")
check("round(col4 x col5)" in messages, "column 6 arithmetic is checked")
check("col6 - col13" in messages, "column 14 arithmetic is checked")
check("INNOTREQUIRD" in messages, "an AE row carrying a real ISIN is caught")
check("must be exactly BE or AE" in messages, "a pasted dropdown label is caught")
check("non-breaking space" in messages, "a retyped header is caught")
check(all(f.get("column") != "15" for f in broken["findings"]),
      "no finding points at a column 15, which does not exist")

loss, loss_msgs = csv_check("schedule112a_loss.csv", 0)
check(loss["ok"], "a 112A LOSS row passes — the minus sign is not a forbidden character")
check(loss["column_14_total"] == "-30000", "a loss totals negative")

blank, blank_msgs = csv_check("schedule112a_blank14.csv", 1)
check(not blank["ok"] and "is blank" in blank_msgs,
      "a blank column 14 is a blocker, not a silent zero")

ae9, ae9_msgs = csv_check("schedule112a_ae_col9.csv", 1)
check(not ae9["ok"] and "column 9 must be blank" in ae9_msgs,
      "column 9 on an AE row is caught before it inflates the cost")

# These are portal upload templates, not broker Tax P&L statements. Keep the
# cases tabular so the next committed template fixture is one row, not another
# hand-written test block.
schedule_112a_templates = (
    "schedule112a_valid.csv",
    "schedule112a_broken.csv",
    "schedule112a_loss.csv",
    "schedule112a_blank14.csv",
    "schedule112a_ae_col9.csv",
)
for fixture in schedule_112a_templates:
    proc = run("parse_capital_gains.py", os.path.join(FIXTURES, fixture),
               expect_code=2)
    refusal = json.loads(proc.stderr or proc.stdout)
    check("check_112a_csv.py" in refusal.get("refused", ""),
          f"{fixture} is refused as an upload template and names its validator")

named_112a = os.path.join(scratch, "ABCDE1234F_schedule112a.csv")
shutil.copyfile(os.path.join(FIXTURES, "schedule112a_valid.csv"), named_112a)
proc = run("parse_capital_gains.py", named_112a, expect_code=2)
check("ABCDE1234F" not in proc.stderr and scratch not in proc.stderr,
      "a Schedule 112A refusal redacts a PAN-like filename and its path")

proc = run("parse_capital_gains.py",
           os.path.join(FIXTURES, "zerodha_tax_pnl_synthetic.xlsx"),
           os.path.join(FIXTURES, "schedule112a_valid.csv"), expect_code=2)
mixed_refusal = json.loads(proc.stderr)
check("check_112a_csv.py" in mixed_refusal.get("refused", "")
      and not proc.stdout,
      "an upload template mixed with a broker file refuses instead of emitting partial totals")

# ---------------------------------------------------------------- reader itself
proc = run("read_tabular.py", os.path.join(FIXTURES, "zerodha_tax_pnl_synthetic.xlsx"),
           expect_code=0)
sheets = json.loads(proc.stdout)
check(len(sheets) == 3, "all sheets are read")
check(any("2025-05-12" in " ".join(r) for rows in sheets.values()
          for r in rows["first_rows"]), "Excel serial dates become ISO strings")

sys.path.insert(0, SCRIPTS)
from read_tabular import _coerce, _serial_to_iso  # noqa: E402

check(_coerce("1,23,456") == 123456, "Indian digit grouping reads as a number")
check(_coerce("1,50") == "1,50", "a European decimal comma is not read as grouping")
check(_coerce("0012345") == "0012345", "a leading zero stays an identifier")
check(_serial_to_iso(3_000_000) == 3_000_000,
      "an amount too large to be a date comes back as the amount, not a crash")

# ------------------------------------------------------------ encrypted PDFs
# The fixtures are written by pikepdf (see evals/fixtures/build_encrypted_pdfs.py)
# and read back here with the standard library alone, so this is a cross-check
# against an independent implementation, not a round trip against ourselves.
from pdf_crypt import (CryptError, aes_cbc_decrypt,  # noqa: E402
                       aes_cbc_encrypt_nopad, make_decryptor)
from read_pdf import (PdfError, _expand_object_streams,  # noqa: E402
                      _stream_bytes)
import read_pdf as read_pdf_module  # noqa: E402

PAGE_ONE = "Page one of an invented statement, amount 1111.11"
PAGE_TWO = "Page two of an invented statement, amount 2222.22"
from open_ais import password as derive_password  # noqa: E402

# A broken font mapping can leave millions of spaces and isolated glyphs, so
# the old "any non-whitespace" check reported success without extracting words.
# The fallback deliberately fails this assertion before the parser grows the
# gate: deleting the gate later must also turn this test red.
word_density_is_plausible = getattr(
    read_pdf_module, "_has_plausible_word_density", lambda pages: True)
unmapped_glyphs = [" " * 9800 + " ".join("abcdefghijklmnopqrstuvwxyz")]
check(not word_density_is_plausible(unmapped_glyphs),
      "near-pure-whitespace extraction with isolated glyphs is refused")

# [observed 2026-07-31] A real 82-page bank statement was refused here although
# it extracted perfectly: 1,928,950 characters of which only 48,085 carried ink,
# 2,745 words. Against the whole laid-out string that is 1.42 per 1,000 and it
# failed a threshold of 5; against ink it is 57.09. The denominator counted the
# padding _page_text adds to keep columns in columns, so a document was judged
# less readable the wider it was drawn.
# `_page_text` rstrips every rendered row, so trailing padding is a shape the
# extractor cannot emit and a test built from it would pass against an
# implementation that merely strips line ends. Real width inflation is the gap
# *between* columns, which is what these rows carry.
def _columns(cells: list[str], gap: int) -> str:
    return (" " * gap).join(cells)


wide_sparse_page = ["\n".join([
    _columns(["Date", "Narration", "Credit", "Balance"], 240),
    _columns(["01/04/2025", "SB Int", "672.40", "126452.48"], 240),
    _columns(["01/07/2025", "Credit Interest", "998.10", "127450.58"], 240),
])]
check(word_density_is_plausible(wide_sparse_page),
      "a wide, numeric statement page with real column gaps is not refused")

# The property that was actually broken: widening the columns must not change
# whether a page is judged readable. Same tokens, same ink, 400x the gap. No
# trailing whitespace on any row, so stripping line ends cannot fake this.
rows = [["Gross Salary", "1111.11"], ["Standard deduction", "222.22"]]
narrow = ["\n".join(_columns(r, 10) for r in rows)]
wide = ["\n".join(_columns(r, 4000) for r in rows)]
check(not any(line != line.rstrip() for page in narrow + wide
              for line in page.splitlines()),
      "the padding-independence fixture has no trailing whitespace to strip")
check(word_density_is_plausible(narrow) == word_density_is_plausible(wide) is True,
      "the readability verdict does not depend on how wide the columns are")

# Ink-only measurement must not rescue a genuinely unreadable page: isolated
# glyphs still produce no three-character words however tightly they are packed.
check(not word_density_is_plausible(["".join(" ".join("abcdefghij") for _ in range(50))]),
      "packing isolated glyphs together does not make them words")

# A density floor alone accepts a page that decoded one heading and reduced the
# rest to isolated glyphs: one token among thirty ink characters clears five per
# thousand. It cleared the old whole-string denominator too, at 17.9 — this is a
# long-standing hole rather than something the ink denominator opened. The
# letters-in-words share closes it: noise scores 0-13%, real documents 78-96%.
check(not word_density_is_plausible(
          ["Page " + " ".join("abcdefghijklmnopqrstuvwxyz")]),
      "one decoded heading does not carry a page of isolated glyphs")
check(not word_density_is_plausible(["Statement " + "A B C D " * 200]),
      "a heading cannot rescue a page whose letters never form words")
# ...and the share must not refuse a real, heavily numeric page.
check(word_density_is_plausible(wide_sparse_page)
      and word_density_is_plausible(
          ["\n".join(_columns(["01/04/2025", "SB Int", "672.40", "126452.48"], 60)
                     for _ in range(40))]),
      "a page that is mostly digits is not refused for being numeric")

# Aggregating pages first lets a readable page dilute a corrupted one. The
# document gate still passes this pair, which is why the per-page gate exists.
_readable_page = ("Gross Salary 1111.11    Standard deduction 222.22    "
                  "Total taxable income 4444.44")
_noise_page = "Page " + " ".join("abcdefghijklmnopqrstuvwxyz")
# A correctly decoded ledger is full of legitimate two-letter labels. Judging
# those as noise refuses a page that decoded perfectly; unmapped output is
# isolated single glyphs, which still scores zero.
check(not read_pdf_module._page_is_glyph_noise("Dt No Cr Dr By To Dt No Cr Ref"),
      "a page of legitimate two-letter labels is not glyph noise")
# A matra is a combining mark, so a class built from \w splits an Indic word at
# every mark and its letters go uncounted while the denominator still counts
# them. The share tokenises the same way the density words do.
for _script, _word in {"Hindi": "नमस्ते", "Tamil": "வணக்கம்",
                       "Bengali": "বাংলা"}.items():
    _page = (_word + " ") * 12
    check(read_pdf_module._letters_in_words_share(_page) > 99.0,
          f"a decoded {_script} page scores as words, not glyphs: "
          f"{read_pdf_module._letters_in_words_share(_page):.1f}%")
    check(not read_pdf_module._page_is_glyph_noise(_page),
          f"a decoded {_script} page is not judged glyph noise")
check(read_pdf_module._page_is_glyph_noise("Page " + " ".join("abcdefghijklmn")),
      "a short glyph-noise page is judged on content, not exempted for being small")
check(not read_pdf_module._page_is_glyph_noise("Page 3"),
      "a sparse page whose few letters form a word is not noise")

check(read_pdf_module._page_is_glyph_noise(_noise_page),
      "a page with a decoded heading and isolated glyphs is judged noise on its own")
check(not read_pdf_module._page_is_glyph_noise(_readable_page),
      "a readable page is not judged noise")
check(not read_pdf_module._page_is_glyph_noise("01/04/2025  672.40  126452.48"),
      "a page with too few letters to judge is left to the document gate")
check(read_pdf_module._page_lost_text(b"BT (x) Tj ET", _noise_page, False),
      "a glyph-noise page reaches the page-level refusal even beside a readable one")

# The numerator counts letters, not token length: _word_tokens admits combining
# marks and joiners that the denominator never counts.
_combining = "abc" + "\u0301" * 15 + " " + " ".join("abcdefghijklmnopqrst")
check(read_pdf_module._letters_in_words_share(_combining)
      < read_pdf_module.MIN_LETTERS_IN_WORDS_PCT,
      "combining marks inside a token do not inflate the letters-in-words share")

short_pages = extract_pages(os.path.join(FIXTURES, "plain_synthetic.pdf"))
check(len("\n".join(short_pages)) == 123
      and word_density_is_plausible(short_pages),
      "the dense 123-character fixture still opens")

word_tokens = getattr(read_pdf_module, "_word_tokens", lambda text: [])
indic_words = {
    "Tamil": "தமிழ்",
    "Kannada": "ಕನ್ನಡ",
    "Hindi": "हिन्दी",
    "Bengali": "বাংলা",
}
for script, word in indic_words.items():
    check(word_tokens(word) == [word],
          f"a correctly decoded {script} word survives its combining marks")

indic_document = [(" ".join(indic_words.values()) + " ") * 20]
check(word_density_is_plausible(indic_document),
      "a correctly decoded Indic document passes the plausibility gate")

join_control_words = {
    "Devanagari ZWJ": "क्‍ष",
    "Malayalam ZWJ": "ന്‍മ",
    "Persian ZWNJ": "می‌روم",
}
for label, word in join_control_words.items():
    check(word_tokens(word) == [word],
          f"{label} stays one word for the plausibility gate")

check(word_tokens("alpha\u200d beta alpha \u200cbeta")
      == ["alpha", "beta", "alpha", "beta"],
      "a leading or trailing join control does not glue separate words")

# [observed 2026-07-30] Portal downloads can be a Java-serialized Object[]
# carrying a header HashMap and the PDF as a length-prefixed byte[]. The builder
# is the source of truth for the invented fixture and for malformed variants.
builder_path = os.path.join(FIXTURES, "build_java_envelope_synthetic.py")
builder_spec = importlib.util.spec_from_file_location(
    "build_java_envelope_synthetic", builder_path)
java_builder = importlib.util.module_from_spec(builder_spec)
builder_spec.loader.exec_module(java_builder)

plain_path = os.path.join(FIXTURES, "plain_synthetic.pdf")
java_path = os.path.join(FIXTURES, "java_envelope_synthetic.pdf")
try:
    java_pages = extract_pages(java_path)
except PdfError:
    java_pages = []
check(java_pages == short_pages,
      "the Java-envelope fixture opens to exactly the plain PDF text")

with open(plain_path, "rb") as fh:
    plain_bytes = fh.read()
with open(java_path, "rb") as fh:
    java_bytes = fh.read()


def java_envelope_must_refuse(data, suffix, required, reason):
    path = os.path.join(scratch, f"ABCDE1234F_{suffix}.pdf")
    with open(path, "wb") as fh:
        fh.write(data)
    try:
        extract_pages(path)
        check(False, f"{reason} is refused")
    except PdfError as e:
        message = str(e)
        check(all(fragment in message for fragment in required)
              and "<redacted>" in message and "ABCDE1234F" not in message
              and scratch not in message,
              f"{reason} is refused without leaking its path")


java_envelope_must_refuse(
    java_bytes[:32], "truncated_java_envelope",
    ("malformed Java-serialized PDF envelope",),
    "a truncated Java envelope")
java_envelope_must_refuse(
    java_builder.wrap_java_envelope(b"invented plain-text payload"),
    "java_envelope_not_pdf", ("Java-serialized", "not a PDF"),
    "a Java envelope whose payload is not a PDF")
long_length = bytearray(java_bytes)
payload_offset = len(java_bytes) - len(plain_bytes)
length_offset = payload_offset - 4
declared_length = int.from_bytes(long_length[length_offset:payload_offset], "big")
long_length[length_offset:payload_offset] = (declared_length + 1).to_bytes(4, "big")
java_envelope_must_refuse(
    bytes(long_length), "java_envelope_long_length",
    ("malformed Java-serialized PDF envelope", "declared byte-array length"),
    "a Java envelope declaring more payload bytes than remain")

PW = derive_password("ABCDE1234F", "01/01/1990")

for name, revision, cipher in [
        ("encrypted_r2_rc4_40_user_synthetic.pdf", 2, "V2"),
        ("encrypted_r3_rc4_128_user_synthetic.pdf", 3, "V2"),
        ("encrypted_r4_aes_128_user_synthetic.pdf", 4, "AESV2"),
        ("encrypted_r6_aes_256_user_synthetic.pdf", 6, "AESV3")]:
    path = os.path.join(FIXTURES, name)
    pages = extract_pages(path, PW)
    label = f"/R {revision} {cipher}"
    check([p.strip() for p in pages] == [PAGE_ONE, PAGE_TWO],
          f"{label}: both pages decrypt to exactly the text pikepdf encrypted")
    dec = make_decryptor(open(path, "rb").read(), PW)
    check((dec.r, dec.cfm) == (revision, cipher),
          f"{label}: the handler is identified from the /Encrypt dictionary")
    check(make_decryptor(open(path, "rb").read(), "ownerpw").opened_with
          == "owner password",
          f"{label}: the owner password opens the file too, and is named as such")
    try:
        make_decryptor(open(path, "rb").read(), "wrongpassword")
        check(False, f"{label}: a wrong password is refused")
    except CryptError as e:
        check("ddmmyyyy" in str(e),
              f"{label}: a wrong password is refused, and the message says why")

# An encrypted file with an empty user password must open without one, and the
# error for a missing password must name the PAN + ddmmyyyy rule.
empty_pw = os.path.join(FIXTURES, "encrypted_r2_rc4_40_empty_synthetic.pdf")
check([p.strip() for p in extract_pages(empty_pw)] == [PAGE_ONE, PAGE_TWO],
      "an empty user password opens with no --password at all")
try:
    extract_pages(os.path.join(FIXTURES, "encrypted_r2_rc4_40_user_synthetic.pdf"))
    check(False, "a password-protected file without a password is refused")
except PdfError as e:
    check("ddmmyyyy" in str(e),
          "a password-protected file without a password names the PAN + ddmmyyyy rule")

# An indirect /Length is an object reference, not a direct byte count. The old
# pattern backtracked inside `12` and treated it as a direct length of `1`.
indirect_length = (b"<< /Length 12 0 R >>\nstream\n"
                   b"full-stream!\nendstream")
check(_stream_bytes(indirect_length, {}) == b"full-stream!",
      "an indirect /Length never truncates the stream to a prefix of its object number")

# Object streams. From PDF 1.5 a writer may pack page and font dictionaries into
# a compressed /Type /ObjStm container, leaving nothing that looks like N 0 obj.
# Every other fixture here is PDF 1.3 or 1.4, so nothing caught that this reader
# returned "no readable pages" for anything a modern writer produced.
for name, password in [("objstm_synthetic.pdf", None),
                       ("encrypted_r4_aes_128_objstm_synthetic.pdf", PW)]:
    path = os.path.join(FIXTURES, name)
    with open(path, "rb") as fh:
        check(b"/ObjStm" in fh.read(),
              f"{name} really does use object streams")
    check([p.strip() for p in extract_pages(path, password)] == [PAGE_ONE, PAGE_TWO],
          f"{name}: pages inside an object stream are read")

# Form XObjects. [observed 2026-07-31, one real employer-issued Form 16] A page
# may draw only a footer and invoke a Form XObject carrying the whole document.
# Reading just /Contents returned the four characters "1of9" across nine pages,
# and the file was then refused with a message blaming font encoding. Nothing
# caught it because every other fixture here puts its text in /Contents.
wrapped_pages = extract_pages(
    os.path.join(FIXTURES, "xobject_wrapped_synthetic.pdf"))
wrapped_text = "\n".join(wrapped_pages)
check(len(wrapped_pages) == 2, "the XObject-wrapped fixture has two pages")
check("Gross Salary 1111.11" in wrapped_text
      and "Standard deduction 222.22" in wrapped_text
      and "Total taxable income 4444.44" in wrapped_text,
      "a body drawn inside a Form XObject is read, not silently dropped")
check("1 of 2" in wrapped_text and "2 of 2" in wrapped_text,
      "the page's own content stream is still read alongside the XObject")
# The regression this pins: before the walk existed, exactly the footer survived.
check([" ".join(p.split()) for p in wrapped_pages]
      != ["1 of 2", "2 of 2"],
      "the page furniture alone is not accepted as the document")

nested_text = "\n".join(extract_pages(
    os.path.join(FIXTURES, "xobject_nested_synthetic.pdf")))
check("Outer form object" in nested_text and "Nested total 5555.55" in nested_text,
      "a Form XObject invoked by another Form XObject is followed too")

# A cycle must terminate, and must not be presented as a clean read. Without a
# visited set this call never returns, so a regression here hangs the suite
# rather than failing it — which is why the fixture exists at all. Dropping the
# recursive invocation is the only way to finish, and what survives is a finite
# prefix of a drawing that cannot be reproduced, so it is refused as loss.
try:
    extract_pages(os.path.join(FIXTURES, "xobject_cycle_synthetic.pdf"))
    check(False, "a cyclic Form graph is refused rather than silently truncated")
except PdfError as cycle_error:
    check("could not read" in str(cycle_error)
          and "could not expand faithfully" in str(cycle_error),
          f"a cyclic Form graph is refused rather than silently truncated: "
          f"{cycle_error}")

# A resource dictionary may hold templates the page never draws — a superseded
# revision, an alternate layout. Walking the dictionary instead of the content
# stream reports their text, including amounts, as part of the document.
unused_text = "\n".join(extract_pages(
    os.path.join(FIXTURES, "xobject_unused_synthetic.pdf")))
check("Invoked total 1234.56" in unused_text,
      "the Form the page actually invokes is read")
check("STALE TEMPLATE" not in unused_text and "9999.99" not in unused_text,
      "a Form present in /XObject but never invoked by Do is not read")

# /Resources is an inheritable attribute. A page carrying none takes the /Pages
# node's, and a reader that looks only at the page object finds no /XObject —
# reading the footer and passing the gates while the body is never read.
inherited_text = "\n".join(extract_pages(
    os.path.join(FIXTURES, "xobject_inherited_synthetic.pdf")))
check("Inherited resources total 2468.10" in inherited_text,
      "a Form reached through /Resources inherited from /Pages is read")

# Two Forms drawing at identical local coordinates, translated apart by the
# page. Appending their streams, or ignoring the CTM, puts both at the origin
# and interleaves them character by character into plausible nonsense.
translated_pages = extract_pages(
    os.path.join(FIXTURES, "xobject_translated_synthetic.pdf"))
translated_rows = [" ".join(line.split())
                   for line in translated_pages[0].splitlines() if line.strip()]
check("UPPER BLOCK gross salary 1111.11" in translated_rows
      and "LOWER BLOCK deductions 2222.22" in translated_rows,
      f"forms invoked under different cm land on their own rows: {translated_rows}")
check(translated_rows.index("UPPER BLOCK gross salary 1111.11")
      < translated_rows.index("LOWER BLOCK deductions 2222.22"),
      "the form translated higher up the page is read first")

# An /Image XObject carries no text operators, and the subtype must be read from
# the dictionary alone: an uncompressed raster whose bytes happen to contain
# "/Subtype /Form" would otherwise be spliced in as content.
check(read_pdf_module._dictionary_of(
          b"<< /Subtype /Image /Length 9 >>\nstream\n/Subtype /Form\nendstream")
      == b"<< /Subtype /Image /Length 9 >>\n",
      "the subtype check reads the dictionary, not the stream payload")
# q/Q saves the whole graphics state, text state included: a Form selecting its
# own font must not leave that font selected for text the page draws after Do.
_state = read_pdf_module._page_text(
    b"BT /A 10 Tf 1 0 0 1 0 700 Tm (aaa) Tj ET "
    b"q BT /B 10 Tf 1 0 0 1 0 600 Tm (bbb) Tj ET Q "
    b"BT 1 0 0 1 0 500 Tm (ccc) Tj ET",
    # Both maps decode 'c', to different letters, so the third line says which
    # font was in effect after Q.
    {"/A": {"map": {ord("a"): "A", ord("c"): "R"}, "bytes": 1},
     "/B": {"map": {ord("b"): "B", ord("c"): "W"}, "bytes": 1}})
check("AAA" in _state and "BBB" in _state and "RRR" in _state
      and "WWW" not in _state,
      f"the font selected inside q/Q is restored on Q: {' '.join(_state.split())}")

# A Form's contents are clipped to its /BBox. Text outside it is not painted by
# a viewer, so a stale amount parked outside the crop must not be extracted.
_clipped = read_pdf_module._page_text(
    b"q 0 0 200 200 re W n "
    b"BT 1 0 0 1 10 100 Tm (INSIDE) Tj ET "
    b"BT 1 0 0 1 10 700 Tm (OUTSIDE) Tj ET Q", {})
check("INSIDE" in _clipped and "OUTSIDE" not in _clipped,
      f"text outside the clip is not extracted: {' '.join(_clipped.split())}")

# PDF names resolve #XX escapes: /Body#5FForm and /Body_Form are one name.
_escaped = {9: b"<< /Type /XObject /Subtype /Form /Length 20 >>\nstream\n"
               b"BT (ESCAPEDNAME) Tj ET\nendstream"}
_esc_out, _ = read_pdf_module._expand_forms(
    b"/Body_Form Do", b"<< /XObject << /Body#5FForm 9 0 R >> >>",
    _escaped, {}, None, {}, set(), [0, 0])
check(b"ESCAPEDNAME" in _esc_out,
      "an escaped resource name matches its unescaped invocation")

# A Do naming something the resources do not resolve is missing content.
_, _unresolved_lost = read_pdf_module._expand_forms(
    b"/Missing Do", b"<< /XObject << /Other 9 0 R >> >>",
    {9: b"<< /Type /XObject /Subtype /Form >>\nstream\n\nendstream"},
    {}, None, {}, set(), [0, 0])
check(_unresolved_lost,
      "a Do the resource dictionary cannot resolve is reported as loss")

# A run starting inside the clip can extend past it; only the origin was tested.
# Tf after Tm, because Tm sets the font size from its own scale.
_overrun = read_pdf_module._page_text(
    b"q 0 690 60 40 re W n BT 1 0 0 1 10 700 Tm /F1 10 Tf "
    b"(VISIBLExxxxxxxxxxHIDDEN) Tj ET Q", {})
check("VISIBLE" in _overrun and "HIDDEN" not in _overrun,
      f"a run is clipped per glyph, not by its origin alone: "
      f"{' '.join(_overrun.split())}")

# The same run under a scaled CTM. `step` is already device-space — it carries
# the CTM through _glyph_size — so advancing the per-glyph probe by ctm[0]*step
# counts the scale twice and walks the row at half speed under `0.5 cm`. Glyphs
# the viewer clips away then stay inside the box and reach the caller. A broker
# statement drawn at CTM 0.3265 is the real shape of this.
_overrun_scaled = read_pdf_module._page_text(
    b"q 0.5 0 0 0.5 0 0 cm 0 690 60 40 re W n BT 1 0 0 1 10 700 Tm /F1 10 Tf "
    b"(VISIBLExxxxxxxxxxZZZZZZ) Tj ET Q", {})
check("VISIBLE" in _overrun_scaled and "Z" not in _overrun_scaled,
      f"per-glyph clipping counts the CTM once, not twice: "
      f"{' '.join(_overrun_scaled.split())}")

# Depth and the cycle check bound recursion but not fan-out. A budget stops a
# compact file from materialising an enormous expansion.
_fan = {}
for _i in range(2, 8):
    _fan[_i] = (b"<< /Type /XObject /Subtype /Form /Resources << /XObject << /N "
                + str(_i + 1).encode() + b" 0 R >> >> /Length 400 >>\nstream\n"
                + (b"/N Do " * 6) + b"BT (X) Tj ET\nendstream")
_fan[8] = b"<< /Type /XObject /Subtype /Form /Length 20 >>\nstream\nBT (LEAF) Tj ET\nendstream"
_budget = read_pdf_module.MAX_FORM_EXPANSION_BYTES
read_pdf_module.MAX_FORM_EXPANSION_BYTES = 20000
try:
    _fan_out, _fan_lost = read_pdf_module._expand_forms(
        b"/N Do", b"<< /XObject << /N 2 0 R >> >>", _fan, {}, None, {},
        set(), [0, 0])
    check(_fan_lost and len(_fan_out) < 200000,
          f"a fan-out expansion stops at the budget and reports loss: "
          f"{len(_fan_out)} bytes, lost={_fan_lost}")
finally:
    read_pdf_module.MAX_FORM_EXPANSION_BYTES = _budget

check(read_pdf_module._invoked_names(b"/Xa Do /Xb Do") == ["Xa", "Xb"]
      and read_pdf_module._invoked_names(b"/Xa /Xb Do") == ["Xb"]
      and read_pdf_module._invoked_names(b"/Xa Tf") == [],
      "only a name immediately followed by Do counts as an invocation")

# A Form whose stream will not decode must reach the page-level refusal. Silently
# dropping it leaves a page that can still pass the gates while missing its body.
lost_content, lost = read_pdf_module._expand_forms(
    b"/Xf1 Do", b"<< /XObject << /Xf1 9 0 R >> >>",
    {9: b"<< /Type /XObject /Subtype /Form /Filter /LZWDecode /Length 4 >>\n"
        b"stream\n\x00\x01\x02\x03\nendstream"},
    {}, None, {}, set(), [0, 0])
check(lost, "a Form whose stream cannot be decoded is reported as loss")

# A PDF may carry its scale in the CTM, leave the text matrix at unity, and draw
# one glyph per Tj. Reading the glyph size off the text matrix then yields 1.0
# instead of the Tf size, the column unit collapses, and every glyph lands
# several columns from its neighbour — the document arrives as single letters
# separated by spaces, carries no word tokens, and is refused although its text
# was recovered correctly and in the right order.
_scaled = extract_pages(os.path.join(FIXTURES, "text_scale_synthetic.pdf"))
_scaled_rows = [" ".join(line.split())
                for line in _scaled[0].splitlines() if line.strip()]
check(_scaled_rows == ["Realized gains for the year",
                       "Non Equity Short Term profit 453.73",
                       "Non Equity Long Term profit 1264.76",
                       "Equity Intraday profit 0"],
      f"CTM-scaled one-glyph-per-Tj text reads as words: {_scaled_rows}")
# The text matrix advances in text space. The composed size carries the CTM, and
# tm[4] is transformed by the CTM again for the next string — advancing by the
# composed size counts it twice, merging labels under a scale below 1 and
# splitting them above it.
_kerned = read_pdf_module._page_text(
    b"q .5 0 0 .5 0 0 cm BT /F1 20 Tf 1 0 0 1 20 700 Tm "
    b"[(AAAA) -1000 (B)] TJ ET Q", {})
check(" ".join(_kerned.split()) == "AAAA B",
      f"a TJ kern still separates strings under a scaled CTM: {_kerned.split()}")

# BT resets the text and line matrices to identity, so the scale they carried
# goes with them. A following object positioned by Td must not inherit it.
_reset = [line for line in read_pdf_module._page_text(
    b"BT /F1 10 Tf 10 0 0 10 0 700 Tm (A) Tj ET "
    b"BT /F1 10 Tf 50 680 Td (B) Tj ET", {}).splitlines() if line.strip()]
check(len(_reset) == 2 and _reset[1].strip() == "B"
      and _reset[1].index("B") > 5,
      f"BT resets the text-matrix scale for the next object: {_reset}")

check(read_pdf_module._glyph_size(9.0, 1.0, [0.5, 0, 0, 0.5, 0, 0]) == 4.5,
      "the glyph size is the Tf size through both matrices, not the matrix alone")
check(read_pdf_module._glyph_size(9.0, 2.0, [1.0, 0, 0, 1.0, 0, 0]) == 18.0,
      "a text-matrix scale multiplies the Tf size rather than replacing it")

# A `%` comment runs to end of line. TOKEN reads the words inside one as
# operators, so a comment between a name and its Do lost the invocation, and a
# commented-out Do fabricated one.
# A clipping path may hold several subpaths, and W applies the whole path. Only
# honouring the last rectangle dropped text a viewer paints through the first.
_multi_clip = read_pdf_module._page_text(
    b"q 0 0 100 100 re 0 400 200 200 re W n "
    b"BT 1 0 0 1 10 50 Tm (LOWERBOX) Tj ET "
    b"BT 1 0 0 1 10 500 Tm (UPPERBOX) Tj ET "
    b"BT 1 0 0 1 10 300 Tm (BETWEEN) Tj ET Q", {})
# A clip built from m/l/c, or an even-odd W*, is not a union of rectangles.
# Treating it as "no clip" surfaces text a viewer never paints, so the page is
# marked lossy and reaches the refusal instead.
for _shape, _ops in (("a path of lines", b"q 10 10 m 100 10 l 100 100 l h W n "),
                     ("an even-odd rule", b"q 0 0 100 100 re W* n ")):
    _hidden = read_pdf_module._page_text(
        _ops + b"BT 1 0 0 1 10 700 Tm (HIDDENAMOUNT) Tj ET "
        b"BT 1 0 0 1 20 50 Tm (VISIBLEROW) Tj ET Q", {})
    check("HIDDENAMOUNT" not in _hidden and "VISIBLEROW" in _hidden,
          f"{_shape} still clips: {' '.join(_hidden.split())}")

check("LOWERBOX" in _multi_clip and "UPPERBOX" in _multi_clip
      and "BETWEEN" not in _multi_clip,
      f"both subpaths are honoured and the gap between them is not: "
      f"{' '.join(_multi_clip.split())}")

# A Form font whose resource name carries an underscore must still be scoped and
# installed, or its glyphs decode as Latin-1 with nothing reported.
_scoped, _map = read_pdf_module._scope_font_names(
    b"/Body_Font 12 Tf (x) Tj", b"<< /Font << /Body_Font 9 0 R >> >>",
    {9: b"<< /Type /Font >>"}, "3")
check(b"/Body_Font__x3 12 Tf" in _scoped and "/Body_Font" in _map,
      f"a font resource name with an underscore is scoped: {_scoped}")

check(read_pdf_module._invoked_names(b"/Xf % draw the body\nDo") == ["Xf"],
      "a comment between a name and its Do does not lose the invocation")
check(read_pdf_module._invoked_names(b"% /Xf Do\n") == [],
      "a Do inside a comment is not treated as an invocation")
check(read_pdf_module._invoked_names(b"(100% of /Xf Do) Tj") == [],
      "a percent sign inside a literal string is data, not a comment")

# Two parents may share one child, and one form may be exposed under two names.
# A page-wide seen set treated the second use as a cycle and dropped it.
shared = {
    9: b"<< /Type /XObject /Subtype /Form /Length 20 >>\nstream\n"
       b"BT (SHARED) Tj ET\nendstream",
}
expanded, shared_lost = read_pdf_module._expand_forms(
    b"/Xa Do /Xb Do", b"<< /XObject << /Xa 9 0 R /Xb 9 0 R >> >>",
    shared, {}, None, {}, set(), [0, 0])
check(expanded.count(b"SHARED") == 2 and not shared_lost,
      f"one Form invoked under two names is expanded both times: {expanded.count(b'SHARED')}")

# Resource categories are independent namespaces. Renaming every occurrence of a
# font name also rewrote a nested XObject that happened to share it.
renamed, mapping = read_pdf_module._scope_font_names(
    b"/F1 12 Tf (x) Tj /F1 Do",
    b"<< /Font << /F1 9 0 R >> >>", {9: b"<< /Type /Font >>"}, "7")
# A font name drawn as text, or sitting in a comment, is not an operand.
_string_safe, _ = read_pdf_module._scope_font_names(
    b"(/F1 12 Tf) Tj % /F1 12 Tf\n/F1 12 Tf",
    b"<< /Font << /F1 9 0 R >> >>", {9: b"<< /Type /Font >>"}, "5")
check(_string_safe.count(b"__x5") == 1
      and b"(/F1 12 Tf) Tj" in _string_safe,
      f"only the real Tf operand is renamed: {_string_safe}")

check(b"/F1__x7 12 Tf" in renamed and b"/F1 Do" in renamed,
      f"only the Tf operand is renamed, not a same-named XObject: {renamed}")

# A resource name follows the PDF name grammar; an allowlist without "_" left
# /Body_Form unexpanded and unreported.
underscore = {9: b"<< /Type /XObject /Subtype /Form /Length 22 >>\nstream\n"
                 b"BT (UNDERSCORE) Tj ET\nendstream"}
expanded_us, _ = read_pdf_module._expand_forms(
    b"/Body_Form Do", b"<< /XObject << /Body_Form 9 0 R >> >>",
    underscore, {}, None, {}, set(), [0, 0])
check(b"UNDERSCORE" in expanded_us,
      "a resource name containing an underscore is expanded")

# Exceeding the nesting cap must refuse rather than return a truncated document.
_, deep_lost = read_pdf_module._expand_forms(
    b"/Xf1 Do", b"<< /XObject << /Xf1 9 0 R >> >>",
    {9: b"<< /Type /XObject /Subtype /Form >>\nstream\n\nendstream"},
    {}, None, {}, set(), [0, 0],
    depth=read_pdf_module.MAX_FORM_XOBJECT_DEPTH + 1)
check(deep_lost, "exceeding the Form nesting cap is reported as loss")

fixture_pdf_names = sorted(
    name for name in os.listdir(FIXTURES) if name.endswith(".pdf"))
# The cycle fixture is refused on purpose: its drawing cannot be reproduced.
REFUSED_BY_DESIGN = {"xobject_cycle_synthetic.pdf"}
fixture_open_failures = []
for fixture_name in fixture_pdf_names:
    if fixture_name in REFUSED_BY_DESIGN:
        continue
    fixture_password = (PW if "_user_" in fixture_name
                        or "encrypted_r4_aes_128_objstm" in fixture_name else None)
    try:
        extract_pages(os.path.join(FIXTURES, fixture_name), fixture_password)
    except (PdfError, CryptError) as exc:
        fixture_open_failures.append(f"{fixture_name}: {exc}")
check(len(fixture_pdf_names) == 23 and not fixture_open_failures,
      f"every fixture PDF except the one refused by design opens: "
      f"{fixture_open_failures}")


def objstm_must_refuse(body, reason):
    try:
        _expand_object_streams({42: body}, {42: 0}, None)
        check(False, f"object stream 42 refuses {reason}")
    except PdfError as e:
        check("object stream 42" in str(e),
              f"object stream 42 refuses {reason} and names its container")


# Once an /ObjStm is encountered, dropping it can produce a plausible but
# incomplete document. Every undecodable or invalid container must fail closed.
objstm_must_refuse(
    b"<< /Type /ObjStm /N 1 /First 4 /Length 4 /Filter /LZWDecode >>\n"
    b"stream\n9 0 \nendstream",
    "an unsupported stream encoding")
objstm_must_refuse(
    b"<< /Type /ObjStm /First 4 /Length 5 >>\nstream\n9 0 X\nendstream",
    "a missing /N")
objstm_must_refuse(
    b"<< /Type /ObjStm /N 1 /Length 5 >>\nstream\n9 0 X\nendstream",
    "a missing /First")
objstm_must_refuse(
    b"<< /Type /ObjStm /N 2 /First 4 /Length 5 >>\nstream\n9 0 X\nendstream",
    "a short object header")
objstm_must_refuse(
    b"<< /Type /ObjStm /N 1 /First 4 /Length 5 >>\nstream\nx 0 X\nendstream",
    "a non-numeric object header")
objstm_must_refuse(
    b"<< /Type /ObjStm /N 1 /First 4 /Length 5 >>\nstream\n9 9 X\nendstream",
    "an out-of-range object offset")
check(_expand_object_streams(
          {42: b"<< /Type /ObjStm /N 0 /First 0 /Length 0 >>\n"
               b"stream\n\nendstream"}, {42: 0}, None) == 0,
      "an explicitly empty /ObjStm is valid rather than a decode failure")

# Every PdfError constructed by read_pdf uses only the redacted base name. Test
# each path-bearing refusal branch, including both password-error variants.
def pdf_refusal_must_redact(path, reason, password=None):
    try:
        extract_pages(path, password)
        check(False, f"{reason} is refused")
    except PdfError as e:
        message = str(e)
        check("ABCDE1234F" not in message and scratch not in message
              and "<redacted>" in message,
              f"{reason} names only the redacted PDF base name")


not_pdf = os.path.join(scratch, "ABCDE1234F_not_pdf.pdf")
with open(not_pdf, "wb") as fh:
    fh.write(b"not a PDF")
pdf_refusal_must_redact(not_pdf, "a file without the PDF signature")

no_pages = os.path.join(scratch, "ABCDE1234F_no_pages.pdf")
with open(no_pages, "wb") as fh:
    fh.write(b"%PDF-1.4\n")
pdf_refusal_must_redact(no_pages, "a PDF with no readable page objects")

no_text = os.path.join(scratch, "ABCDE1234F_no_text.pdf")
with open(no_text, "wb") as fh:
    fh.write(b"%PDF-1.4\n1 0 obj\n<< /Type /Page >>\nendobj\n")
pdf_refusal_must_redact(no_text, "a PDF with no text layer")

# Exercise the extract_pages integration without pretending to synthesise the
# unsupported font encoding itself: the direct unit above owns the ratio, while
# this test makes the page extractor return the measured failure shape.
unmapped_pdf = os.path.join(scratch, "ABCDE1234F_unmapped_font.pdf")
with open(unmapped_pdf, "wb") as fh:
    fh.write(b"%PDF-1.4\n1 0 obj\n<< /Type /Page /Contents 2 0 R >>\nendobj\n"
             b"2 0 obj\n<< /Length 1 >>\nstream\nx\nendstream\nendobj\n")
original_page_text = read_pdf_module._page_text
read_pdf_module._page_text = lambda content, fonts: unmapped_glyphs[0]
try:
    try:
        extract_pages(unmapped_pdf)
        check(False, "extract_pages refuses text that does not form words")
    except PdfError as e:
        message = str(e)
        # The per-page gate now catches this first and names the page count,
        # which is more actionable than the document-level message. Either way
        # the path and the PAN must not appear.
        check("could not read 1 of 1 pages" in message
              and "unmapped glyphs" in message
              and "<redacted>" in message and "ABCDE1234F" not in message
              and scratch not in message,
              "extract_pages names the glyph-noise page without leaking its path")
finally:
    read_pdf_module._page_text = original_page_text


def write_page_state_pdf(path, streams, unsupported=()):
    """Write a synthetic PDF whose page content states are controlled exactly."""
    with open(path, "wb") as fh:
        fh.write(b"%PDF-1.4\n")
        for index, stream in enumerate(streams):
            page_num = 2 * index + 1
            if stream is None:
                fh.write(f"{page_num} 0 obj\n<< /Type /Page >>\nendobj\n".encode())
                continue
            content_num = page_num + 1
            fh.write(
                f"{page_num} 0 obj\n<< /Type /Page /Contents "
                f"{content_num} 0 R >>\nendobj\n".encode())
            filter_entry = " /Filter /LZWDecode" if index in unsupported else ""
            fh.write(
                f"{content_num} 0 obj\n<< /Length {len(stream)}"
                f"{filter_entry} >>\nstream\n".encode())
            fh.write(stream + b"\nendstream\nendobj\n")


cover_stream = b"BT (cover) Tj ET"
wordless_stream = b"BT <00> Tj ET"
original_page_text = read_pdf_module._page_text
read_pdf_module._page_text = lambda content, fonts: (
    "Readable cover page words" if b"(cover)" in content else "")
try:
    mostly_lost = os.path.join(scratch, "ABCDE1234F_mostly_lost.pdf")
    write_page_state_pdf(mostly_lost, [cover_stream] + [wordless_stream] * 49)
    try:
        extract_pages(mostly_lost)
        check(False, "49 wordless text pages cannot hide behind one readable cover")
    except PdfError as e:
        message = str(e)
        check("49 of 50" in message and "could not read" in message
              and "no readable words" in message
              and "<redacted>" in message and "ABCDE1234F" not in message
              and scratch not in message,
              "49 wordless text pages cannot hide behind one readable cover")

    failed_stream = os.path.join(scratch, "ABCDE1234F_failed_stream.pdf")
    write_page_state_pdf(failed_stream, [cover_stream, b"unsupported"], {1})
    try:
        extract_pages(failed_stream)
        check(False, "an undecodable referenced content stream is refused")
    except PdfError as e:
        message = str(e)
        check("1 of 2" in message and "could not read" in message
              and "would not decode" in message
              and "<redacted>" in message and "ABCDE1234F" not in message
              and scratch not in message,
              "an undecodable referenced content stream is refused")

    blank_page = os.path.join(scratch, "ABCDE1234F_blank_page.pdf")
    write_page_state_pdf(blank_page, [cover_stream, None])
    check(extract_pages(blank_page) == ["Readable cover page words", ""],
          "a genuinely blank separator page remains valid")

    image_page = os.path.join(scratch, "ABCDE1234F_image_page.pdf")
    write_page_state_pdf(image_page, [cover_stream, b"q /Im1 Do Q"])
    check(extract_pages(image_page) == ["Readable cover page words", ""],
          "one image-only page does not condemn a readable document")
finally:
    read_pdf_module._page_text = original_page_text

protected = os.path.join(scratch, "ABCDE1234F_protected.pdf")
shutil.copy(os.path.join(FIXTURES, "encrypted_r2_rc4_40_user_synthetic.pdf"),
            protected)
pdf_refusal_must_redact(protected, "an encrypted PDF with no password")
pdf_refusal_must_redact(protected, "an encrypted PDF with a wrong password",
                        "wrongpassword")

# PKCS#7 is the only integrity signal for these AES streams. A whole ciphertext
# block with no valid pad must refuse, just as a partial block already does.
bad_padding_plaintext = b"A" * 16
bad_padding_iv = b"\x33" * 16
bad_padding_ciphertext = (bad_padding_iv + aes_cbc_encrypt_nopad(
    b"k" * 16, bad_padding_plaintext, bad_padding_iv))
try:
    aes_cbc_decrypt(b"k" * 16, bad_padding_ciphertext)
    check(False, "an AES stream with invalid PKCS#7 padding is refused")
except CryptError as e:
    check("padding" in str(e),
          "an AES stream with invalid PKCS#7 padding is refused explicitly")


def corrupt_final_padding_byte(source, destination):
    """Change only the last pad byte of the first encrypted Flate stream."""
    data = bytearray(open(source, "rb").read())
    dec = make_decryptor(bytes(data), PW)
    for match in re.finditer(rb"(\d+)\s+(\d+)\s+obj\b", data):
        end = data.find(b"endobj", match.end())
        if end < 0:
            continue
        body = bytes(data[match.end():end])
        stream = re.search(rb"stream\r?\n", body)
        length = re.search(rb"/Length\s+(\d+)(?!\d)", body)
        if not stream or not length or b"FlateDecode" not in body:
            continue
        raw_start = match.end() + stream.end()
        raw_length = int(length.group(1))
        raw = bytes(data[raw_start:raw_start + raw_length])
        if len(raw) < 32 or len(raw) % 16:
            continue
        try:
            clear = dec.decrypt(raw, int(match.group(1)), int(match.group(2)))
        except CryptError:
            continue
        pad_length = len(raw) - 16 - len(clear)
        if not 1 <= pad_length <= 16:
            continue
        # CBC XORs the previous ciphertext block into the final plaintext
        # block. Flipping its last byte changes only the final padding byte.
        data[raw_start + len(raw) - 17] ^= 1
        with open(destination, "wb") as fh:
            fh.write(data)
        return
    raise AssertionError("no encrypted Flate stream found in synthetic fixture")


corrupt_aes = os.path.join(scratch, "ABCDE1234F_corrupt_padding.pdf")
corrupt_final_padding_byte(
    os.path.join(FIXTURES, "encrypted_r4_aes_128_user_synthetic.pdf"),
    corrupt_aes)
for script in ("parse_tax_docs.py", "parse_bank_statement.py"):
    proc = run(script, corrupt_aes, "--password", PW, expect_code=2)
    try:
        refusal = json.loads(proc.stderr)
    except json.JSONDecodeError:
        refusal = {}
    check(proc.returncode == 2 and "refused" in refusal
          and "Traceback" not in proc.stderr,
          f"{script} turns stream-decryption failure into a JSON refusal with exit 2")
    check("ABCDE1234F" not in proc.stderr and scratch not in proc.stderr,
          f"{script} does not leak the corrupt PDF path while refusing it")

# Decryption must not change what a plain file reads as.
check([p.strip() for p in extract_pages(os.path.join(FIXTURES, "plain_synthetic.pdf"))]
      == [PAGE_ONE, PAGE_TWO],
      "the unencrypted original of the same document reads identically")

# ----------------------------------------------------------- bank statements
def bank(name, *extra):
    proc = run("parse_bank_statement.py", os.path.join(FIXTURES, name), *extra,
               expect_code=0)
    doc = json.loads(proc.stdout)
    return doc, doc["accounts"][0]


doc, acct = bank("bank_statement_dotted_synthetic.pdf")

# The 58-page/2-row bug: dotted dates were not dates, so the rows vanished.
check(acct["transaction_rows_read"] == 13,
      f"every dotted-date row is read (23.04.2025), not skipped: "
      f"{acct['transaction_rows_read']}")
check(acct["bank"] == "HDFC" and acct["ifsc"] == "HDFC0000123",
      "the bank comes from the IFSC prefix")

# The other half of the same bug: 23.04.2025 also matched the amount pattern.
check("23.04" not in json.dumps(acct),
      "no part of a dotted date is read as an amount")

interest = acct["interest_credited"]
check(interest["total"] == 1950.0 and interest["count"] == 4,
      f"interest is exactly the four credited entries: {interest['total']} "
      f"across {interest['count']}")
check(interest["by_quarter"] == {"16 Jun to 15 Sep": 325.0,
                                 "16 Sep to 15 Dec": 425.0,
                                 "16 Dec to 15 Mar": 525.0,
                                 "16 Mar to 31 Mar": 675.0},
      f"each interest credit lands in the right Schedule OS quarter: "
      f"{interest['by_quarter']}")
check(all("COLL" not in e["narration"] for e in interest["entries"]),
      "interest the bank charged is not counted as interest earned")

# Direction. The fixture holds an ₹80,000 rent payment out. Before the balance
# was read it was offered as a credit needing explanation.
check(acct["direction_from_balance"] is True,
      "the running-balance column is identified")
credit_amounts = sorted(c["amount"] for c in acct["large_credits"])
check(credit_amounts == [50000.0, 75000.0],
      f"only the money coming in is offered for explanation: {credit_amounts}")
check(all(c["amount"] != 80000.0 for c in acct["large_credits"]),
      "an ₹80,000 withdrawal is not offered as a credit to explain")
check([c["amount"] for c in acct["large_credits_self_evident"]] == [60000.0],
      "a merchant refund is set aside as self-evident, not put to the taxpayer")

# The same statement printed newest-first must give the same answers.
rev_doc, rev = bank("bank_statement_reverse_synthetic.pdf")
check("reverse-chronological" in rev["layout_confidence"],
      "a newest-first statement is recognised as reversed")
check(rev["interest_credited"]["total"] == interest["total"],
      f"reversed order gives the same interest: {rev['interest_credited']['total']}")
check(rev["interest_credited"]["by_quarter"] == interest["by_quarter"],
      "reversed order gives the same quarterly split")
check(sorted(c["amount"] for c in rev["large_credits"]) == [50000.0, 75000.0],
      f"reversed order finds the same credits, no more and no fewer: "
      f"{[c['amount'] for c in rev['large_credits']]}")
check(all(c["amount"] != 80000.0 for c in rev["large_credits"]),
      "the ₹80,000 withdrawal stays a withdrawal when the statement is reversed")

# With both balance-carry lines present every transaction can be signed.
check(rev["large_amounts_direction_unknown"] == [],
      f"nothing is left undetermined once the statement prints both of its own "
      f"balances: {rev['large_amounts_direction_unknown']}")
check(all(c["amount"] != 81700.0 for c in rev["large_credits"]),
      "a carried-forward balance line is not offered as a receipt")

# Drop the brought-forward line and the first transaction can no longer be
# signed — it must be reported as undetermined, never quietly dropped.
sys.path.insert(0, SCRIPTS)
from parse_bank_statement import (apply_direction, balance_integrity,  # noqa: E402
                                  balance_order, transaction_rows)

no_anchor = [{"date": "2025-04-23", "values": [50000.0, 60000.0],
              "line": "23.04.2025 UPI CR 50,000.00 60,000.00",
              "movement": 50000.0, "direction": "unknown"},
             {"date": "2025-05-15", "values": [20000.0, 40000.0],
              "line": "15.05.2025 ATM WDL 20,000.00 40,000.00",
              "movement": 20000.0, "direction": "unknown"},
             {"date": "2025-06-30", "values": [300.0, 40300.0],
              "line": "30.06.2025 CREDIT INTEREST 300.00 40,300.00",
              "movement": 300.0, "direction": "unknown"},
             {"date": "2025-07-05", "values": [15000.0, 25300.0],
              "line": "05.07.2025 NEFT DR 15,000.00 25,300.00",
              "movement": 15000.0, "direction": "unknown"}]
order, _ = balance_order(no_anchor)
apply_direction(no_anchor, order)
partial = balance_integrity(no_anchor, order)
check(partial["reconciles"] and not partial["covers_the_whole_statement"],
      f"without a brought-forward line the identity still holds among the rows "
      f"read, and says it covers only those: {partial}")
check(no_anchor[0]["direction"] == "unknown",
      "the first row has no previous balance to step from and stays unsigned")

# The running balance is the only thing in a statement that can notice rows
# that were never read at all.
integrity = acct["balance_integrity"]
check(integrity["checked"] and integrity["reconciles"],
      f"opening plus every movement reaches the closing balance: {integrity}")
check((integrity["first_balance_read"], integrity["last_balance_read"])
      == (10000.0, 81700.0),
      f"the first and last balances are read: {integrity}")
check(integrity["covers_the_whole_statement"],
      "both ends sit on the statement's own brought-forward and carried-forward "
      "lines, so the identity covers the whole statement rather than only the "
      "rows that happened to survive")
check(any("no row was missed anywhere in it" in c for c in doc["checks"]),
      "and the check says so in those terms")
check(any("reaches 81,700.00 exactly" in c for c in doc["checks"]),
      "a statement that reconciles end to end says so")

# The same statement with three rows missing. Interest is still a plausible
# figure and the credit list is still a plausible list; both are wrong.
torn_doc, torn = bank("bank_statement_torn_synthetic.pdf")
check(torn["interest_credited"]["total"] == 1950.0,
      "the torn statement still reports a plausible interest figure — which is "
      "exactly why the balance check has to exist")
check(not torn["balance_integrity"]["reconciles"],
      f"missing rows break the balance identity: {torn['balance_integrity']}")
check(torn["balance_integrity"]["unexplained"] == 120425.0,
      f"the shortfall is reported as a figure, not a warning: "
      f"{torn['balance_integrity']['unexplained']}")
check(any("unaccounted for" in f and "treat the interest figure as a floor" in f
          for f in torn_doc["flags"]),
      "the flag says what the interest figure is now worth")

# A bare "INTEREST" narration, and a statement that crosses 31 March.
cy_doc, cy = bank("bank_statement_crossyear_synthetic.pdf")
check(cy["interest_credited"]["by_financial_year"] == {"2024-25": 2000.0,
                                                       "2025-26": 1300.0},
      f"interest is split by financial year, not lumped: "
      f"{cy['interest_credited']['by_financial_year']}")
check(cy["interest_credited"]["count"] == 3,
      f"a narration that is nothing but the word INTEREST is counted: "
      f"{cy['interest_credited']['count']}")
check(all(c["amount"] != 71000.0
          for c in cy["large_credits"] if "INTEREST" in c["narration"].upper()
          and c["amount"] in (i["amount"] for i in cy["interest_credited"]["entries"])),
      "a payment from a company with INTEREST in its name is not interest income")
check(71000.0 in [c["amount"] for c in cy["large_credits"]],
      "that payment is still offered as a credit to explain")
check(any("more than one financial year" in f for f in cy_doc["flags"]),
      "a statement crossing 31 March is flagged, not silently summed")

_, cy_filtered = bank("bank_statement_crossyear_synthetic.pdf",
                      "--financial-year", "2025-26")
check(cy_filtered["interest_credited"]["total"] == 1300.0,
      f"--financial-year takes one year's interest only: "
      f"{cy_filtered['interest_credited']['total']}")
check(len(cy_filtered["interest_credited"]["entries"])
      == cy_filtered["interest_credited"]["count"] == 1
      and {e["financial_year"]
           for e in cy_filtered["interest_credited"]["entries"]} == {"2025-26"},
      "the selected-year entry list contains exactly the rows counted for that year")
check(cy_filtered["interest_credited"]["by_financial_year"]
      == cy["interest_credited"]["by_financial_year"],
      "the year that was excluded is still reported, not hidden")

_, wrong_year = bank("bank_statement_crossyear_synthetic.pdf",
                     "--financial-year", "2030-31")
check(wrong_year["interest_credited"]["total"] == 0.0,
      "a year the statement does not cover yields zero, not a fallback total")

sys.path.insert(0, SCRIPTS)
from parse_bank_statement import financial_year_of, looks_like_bare_interest  # noqa: E402

check(financial_year_of("2025-03-31") == "2024-25"
      and financial_year_of("2025-04-01") == "2025-26",
      "the financial year turns over on 1 April, not 1 January")
check(looks_like_bare_interest("01/01/2026 INTEREST 480.21 98,615.10"),
      "a bare INTEREST row is recognised")
check(not looks_like_bare_interest("UPI/INTEREST KUMAR/PAY 500.00 1,000.00"),
      "a UPI payment to a person named Interest is not")

# Raising the threshold must drop rows, never add them.
_, high = bank("bank_statement_dotted_synthetic.pdf", "--credits-above", "100000")
check(high["large_credits"] == [] and high["interest_credited"]["total"] == 1950.0,
      "--credits-above filters credits without touching the interest figure")

sys.path.insert(0, SCRIPTS)
from parse_bank_statement import mask_dates, parse_date, amounts  # noqa: E402

check(parse_date("23.04.2025 SOME NARRATION 1,000.00") == "2025-04-23",
      "a dotted date parses")
check(parse_date("23-04-25 SOME NARRATION") == "2025-04-23",
      "a two-digit year parses")
check(amounts(mask_dates("23.04.2025 UPI 1,234.56 9,999.00")) == [1234.56, 9999.0],
      "masking leaves the real amounts and removes the date")
check(amounts(mask_dates("01/04/2025 to 31/03/2026 opening 10,000.00")) == [10000.0],
      "a date range contributes no amounts")

# ------------------------------------------------------- AIS Part B2 detail
proc = run("parse_tax_docs.py", os.path.join(FIXTURES, "ais_synthetic.pdf"),
           expect_code=0)
ais_doc = json.loads(proc.stdout)["documents"][0]
check(ais_doc["document"] == "AIS", "an AIS is recognised from its own title")
ais = ais_doc["data"]

check(ais["totals_by_information_code"] == {"TDS-192": 1120000.0,
                                            "SFT-016(SB)": 3400.0,
                                            "SFT-016(TD)": 2400.0,
                                            "SFT-17-LES(M)": 12407.0},
      f"every information code totals exactly: {ais['totals_by_information_code']}")

# Which account. Savings interest is reported one block per bank, and that is
# the only place any document says which bank reported what.
savings = ais["savings_bank_interest_by_reporter"]
check(savings["distinct_reporter_names"] == 4 and savings["total"] == 3400.0,
      f"savings interest is broken out per reporter: "
      f"{savings['distinct_reporter_names']} names totalling {savings['total']}")
check([r["amount"] for r in savings["reporters"]] == [1950.0, 725.0, 640.0, 85.0],
      f"each bank's own figure survives: "
      f"{[r['amount'] for r in savings['reporters']]}")

# Which trade.
disposals = next(e for e in ais["entries"]
                 if e["information_code"] == "SFT-17-LES(M)")
check(len(disposals["rows"]) == 3,
      f"every disposal is a row, not just the category total: "
      f"{len(disposals['rows'])}")
check([r.get("isin") for r in disposals["rows"]]
      == ["INE943D01017", "INE887G01027", "INE439E01022"],
      "each disposal carries its ISIN, including one wrapped onto a second line")
check([r.get("term") for r in disposals["rows"]] == ["short", "short", "long"],
      f"short and long term are read from the asset column, not the column "
      f"beside it: {[r.get('term') for r in disposals['rows']]}")
check([r["sale_consideration"] for r in disposals["rows"]]
      == [5131.0, 6292.0, 985.0],
      "the sale consideration is the right one of seven figures on the row")
check(disposals["rows"][1]["security"]
      == "GOKALDAS EXPORTS LIMITED -NEW EQUITY SHARES OF RS. 5/-AFTER SPLIT",
      f"a scrip name wrapped over two lines is rejoined and carries no column "
      f"labels: {disposals['rows'][1]['security']!r}")
check("within per-row rounding" in disposals["rows_reconcile"],
      f"the rows reconcile to the category total: {disposals['rows_reconcile']}")

# Nothing that identifies anybody comes out, whatever column it was in.
blob = json.dumps(ais)
check(not re.search(r"\d{9,}", blob),
      f"no account number reaches the output: "
      f"{re.findall(chr(92) + 'd{9,}', blob)[:3]}")
check(not re.search(r"\b[A-Z]{4}\d{5}[A-Z]\b", blob),
      "no reporting entity's TAN reaches the output")
check(all(r["ACCOUNT NUMBER"] == "<redacted>"
          for e in ais["entries"]
          for r in e["rows"] if "ACCOUNT NUMBER" in r),
      "the account-number column is redacted by name, not just by shape")

# A section heading printed under a table must not be swallowed by its last row.
last_savings = [e for e in ais["entries"]
                if e["information_code"] == "SFT-016(SB)"][-1]
check(last_savings["rows"][0]["SR.NO."] == "1"
      and last_savings["rows"][0]["REPORTED ON"] == "27/05/2026",
      f"the row under a section heading is not polluted by it: "
      f"{last_savings['rows'][0]}")

# SFT-016(SB) and SFT-016(TD) share a prefix and are different money. s.80TTA
# reaches a savings account and not a term deposit, so a reader that matched the
# prefix over-claimed the deduction by the whole deposit figure — and fed the
# same inflated number to reconcile_interest.py, which then reported a
# discrepancy against a bank account that was never missing.
check(savings["distinct_reporter_names"] == 4 and savings["blocks"] == 4
      and savings["total"] == 3400.0,
      f"the savings figure excludes term deposits: {savings}")
check(all("TermDeposit" not in r["reported_by"] for r in savings["reporters"]),
      "no term-deposit block appears among the savings reporters")

deposits = ais["term_deposit_interest_by_reporter"]
check(deposits["total"] == 2400.0 and deposits["blocks"] == 1
      and deposits["distinct_reporter_names"] == 1,
      f"term-deposit interest is reported separately and in full: {deposits}")
check("80TTA" in deposits["note"] and "80TTB" in deposits["note"],
      "the term-deposit block names s.80TTA and the s.80TTB senior-citizen case")
check("115BAC" in deposits["note"],
      "the term-deposit block says neither section survives the new regime")
# Every user-visible sentence carries provenance: a consumer reading the JSON or
# the summary never sees a source comment.
check(deposits["note"].count("[documented]") >= 3
      and "[inferred]" in deposits["note"],
      "each deduction conclusion in the emitted note is tagged")
# The script does not compute the deduction, so it states no threshold it
# cannot check.
check("50,000" not in deposits["note"] and "50000" not in deposits["note"],
      "the note claims no figure this script cannot verify")
# Being outside 80TTA and 80TTB does not make the money taxable: an NRE deposit
# may be exempt, and this script knows neither residence nor account type.
check("10(4)(ii)" in deposits["note"] and "taxable in full" not in deposits["note"],
      "the note does not declare every new-regime deposit taxable")

# A block whose amount cannot be read must not vanish: dropping it hides the
# account and makes an incomplete total look complete.
sys.path.insert(0, SCRIPTS)
from parse_tax_docs import reporter_counts as _reporter_counts  # noqa: E402

unreadable = [{"reported_by": "BANK ONE", "amount": 100.0},
              {"reported_by": "BANK TWO", "amount": None}]
named, unnamed = _reporter_counts(unreadable)
check((named, unnamed) == (2, 0),
      "a block with an unreadable amount still counts as a named reporter")

# Extraction can lose a block's source text. Folding unnamed blocks into a
# distinct-reporter count collapses every unknown bank into one and understates
# how many statements are still missing. No readable fixture produces a block
# with no source, so the counter is exercised directly.
sys.path.insert(0, SCRIPTS)
from parse_tax_docs import parse_ais as parse_ais_pages  # noqa: E402
from parse_tax_docs import reporter_counts  # noqa: E402

check(reporter_counts([{"reported_by": "BANK ONE", "amount": 100.0},
                       {"reported_by": None, "amount": 200.0},
                       {"reported_by": None, "amount": 300.0}]) == (1, 2),
      "two blocks with no readable reporter are counted separately, not as one bank")
check(reporter_counts([{"reported_by": "BANK ONE", "amount": 1.0},
                       {"reported_by": "BANK ONE", "amount": 2.0}]) == (1, 0),
      "one bank filing two blocks is still one bank")
check(reporter_counts([]) == (0, 0), "no blocks counts as no reporter names")

# COUNT and AMOUNT are both integers at the end of a summary row, so when
# extraction loses the amount the count slides into its place and a one-record
# block reads as 1 rupee. Position tells them apart; both are right-aligned.
_hdr = "    SR. NO.    INFORMATION  CODE    INFORMATION   DESCRIPTION    INFORMATION  SOURCE       COUNT           AMOUNT"
_full = "    1          SFT-016(TD)          Interestincome -TermDeposit    SPECIMEN BANK                   1            2,400"
_lost = "    1          SFT-016(TD)          Interestincome -TermDeposit    SPECIMEN BANK                   1"
_parsed_full = parse_ais_pages(["\n".join([_hdr, _full])])
_parsed_lost = parse_ais_pages(["\n".join([_hdr, _lost])])
check([e["amount"] for e in _parsed_full["entries"]] == [2400.0],
      f"the AMOUNT column is read from its own position: "
      f"{[e['amount'] for e in _parsed_full['entries']]}")
check([e["amount"] for e in _parsed_lost["entries"]] == [None],
      f"a row whose AMOUNT column is empty reports no amount, not the count: "
      f"{[e['amount'] for e in _parsed_lost['entries']]}")
check(savings["blocks_with_unread_reporter"] == 0
      and deposits["blocks_with_unread_reporter"] == 0,
      "a fixture whose reporters all read reports no unread-reporter blocks")

# The fixture's term deposit is filed by a bank that also files a savings block,
# which is what makes a distinct-reporter count different from a block count.
check({r["reported_by"] for r in deposits["reporters"]}
      & {r["reported_by"] for r in savings["reporters"]} == set(),
      "the two buckets never share a block even when one bank files both")

# ------------------------------------------------- AIS against the statements
def reconcile(*statements, ais="ais_synthetic.pdf", extra=(), code=0):
    proc = run("reconcile_interest.py",
               *[os.path.join(FIXTURES, s) for s in statements],
               "--ais", os.path.join(FIXTURES, ais), *extra, expect_code=code)
    return json.loads(proc.stdout or proc.stderr)


# The AIS side of this comparison is savings interest only, but a bank may
# credit a deposit's interest into the savings account, where the statement
# counts it. That makes a statement look larger than AIS by the deposit and
# reads as a missing account. Named rather than netted off: whether it was
# credited here is a fact about the account this script cannot see.
_dep = reconcile("bank_statement_dotted_synthetic.pdf",
                 extra=("--financial-year", "2025-26"))
check(_dep["ais_term_deposit_total_not_compared"] == 2400.0,
      f"the deposit total AIS reports separately is carried through: "
      f"{_dep.get('ais_term_deposit_total_not_compared')}")
check(any("term-deposit interest" in f and "NOT part of the comparison" in f
          for f in _dep["flags"]),
      "the reconciliation says the deposit is outside its comparison")


# AIS covers one financial year. A statement spanning two must not be summed
# until the caller explicitly selects the year being reconciled.
crossyear_path = os.path.join(FIXTURES, "bank_statement_crossyear_synthetic.pdf")
ais_path = os.path.join(FIXTURES, "ais_synthetic.pdf")
proc = run("reconcile_interest.py", crossyear_path, "--ais", ais_path)
crossyear_refusal = json.loads(proc.stdout or proc.stderr)
check(proc.returncode == 2
      and "more than one financial year" in crossyear_refusal.get("refused", "")
      and "--financial-year" in crossyear_refusal.get("refused", ""),
      "reconciliation refuses a multi-year statement until a year is selected")

# Path identity, not spelling, prevents one statement being counted twice. A
# relative path and an absolute path to the same file must therefore refuse.
duplicate_path = os.path.join(FIXTURES, "bank_statement_dotted_synthetic.pdf")
proc = run("reconcile_interest.py", os.path.relpath(duplicate_path, ROOT),
           duplicate_path, "--ais", ais_path)
duplicate_refusal = json.loads(proc.stdout or proc.stderr)
check(proc.returncode == 2
      and "same file" in duplicate_refusal.get("refused", ""),
      "reconciliation rejects duplicate statement inputs by resolved path")

rec = reconcile("bank_statement_dotted_synthetic.pdf")
check([(m["bank"], m["ais_amount"], m["statement_amount"], m["agrees"])
       for m in rec["matched"]] == [("HDFC", 1950.0, 1950.0, True)],
      f"a bank in both lists is matched by name against its IFSC-derived bank "
      f"and the figures compared: {rec['matched']}")
check([(r["bank"], r["ais_amount"])
       for r in rec["reported_to_ais_with_no_statement"]]
      == [("Kotak", 725.0), ("Standard Chartered", 640.0), ("DCB", 85.0)],
      f"every bank that reported without a statement is named with its figure: "
      f"{rec['reported_to_ais_with_no_statement']}")
check((rec["ais_total"], rec["statement_total"], rec["difference"])
      == (3400.0, 1950.0, 1450.0),
      f"the totals and the difference are exact: {rec['difference']}")
check(round(sum(r["ais_amount"]
                for r in rec["reported_to_ais_with_no_statement"]), 2)
      == rec["difference"],
      "every rupee of the difference is accounted for by a named account — that "
      "is what turns an unexplained shortfall into a list of statements to fetch")
check(any("where an unexplained shortfall" in f for f in rec["flags"]),
      "the missing accounts are flagged, not left in the JSON")
check(not re.search(r"\d{9,}", json.dumps(rec)),
      "no account number reaches the output")

# A statement that lost rows must not be reported as a bank that under-reported.
torn_rec = reconcile("bank_statement_torn_synthetic.pdf")
check(any("do not reconcile from their opening balance" in f
          and "may be theirs rather than a missing account" in f
          for f in torn_rec["flags"]),
      "a torn statement is called out before its shortfall is blamed on a "
      "missing account")

# The reverse direction: a bank AIS never mentions is still taxable.
sys.path.insert(0, SCRIPTS)
import reconcile_interest as interest_reconciliation  # noqa: E402
from reconcile_interest import (bank_from_reporter, report,  # noqa: E402
                                reconcile as join)

only = join([], [{"file": "x.pdf", "bank": "Axis",
                  "interest_credited": {"total": 500.0}}])
check(only["in_a_statement_but_not_reported_to_ais"][0]["bank"] == "Axis"
      and only["difference"] == -500.0,
      "interest a bank never reported to AIS is surfaced, not dropped")

overstated = join(
    [{"reported_by": "HDFC BANK LIMITED", "amount": 700.0}],
    [{"file": "x.pdf", "bank": "HDFC",
      "interest_credited": {"total": 500.0}}])
overstated_checks, overstated_flags = report(overstated)
overstated_guidance = " ".join(overstated_checks + overstated_flags)
check("[documented]" in overstated_guidance
      and "AIS feedback" in overstated_guidance
      and "statement" in overstated_guidance
      and "s.143(1)(a)" in overstated_guidance
      and "higher of the two" not in overstated_guidance
      and "Over-reporting never" not in overstated_guidance
      and "statement is the primary record" not in
          (interest_reconciliation.__doc__ or ""),
      "an AIS overstatement gets provenance-tagged resolution guidance, not an "
      "instruction to over-declare")

check(bank_from_reporter("STATE BANK OF INDIA") == "SBI"
      and bank_from_reporter("SOUTH INDIAN BANK LIMITED") == "South Indian"
      and bank_from_reporter("INDIAN BANK") == "Indian Bank",
      "a longer bank name never loses to a shorter one contained inside it")
check(bank_from_reporter("CPRC CHENNAI (AAAA00000A.AP001)") is None,
      "a reporting source that is not a bank is left unmatched rather than "
      "assigned to the nearest account")

# AIS reports one block per account. Two accounts at one bank must be summed
# before anything is compared, or the bank is reported twice, each row
# disagreeing, on a return that is in fact correct.
two = join([{"reported_by": "HDFC BANK LIMITED", "amount": 300.0},
            {"reported_by": "HDFC BANK LIMITED", "amount": 45.0}],
           [{"file": "a.pdf", "bank": "HDFC",
             "interest_credited": {"total": 345.0}}])
check([(m["bank"], m["accounts_reported"], m["ais_amount"], m["agrees"])
       for m in two["matched"]] == [("HDFC", 2, 345.0, True)],
      f"two accounts at one bank are summed before comparison: {two['matched']}")
check(two["difference"] == 0.0,
      "and the bank is not reported as disagreeing with itself")

# A block whose amount could not be read must shrink nothing silently.
blank = join([{"reported_by": "HDFC BANK LIMITED", "amount": None}], [])
check(blank["ais_blocks_with_no_readable_amount"] == 1 and blank["ais_total"] == 0.0,
      "a savings block with no readable amount is counted and reported, not "
      "dropped as if it were absent")
_, blank_flags = report(blank)
check(any("AIS total is therefore a floor" in f for f in blank_flags),
      "and the AIS total is called a floor when one is unreadable")

# An AIS with no savings block cannot be reconciled against anything.
refused = reconcile("bank_statement_dotted_synthetic.pdf",
                    ais="tis_synthetic.pdf", code=2)
check("no SFT-016 savings-interest block" in refused["refused"],
      "a document with no savings block is refused, not reconciled to zero")

# --------------------------------------------------------------- portal JSON
def portal(*names, code=0):
    proc = run("parse_portal_json.py",
               *[os.path.join(FIXTURES, n) for n in names], expect_code=code)
    return json.loads(proc.stdout or proc.stderr)


pre = portal("prefill_synthetic.json")["documents"][0]
check(pre["document"] == "prefill", "a prefill is told from a filed return")
check(not pre["refusals"], "the committed prefill fixture has no refusals")
check([b["bank"] for b in pre["bank_accounts"]] == ["Kotak", "HDFC", "DCB"],
      f"every bank on record is listed, named from its IFSC: "
      f"{[b['bank'] for b in pre['bank_accounts']]}")
check(sum(b["nominated_for_refund"] for b in pre["bank_accounts"]) == 1,
      "the account nominated for refund is identified")
check(pre["savings_bank_interest_by_source"] == {"AIS insights": 9000.0,
                                                 "employer Form 24Q": 9000.0},
      "savings interest is read from every source that states it")
check(not pre["flags"], f"a clean prefill raises nothing: {pre['flags']}")
check(json.dumps(pre).count("ABCDE1234F") == 0
      and json.dumps(pre).count("000011112222") == 0,
      "no PAN and no Aadhaar number reaches the output")

bad = portal("prefill_broken_synthetic.json")["documents"][0]
messages = " ".join(bad["flags"])
check("no account is nominated for refund" in messages,
      "a prefill with no refund account is flagged")
check("9,900 claimed against 1,200 deducted" in messages,
      "TDS credit above what was deducted is caught")
check("gross amount of zero" in messages,
      "tax deducted against a gross of zero is caught")
check("stated differently by different sources" in messages,
      "savings interest that disagrees between AIS and the employer is flagged")
check("lists dividend twice by design" in messages,
      "a dividend disagreement names the SFT-015 / TDS-194 double-count")

ret = portal("filed_itr3_synthetic.json")["documents"][0]
check((ret["document"], ret["form"]) == ("filed return", "ITR3"),
      "the form is read from the ITR wrapper")
check(ret["assessment_year"] == "2026", "the assessment year is reported as filed")
check(any("assessment year 2026-27" in c and "financial year 2025-26" in c
          for c in ret["checks"]),
      "AY 2026-27 is spelled out as FY 2025-26, against the Form 168 Tax Year trap")
check(not ret["refusals"], "the committed filed ITR-3 fixture has no refusals")
check(any("unread schedule(s) are not proven zero" in f
          and "PartB-TI" in f and "ScheduleOS" in f
          for f in ret["flags"]),
      f"populated unread income schedules are flags, not successful checks: "
      f"{ret['flags']}")
check(ret["taxes_paid"]["total"] == 75200.0 and ret["liability"]["aggregate"] == 63197.0,
      "the prepaid tax and the liability are read exactly")
check(ret["liability"]["refund_due"] == 12000.0,
      "a balance of 12,003 is stated as a refund of 12,000, and s.288B rounding "
      "is not reported as a defect")

sys.path.insert(0, SCRIPTS)
import parse_portal_json as portal_json  # noqa: E402
from parse_portal_json import round_288b  # noqa: E402

check([round_288b(n) for n in (66243, 7137, 35312, 4, 5, 14, 15)]
      == [66240, 7140, 35310, 0, 10, 10, 20],
      "s.288B rounds to the nearest ten, with five rounding up")

old = portal("filed_itr3_oldschema_synthetic.json")["documents"][0]
check(not old["refusals"],
      "the committed old-schema filed ITR-3 fixture has no refusals")
check(any("unread schedule(s) are not proven zero" in f
          and "PartB-TI" in f and "ScheduleOS" in f
          for f in old["flags"])
      and not any("refund account" in f for f in old["flags"]),
      f"the old schema flags its unread income without inventing a missing "
      f"refund account: {old['flags']}")
check(any("carries no UseForRefund flag" in c for c in old["checks"]),
      "the missing flag is stated rather than assumed either way")

cf = ret["carry_forward"]
check(cf["schedule_cfl"]["carried_forward"] == {
          "business, other than speculation":
              {"amount": 30000.0,
               "set_off_window": "8 years, against business income only"},
          "short-term capital loss":
              {"amount": 45000.0,
               "set_off_window": "8 years, against any capital gain"}},
      f"ScheduleCFL carry-forwards are read by head, with the window each one "
      f"survives: {cf['schedule_cfl']['carried_forward']}")
check(cf["unabsorbed_depreciation"] == 60000.0,
      "unabsorbed depreciation is read from ScheduleUD")
check(cf["amt_credit_115JD"] == 25000.0, "the AMT credit carried forward is read")

# Silence about a schedule must not read as approval of it.
check(ret["schedules_not_checked"] == ["PartB-TI", "ScheduleBP", "ScheduleOS"],
      f"every schedule this script does not read is named: "
      f"{ret['schedules_not_checked']}")
check(not any("schedule(s) in this return were not looked at" in c
              for c in ret["checks"]),
      "unread schedules are never presented as successful checks")

broken_ret = portal("filed_itr3_broken_synthetic.json")["documents"][0]
msgs = " ".join(broken_ret["flags"])
check("Schedule TDS2 (other than salary): the rows add to 5,200" in msgs,
      "a TDS schedule whose rows do not add to its own total is caught")
check("Part B-TTI claims TDS of 61,000" in msgs,
      "Part B-TTI disagreeing with the TDS schedules is caught")
check("total taxes paid is stated as 78,500" in msgs,
      "total taxes paid that is not the sum of its components is caught")
check("both a refund" in msgs and "balance payable" in msgs,
      "a return claiming a refund and a balance payable at once is caught")
check("neither 'TaxPayment' nor 'TotalTaxPayments' was found" in msgs,
      "a schedule under names this script does not know is reported, not skipped")
check(len(broken_ret["flags"]) == 6
      and any("unread schedule(s) are not proven zero" in f
              for f in broken_ret["flags"]),
      f"the five planted breaks plus the unread-income caveat are exact: "
      f"{broken_ret['flags']}")
check(not any("ScheduleTDS3" in f or "Schedule TCS" in f for f in ret["flags"]),
      "an empty schedule stating a zero total is not reported as a schema change")

both = portal("prefill_synthetic.json", "filed_itr3_synthetic.json")
check(any("same taxpayer" in c for c in both["checks"]),
      "two files for one taxpayer are recognised as such")
check(any("exactly what the prefill offered" in c for c in both["checks"]),
      "the TDS claimed in the return is reconciled against the prefill")
check("ABCDE1234F" not in json.dumps(both),
      "the cross-check compares PANs without printing one")

# The broken prefill offers 55,000 salary TDS + 4,000 + 9,900 claimed = 68,900;
# the return claims 60,200. Assert the figures, not that something was said.
mixed = portal("prefill_broken_synthetic.json", "filed_itr3_synthetic.json")
check(any("the prefill offers 68,900 of TDS and the return claims 60,200" in f
          for f in mixed["flags"]),
      f"a prefill and a return that disagree on TDS are flagged with both "
      f"figures: {mixed['flags']}")

# ITR-5, ITR-6 and ITR-7 exist and are not this skill's forms. Reading one would
# produce figures that look right.
for form, who in [("ITR5", "firm"), ("ITR6", "company"), ("ITR7", "trust")]:
    out_of_scope = os.path.join(scratch, f"{form}.json")
    with open(out_of_scope, "w") as fh:
        json.dump({"ITR": {form: {"PartB_TTI": {}}}}, fh)
    proc = run("parse_portal_json.py", out_of_scope, expect_code=2)
    check(f"{form[:3]}-{form[3:]}" in proc.stderr and who in proc.stderr,
          f"an {form[:3]}-{form[3:]} is refused as the return of a {who}, not "
          f"read as an individual's")

# ---- the review findings on this branch, each pinned ----
# The portal names its downloads after the taxpayer, and every script was
# copying that name into its output verbatim.
from redact import safe_name  # noqa: E402

check(safe_name("/tmp/ABCDE1234F_upload_2026-27.json")
      == "<redacted>_upload_2026-27.json",
      "a PAN in a file name is masked even though `_` defeats a word boundary")
check(safe_name("Form168_ABCDE1234F_2026-27.pdf")
      == "Form168_<redacted>_2026-27.pdf",
      "and one in the middle of a name is masked too")
check(safe_name("kotak.pdf") == "kotak.pdf",
      "an ordinary file name is left alone")

leaky = os.path.join(scratch, "ABCDE1234F_upload_2026-27.json")
shutil.copy(os.path.join(FIXTURES, "filed_itr3_synthetic.json"), leaky)
proc = run("parse_portal_json.py", leaky, expect_code=0)
check("ABCDE1234F" not in proc.stdout,
      "no PAN reaches the output through the file name it was read from")
broken_name = os.path.join(scratch, "ABCDE1234F_unparseable.json")
with open(broken_name, "w") as fh:
    fh.write("{")
proc = run("parse_portal_json.py", broken_name, expect_code=2)
check("ABCDE1234F" not in proc.stderr and "<redacted>" in proc.stderr,
      "and none reaches a refusal message either")


def variant(name, mutate):
    with open(os.path.join(FIXTURES, "filed_itr3_synthetic.json")) as fh:
        doc = json.load(fh)
    mutate(doc["ITR"]["ITR3"])
    path = os.path.join(scratch, name)
    with open(path, "w") as fh:
        json.dump(doc, fh)
    return path


def flags_of(path, code=0):
    proc = run("parse_portal_json.py", path, expect_code=code)
    return " ".join(json.loads(proc.stdout or proc.stderr)["documents"][0]["flags"])


def refusal_message(proc):
    try:
        return json.loads(proc.stderr).get("refused", "")
    except json.JSONDecodeError:
        return ""


def has_unverified_reporting_instruction(message, form, schema_version):
    return ("[UNVERIFIED]" in message
            and "identifier-free specimen" in message
            and "report it as a parser bug" in message
            and form in message
            and schema_version in message)


REQUIRED_ARITHMETIC_PATHS = [
    "ComputationOfTaxLiability.NetTaxLiability",
    "ComputationOfTaxLiability.IntrstPay.TotalIntrstPay",
    "ComputationOfTaxLiability.AggregateTaxInterestLiability",
    "TaxPaid.TaxesPaid.AdvanceTax",
    "TaxPaid.TaxesPaid.TDS",
    "TaxPaid.TaxesPaid.TCS",
    "TaxPaid.TaxesPaid.SelfAssessmentTax",
    "TaxPaid.TaxesPaid.TotalTaxesPaid",
]


def minimal_filed_return(form, required_value=0, unread_value=...):
    itr = {
        f"Form_{form}": {"SchemaVer": f"numeric-leaf-{form.lower()}"},
        "PartA_GEN1": {
            "PersonalInfo": {"Status": "I"},
            "FilingStatus": {"ResidentialStatus": "RES"},
        },
        "PartB_TTI": {
            "ComputationOfTaxLiability": {
                "NetTaxLiability": required_value,
                "IntrstPay": {"TotalIntrstPay": required_value},
                "AggregateTaxInterestLiability": required_value,
            },
            "TaxPaid": {
                "TaxesPaid": {
                    "AdvanceTax": required_value,
                    "TDS": required_value,
                    "TCS": required_value,
                    "SelfAssessmentTax": required_value,
                    "TotalTaxesPaid": required_value,
                },
                "BalTaxPayable": 0,
            },
            "Refund": {"RefundDue": 0},
        },
    }
    if unread_value is not ...:
        itr["PartB-TI"] = {"TotalIncome": unread_value}
    return {"ITR": {form: itr}}


def write_portal_case(name, doc):
    path = os.path.join(scratch, name)
    with open(path, "w") as fh:
        json.dump(doc, fh)
    return path


# Schedule TCS and Part B-TTI state the same credit. Inflating only Part B-TTI
# used to pass because TotalTaxesPaid and the refund were inflated with it.
def _unsupported_tcs(r):
    r["ScheduleTCS"] = {
        "TCS": [{"AmtTCSClaimedThisYear": 100}],
        "TotalSchTCS": 100,
    }
    paid = r["PartB_TTI"]["TaxPaid"]["TaxesPaid"]
    paid["TCS"] = 500
    paid["TotalTaxesPaid"] = 75700
    r["PartB_TTI"]["Refund"]["RefundDue"] = 12500


check("Part B-TTI claims TCS of 500 but Schedule TCS adds to 100" in flags_of(
          variant("unsupported_tcs.json", _unsupported_tcs)),
      "TCS claimed in Part B-TTI above what Schedule TCS supports is caught")

# The liability and payment identities are meaningless without the core
# Part B-TTI objects. A truncated return must refuse before any zero arithmetic.
missing_tti = os.path.join(scratch, "missing_partb_tti.json")
with open(missing_tti, "w") as fh:
    json.dump({"ITR": {"ITR3": {}}}, fh)
proc = run("parse_portal_json.py", missing_tti, expect_code=2)
refused = refusal_message(proc)
check("PartB_TTI" in refused and "Traceback" not in proc.stderr,
      "a filed return with no PartB_TTI is refused before arithmetic")

no_computation = variant(
    "missing_computation.json",
    lambda r: r["PartB_TTI"].pop("ComputationOfTaxLiability"))
proc = run("parse_portal_json.py", no_computation, expect_code=2)
refused = refusal_message(proc)
check("ComputationOfTaxLiability" in refused
      and "Traceback" not in proc.stderr,
      "a PartB_TTI with no ComputationOfTaxLiability is refused")

no_taxes_paid = variant(
    "missing_taxes_paid.json",
    lambda r: r["PartB_TTI"]["TaxPaid"].pop("TaxesPaid"))
proc = run("parse_portal_json.py", no_taxes_paid, expect_code=2)
refused = refusal_message(proc)
check("TaxPaid.TaxesPaid" in refused
      and "Traceback" not in proc.stderr,
      "a PartB_TTI with no TaxPaid.TaxesPaid is refused")

# Object truthiness is not evidence that the figures used by the arithmetic
# exist. Pin the review reproduction across every accepted filed-return form.
for form in ("ITR2", "ITR3", "ITR4"):
    schema_version = f"review-probe-{form.lower()}"
    schema_marker = os.path.join(scratch, f"schema_marker_{form.lower()}.json")
    with open(schema_marker, "w") as fh:
        json.dump({
            "ITR": {form: {
                f"Form_{form}": {"SchemaVer": schema_version},
                "PartA_GEN1": {
                    "PersonalInfo": {"Status": "I"},
                    "FilingStatus": {"ResidentialStatus": "RES"},
                },
                "PartB_TTI": {
                    "ComputationOfTaxLiability": {"SchemaMarker": "present"},
                    "TaxPaid": {
                        "TaxesPaid": {"SchemaMarker": "present"},
                    },
                },
            }},
        }, fh)
    proc = run("parse_portal_json.py", schema_marker, expect_code=2)
    refused = refusal_message(proc)
    check("NetTaxLiability" in refused and "TotalTaxesPaid" in refused
          and has_unverified_reporting_instruction(
              refused, form, schema_version)
          and "Traceback" not in proc.stderr,
          f"unrelated keys cannot satisfy required tax fields for {form}, and "
          "the refusal carries the unverified-schema reporting path")

# Empty required objects carry no arithmetic fields. Explicit zeros are the
# synthetic contract this project can test; whether real portal exports omit
# zero-valued fields remains unverified and must be stated in every refusal.
for form in ("ITR2", "ITR3", "ITR4"):
    empty_tti = os.path.join(scratch, f"empty_partb_tti_{form.lower()}.json")
    with open(empty_tti, "w") as fh:
        json.dump({"ITR": {form: {"PartB_TTI": {}}}}, fh)
    proc = run("parse_portal_json.py", empty_tti, expect_code=2)
    refused = refusal_message(proc)
    check("ComputationOfTaxLiability" in refused and "[UNVERIFIED]" in refused
          and "Traceback" not in proc.stderr,
          f"a PartB_TTI with no required tax objects is refused for {form}")

empty_computation = variant(
    "empty_computation.json",
    lambda r: r["PartB_TTI"].update({"ComputationOfTaxLiability": {}}))
proc = run("parse_portal_json.py", empty_computation, expect_code=2)
refused = refusal_message(proc)
check("ComputationOfTaxLiability.NetTaxLiability" in refused
      and "ComputationOfTaxLiability.IntrstPay.TotalIntrstPay" in refused
      and "ComputationOfTaxLiability.AggregateTaxInterestLiability" in refused
      and "[UNVERIFIED]" in refused
      and "Traceback" not in proc.stderr,
      "an empty ComputationOfTaxLiability names every absent arithmetic field")

empty_taxes_paid = variant(
    "empty_taxes_paid.json",
    lambda r: r["PartB_TTI"]["TaxPaid"].update({"TaxesPaid": {}}))
proc = run("parse_portal_json.py", empty_taxes_paid, expect_code=2)
refused = refusal_message(proc)
check("TaxPaid.TaxesPaid.AdvanceTax" in refused
      and "TaxPaid.TaxesPaid.TDS" in refused
      and "TaxPaid.TaxesPaid.TCS" in refused
      and "TaxPaid.TaxesPaid.SelfAssessmentTax" in refused
      and "TaxPaid.TaxesPaid.TotalTaxesPaid" in refused
      and "[UNVERIFIED]" in refused
      and "Traceback" not in proc.stderr,
      "an empty TaxPaid.TaxesPaid names every absent arithmetic field")

partial_liability = variant(
    "partial_liability.json",
    lambda r: (r["PartB_TTI"]["ComputationOfTaxLiability"].pop("IntrstPay"),
               r["PartB_TTI"]["ComputationOfTaxLiability"].pop(
                   "AggregateTaxInterestLiability")))
proc = run("parse_portal_json.py", partial_liability, expect_code=2)
refused = refusal_message(proc)
check("ComputationOfTaxLiability.IntrstPay.TotalIntrstPay" in refused
      and "ComputationOfTaxLiability.AggregateTaxInterestLiability" in refused
      and "ComputationOfTaxLiability.NetTaxLiability" not in refused,
      "a partial liability block names only the required fields that are absent")

partial_payment = variant(
    "partial_payment.json",
    lambda r: r["PartB_TTI"]["TaxPaid"]["TaxesPaid"].pop("TCS"))
proc = run("parse_portal_json.py", partial_payment, expect_code=2)
refused = refusal_message(proc)
check("TaxPaid.TaxesPaid.TCS" in refused
      and "TaxPaid.TaxesPaid.TDS" not in refused,
      "a partial payment block names the required field that is absent")

# Required leaves must be usable numbers, not merely present. Keep this table
# broad so the next unexpected JSON value is added here instead of inspiring a
# fourth proxy guard. The refusal must name all eight paths and the value class.
invalid_required_values = [
    ("question-mark", "?", "non-numeric string", True),
    ("array", [], "array", True),
    ("object", {}, "object", True),
    ("false", False, "boolean", True),
    ("null", None, "null", True),
    ("string-NaN", "NaN", "non-finite numeric string", True),
    ("string-nan", "nan", "non-finite numeric string", True),
    ("string-inf", "inf", "non-finite numeric string", True),
    ("string-Infinity", "Infinity", "non-finite numeric string", True),
    ("string-negative-Infinity", "-Infinity",
     "non-finite numeric string", True),
    ("integer-outside-float-range", 10 ** 400,
     "outside the finite number range", True),
    # json.dump writes this as a bare NaN token. Python accepts that extension
    # by default even though RFC 8259 does not; the input boundary must refuse it.
    ("bare-NaN", float("nan"), "non-finite numeric constant NaN", False),
]
for case_name, value, reason, expect_paths in invalid_required_values:
    path = write_portal_case(
        f"required_leaf_{case_name}.json",
        minimal_filed_return("ITR1", required_value=value))
    proc = run("parse_portal_json.py", path, expect_code=2)
    refused = refusal_message(proc)
    path_evidence = (all(field in refused for field in REQUIRED_ARITHMETIC_PATHS)
                     and has_unverified_reporting_instruction(
                         refused, "ITR1", "numeric-leaf-itr1"))
    check((path_evidence if expect_paths else "RFC 8259" in refused)
          and reason in refused and "Traceback" not in proc.stderr,
          f"required leaves containing {case_name} refuse with every path, the "
          "value class and the applicable input/reporting boundary")

valid_required_values = [
    ("numeric-zero", 0, 0.0),
    ("string-zero", "0", 0.0),
    ("formatted-numeric-string", "3,400", 3400.0),
    ("decimal-number", 3400.5, 3400.5),
]
for case_name, value, expected in valid_required_values:
    path = write_portal_case(
        f"required_leaf_{case_name}.json",
        minimal_filed_return("ITR1", required_value=value))
    proc = run("parse_portal_json.py", path, expect_code=0)
    doc = json.loads(proc.stdout)["documents"][0] if proc.returncode == 0 else {}
    check(proc.returncode == 0 and not doc["refusals"]
          and doc["liability"]["net_tax"] == expected
          and doc["taxes_paid"]["total"] == expected,
          f"required leaves containing {case_name} remain usable numbers")

strict_json_dumps = getattr(portal_json, "strict_json_dumps", None)
strict_output_refused = False
if strict_json_dumps:
    try:
        strict_json_dumps({"poison": float("nan")})
    except Exception as exc:
        strict_output_refused = ("non-finite" in str(exc)
                                 and "No JSON was emitted" in str(exc))
check(strict_output_refused,
      "the parser's serialization boundary refuses non-finite output before "
      "emitting invalid JSON")

populated_unread = variant(
    "populated_unread_income.json",
    lambda r: r.update({"ScheduleBP": {"BusinessIncOthThanSpec": 250000}}))
populated_doc = json.loads(run(
    "parse_portal_json.py", populated_unread, expect_code=0).stdout)["documents"][0]
check(any("unread schedule(s) are not proven zero" in f
          and "ScheduleBP" in f for f in populated_doc["flags"]),
      "a populated unread business-income schedule produces a specific flag")
check(any("[UNVERIFIED] The presumptive blocks under s.44AD, s.44ADA and "
          "s.44AE are not mapped" in flag
          for flag in populated_doc["flags"]),
      "the unread-schedule flag tags the unseen ITR-4 schema claim unverified")


def _zero_only_unread(r):
    r.pop("PartB-TI")
    r.pop("ScheduleOS")
    r["ScheduleBP"] = {"BusinessIncOthThanSpec": 0}


zero_only_doc = json.loads(run(
    "parse_portal_json.py",
    variant("zero_only_unread_income.json", _zero_only_unread),
    expect_code=0).stdout)["documents"][0]
check(zero_only_doc["schedules_not_checked"] == ["ScheduleBP"]
      and not any("unread schedule(s) are not proven zero" in f
                  for f in zero_only_doc["flags"]),
      "an explicit-zero-only unread schedule stays visible without creating a "
      "material-data flag")

indeterminate_unread = write_portal_case(
    "indeterminate_unread_income.json",
    minimal_filed_return("ITR1", unread_value=None))
indeterminate_doc = json.loads(run(
    "parse_portal_json.py", indeterminate_unread,
    expect_code=0).stdout)["documents"][0]
check(any("unread schedule(s) are not proven zero" in flag
          and "PartB-TI" in flag for flag in indeterminate_doc["flags"]),
      "an unread income schedule with an indeterminate leaf is flagged")

explicit_zero_unread = write_portal_case(
    "explicit_zero_unread_income.json",
    minimal_filed_return("ITR1", unread_value=0))
explicit_zero_unread_doc = json.loads(run(
    "parse_portal_json.py", explicit_zero_unread,
    expect_code=0).stdout)["documents"][0]
check(explicit_zero_unread_doc["schedules_not_checked"] == ["PartB-TI"]
      and not any("unread schedule(s) are not proven zero" in flag
                  for flag in explicit_zero_unread_doc["flags"]),
      "an unread income schedule whose only leaf is explicit zero stays quiet")

unread_summary = run(
    "parse_portal_json.py", explicit_zero_unread, "--summary",
    expect_code=0).stdout
check("schedules not checked: PartB-TI" in unread_summary,
      "summary mode names an unread schedule even when it is proven zero")

# Valid JSON is not necessarily an object. Every other JSON root type must get
# the same structured refusal rather than an AttributeError traceback.
for root_value, root_kind in [([], "array"), ("text", "string"),
                              (42, "number"), (True, "boolean"),
                              (None, "null")]:
    root_path = os.path.join(scratch, f"root_{root_kind}.json")
    with open(root_path, "w") as fh:
        json.dump(root_value, fh)
    proc = run("parse_portal_json.py", root_path, expect_code=2)
    refused = refusal_message(proc)
    check(root_kind in refused and "object" in refused
          and "Traceback" not in proc.stderr,
          f"a JSON {root_kind} root gets a structured refusal")

# Schedule SI cannot tie to its own total when TotSplRateInc is absent.
no_si_total = variant(
    "missing_si_total.json", lambda r: r["ScheduleSI"].pop("TotSplRateInc"))
proc = run("parse_portal_json.py", no_si_total, expect_code=0)
si_doc = json.loads(proc.stdout)["documents"][0]
check(any("Schedule SI" in f and "no stated total" in f for f in si_doc["flags"])
      and not any(c.startswith("Schedule SI:")
                  and "ties to the schedule's own total" in c
                  for c in si_doc["checks"]),
      "live Schedule SI rows without TotSplRateInc are not claimed reconciled")


# Schedule IT holds the challans behind advance and self-assessment tax, and
# Part B-TTI states the same figures. Nothing compared the two.
no_challans = variant("no_challans.json",
                      lambda r: r["ScheduleIT"].update(
                          {"TaxPayment": [], "TotalTaxPayments": 0}))
check("Schedule IT accounts for 0" in flags_of(no_challans),
      "advance and self-assessment tax claimed with no challan behind it is "
      "caught")

# Taxes paid exactly equal the liability, and the return still claims a refund.
def _zero_balance(r):
    r["PartB_TTI"]["TaxPaid"]["TaxesPaid"]["TotalTaxesPaid"] = 63197
    r["PartB_TTI"]["TaxPaid"]["TaxesPaid"]["AdvanceTax"] = 2803
    r["PartB_TTI"]["Refund"]["RefundDue"] = 12000


check("nothing to pay and nothing to refund" in flags_of(
          variant("zero_balance.json", _zero_balance)),
      "a refund claimed when the balance is exactly zero is caught, rather than "
      "falling through to the success branch")

# ITR-2 and ITR-3 are filed by HUFs too; the form alone proves nothing.
huf = variant("huf.json",
              lambda r: r["PartA_GEN1"]["PersonalInfo"].update({"Status": "H"}))
proc = run("parse_portal_json.py", huf, expect_code=3)
refusals = " ".join(json.loads(proc.stdout)["documents"][0]["refusals"])
check("'H'" in refusals and "HUF" in refusals,
      f"an HUF return is refused rather than read as an individual's: {refusals}")

# A file with no readable PAN cannot be said to belong to the same taxpayer.
anon = os.path.join(scratch, "anonymous.json")
with open(os.path.join(FIXTURES, "prefill_synthetic.json")) as fh:
    doc = json.load(fh)
doc["personalInfo"].pop("pan")
with open(anon, "w") as fh:
    json.dump(doc, fh)
proc = run("parse_portal_json.py", anon,
           os.path.join(FIXTURES, "filed_itr3_synthetic.json"), expect_code=0)
both_files = json.loads(proc.stdout)
check(any("cannot be confirmed to belong to the same taxpayer" in f
          for f in both_files["flags"]),
      f"a file with no PAN is not counted as agreeing with the ones that have "
      f"one: {both_files['flags']}")
check(not any("all 2 files belong to the same taxpayer" in c
              for c in both_files["checks"]),
      "and the same-taxpayer claim is withheld")

# A truncated AES stream must refuse rather than return the part that decodes.
try:
    aes_cbc_decrypt(b"k" * 16, b"\x00" * 16 + b"\x01" * 20)
    check(False, "a truncated AES stream is refused")
except CryptError as e:
    check("truncated" in str(e), "a truncated AES stream is refused, not "
                                 "silently shortened")

# Anything that is neither must be refused, not guessed at.
notjson = os.path.join(scratch, "_not_a_return.json")
with open(notjson, "w") as fh:
    fh.write('{"something": "else"}')
proc = run("parse_portal_json.py", notjson, expect_code=2)
check("neither a prefill nor a filed return" in proc.stderr,
      "a JSON that is neither document is refused, not guessed at")

# --------------------------------------------------------- summary contracts
def summary_messages(value):
    messages = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"flags", "refusals"} and isinstance(item, list):
                messages.extend(message for message in item
                                if isinstance(message, str))
            else:
                messages.extend(summary_messages(item))
    elif isinstance(value, list):
        for item in value:
            messages.extend(summary_messages(item))
    return messages


def summary_contract(script, clean_args, flagged_args, *, refusal_args=None,
                     text_args=None):
    clean_json = run(script, *clean_args)
    clean_summary = run(script, *clean_args, "--summary")
    flagged_json = run(script, *flagged_args)
    flagged_summary = run(script, *flagged_args, "--summary")
    flagged_result = json.loads(flagged_json.stdout)
    messages = summary_messages(flagged_result)

    json_path = os.path.join(scratch, script.removesuffix(".py") + "-summary.json")
    combined = run(script, *flagged_args, "--summary", "--json", json_path)
    try:
        with open(json_path, encoding="utf-8") as fh:
            combined_json = json.load(fh)
    except (OSError, json.JSONDecodeError):
        combined_json = None

    ok = (
        clean_summary.returncode == clean_json.returncode
        and flagged_summary.returncode == flagged_json.returncode
        and combined.returncode == flagged_json.returncode
        and combined_json == flagged_result
        and messages
        and all(message in flagged_summary.stdout.splitlines()
                for message in messages)
        and all(message in combined.stdout.splitlines() for message in messages)
        and not flagged_summary.stdout.lstrip().startswith("{")
    )

    if refusal_args:
        refusal_json = run(script, *refusal_args)
        refusal_summary = run(script, *refusal_args, "--summary")
        refusal_result = json.loads(refusal_json.stdout)
        refusals = summary_messages(refusal_result)
        ok = (ok and refusal_summary.returncode == refusal_json.returncode
              and refusals
              and all(message in refusal_summary.stdout.splitlines()
                      for message in refusals))

    if text_args:
        conflict = run(script, *text_args, "--summary", "--text")
        try:
            conflict_result = json.loads(conflict.stderr)
        except json.JSONDecodeError:
            conflict_result = {}
        ok = (ok and conflict.returncode == 2
              and "two different stdout modes" in conflict_result.get("refused", ""))

    check(ok, f"{script} --summary preserves codes, full JSON files, flags and refusals")


summary_contract(
    "parse_tax_docs.py",
    [os.path.join(FIXTURES, "tis_synthetic.pdf")],
    [os.path.join(FIXTURES, "ais_synthetic.pdf")],
    text_args=[os.path.join(FIXTURES, "tis_synthetic.pdf")],
)
summary_contract(
    "parse_bank_statement.py",
    [os.path.join(FIXTURES, "bank_statement_dotted_synthetic.pdf")],
    [os.path.join(FIXTURES, "bank_statement_torn_synthetic.pdf")],
    text_args=[os.path.join(FIXTURES, "bank_statement_dotted_synthetic.pdf")],
)
# parse_capital_gains.py is deliberately outside summary_contract: its --json
# writes the FULL row detail while stdout truncates records to a sample, so the
# contract's "the file equals stdout" clause would force that feature out. The
# properties that do apply are asserted directly.
_cg_clean = os.path.join(FIXTURES, "zerodha_tax_pnl_synthetic.xlsx")
_cg_flagged = os.path.join(FIXTURES, "adversarial_layout_synthetic.xlsx")
_cg_json = run("parse_capital_gains.py", _cg_flagged)
_cg_summary = run("parse_capital_gains.py", _cg_flagged, "--summary")
_cg_result = json.loads(_cg_json.stdout)
_cg_messages = summary_messages(_cg_result)
check(_cg_summary.returncode == _cg_json.returncode
      and not _cg_summary.stdout.lstrip().startswith("{")
      and _cg_messages
      and all(m in _cg_summary.stdout.splitlines() for m in _cg_messages),
      "parse_capital_gains.py --summary keeps the exit code and every flag")
check(run("parse_capital_gains.py", _cg_clean, "--summary").returncode
      == run("parse_capital_gains.py", _cg_clean).returncode,
      "parse_capital_gains.py --summary keeps the exit code on a clean file")
check("NOT in any total until answered" in _cg_summary.stdout,
      "the summary says an unresolved bucket is excluded from the totals")
summary_contract(
    "parse_portal_json.py",
    [os.path.join(FIXTURES, "filed_itr3_synthetic.json")],
    [os.path.join(FIXTURES, "filed_itr3_broken_synthetic.json")],
    refusal_args=[huf],
)
summary_contract(
    "reconcile_interest.py",
    [os.path.join(FIXTURES, "bank_statement_dotted_synthetic.pdf"),
     "--ais", os.path.join(FIXTURES, "ais_synthetic.pdf")],
    [os.path.join(FIXTURES, "bank_statement_torn_synthetic.pdf"),
     "--ais", os.path.join(FIXTURES, "ais_synthetic.pdf")],
)

# A summary may condense detail, but never the qualifier that makes a figure
# safe to act on: what it is, which period it belongs to, and whether a count is
# an aggregate.
tis_summary = run(
    "parse_tax_docs.py", os.path.join(FIXTURES, "tis_synthetic.pdf"),
    "--summary", expect_code=0).stdout
sale_lines = [line for line in tis_summary.splitlines()
              if "Sale of securities and mutual-fund units" in line]
check(sale_lines
      and all("consideration" in line.lower() and "not gain" in line.lower()
              for line in sale_lines)
      and "broker Tax P&L is mandatory" in tis_summary,
      "the TIS summary labels securities proceeds as consideration, not gain, "
      "and retains the broker Tax P&L requirement")

ais_summary = run(
    "parse_tax_docs.py", os.path.join(FIXTURES, "ais_synthetic.pdf"),
    "--summary", expect_code=0).stdout
check("FY 2025-26" in tis_summary and "FY 2025-26" in ais_summary,
      "AIS and TIS summary headings name their financial year")
check("TDS-192 reported gross amount (not TDS deducted)" in ais_summary
      and "SFT-17-LES(M) sale consideration (not gain)" in ais_summary,
      "the AIS summary distinguishes gross reported amounts and sale "
      "consideration from tax deducted and gain")

bank_year_summary = run(
    "parse_bank_statement.py",
    os.path.join(FIXTURES, "bank_statement_crossyear_synthetic.pdf"),
    "--financial-year", "2025-26", "--summary", expect_code=0).stdout
check("FY 2025-26" in bank_year_summary,
      "a filtered bank-statement summary names the selected financial year")

filed_summary = run(
    "parse_portal_json.py",
    os.path.join(FIXTURES, "filed_itr3_synthetic.json"),
    "--summary", expect_code=0).stdout
check("AY 2026-27" in filed_summary and "assessment year: 2026\n" not in filed_summary,
      "a filed-return summary prints the normalised assessment year")

prefill_summary = run(
    "parse_portal_json.py", os.path.join(FIXTURES, "prefill_synthetic.json"),
    "--summary", expect_code=0).stdout
check("AIS insights: ₹9,000.00" in prefill_summary
      and "employer Form 24Q: ₹9,000.00" in prefill_summary
      and "₹18,000.00" not in prefill_summary,
      "a prefill summary attributes monetary figures to each source without "
      "choosing or summing them")

ais_builder_path = os.path.join(FIXTURES, "build_ais_synthetic.py")
ais_builder_spec = importlib.util.spec_from_file_location(
    "build_ais_summary_count_fixture", ais_builder_path)
ais_builder = importlib.util.module_from_spec(ais_builder_spec)
ais_builder_spec.loader.exec_module(ais_builder)
first_kotak = ais_builder.SAVINGS[1]
second_kotak = (
    first_kotak[0].replace("AB002", "AB005"),
    first_kotak[1],
    first_kotak[2][:-1] + "5",
    "275",
)
ais_builder.SAVINGS = [first_kotak, second_kotak]
two_account_ais = os.path.join(scratch, "ais_two_kotak_accounts.pdf")
ais_builder.write_pdf(
    two_account_ais,
    ais_builder.page_header() + ais_builder.part_b1() + ais_builder.part_b2(),
)
two_account_summary = run(
    "reconcile_interest.py",
    os.path.join(FIXTURES, "bank_statement_dotted_synthetic.pdf"),
    "--ais", two_account_ais, "--summary", expect_code=0).stdout
check("AIS accounts without statements: 2" in two_account_summary
      and "2 account(s) reported" in two_account_summary,
      "the reconciliation summary counts both unmatched AIS accounts at one bank")

# ------------------------------------------------------ repository guard rails
scan_pii = load_ci_script("scan_pii.py")
image = os.path.join(scratch, "fixture.png")
with open(image, "wb") as fh:
    fh.write(b"\x89PNG\r\n\x1a\nsynthetic fixture pixels")

problems = scan_pii.reviewed_image_problems([image], root=scratch, reviewed={})
check(any("no REVIEWED_IMAGES entry" in p for p in problems),
      "an unreviewed raster file fails closed")

with open(image, "rb") as fh:
    digest = hashlib.sha256(fh.read()).hexdigest()
reviewed = {"fixture.png": (digest, "checked that the image is synthetic")}
check(scan_pii.reviewed_image_problems([image], root=scratch, reviewed=reviewed) == [],
      "a human review is bound to the raster's exact SHA-256 and note")

with open(image, "ab") as fh:
    fh.write(b"changed")
problems = scan_pii.reviewed_image_problems([image], root=scratch, reviewed=reviewed)
check(any("SHA-256 changed" in p for p in problems),
      "editing a reviewed image invalidates its review")
problems = scan_pii.reviewed_image_problems([], root=scratch, reviewed=reviewed)
check(any("is stale" in p for p in problems),
      "a REVIEWED_IMAGES entry for a deleted raster fails")

counts = load_ci_script("check_stated_counts.py")
with open(os.path.join(SKILL, "SKILL.md"), encoding="utf-8") as fh:
    skill_frontmatter = fh.read().split("---", 2)[1]
check('last-verified: "2026-07-31"' in skill_frontmatter,
      "the skill verification date reflects the statutory-cutoff review")
manifest_version = "0.1.0"
complete_marketplace = {
    "metadata": {"version": manifest_version},
    "plugins": [{"version": manifest_version}],
}
versions, problems = counts.required_marketplace_versions(
    complete_marketplace, manifest_version)
check(not problems and set(versions.values()) == {manifest_version}
      and len(versions) == 2,
      "both required marketplace version paths are found explicitly")

_, problems = counts.required_marketplace_versions(
    {"metadata": {}, "plugins": [{"version": manifest_version}]},
    manifest_version)
check(any("metadata.version is missing" in p for p in problems),
      "deleting marketplace metadata.version fails with the exact path")

_, problems = counts.required_marketplace_versions(
    {"metadata": {"version": manifest_version}, "plugins": [{}]},
    manifest_version)
check(any("plugins[0].version is missing" in p for p in problems),
      "deleting marketplace plugins[0].version fails with the exact path")

shutil.rmtree(scratch, ignore_errors=True)

print()
if failures:
    print(f"{len(failures)} FAILURE(S):")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("Parsers behave as documented.")
