"""Exercise the real API parser with synthetic responses; never contact PGE."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).parents[1] / "custom_components/pge_sensor"
PACKAGE = "pge_settlement_api_test"
pkg = types.ModuleType(PACKAGE)
pkg.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = pkg
requests_stub = types.ModuleType("requests")
requests_stub.RequestException = type("RequestException", (Exception,), {})
requests_stub.Session = lambda: types.SimpleNamespace(headers={})
spec = importlib.util.spec_from_file_location(PACKAGE + ".api", ROOT / "api.py")
api = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = api
with patch.dict(sys.modules, {"requests": requests_stub}):
    spec.loader.exec_module(api)


def document(kind="INVOICE", *, creation="2026-08-01", ppm=True, prosument=True):
    doc = {"documentType": kind, "documentId": "synthetic-doc", "documentNumber": "TEST/1",
           "creationDate": creation + " 00:00:00.000", "paymentDueDate": "2026-10-30 00:00:00.000",
           "paymentStatus": "UNPAID", "amountToPay": 20, "totalAmount": 50,
           "prosument": prosument, "ppmConsumptions": []}
    if ppm:
        doc["ppmConsumptions"] = [{"billingPeriodFrom": "2026-01-01T00:00:00",
            "billingPeriodTo": "2026-06-30T00:00:00", "consumptionValue": 100,
            "feedInValue": 200, "valueSettledEnergyConsumed": 60, "ppmNumber": "TEST-PPE",
            "ppm": {"id": "synthetic-point"}}]
    return doc


class ApiTests(unittest.TestCase):
    def run_parser(self, docs, *, bank_error=False):
        scraper = api.PgeScraper("synthetic@example.invalid", "synthetic-password")
        scraper._access_token = "synthetic-token"
        scraper._login = Mock()
        scraper._get_balance = Mock(return_value={"totalAmount": 123.45})
        scraper._get_documents = Mock(return_value=docs)
        session = Mock(headers={})
        response = Mock()
        response.json.return_value = {"zones": {"Strefa 1": {"dataWarehouseSummary": {"leftEnergyAmountSum": 100, "factor": .8}}}}
        session.get.return_value = response
        if bank_error:
            session.get.side_effect = requests_stub.RequestException("synthetic failure")
        scraper._session = session
        return scraper.get_balance_details(1), session

    def test_payment_and_forecast_do_not_replace_actual_energy(self):
        forecast = document("PREPAYMENT_INVOICE", creation="2026-09-01")
        forecast["totalAmount"] = 25
        forecast["ppmConsumptions"][0]["consumptionValue"] = 300
        actual = document()
        data, session = self.run_parser([forecast, actual])
        self.assertEqual((data.amount, data.invoice_amount, data.current_payment), (123.45,25,20))
        self.assertEqual((data.consumed_energy,data.feed_in_energy,data.forecast_energy), (100,200,300))
        self.assertEqual((data.actual_invoice_amount,data.settlement_amount,data.settled_energy), (50,60,None))
        self.assertEqual(data.settlement_date, "2026-06-30")
        self.assertIn('/synthetic-doc/datawarehouse/synthetic-point', session.get.call_args.args[0])

    def test_previous_settlement_bank_is_fetched(self):
        previous = document(creation="2026-02-01")
        previous["documentId"] = "previous-doc"
        previous["ppmConsumptions"][0].update(billingPeriodFrom="2025-07-01T00:00:00",
                                              billingPeriodTo="2025-12-31T00:00:00")
        data, session = self.run_parser([document(), previous])
        self.assertEqual(data.previous_billing_period, "2025-07-01 / 2025-12-31")
        self.assertIsNotNone(data.previous_energy_storage)
        self.assertIn('/previous-doc/datawarehouse/synthetic-point', session.get.call_args.args[0])

    def test_no_previous_settlement_leaves_it_unknown(self):
        data, session = self.run_parser([document()])
        self.assertIsNone(data.previous_energy_storage)
        self.assertIsNone(data.previous_billing_period)
        self.assertEqual(session.get.call_count, 1)

    def test_ordinary_customer_keeps_finances_without_energy(self):
        data, session = self.run_parser([document(ppm=False, prosument=False)])
        self.assertEqual(data.actual_invoice_amount, 50)
        self.assertFalse(data.prosument)
        for key in ('consumed_energy','feed_in_energy','energy_storage','billing_period','settlement_date'):
            self.assertIsNone(getattr(data,key))
        session.get.assert_not_called()

    def test_ordinary_customer_with_energy_keeps_measured_values(self):
        doc=document(prosument=False)
        doc["ppmConsumptions"][0].update(consumptionValue=104,feedInValue=0,valueSettledEnergyConsumed=0)
        data,session=self.run_parser([doc])
        self.assertEqual(data.consumed_energy,104)
        self.assertEqual(data.settlement_amount,0)
        self.assertIsNone(data.forecast_energy)
        self.assertIsNone(data.energy_storage)
        session.get.assert_not_called()

    def test_forecast_only_does_not_invent_settlement_or_bank(self):
        data, session = self.run_parser([document('PREPAYMENT_INVOICE')])
        self.assertEqual(data.forecast_energy,100)
        self.assertIsNone(data.consumed_energy)
        self.assertIsNone(data.actual_invoice_amount)
        self.assertIsNone(data.energy_storage)
        session.get.assert_not_called()

    def test_missing_amount_to_pay_is_safe(self):
        doc = document(ppm=False, prosument=False)
        doc['amountToPay'] = None
        data,_ = self.run_parser([doc])
        self.assertEqual(data.invoice_amount,50)
        self.assertIsNone(data.current_payment)

    def test_bank_failure_preserves_other_data(self):
        data,_ = self.run_parser([document()],bank_error=True)
        self.assertEqual(data.consumed_energy,100)
        self.assertEqual(data.actual_invoice_amount,50)
        self.assertIsNone(data.energy_storage)

    def test_multiple_points_are_not_silently_truncated(self):
        doc = document();doc['ppmConsumptions'].append(dict(doc['ppmConsumptions'][0]))
        data,session = self.run_parser([doc])
        self.assertEqual(data.actual_invoice_amount,50)
        self.assertIsNone(data.consumed_energy)
        self.assertIsNone(data.energy_storage)
        session.get.assert_not_called()

    def test_new_invoice_without_energy_has_independent_financial_amount(self):
        old=document();new=document(creation='2026-09-01',ppm=False)
        new['totalAmount']=75
        data,_=self.run_parser([new,old])
        self.assertEqual(data.actual_invoice_amount,75)
        self.assertEqual(data.consumed_energy,100)

    def test_empty_documents_do_not_invent_values(self):
        data,session=self.run_parser([])
        self.assertEqual(data.amount,123.45)
        self.assertIsNone(data.actual_invoice_amount)
        self.assertIsNone(data.prosument)
        session.get.assert_not_called()


if __name__ == '__main__':
    unittest.main()
