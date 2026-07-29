#!/usr/bin/env python3
"""
Rebuild the portal-JSON fixtures. Standard library only.

    python3 build_portal_json_synthetic.py

The *shape* is taken from real files — key names, nesting, the inconsistent
capitalisation between a prefill (`personalInfo`, `ifsccode`) and a filed return
(`PersonalInfo`, `IFSCCode`), the schedules that exist only on ITR-3. The
*content* is invented: the PAN is the documented placeholder, the Aadhaar number
is not a valid Aadhaar, the account numbers are Xs, and every figure was chosen
to make an arithmetic check either hold or fail on purpose.

Four files:

`prefill_synthetic.json` — clean. Three bank accounts, one nominated for refund,
two TDS rows, savings interest stated identically by AIS and by the employer's
24Q.

`prefill_broken_synthetic.json` — every prefill defect at once: no account
nominated for refund, TDS credit claimed above what was deducted, a TDS row with
tax deducted against a gross of zero, and savings-bank interest that disagrees
between AIS and the employer.

`filed_itr3_synthetic.json` — an ITR-3 that reconciles, and carries a
short-term capital loss, unabsorbed depreciation and an AMT credit forward. The
carry-forwards are the point: nothing else in this project reads them, and a
later year cannot reconstruct them from a PDF.

`filed_itr3_oldschema_synthetic.json` — the same return with `UseForRefund`
removed from every bank row, as an AY 2024-25 ITR-2 actually has it. Reading
that absence as "no account nominated" reports a defect on a return that was
filed and refunded years ago.

`filed_itr3_broken_synthetic.json` — the same return with four planted breaks:
the TDS schedule rows no longer add to the schedule total, Part B-TTI claims a
different TDS figure again, the four components of "total taxes paid" do not add
to it, and the return shows a refund and a balance payable at once.
"""
import json
import sys

PAN = "ABCDE1234F"          # the documented placeholder, not a real PAN
AADHAAR = "000011112222"    # not a valid Aadhaar number


def bank(prefix, name, refund, account="XXXXXXXXXX"):
    return {"ifsccode": f"{prefix}0000123", "bankName": name,
            "bankAccountNo": account, "AccountType": "SB",
            "useForRefund": "true" if refund else "false"}


def prefill(broken=False):
    return {
        "personalInfo": {
            "pan": PAN, "aadhaarCardNo": AADHAAR, "dob": "1990-01-01",
            "status": "I",
            "assesseeName": {"firstName": "SPECIMEN", "surNameOrOrgName": "FIXTURE"},
            "address": {"pinCode": 302001, "stateCode": "29",
                        "emailAddress": "nobody@example.invalid",
                        "mobileNo": 9000000000},
            "filingStatus": {"residentialStatus": "RES"},
        },
        "bankAccountDtls": [{"addtnlBankDetails": [
            bank("KKBK", "KOTAK MAHINDRA BANK", not broken),
            bank("HDFC", "HDFC BANK LTD", False),
            bank("DCBL", "DCB BANK", False),
        ]}],
        "form26as": {
            "tdsOnOthThanSals": {"tdSonOthThanSal": [
                {"sectionCode": "194A", "grossAmount": 40000,
                 "employerOrDeductorOrCollectDetl": {
                     "tan": "AAAA00000A",
                     "employerOrDeductorOrCollecterName": "SPECIMEN BANK LIMITED"},
                 "taxDeductCreditDtls": {"taxDeductedOwnHands": 4000,
                                         "taxClaimedOwnHands": 4000}},
                {"sectionCode": "194K",
                 "grossAmount": 0 if broken else 12000,
                 "employerOrDeductorOrCollectDetl": {
                     "tan": "BBBB11111B",
                     "employerOrDeductorOrCollecterName": "SPECIMEN AMC"},
                 "taxDeductCreditDtls": {"taxDeductedOwnHands": 1200,
                                         "taxClaimedOwnHands":
                                             9900 if broken else 1200}},
            ]},
            "tdsOnSalaries": {"tdSonSalary": [
                {"employerOrDeductorOrCollectDetl": {
                    "tan": "CCCC22222C",
                    "employerOrDeductorOrCollecterName": "SPECIMEN EMPLOYER"},
                 "incChrgSal": 900000, "totalTDSSal": 55000}]},
            "scheduleOS": {"incOthThanOwnRaceHorse": {"dividendGross": 7500}},
        },
        "insights": {
            "intrstFrmSavingBank": 9000 if not broken else 12500,
            "scheduleOS": {"incOthThanOwnRaceHorse": {"dividendGross":
                                                      15000 if broken else 7500}},
            "incomeDeductionsOthersInc": [
                {"othSrcNatureDesc": "Interest from deposit", "othSrcOthAmount": 3300}],
        },
        "form24q": {"isActive": True, "intrstFrmSavingBank": 9000,
                    "usrDeductUndChapVIAType": {"section80TTA": 0}},
        "form10IF": {"newTaxRegime": "Y"},
        "scheduleCFL": {"CarryFwdLossDetail": []},
        "lastFiledITR": {
            "scheduleUD": [],
            "scheduleAMTC": {"scheduleAMTCDtls": [
                {"assYr": "2023-24", "gross": 0, "amtCreditSetOfEy": 0,
                 "amtCreditFwd": 0}]},
        },
        "filingStatus": {"SeventhProvisio139": "N"},
    }


def filed_itr3(broken=False):
    # A return that adds up. Every figure below is invented; the identities
    # between them are the real subject of the fixture.
    tds_salary_rows = [{"EmployerOrDeductorOrCollectDetl": {
        "TAN": "CCCC22222C",
        "EmployerOrDeductorOrCollecterName": "SPECIMEN EMPLOYER"},
        "IncChrgSal": 900000, "TotalTDSSal": 55000}]
    tds_other_rows = [
        {"TDSCreditName": "SELF", "TDSSection": "194A", "TANOfDeductor": "AAAA00000A",
         "GrossAmount": 40000, "HeadOfIncome": "OS",
         "TaxDeductCreditDtls": {"TaxDeductedOwnHands": 4000,
                                 "TaxClaimedOwnHands": 4000}},
        {"TDSCreditName": "SELF", "TDSSection": "194K", "TANOfDeductor": "BBBB11111B",
         "GrossAmount": 12000, "HeadOfIncome": "OS",
         "TaxDeductCreditDtls": {"TaxDeductedOwnHands": 1200,
                                 "TaxClaimedOwnHands": 1200}},
    ]
    # 55,000 + 4,000 + 1,200 = 60,200 of TDS.
    stated_tds2_total = 5200 if not broken else 9000
    part_b_tds = 60200 if not broken else 61000

    advance, self_assessment, tcs = 10000, 5000, 0
    total_paid = advance + part_b_tds + tcs + self_assessment
    if broken:
        total_paid += 2500          # no longer the sum of its parts

    net_tax = 62000
    # 1,197 makes the balance 12,003, which s.288B rounds to a refund of
    # 12,000. Every real return does this, and a naive equality check flags
    # all of them.
    interest_234 = 1197
    aggregate = net_tax + interest_234       # 63,197

    def round_288b(amount):
        """What the utility itself writes: nearest ten rupees, five rounds up."""
        return int((abs(amount) + 5) // 10 * 10)

    refund = round_288b(max(0, total_paid - aggregate))     # 12,003 -> 12,000
    payable = round_288b(max(0, aggregate - total_paid))

    return {"ITR": {"ITR3": {
        "Form_ITR3": {"AssessmentYear": "2026", "SchemaVer": "Ver1.0",
                      "FormVer": "Ver1.0", "FormName": "ITR-3",
                      "Description": "SYNTHETIC FIXTURE"},
        "CreationInfo": {"SWVersionNo": "1.0", "SWCreatedBy": "SW00000000",
                         "JSONCreatedBy": "SW00000000",
                         "JSONCreationDate": "2026-07-28", "Digest": "-"},
        "PartA_GEN1": {
            "PersonalInfo": {"PAN": PAN, "AadhaarCardNo": AADHAAR,
                             "DOB": "1990-01-01", "Status": "I",
                             "AssesseeName": {"FirstName": "SPECIMEN",
                                              "SurNameOrOrgName": "FIXTURE"},
                             "Address": {"PinCode": 302001, "StateCode": "29",
                                         "EmailAddress": "nobody@example.invalid",
                                         "MobileNo": 9000000000}},
            "FilingStatus": {"ResidentialStatus": "RES", "ReturnFileSec": 11,
                             "NewTaxRegime": "Y", "SeventhProvisio139": "N",
                             "ItrFilingDueDate": "2026-09-15"}},
        "ScheduleTDS1": {"TDSonSalary": tds_salary_rows,
                         "TotalTDSonSalaries": 55000},
        "ScheduleTDS2": {"TDSOthThanSalaryDtls": tds_other_rows,
                         "TotalTDSonOthThanSals": stated_tds2_total},
        # An empty schedule states a zero total and carries no rows. That is
        # the common case and must not read as a schema this script cannot
        # parse; a real AY 2026-27 ITR-2 carries all three like this.
        "ScheduleTDS3": {"TotalTDS3OnOthThanSal": 0},
        "ScheduleTCS": {"TotalSchTCS": 0},
        # Advance tax and self-assessment tax have challans behind them, and
        # Part B-TTI states the same figures again. The clean fixture has to be
        # consistent across the two or it is not a clean fixture — the first
        # draft claimed 15,000 in Part B-TTI against an empty Schedule IT, and
        # the check caught it.
        # In the broken variant the schedule is under a name this script does
        # not know, which must be reported rather than silently skipped.
        "ScheduleIT": {"SomeFutureSchemaKey": []} if broken else {
            "TotalTaxPayments": 15000,
            "TaxPayment": [
                {"BSRCode": "0000001", "DateDep": "2025-12-15",
                 "SrlNoOfChaln": 11111, "Amt": 10000},
                {"BSRCode": "0000001", "DateDep": "2026-07-28",
                 "SrlNoOfChaln": 22222, "Amt": 5000}]},
        # Schedules this script does not read. They are here so the fixture can
        # prove it says so: a script silent about ScheduleBP reads exactly like
        # a script that found nothing wrong with it.
        "PartB-TI": {"TotalIncome": 500000},
        "ScheduleOS": {"IncOthThanOwnRaceHorse": {"InterestGross": 5000}},
        "ScheduleBP": {"BusinessIncOthThanSpec": 0},
        "ScheduleSI": {"SplCodeRateTax": [
            {"SecCode": "1A", "SplRatePercent": 20, "SplRateInc": 61500,
             "SplRateIncTax": 12300},
            {"SecCode": "22", "SplRatePercent": 12.5, "SplRateInc": 40000,
             "SplRateIncTax": 5000},
            {"SecCode": "5BB", "SplRatePercent": 30, "SplRateInc": 0,
             "SplRateIncTax": 0}],
            "TotSplRateInc": 101500, "TotSplRateIncTax": 17300},
        "ScheduleCFL": {
            "CurrentAYloss": {"LossSummaryDetail": {
                "TotalSTCGPTILossCF": 45000, "TotalLTCGPTILossCF": 0,
                "TotalHPPTILossCF": 0, "BusLossOthThanSpecLossCF": 0,
                "LossFrmSpecBusCF": 0, "LossFrmSpecifiedBusCF": 0,
                "OthSrcLossRaceHorseCF": 0}},
            "TotalOfBFLossesEarlierYrs": {"LossSummaryDetail": {
                "TotalSTCGPTILossCF": 0, "BusLossOthThanSpecLossCF": 30000,
                "TotalLTCGPTILossCF": 0, "TotalHPPTILossCF": 0,
                "LossFrmSpecBusCF": 0, "LossFrmSpecifiedBusCF": 0,
                "OthSrcLossRaceHorseCF": 0}},
            "TotalLossCFSummary": {"LossSummaryDetail": {
                "TotalSTCGPTILossCF": 45000, "BusLossOthThanSpecLossCF": 30000,
                "TotalLTCGPTILossCF": 0, "TotalHPPTILossCF": 0,
                "LossFrmSpecBusCF": 0, "LossFrmSpecifiedBusCF": 0,
                "OthSrcLossRaceHorseCF": 0}}},
        "ITR3ScheduleUD": {"CurrAssYr": "2026", "TotBFUDepritAmt": 80000,
                           "TotCurYrdepritSetoffInc": 20000,
                           "TotDepritBalCFNY": 60000, "TotalBalCFNY": 0,
                           "TotBFUAllowAmt": 0, "TotCurYrAllowSetoffInc": 0,
                           "CurBalCFNY": 0, "CurAllowBalCFNY": 0,
                           "TotAdjustAccTax115BACAmt": 0},
        "ScheduleAMTC": {"CurrAssYr": "2026", "TotBalAMTCreditCF": 25000,
                         "ScheduleAMTCDtls": [
                             {"AssYr": "2023-24", "AmtCreditBalBroughtFwd": 25000,
                              "AmtCreditUtilized": 0, "BalAmtCreditCarryFwd": 25000,
                              "AmtCreditSetOfEy": 0, "AmtCreditFwd": 25000}]},
        "PartB_TTI": {
            "ComputationOfTaxLiability": {
                "TaxPayableOnTI": {"TaxAtNormalRatesOnAggrInc": 48000,
                                   "TaxAtSpecialRates": 17300,
                                   "RebateOnAgriInc": 0,
                                   "TaxPayableOnTotInc": 65300},
                "Rebate87A": 0, "TaxPayableOnRebate": 65300,
                "TotalSurcharge": 0, "EducationCess": 2612,
                "GrossTaxLiability": 67912, "GrossTaxPayable": 67912,
                "CreditUS115JD": 0, "TaxPayAfterCreditUs115JD": 67912,
                "TaxRelief": {"Section89": 0, "Section90": 0, "Section91": 0,
                              "TotTaxRelief": 0},
                "NetTaxLiability": net_tax,
                "IntrstPay": {"IntrstPayUs234A": 0, "IntrstPayUs234B": 800,
                              "IntrstPayUs234C": 400, "LateFilingFee234F": 0,
                              "TotalIntrstPay": interest_234},
                "AggregateTaxInterestLiability": aggregate},
            "TaxPaid": {"TaxesPaid": {"AdvanceTax": advance, "TDS": part_b_tds,
                                      "TCS": tcs,
                                      "SelfAssessmentTax": self_assessment,
                                      "TotalTaxesPaid": total_paid},
                        "BalTaxPayable": 4000 if broken else payable},
            "Refund": {"RefundDue": refund if not broken else 12000,
                       "BankAccountDtls": {
                           "BankDtlsFlag": "Y",
                           "AddtnlBankDetails": [
                               {"IFSCCode": "KKBK0000123",
                                "BankName": "KOTAK MAHINDRA BANK",
                                "BankAccountNo": "XXXXXXXXXX",
                                "AccountType": "SB", "UseForRefund": "true"}]}},
            "AssetOutIndiaFlag": "N"},
        "Verification": {"Declaration": {"AssesseeVerName": "SPECIMEN FIXTURE"},
                         "Capacity": "S"},
    }}}


def main() -> int:
    old_schema = filed_itr3(False)
    for row in (old_schema["ITR"]["ITR3"]["PartB_TTI"]["Refund"]
                ["BankAccountDtls"]["AddtnlBankDetails"]):
        row.pop("UseForRefund", None)

    files = {
        "filed_itr3_oldschema_synthetic.json": old_schema,
        "prefill_synthetic.json": prefill(False),
        "prefill_broken_synthetic.json": prefill(True),
        "filed_itr3_synthetic.json": filed_itr3(False),
        "filed_itr3_broken_synthetic.json": filed_itr3(True),
    }
    for name, payload in files.items():
        with open(name, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=1)
        print("wrote", name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
