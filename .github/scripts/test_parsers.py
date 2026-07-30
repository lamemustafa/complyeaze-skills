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

fixture_pdf_names = sorted(
    name for name in os.listdir(FIXTURES) if name.endswith(".pdf"))
fixture_open_failures = []
for fixture_name in fixture_pdf_names:
    fixture_password = (PW if "_user_" in fixture_name
                        or "encrypted_r4_aes_128_objstm" in fixture_name else None)
    try:
        extract_pages(os.path.join(FIXTURES, fixture_name), fixture_password)
    except (PdfError, CryptError) as exc:
        fixture_open_failures.append(f"{fixture_name}: {exc}")
check(len(fixture_pdf_names) == 15 and not fixture_open_failures,
      f"all 14 existing fixture PDFs plus the Java envelope open: "
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
                                            "SFT-17-LES(M)": 12407.0},
      f"every information code totals exactly: {ais['totals_by_information_code']}")

# Which account. Savings interest is reported one block per bank, and that is
# the only place any document says which bank reported what.
savings = ais["savings_bank_interest_by_reporter"]
check(savings["banks"] == 4 and savings["total"] == 3400.0,
      f"savings interest is broken out per reporting bank: {savings['banks']} "
      f"banks totalling {savings['total']}")
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
                if e["information_code"].startswith("SFT-016")][-1]
check(last_savings["rows"][0]["SR.NO."] == "1"
      and last_savings["rows"][0]["REPORTED ON"] == "27/05/2026",
      f"the row under a section heading is not polluted by it: "
      f"{last_savings['rows'][0]}")

# ------------------------------------------------- AIS against the statements
def reconcile(*statements, ais="ais_synthetic.pdf", extra=(), code=0):
    proc = run("reconcile_interest.py",
               *[os.path.join(FIXTURES, s) for s in statements],
               "--ais", os.path.join(FIXTURES, ais), *extra, expect_code=code)
    return json.loads(proc.stdout or proc.stderr)


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
