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

    def test_single_configured_account_uses_clean_ids(self):
        self.assertEqual(
            ids.default_entity_id("12345678", "balance", multiple_accounts=False),
            "sensor.pge_saldo",
        )
        self.assertEqual(
            ids.default_entity_id("12345678", "consumed_energy", multiple_accounts=False),
            "sensor.pge_energia_pobrana",
        )

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
