"""Short entity IDs retain stable account separation and legacy entry support."""
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).parents[1] / "custom_components/pge_sensor/entity_ids.py"
SPEC = importlib.util.spec_from_file_location("pge_ids", PATH)
ids = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ids)


class EntityIdTests(unittest.TestCase):
    def test_stored_number_does_not_depend_on_title(self):
        data = {"account_number": "12345678", "account_id": 999}
        self.assertEqual(ids.account_number_for_entry(data, "Dowolny adres"), "12345678")
        self.assertEqual(ids.default_entity_id("12345678", "balance"), "sensor.pge_12345678_saldo")

    def test_identifier_is_always_included(self):
        self.assertEqual(ids.default_entity_id("590243000000000001", "consumed_energy"),
                         "sensor.pge_590243000000000001_energia_pobrana")

    def test_identifier_is_sanitized(self):
        self.assertEqual(ids.default_entity_id("PL-0037/1", "balance"), "sensor.pge_pl_0037_1_saldo")

    def test_stored_ppe_wins(self):
        data = {"ppe": "590243000000000001", "account_number": "123"}
        self.assertEqual(ids.entry_identifier(data, "Adres — PPE 999 | konto 123"), "590243000000000001")

    def test_ppe_from_title_of_existing_entry(self):
        self.assertEqual(ids.ppe_for_entry({}, "Testowa 1 — PPE 5902430001 | konto 123"), "5902430001")

    def test_ppe_from_reported_points(self):
        self.assertEqual(ids.ppe_for_entry({}, "123", ["5902430001", "5902430001"]), "5902430001")

    def test_account_with_several_points_falls_back_to_account_number(self):
        title = "A — PPE 1 / B — PPE 2 | konto 123"
        self.assertIsNone(ids.ppe_for_entry({}, title, ["1", "2"]))
        self.assertEqual(ids.entry_identifier({"account_id": 9}, title), "123")

    def test_existing_descriptive_title_is_supported(self):
        self.assertEqual(ids.account_number_for_entry({"account_id": 999}, "Testowa 1 — PPE 456 | konto 123 | ARCHIWALNE"), "123")

    def test_original_numeric_title_is_supported(self):
        self.assertEqual(ids.account_number_for_entry({"account_id": 999}, "123"), "123")

    def test_internal_id_is_safe_fallback(self):
        self.assertEqual(ids.account_number_for_entry({"account_id": 999}, "Moje mieszkanie"), "999")

    def test_legacy_single_account_without_id(self):
        self.assertIsNone(ids.account_number_for_entry({}, "Nazwa konta"))
        self.assertEqual(ids.default_entity_id(None, "balance"), "sensor.pge_saldo")

    def test_accounts_sharing_ppe_do_not_collide(self):
        self.assertNotEqual(ids.default_entity_id("123", "balance"), ids.default_entity_id("456", "balance"))

    def test_sensor_keys_are_distinct(self):
        generated = [ids.default_entity_id("123", key) for key in ids.SENSOR_KEYS]
        self.assertEqual(len(generated), len(set(generated)))


if __name__ == "__main__":
    unittest.main()
