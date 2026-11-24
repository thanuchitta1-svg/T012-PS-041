"""
PS-041 Test Suite
Run:  python -m unittest test_suite.py -v   (or:  python test_suite.py)

Covers every planted edge case (EC-01..EC-08) plus the extra traps in the
sample data pack, and unit-tests the core tariff/allocation helpers.
"""

import os
import csv
import unittest
from datetime import datetime

import main

DATA_DIR = os.path.dirname(os.path.abspath(__file__))


def ts(s):
    return main.parse_ts(s)


class TestSampleDataEndToEnd(unittest.TestCase):
    """Runs the full command stream once and checks receipt outputs."""

    @classmethod
    def setUpClass(cls):
        cls.g = main.Garage(DATA_DIR)
        cls.g.run()
        cls.summaries = {r["ticket_id"]: r for r in cls.g.summary_rows}
        cls.receipts = {}
        for r in cls.g.receipt_rows:
            cls.receipts.setdefault(r["ticket_id"], []).append(r)
        cls.pass_sales = {r["pass_id"]: r for r in cls.g.pass_sales}
        cls.daily = cls.g.daily_rows

    # EC-01 grace boundary -------------------------------------------------
    def test_ec01_grace_exactly_15min_free(self):
        t = self.summaries["TKT-00092"]          # 14:00 -> 14:15:00
        self.assertEqual(t["duration_min"], "15")
        self.assertEqual(t["parking_fee"], "0.00")
        self.assertEqual(t["total"], "0.00")

    def test_ec01_grace_15min_01s_billed(self):
        t = self.summaries["TKT-00098"]          # 16:30 -> 16:45:01
        self.assertEqual(t["duration_min"], "15")
        self.assertEqual(t["parking_fee"], "40.00")
        self.assertEqual(t["total"], "47.20")    # + 18% GST

    # EC-02 night flat ------------------------------------------------------
    def test_ec02_night_flat_boundary(self):
        t104 = self.summaries["TKT-00104"]       # entry 19:59 -> slab cap 300
        self.assertEqual(t104["parking_fee"], "300.00")
        self.assertIn("PARKING", [l["line_type"] for l in self.receipts["TKT-00104"]])

        t105 = self.summaries["TKT-00105"]       # entry 20:00 -> night flat 150
        self.assertEqual(t105["parking_fee"], "150.00")
        self.assertIn("NIGHT_FLAT", [l["line_type"] for l in self.receipts["TKT-00105"]])

    # EC-03 slab boundaries -------------------------------------------------
    def test_ec03_exactly_2h_vs_2h1m(self):
        t74 = self.summaries["TKT-00074"]        # 120 min -> Rs 40
        self.assertEqual(t74["parking_fee"], "40.00")
        t75 = self.summaries["TKT-00075"]        # 121 min -> Rs 70
        self.assertEqual(t75["parking_fee"], "70.00")

    # EC-04 26-hour SUV ------------------------------------------------------
    def test_ec04_second_24h_block(self):
        t = self.summaries["TKT-00066"]          # 1560 min -> 450 + 60 = 510
        self.assertEqual(t["duration_min"], "1560")
        self.assertEqual(t["parking_fee"], "510.00")

    # EC-05 pass pro-ration --------------------------------------------------
    def test_ec05_pass_prorated_30th_of_31day_month(self):
        p = self.pass_sales["PAS-009"]
        self.assertEqual(str(p["days_charged"]), "2")
        self.assertEqual(p["amount"], "167.00")  # ceil(2500*2/30)
        t = self.summaries["TKT-00157"]
        self.assertEqual(t["pass_covered_min"], "270")
        self.assertEqual(t["parking_fee"], "0.00")
        self.assertEqual(t["total"], "0.00")

    # EC-06 pass window 06:00-23:00 ------------------------------------------
    def test_ec06_pass_outside_hours_billed(self):
        t = self.summaries["TKT-00109"]          # 05:30 -> 23:30
        self.assertEqual(str(t["duration_min"]), "1080")
        self.assertEqual(str(t["pass_covered_min"]), "1020")
        self.assertEqual(t["parking_fee"], "40.00")
        self.assertEqual(t["total"], "47.20")

    # EC-07 EV idle at exactly 120 min ---------------------------------------
    def test_ec07_ev_idle_zero_at_120min(self):
        t = self.summaries["TKT-00079"]
        self.assertEqual(str(t["duration_min"]), "120")
        self.assertEqual(t["idle_fee"], "0.00")
        self.assertEqual(t["energy_fee"], "567.00")   # 31.5 kWh * 18
        self.assertEqual(t["gst_total"], "35.55")     # 7.20 + 28.35
        self.assertEqual(t["total"], "642.55")

    # EV idle cap trap --------------------------------------------------------
    def test_ev_idle_fee_capped_400(self):
        t = self.summaries["TKT-00094"]
        self.assertEqual(t["idle_fee"], "400.00")
        self.assertEqual(t["energy_fee"], "396.00")   # 22 kWh * 18
        self.assertEqual(t["parking_fee"], "220.00")
        self.assertEqual(t["total"], "1147.40")

    # Lost tickets -------------------------------------------------------------
    def test_lost_ticket_anpr_match_max_of_actual_and_flat(self):
        t = self.summaries["TKT-00071"]          # CAR, ANPR exact -> max(slab,500)
        self.assertEqual(t["parking_fee"], "500.00")
        self.assertEqual(t["total"], "590.00")
        self.assertIn("LOST_TICKET", [l["line_type"] for l in self.receipts["TKT-00071"]])

    def test_lost_ticket_anpr_misread_flat_fee(self):
        t = self.summaries["TKT-00137"]          # TWO_WHEELER, no exact ANPR -> 200
        self.assertEqual(t["parking_fee"], "200.00")
        self.assertEqual(t["total"], "236.00")

    # Overstay ------------------------------------------------------------------
    def test_overstay_100_per_day_from_4th_day(self):
        t = self.summaries["TKT-00001"]          # 157 h -> 7 days -> 4 * 100
        self.assertEqual(t["parking_fee"], "2100.00")
        self.assertEqual(t["surcharges"], "400.00")
        self.assertEqual(t["total"], "2950.00")

    # Wallet all-or-nothing + retry ----------------------------------------------
    def test_wallet_insufficient_then_card_retry(self):
        t = self.summaries["TKT-00169"]
        self.assertEqual(t["payment_mode"], "CARD")
        self.assertEqual(t["status"], "PAID")
        self.assertEqual(t["total"], "188.80")

    # Pass misuse -----------------------------------------------------------------
    def test_pass_misuse_penalty_and_suspension(self):
        t72 = self.summaries["TKT-00072"]        # wrong plate, misuse #1
        self.assertEqual(t72["surcharges"], "100.00")
        t151 = self.summaries["TKT-00151"]       # wrong plate, misuse #2 -> suspend
        self.assertEqual(t151["surcharges"], "100.00")
        t156 = self.summaries["TKT-00156"]       # genuine plate after suspension
        self.assertEqual(str(t156["pass_covered_min"]), "0")
        self.assertEqual(t156["parking_fee"], "250.00")
        self.assertEqual(t156["surcharges"], "0.00")

    # Daily collection reconciliation ----------------------------------------------
    def test_daily_collection_reconciliation(self):
        for row in self.daily:
            pf = float(row["parking_and_fees"])
            ef = float(row["energy"])
            gst = float(row["gst"])
            tot = float(row["total"])
            self.assertAlmostEqual(pf + ef + gst, tot, places=2,
                                   msg=f"daily row {row} does not reconcile")

    def test_daily_collection_covers_all_three_days(self):
        dates = {r["date"] for r in self.daily}
        self.assertEqual(dates, {"2026-10-29", "2026-10-30", "2026-10-31"})


class TestTariffHelpers(unittest.TestCase):
    """Unit tests for slab / night / grace logic independent of sample data."""

    @classmethod
    def setUpClass(cls):
        cls.g = main.Garage(DATA_DIR)

    def test_slab_car_boundaries(self):
        g = self.g
        # 2h exactly -> 40 ; 2h1m -> 70 ; 13h -> capped 300
        self.assertEqual(g.slab_fee_for_seconds(2 * 3600, "CAR"), 40.0)
        self.assertEqual(g.slab_fee_for_seconds(2 * 3600 + 60, "CAR"), 70.0)
        self.assertEqual(g.slab_fee_for_seconds(13 * 3600, "CAR"), 300.0)

    def test_slab_24h_blocks(self):
        g = self.g
        # 26h -> cap(300) + slab(2h)=40 -> 340 for CAR
        self.assertEqual(g.slab_fee_for_seconds(26 * 3600, "CAR"), 340.0)
        # exactly 24h -> cap only
        self.assertEqual(g.slab_fee_for_seconds(24 * 3600, "CAR"), 300.0)

    def test_suv_is_1_5x_car(self):
        g = self.g
        self.assertEqual(g.slab_fee_for_seconds(2 * 3600, "SUV"), 60.0)
        self.assertEqual(g.slab_fee_for_seconds(13 * 3600, "SUV"), 450.0)

    def test_two_wheeler_tariff(self):
        g = self.g
        self.assertEqual(g.slab_fee_for_seconds(2 * 3600, "TWO_WHEELER"), 15.0)
        self.assertEqual(g.slab_fee_for_seconds(5 * 3600, "TWO_WHEELER"), 45.0)
        self.assertEqual(g.slab_fee_for_seconds(20 * 3600, "TWO_WHEELER"), 80.0)

    def test_night_flat_only_when_cheaper(self):
        g = self.g
        entry = ts("2026-10-29 20:00:00")
        exit_ = ts("2026-10-30 08:59:00")
        fee, lt = g.parking_fee(entry, exit_, "CAR")
        self.assertEqual((fee, lt), (150.0, "NIGHT_FLAT"))
        # 19:59 entry is not eligible -> slab cap
        entry2 = ts("2026-10-29 19:59:00")
        fee2, lt2 = g.parking_fee(entry2, exit_, "CAR")
        self.assertEqual(fee2, 300.0)
        self.assertEqual(lt2, "PARKING")

    def test_grace_boundary(self):
        g = self.g
        entry = ts("2026-10-29 10:00:00")
        fee, _ = g.parking_fee(entry, ts("2026-10-29 10:15:00"), "CAR")
        self.assertEqual(fee, 0.0)
        fee, _ = g.parking_fee(entry, ts("2026-10-29 10:15:01"), "CAR")
        self.assertEqual(fee, 40.0)


class TestAllocationRules(unittest.TestCase):
    """Bay allocation preference order."""

    @classmethod
    def setUpClass(cls):
        cls.g = main.Garage(DATA_DIR)

    def test_ev_prefers_ev_car_bay(self):
        g = self.g
        bay, btype, sur, res = g.allocate("CAR", True, "TESTPLATE1", ts("2026-10-29 10:00:00"))
        self.assertEqual(btype, "EV_CAR")
        self.assertFalse(sur)

    def test_non_ev_car_prefers_car_bay(self):
        g = self.g
        bay, btype, sur, res = g.allocate("CAR", False, "TESTPLATE2", ts("2026-10-29 10:00:00"))
        self.assertEqual(btype, "CAR")
        self.assertFalse(sur)

    def test_suv_never_uses_car_bay(self):
        g = self.g
        bay, btype, sur, res = g.allocate("SUV", False, "TESTPLATE3", ts("2026-10-29 10:00:00"))
        self.assertEqual(btype, "SUV")

    def test_two_wheeler_only_two_wheeler_bays(self):
        g = self.g
        bay, btype, sur, res = g.allocate("TWO_WHEELER", False, "TESTPLATE4", ts("2026-10-29 10:00:00"))
        self.assertEqual(btype, "TWO_WHEELER")


if __name__ == "__main__":
    unittest.main()
