"""Account labels can be tested without Home Assistant or a live PGE account."""
import importlib.util
from pathlib import Path
import unittest

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "pge_sensor"
    / "accounts.py"
)
SPEC = importlib.util.spec_from_file_location("pge_account_labels", MODULE_PATH)
accounts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(accounts)


class AccountLabelTests(unittest.TestCase):
    def test_supply_address_is_used_instead_of_mailing_address(self):
        label = accounts.describe_billing_account({
            "accountNumber": "123",
            "ppms": [{"number": "456", "address": "Adres punktu"}],
            "addresses": [{"street": "Adres korespondencyjny"}],
        })
        self.assertIn("Adres punktu", label)
        self.assertIn("PPE 456", label)
        self.assertNotIn("korespondencyjny", label)

    def test_missing_supply_point_does_not_use_mailing_address(self):
        label = accounts.describe_billing_account({
            "id": 12,
            "addresses": [{"street": "Adres korespondencyjny"}],
        })
        self.assertIn("nieopisany", label)
        self.assertIn("konto 12", label)
        self.assertNotIn("korespondencyjny", label)

    def test_active_and_archived_accounts_for_same_point_are_distinct(self):
        point = {"number": "456", "address": "Ten sam adres"}
        active = accounts.describe_billing_account({
            "accountNumber": "1", "ppms": [point],
        })
        archived = accounts.describe_billing_account({
            "accountNumber": "2", "ppms": [point], "archived": True,
        })
        self.assertNotEqual(active, archived)
        self.assertIn("konto 1", active)
        self.assertIn("konto 2", archived)
        self.assertIn("ARCHIWALNE", archived)

    def test_document_points_are_formatted_and_deduplicated(self):
        document = {"ppmConsumptions": [{
            "ppmNumber": "456",
            "ppm": {
                "street": "Testowa", "buildingNumber": "1", "flatNumber": "2",
                "postcode": "00-000", "city": "Miasto",
            },
        }]}
        self.assertEqual(accounts.points_from_documents([document, document]), [{
            "number": "456", "address": "Testowa 1/2 00-000 Miasto", "medium": None,
        }])

    def test_legacy_description_is_retained_without_guessing_point_address(self):
        label = accounts.describe_billing_account({
            "id": 1, "shortName": "Opis konta", "ppeNumber": "456",
        })
        self.assertIn("opis konta: Opis konta", label)
        self.assertIn("PPE 456", label)

    def test_active_default_account_precedes_other_accounts(self):
        values = [{"id": 1, "archived": True}, {"id": 2}, {
            "id": 3, "defaultAccount": True, "prosument": True,
        }]
        ordered = sorted(values, key=accounts.account_sort_key)
        self.assertEqual([value["id"] for value in ordered], [3, 2, 1])
        label = accounts.describe_billing_account(ordered[0])
        self.assertIn("domyślne", label)
        self.assertIn("prosument", label)

    def test_all_supply_points_of_an_account_are_listed(self):
        label = accounts.describe_billing_account({
            "accountNumber": "123",
            "ppms": [
                {"number": "1", "address": "Pierwszy adres"},
                {"number": "2", "address": "Drugi adres"},
            ],
        })
        self.assertIn("Pierwszy adres — PPE 1", label)
        self.assertIn("Drugi adres — PPE 2", label)

    def test_missing_address_preserves_point_number(self):
        label = accounts.describe_billing_account({
            "accountNumber": "123", "ppms": [{"number": "456"}],
        })
        self.assertIn("Adres PPE niedostępny — PPE 456", label)

    def test_legacy_account_number_is_preserved(self):
        label = accounts.describe_billing_account({"consumerNumber": "123", "id": 999})
        self.assertIn("konto 123", label)


if __name__ == "__main__":
    unittest.main()
