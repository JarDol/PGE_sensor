"""The bank projection is checked on hand-computed months, without Home Assistant."""
from datetime import date
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).parents[1] / "custom_components/pge_sensor/local_bank.py"
SPEC = importlib.util.spec_from_file_location("pge_local_bank", PATH)
bank = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bank)


def batch(day, raw):
    return {"insertToGridDate": f"{day}T00:00:00", "leftEnergyAmount": raw}


class ProjectionDatesTests(unittest.TestCase):
    def test_start_is_day_after_settled_period(self):
        self.assertEqual(bank.projection_start("2025-01-01 / 2025-12-31"), date(2026, 1, 1))

    def test_unknown_period_has_no_start(self):
        self.assertIsNone(bank.projection_start(None))
        self.assertIsNone(bank.projection_start("brak"))

    def test_reading_days_cross_year(self):
        self.assertEqual(bank.reading_days(date(2025, 11, 1), date(2026, 1, 15)),
                         [date(2025, 11, 1), date(2025, 12, 1), date(2026, 1, 1)])

    def test_period_reading_days_end_after_period(self):
        self.assertEqual(bank.period_reading_days("2025-11-16 / 2026-01-15"),
                         [date(2025, 11, 16), date(2025, 12, 1), date(2026, 1, 1), date(2026, 1, 16)])
        self.assertEqual(bank.period_reading_days("2026-01-01 / 2026-02-28"),
                         [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)])
        self.assertEqual(bank.period_reading_days(None), [])
        self.assertEqual(bank.period_reading_days("2026-03-01 / 2026-01-01"), [])

    def test_mid_month_start_then_month_starts(self):
        self.assertEqual(bank.reading_days(date(2026, 3, 16), date(2026, 4, 1)),
                         [date(2026, 3, 16), date(2026, 4, 1)])


class SimulationTests(unittest.TestCase):
    def test_settled_batches_are_drawn_fifo(self):
        history = [batch("2025-06-01", 100), batch("2025-05-01", 50)]
        readings = [(date(2026, 1, 1), 1000, 500), (date(2026, 1, 20), 1060, 500)]
        result = bank.simulate_bank(history, 0.8, readings, date(2026, 1, 20))
        # 40 + 80 kWh banked; 60 kWh consumed takes all of May and 20 of June.
        self.assertEqual(result["pozostalo"], 60.0)
        self.assertEqual(result["partie"], [
            {"miesiac": "2025-06", "kwh": 60.0, "wygasa_z_koncem": "2026-06"}])
        self.assertEqual(result["najblizsze_wygasniecie"]["miesiac"], "2025-06")

    def test_export_adds_batch_after_opust(self):
        readings = [(date(2026, 5, 1), 0, 0), (date(2026, 5, 31), 100, 500)]
        result = bank.simulate_bank([], 0.8, readings, date(2026, 5, 31))
        self.assertEqual(result["pozostalo"], 300.0)
        self.assertEqual(result["oddana_po_opuscie"], 400.0)
        self.assertEqual(result["pobrana_od_startu"], 100.0)

    def test_empty_bank_stays_zero_and_deficit_is_repaid_first(self):
        readings = [(date(2026, 1, 1), 0, 0), (date(2026, 2, 1), 100, 0),
                    (date(2026, 3, 1), 100, 200)]
        winter = bank.simulate_bank([], 0.8, readings[:2], date(2026, 1, 31))
        self.assertEqual((winter["pozostalo"], winter["deficyt"], winter["deficyt_od"]), (0.0, 100.0, "2026-01"))
        spring = bank.simulate_bank([], 0.8, readings, date(2026, 2, 28))
        # 160 kWh banked from February repays the 100 kWh January deficit.
        self.assertEqual((spring["pozostalo"], spring["deficyt"], spring["deficyt_od"]), (60.0, 0.0, None))

    def test_deficit_starts_when_bank_runs_out(self):
        history = [batch("2025-09-01", 50)]
        readings = [(date(2026, 1, 1), 0, 0), (date(2026, 2, 1), 30, 0),
                    (date(2026, 3, 1), 80, 0), (date(2026, 3, 10), 90, 0)]
        result = bank.simulate_bank(history, 0.8, readings, date(2026, 3, 10))
        # 40 kWh bank: January uses 30, February the last 10 and 40 beyond it, March 10 more.
        self.assertEqual((result["pozostalo"], result["deficyt"], result["deficyt_od"]), (0.0, 50.0, "2026-02"))

    def test_previous_period_ends_where_current_starts(self):
        # The previous settlement's bank, run through the latest settled period,
        # meets the current projection on the day after that period.
        previous = [batch("2025-11-01", 100)]
        readings = [(day, imp, 0) for day, imp in zip(
            bank.period_reading_days("2026-01-01 / 2026-02-28"), (0, 50, 120))]
        settled = bank.simulate_bank(previous, 0.8, readings, date(2026, 2, 28))
        self.assertEqual((settled["pozostalo"], settled["deficyt"], settled["deficyt_od"]), (0.0, 40.0, "2026-02"))
        self.assertEqual(readings[-1][0], bank.projection_start("2026-01-01 / 2026-02-28"))

    def test_batches_expire_after_twelve_months(self):
        history = [batch("2025-01-10", 100)]
        readings = [(date(2026, 1, 1), 0, 0), (date(2026, 2, 1), 0, 0)]
        self.assertEqual(bank.simulate_bank(history, 0.8, readings, date(2026, 1, 31))["pozostalo"], 80.0)
        expired = bank.simulate_bank(history, 0.8, readings, date(2026, 2, 1))
        self.assertEqual((expired["pozostalo"], expired["wygaslo"]), (0.0, 80.0))

    def test_meter_reset_does_not_create_energy(self):
        readings = [(date(2026, 1, 1), 5000, 300), (date(2026, 1, 9), 10, 0)]
        result = bank.simulate_bank([batch("2025-12-01", 10)], 0.8, readings, date(2026, 1, 9))
        self.assertEqual((result["pozostalo"], result["pobrana_od_startu"]), (8.0, 0.0))

    def test_step_rounds_every_energy_value(self):
        readings = [(date(2026, 5, 1), 0, 0), (date(2026, 5, 31), 100.3, 500.6)]
        result = bank.simulate_bank([], 0.8, readings, date(2026, 5, 31), step=0.5)
        # 500.6 × 0.8 − 100.3 = 300.18 kWh
        self.assertEqual(result["pozostalo"], 300.0)
        self.assertEqual(result["pobrana_od_startu"], 100.5)
        self.assertEqual(result["oddana_od_startu"], 500.5)
        self.assertEqual(result["partie"][0]["kwh"], 300.0)
        self.assertEqual(bank.simulate_bank([], 0.8, readings, date(2026, 5, 31), step=1)["pozostalo"], 300.0)
        self.assertEqual(bank.simulate_bank([], 0.8, readings, date(2026, 5, 31), step=0.01)["pozostalo"], 300.18)

    def test_malformed_history_is_ignored(self):
        history = [batch("2025-12-01", "x"), batch("2025-12-01", -3),
                   {"leftEnergyAmount": 10}, batch("2025-12-01", 5)]
        result = bank.simulate_bank(history, 0.8, [(date(2026, 1, 1), 0, 0)], date(2026, 1, 1))
        self.assertEqual(result["pozostalo"], 4.0)


if __name__ == "__main__":
    unittest.main()
