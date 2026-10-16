"""Synthetic fixtures exercise snapshot selection and opust exactly once."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).parents[1] / "custom_components/pge_sensor"
SPEC = importlib.util.spec_from_file_location("pge_settlement", ROOT / "settlement.py")
helpers = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helpers)


def zone(raw=100, factor=0.8):
    return {"dataWarehouseSummary": {"leftEnergyAmountSum": raw, "factor": factor}}


class SettlementTests(unittest.TestCase):
    def test_forecast_is_never_actual(self):
        forecast = {"documentType": "PREPAYMENT_INVOICE", "ppmConsumptions": [{}]}
        self.assertIsNone(helpers.latest_actual([forecast]))

    def test_latest_period_wins_over_list_order(self):
        older = {"documentType": "INVOICE", "creationDate": "2026-08-01", "ppmConsumptions": [{"billingPeriodTo": "2025-12-31"}]}
        newer = {"documentType": "INVOICE", "creationDate": "2026-07-01", "ppmConsumptions": [{"billingPeriodTo": "2026-06-30"}]}
        self.assertIs(helpers.latest_actual([older, newer]), newer)

    def test_previous_settlement_ends_before_latest_period(self):
        def invoice(start, end, created):
            return {"documentType": "INVOICE", "creationDate": created,
                    "ppmConsumptions": [{"billingPeriodFrom": start + "T00:00:00", "billingPeriodTo": end + "T00:00:00"}]}
        oldest = invoice("2025-07-01", "2025-12-31", "2026-01-10")
        previous = invoice("2026-01-01", "2026-06-30", "2026-07-10")
        latest = invoice("2026-07-01", "2026-12-31", "2027-01-10")
        correction = invoice("2026-07-01", "2026-12-31", "2027-02-01")
        forecast = {"documentType": "PREPAYMENT_INVOICE", "ppmConsumptions": [{"billingPeriodTo": "2026-06-30"}]}
        documents = [correction, latest, forecast, previous, oldest]
        self.assertIs(helpers.previous_actual(documents, latest), previous)
        self.assertIsNone(helpers.previous_actual(documents, oldest))

    def test_financial_invoice_without_energy_is_still_latest(self):
        older = {"documentType": "INVOICE", "creationDate": "2026-01-01", "ppmConsumptions": [{}]}
        newer = {"documentType": "INVOICE", "creationDate": "2026-02-01", "ppmConsumptions": []}
        self.assertIs(helpers.latest_invoice([older, newer]), newer)

    def test_financial_ties_retain_pge_order(self):
        a = {"documentType": "INVOICE", "creationDate": "2026-02-01"}
        b = dict(a)
        self.assertIs(helpers.latest_invoice([a, b]), a)

    def test_complete_period_and_invalid_dates(self):
        self.assertEqual(helpers.billing_period({"billingPeriodFrom": "2026-01-01T00:00:00", "billingPeriodTo": "2026-06-30T00:00:00"}), ("2026-01-01 / 2026-06-30", "2026-06-30"))
        for ppm in ({}, {"billingPeriodFrom": "bad", "billingPeriodTo": "2026-06-30"}, {"billingPeriodFrom": "2026-07-01", "billingPeriodTo": "2026-06-30"}):
            self.assertEqual(helpers.billing_period(ppm), (None, None))

    def test_both_zones_are_summed_after_factor(self):
        storage = {"zones": {"Strefa 1": zone(100, .8), "Strefa 2": zone(50, .7)}}
        self.assertEqual(helpers.bank_total(storage), 115)
        self.assertEqual(helpers.bank_zones(storage)["Strefa 1"]["raw_kwh"], 100)

    def test_zero_is_known_energy(self):
        self.assertEqual(helpers.bank_total({"zones": {"Strefa 1": zone(0)}}), 0)

    def test_alias_never_double_counts(self):
        storage = {"zones": {"Strefa 1": zone(), "Strefa 1 w sumie": zone(500), "Strefa 2": zone(50)}}
        self.assertEqual(helpers.bank_total(storage), 120)

    def test_alias_only_is_supported(self):
        self.assertEqual(helpers.bank_total({"zones": {"Strefa 1 w sumie": zone()}}), 80)

    def test_partial_bank_is_unknown(self):
        self.assertIsNone(helpers.bank_total({"zones": {"Strefa 1": zone(), "Strefa 2": zone(50, None)}}))
        self.assertEqual(set(helpers.bank_zones({"zones": {"Strefa 1": zone(), "Strefa 2": zone(50, None)}})), {"Strefa 1"})

    def test_bad_numbers_and_factors_do_not_crash_or_become_zero(self):
        for raw, factor in ((None,.8),(-1,.8),("bad",.8),(float('nan'),.8),(100,0),(100,1.1),(100,float('inf')),(True,.8)):
            with self.subTest(raw=raw, factor=factor):
                self.assertIsNone(helpers.bank_total({"zones": {"Strefa 1": zone(raw,factor)}}))
        self.assertIsNone(helpers.bank_total(None))


if __name__ == "__main__":
    unittest.main()
