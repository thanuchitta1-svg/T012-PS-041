"""
PS-041: Parking Garage Billing with Slabs, Lost Tickets, Monthly Passes and EV Bays
Command-file driven billing engine. No UI.

Usage:  python main.py [data_dir]
Reads  : bays.csv, tariffs.csv, passes.csv, wallets.csv, reservations.csv,
         opening_occupancy.csv, anpr_log.csv, commands.txt   (from data_dir)
Writes : receipts.csv, receipt_summary.csv, daily_collection.csv, pass_sales.csv
"""

import csv
import math
import os
import sys
import calendar
from datetime import datetime, timedelta, time as dtime

# ---------------------------------------------------------------------------
# Constants (business rules)
# ---------------------------------------------------------------------------
GRACE_SECONDS = 15 * 60                 # exit within 15 min of entry is free
NIGHT_START = dtime(20, 0)              # night window start (inclusive)
NIGHT_END = dtime(6, 0)                 # night window end (exclusive, early morning)
NIGHT_EXIT_LIMIT = dtime(9, 0)          # exit must be before 09:00 next day
PASS_COVER_START = dtime(6, 0)          # monthly pass covers 06:00-23:00
PASS_COVER_END = dtime(23, 0)
EV_IDLE_FREE_MINUTES = 120              # first 120 min in bay after 100% charge
EV_IDLE_RATE = 2.0                      # Rs per minute
EV_IDLE_CAP = 400.0                     # Rs per session
EV_ENERGY_RATE = 18.0                   # Rs per kWh
EV_ENERGY_GST = 5.0                     # percent
PARKING_GST = 18.0                      # percent on parking-side fees
EV_BAY_SURCHARGE = 50.0                 # non-EV car in EV bay
RESERVED_BAY_RATE = 20.0                # Rs per hour (or part)
PASS_MISUSE_FEE = 100.0
OVERSTAY_FREE_DAYS = 3                  # >72h flagged; Rs 100/day from 4th day
OVERSTAY_RATE = 100.0
PASS_SUSPEND_AFTER = 2                  # misuses in a month
PAYMENT_MODES = ["CASH", "CARD", "UPI", "WALLET"]

TS_FMT = "%Y-%m-%d %H:%M:%S"


def parse_ts(s):
    return datetime.strptime(s.strip(), TS_FMT)


def fmt_ts(dt):
    return dt.strftime(TS_FMT) if dt else ""


def fmt_money(x):
    return f"{x:.2f}"


def ceil_hours(seconds):
    return int(math.ceil(seconds / 3600.0))


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_csv(data_dir, name):
    path = os.path.join(data_dir, name)
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_all(data_dir):
    bays = sorted(load_csv(data_dir, "bays.csv"), key=lambda r: r["bay_id"])

    tariffs = {}
    for r in load_csv(data_dir, "tariffs.csv"):
        tariffs[r["vehicle_type"]] = {
            "first_block_hours": int(r["first_block_hours"]),
            "first_block_fee": float(r["first_block_fee"]),
            "additional_hour_fee": float(r["additional_hour_fee"]),
            "daily_cap": float(r["daily_cap"]),
            "night_flat_fee": float(r["night_flat_fee"]) if r["night_flat_fee"] else None,
            "lost_ticket_fee": float(r["lost_ticket_fee"]) if r["lost_ticket_fee"] else None,
            "monthly_pass_fee": float(r["monthly_pass_fee"]) if r["monthly_pass_fee"] else None,
        }

    passes = {}
    for r in load_csv(data_dir, "passes.csv"):
        passes[r["pass_id"]] = {
            "pass_id": r["pass_id"],
            "plate": r["plate"],
            "vehicle_type": r["vehicle_type"],
            "valid_from": datetime.strptime(r["valid_from"], "%Y-%m-%d").date(),
            "valid_to": datetime.strptime(r["valid_to"], "%Y-%m-%d").date(),
            "status": r["status"],
            "misuse_count": 0,
            "misuse_month": None,
        }

    wallets = {}
    for r in load_csv(data_dir, "wallets.csv"):
        wallets[r["wallet_id"]] = {"balance": float(r["balance"]),
                                   "owner_plate": r["owner_plate"]}

    reservations = []
    for r in load_csv(data_dir, "reservations.csv"):
        reservations.append({
            "reservation_id": r["reservation_id"],
            "plate": r["plate"],
            "bay_type": r["bay_type"],
            "from_ts": parse_ts(r["from_ts"]),
            "to_ts": parse_ts(r["to_ts"]),
            "used": False,
        })

    anpr_plates = set()
    for r in load_csv(data_dir, "anpr_log.csv"):
        if r["gate"] == "ENTRY":
            anpr_plates.add(r["plate_read"].strip())

    return bays, tariffs, passes, wallets, reservations, anpr_plates


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
class Garage:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        (self.bays, self.tariffs, self.passes, self.wallets,
         self.reservations, self.anpr_plates) = load_all(data_dir)

        # bay_id -> ticket_id ; ticket_id -> record
        self.bay_occupied = {}
        self.tickets = {}
        self.plate_to_ticket = {}

        # outputs
        self.pass_sales = []
        self.summary_rows = []
        self.receipt_rows = []
        self.daily_rows = []
        self.paid_exits = []          # dicts for PRINT_DAILY lookups

        self._load_opening_occupancy(data_dir)

    # -- bay helpers ---------------------------------------------------------
    def lowest_free_bay(self, bay_type):
        for b in self.bays:
            if b["bay_type"] == bay_type and b["bay_id"] not in self.bay_occupied:
                return b["bay_id"]
        return None

    def allocation_chain(self, vtype, is_ev):
        """Ordered bay types the vehicle may use (before surcharge tier)."""
        if vtype == "TWO_WHEELER":
            return ["TWO_WHEELER"]
        if vtype == "SUV":
            return ["SUV"]
        if is_ev:                      # EV car
            return ["EV_CAR", "CAR"]
        return ["CAR", "SUV"]          # non-EV car; EV_CAR is surcharge tier

    def surcharge_tier(self, vtype, is_ev):
        return "EV_CAR" if (vtype == "CAR" and not is_ev) else None

    def find_reservation(self, plate, vtype, ts):
        for r in self.reservations:
            if (not r["used"] and r["plate"] == plate
                    and r["bay_type"] == vtype
                    and r["from_ts"] <= ts <= r["to_ts"]):
                return r
        return None

    def allocate(self, vtype, is_ev, plate, ts):
        """Returns (bay_id, bay_type, ev_surcharge, reservation) or (None,...)."""
        chain = self.allocation_chain(vtype, is_ev)
        for t in chain:
            bay = self.lowest_free_bay(t)
            if bay:
                return bay, t, False, None

        res = self.find_reservation(plate, vtype, ts)
        if res:
            for t in chain + [self.surcharge_tier(vtype, is_ev)]:
                if not t:
                    continue
                bay = self.lowest_free_bay(t)
                if bay:
                    return bay, t, False, res

        tier = self.surcharge_tier(vtype, is_ev)
        if tier:
            bay = self.lowest_free_bay(tier)
            if bay:
                return bay, tier, True, None
        return None, None, False, None

    # -- opening occupancy ---------------------------------------------------
    def _load_opening_occupancy(self, data_dir):
        for r in load_csv(data_dir, "opening_occupancy.csv"):
            tkt = r["ticket_id"]
            bay_type = r["bay_type"]
            bay = self.lowest_free_bay(bay_type)
            if bay is None:
                continue
            self.bay_occupied[bay] = tkt
            self.tickets[tkt] = {
                "ticket_id": tkt,
                "plate": r["plate"],
                "vehicle_type": r["vehicle_type"],
                "ev": r["ev"].strip().lower() == "true",
                "entry_ts": parse_ts(r["entry_ts"]),
                "bay_id": bay,
                "bay_type": bay_type,
                "pass_id": None,
                "pass_active": False,
                "pass_misuse": False,
                "charge_start_ts": None,
                "charge_complete_ts": None,
                "charge_kwh": 0.0,
                "ev_surcharge": False,
                "reservation": None,
                "status": "OPEN",
                "exit_ts": None,
                "receipt_lines": [],
            }
            self.plate_to_ticket[r["plate"]] = tkt

    # -- tariff helpers ------------------------------------------------------
    def slab_fee_for_seconds(self, seconds, vtype):
        """Slab fee for a duration, billed per 24-hour block from entry."""
        t = self.tariffs[vtype]
        if seconds <= 0:
            return 0.0
        full_blocks = int(seconds // 86400)
        rem = seconds % 86400
        fee = full_blocks * t["daily_cap"]
        if rem > 0:
            fee += self._slab_for_hours(ceil_hours(rem), vtype)
        return fee

    def _slab_for_hours(self, hours, vtype):
        t = self.tariffs[vtype]
        if hours <= t["first_block_hours"]:
            return t["first_block_fee"]
        return min(t["first_block_fee"]
                   + (hours - t["first_block_hours"]) * t["additional_hour_fee"],
                   t["daily_cap"])

    def night_flat_eligible(self, entry_ts, exit_ts, vtype):
        t = self.tariffs[vtype]
        if t["night_flat_fee"] is None:
            return False
        et = entry_ts.time()
        in_window = et >= NIGHT_START or et < NIGHT_END
        if not in_window:
            return False
        # exit before 09:00 on the next calendar day
        return (exit_ts.date() == entry_ts.date() + timedelta(days=1)
                and exit_ts.time() < NIGHT_EXIT_LIMIT)

    def parking_fee(self, entry_ts, exit_ts, vtype, ignore_grace=False):
        """Returns (fee, line_type). Applies grace, night flat, slabs."""
        seconds = (exit_ts - entry_ts).total_seconds()
        if not ignore_grace and seconds <= GRACE_SECONDS:
            return 0.0, "PARKING"
        slab = self.slab_fee_for_seconds(seconds, vtype)
        if self.night_flat_eligible(entry_ts, exit_ts, vtype):
            flat = self.tariffs[vtype]["night_flat_fee"]
            if flat < slab:
                return flat, "NIGHT_FLAT"
        return slab, "PARKING"

    # -- pass helpers --------------------------------------------------------
    def pass_coverage_seconds(self, entry_ts, exit_ts):
        """Seconds of [entry,exit] falling inside 06:00-23:00 each day."""
        covered = 0.0
        day = entry_ts.date()
        end_day = exit_ts.date()
        while day <= end_day:
            win_start = datetime.combine(day, PASS_COVER_START)
            win_end = datetime.combine(day, PASS_COVER_END)
            lo = max(entry_ts, win_start)
            hi = min(exit_ts, win_end)
            if hi > lo:
                covered += (hi - lo).total_seconds()
            day += timedelta(days=1)
        return covered

    def active_pass_for(self, pass_id, plate, entry_ts):
        p = self.passes.get(pass_id)
        if not p or p["status"] != "ACTIVE":
            return None
        if p["plate"] != plate:
            return None
        if not (p["valid_from"] <= entry_ts.date() <= p["valid_to"]):
            return None
        return p

    def register_misuse(self, pass_id, month):
        p = self.passes.get(pass_id)
        if not p:
            return
        if p["misuse_month"] != month:
            p["misuse_month"] = month
            p["misuse_count"] = 0
        p["misuse_count"] += 1
        if p["misuse_count"] >= PASS_SUSPEND_AFTER:
            p["status"] = "SUSPENDED"

    # -- receipt line helper -------------------------------------------------
    @staticmethod
    def add_line(lines, line_type, description, amount, gst_rate):
        gst = round(amount * gst_rate / 100.0, 2)
        lines.append({
            "line_type": line_type,
            "description": description,
            "amount": round(amount, 2),
            "gst_rate": gst_rate,
            "gst_amount": gst,
        })
        return gst

    # -- command handlers ----------------------------------------------------
    def cmd_entry(self, parts):
        tkt, ts_s, plate, vtype, ev_s = parts[1], parts[2], parts[3], parts[4], parts[5]
        pass_id = parts[6] if len(parts) > 6 and parts[6] else None
        ts = parse_ts(ts_s)
        is_ev = ev_s.strip().lower() == "true"

        # pass validation / misuse
        active_pass = None
        pass_misuse = False
        if pass_id:
            p = self.passes.get(pass_id)
            if p and p["status"] == "ACTIVE":
                if p["plate"] == plate:
                    active_pass = self.active_pass_for(pass_id, plate, ts)
                else:
                    pass_misuse = True
                    self.register_misuse(pass_id, ts.strftime("%Y-%m"))

        bay, bay_type, ev_sur, res = self.allocate(vtype, is_ev, plate, ts)
        if bay is None:
            self.tickets[tkt] = {
                "ticket_id": tkt, "plate": plate, "vehicle_type": vtype,
                "ev": is_ev, "entry_ts": ts, "exit_ts": None, "bay_id": None,
                "bay_type": None, "pass_id": None, "pass_active": False,
                "pass_misuse": pass_misuse, "charge_start_ts": None,
                "charge_complete_ts": None, "charge_kwh": 0.0,
                "ev_surcharge": False, "reservation": None,
                "status": "REJECTED_ENTRY", "receipt_lines": [],
            }
            return

        self.bay_occupied[bay] = tkt
        if res:
            res["used"] = True
        self.tickets[tkt] = {
            "ticket_id": tkt, "plate": plate, "vehicle_type": vtype,
            "ev": is_ev, "entry_ts": ts, "exit_ts": None, "bay_id": bay,
            "bay_type": bay_type,
            "pass_id": pass_id if active_pass else None,
            "pass_active": active_pass is not None,
            "pass_misuse": pass_misuse,
            "charge_start_ts": None, "charge_complete_ts": None,
            "charge_kwh": 0.0,
            "ev_surcharge": ev_sur,
            "reservation": res,
            "status": "OPEN", "receipt_lines": [],
        }
        self.plate_to_ticket[plate] = tkt

    def cmd_charge_start(self, parts):
        tkt = parts[1]
        if tkt in self.tickets:
            self.tickets[tkt]["charge_start_ts"] = parse_ts(parts[2])

    def cmd_charge_complete(self, parts):
        tkt = parts[1]
        if tkt in self.tickets:
            self.tickets[tkt]["charge_complete_ts"] = parse_ts(parts[2])
            self.tickets[tkt]["charge_kwh"] = float(parts[3])

    def cmd_issue_pass(self, parts):
        pid, ts_s, plate, vtype, month = parts[1], parts[2], parts[3], parts[4], parts[5]
        ts = parse_ts(ts_s)
        year, mon = int(month[:4]), int(month[5:7])
        last_day = calendar.monthrange(year, mon)[1]
        days_charged = min(30, last_day - ts.day + 1)
        fee = self.tariffs[vtype]["monthly_pass_fee"]
        amount = math.ceil(fee * days_charged / 30.0)
        valid_to = datetime(year, mon, last_day).date()

        self.passes[pid] = {
            "pass_id": pid, "plate": plate, "vehicle_type": vtype,
            "valid_from": ts.date(), "valid_to": valid_to,
            "status": "ACTIVE", "misuse_count": 0, "misuse_month": None,
        }
        self.pass_sales.append({
            "pass_id": pid, "plate": plate, "issue_ts": fmt_ts(ts),
            "days_charged": days_charged, "amount": fmt_money(amount),
        })

    # -- billing -------------------------------------------------------------
    def compute_bill(self, rec, exit_ts, is_lost, anpr_matched):
        """Builds receipt lines and totals. Returns dict of bill fields."""
        entry_ts = rec["entry_ts"]
        vtype = rec["vehicle_type"]
        seconds = (exit_ts - entry_ts).total_seconds()
        duration_min = int(seconds // 60)

        lines = []
        parking_fee = 0.0
        pass_covered_min = 0
        idle_fee = 0.0
        energy_fee = 0.0
        surcharges = 0.0
        gst_total = 0.0

        # ---- primary parking charge -------------------------------------
        if is_lost:
            t = self.tariffs[vtype]
            if anpr_matched:
                computed, _lt = self.parking_fee(entry_ts, exit_ts, vtype,
                                                 ignore_grace=True)
                fee = max(computed, t["lost_ticket_fee"])
                desc = "Lost Ticket (ANPR Matched)"
            else:
                fee = t["lost_ticket_fee"]
                desc = "Lost Ticket (No ANPR Match)"
            parking_fee = fee
            gst_total += self.add_line(lines, "LOST_TICKET", desc, fee, PARKING_GST)

        elif rec["pass_active"]:
            covered = self.pass_coverage_seconds(entry_ts, exit_ts)
            pass_covered_min = int(covered // 60)
            uncovered = seconds - covered
            uncov_fee = 0.0
            if uncovered > 0:
                uncov_fee = self._slab_for_hours(ceil_hours(uncovered), vtype)
            self.add_line(lines, "PASS_COVER", "Monthly Pass Coverage", 0.0, PARKING_GST)
            if uncov_fee > 0:
                parking_fee = uncov_fee
                gst_total += self.add_line(
                    lines, "PARKING",
                    f"Parking Outside Pass Hours ({int(uncovered // 60)} min)",
                    uncov_fee, PARKING_GST)

        elif rec["pass_misuse"]:
            fee, _lt = self.parking_fee(entry_ts, exit_ts, vtype, ignore_grace=True)
            parking_fee = fee
            gst_total += self.add_line(lines, "PARKING",
                                      f"Parking Fee ({duration_min} min)", fee, PARKING_GST)

        else:
            fee, line_type = self.parking_fee(entry_ts, exit_ts, vtype)
            parking_fee = fee
            desc = ("Parking Fee (Grace Period)" if fee == 0.0 and seconds <= GRACE_SECONDS
                    else f"Parking Fee ({duration_min} min)")
            if line_type == "NIGHT_FLAT":
                gst_total += self.add_line(lines, "NIGHT_FLAT", "Night Flat Fee", fee, PARKING_GST)
            else:
                gst_total += self.add_line(lines, "PARKING", desc, fee, PARKING_GST)

        # ---- overstay ----------------------------------------------------
        if seconds > OVERSTAY_FREE_DAYS * 86400 and not rec["pass_active"]:
            days = int(math.ceil(seconds / 86400.0))
            overstay_days = days - OVERSTAY_FREE_DAYS
            fee = overstay_days * OVERSTAY_RATE
            surcharges += fee
            gst_total += self.add_line(lines, "OVERSTAY",
                                      f"Overstay Penalty ({overstay_days} days beyond 72h)",
                                      fee, PARKING_GST)

        # ---- EV bay surcharge (non-EV car in EV bay) ----------------------
        if rec["ev_surcharge"]:
            surcharges += EV_BAY_SURCHARGE
            gst_total += self.add_line(lines, "EV_BAY_SURCHARGE",
                                      "Non-EV Parked in EV Bay Surcharge",
                                      EV_BAY_SURCHARGE, PARKING_GST)

        # ---- reserved bay --------------------------------------------------
        if rec["reservation"] is not None:
            hours = ceil_hours(seconds)
            fee = hours * RESERVED_BAY_RATE
            surcharges += fee
            gst_total += self.add_line(lines, "RESERVED_BAY",
                                      f"Reserved Bay Fee ({hours}h @ Rs {RESERVED_BAY_RATE:.0f}/h)",
                                      fee, PARKING_GST)

        # ---- pass misuse ---------------------------------------------------
        if rec["pass_misuse"]:
            surcharges += PASS_MISUSE_FEE
            gst_total += self.add_line(lines, "PASS_MISUSE", "Pass Misuse Penalty",
                                      PASS_MISUSE_FEE, PARKING_GST)

        # ---- EV energy & idle ----------------------------------------------
        if rec["charge_complete_ts"] is not None:
            kwh = rec["charge_kwh"]
            energy_fee = round(kwh * EV_ENERGY_RATE, 2)
            gst_total += self.add_line(lines, "EV_ENERGY",
                                      f"EV Charging Energy ({kwh} kWh @ Rs {EV_ENERGY_RATE:.0f})",
                                      energy_fee, EV_ENERGY_GST)

            idle_start = max(rec["charge_complete_ts"],
                             entry_ts + timedelta(minutes=EV_IDLE_FREE_MINUTES))
            idle_sec = (exit_ts - idle_start).total_seconds()
            if idle_sec > 0:
                idle_min = int(math.ceil(idle_sec / 60.0))
                idle_fee = min(EV_IDLE_CAP, idle_min * EV_IDLE_RATE)
                if idle_fee > 0:
                    gst_total += self.add_line(lines, "EV_IDLE",
                                              f"EV Idle Fee ({idle_min} min @ Rs {EV_IDLE_RATE:.0f}/min, capped at {EV_IDLE_CAP:.0f})",
                                              idle_fee, PARKING_GST)

        total = round(parking_fee + idle_fee + energy_fee + surcharges + gst_total, 2)
        return {
            "lines": lines, "parking_fee": parking_fee,
            "pass_covered_min": pass_covered_min, "idle_fee": idle_fee,
            "energy_fee": energy_fee, "surcharges": surcharges,
            "gst_total": round(gst_total, 2), "total": total,
            "duration_min": duration_min,
        }

    def settle_payment(self, rec, exit_ts, pmode, wid, bill):
        """Returns 'PAID' or 'PAYMENT_FAILED'. Mutates wallet on success."""
        if pmode == "WALLET":
            w = self.wallets.get(wid)
            if w is None or w["balance"] < bill["total"]:
                return "PAYMENT_FAILED"
            w["balance"] = round(w["balance"] - bill["total"], 2)
        return "PAID"

    def finalize_exit(self, rec, exit_ts, pmode, bill, status):
        rec["exit_ts"] = exit_ts
        rec["duration_min"] = bill["duration_min"]
        rec["parking_fee"] = bill["parking_fee"]
        rec["pass_covered_min"] = bill["pass_covered_min"]
        rec["idle_fee"] = bill["idle_fee"]
        rec["energy_fee"] = bill["energy_fee"]
        rec["surcharges"] = bill["surcharges"]
        rec["gst_total"] = bill["gst_total"]
        rec["total"] = bill["total"]
        rec["payment_mode"] = pmode
        rec["status"] = status
        rec["receipt_lines"] = bill["lines"]

        if status == "PAID":
            bid = rec["bay_id"]
            if bid and self.bay_occupied.get(bid) == rec["ticket_id"]:
                del self.bay_occupied[bid]
            if self.plate_to_ticket.get(rec["plate"]) == rec["ticket_id"]:
                del self.plate_to_ticket[rec["plate"]]
            self.paid_exits.append({
                "date": exit_ts.date().isoformat(),
                "payment_mode": pmode,
                "parking_and_fees": round(bill["parking_fee"] + bill["idle_fee"]
                                          + bill["surcharges"], 2),
                "energy": bill["energy_fee"],
                "gst": bill["gst_total"],
                "total": bill["total"],
            })

    def cmd_exit(self, parts):
        tkt = parts[1]
        exit_ts = parse_ts(parts[2])
        pmode = parts[3]
        wid = parts[4] if len(parts) > 4 and parts[4] else None
        rec = self.tickets.get(tkt)
        if not rec or rec["status"] not in ("OPEN", "PAYMENT_FAILED"):
            return
        bill = self.compute_bill(rec, exit_ts, is_lost=False, anpr_matched=False)
        status = self.settle_payment(rec, exit_ts, pmode, wid, bill)
        self.finalize_exit(rec, exit_ts, pmode, bill, status)

    def cmd_lost_ticket_exit(self, parts):
        exit_ts = parse_ts(parts[1])
        plate = parts[2]
        vtype = parts[3]
        pmode = parts[4]
        wid = parts[5] if len(parts) > 5 and parts[5] else None

        # find the open ticket for this plate (entry recoverable from command log)
        rec = None
        for tid, t in self.tickets.items():
            if t["plate"] == plate and t["status"] in ("OPEN", "PAYMENT_FAILED"):
                rec = t
                break

        anpr_matched = plate in self.anpr_plates

        if rec is None:
            # No entry on record: flat lost-ticket fee, synthetic id
            t = self.tariffs[vtype]
            fee = t["lost_ticket_fee"]
            gst = round(fee * PARKING_GST / 100.0, 2)
            total = round(fee + gst, 2)
            status = self.settle_payment(None, exit_ts, pmode, wid,
                                         {"total": total})
            rec = {
                "ticket_id": f"LOST-{plate}", "plate": plate,
                "vehicle_type": vtype, "ev": False, "entry_ts": exit_ts,
                "exit_ts": exit_ts, "bay_id": None, "bay_type": None,
                "pass_active": False, "pass_misuse": False,
                "duration_min": 0, "parking_fee": fee, "pass_covered_min": 0,
                "idle_fee": 0.0, "energy_fee": 0.0, "surcharges": 0.0,
                "gst_total": gst, "total": total, "payment_mode": pmode,
                "status": status,
                "receipt_lines": [{
                    "line_type": "LOST_TICKET",
                    "description": "Lost Ticket (No ANPR Match)",
                    "amount": fee, "gst_rate": PARKING_GST, "gst_amount": gst,
                }],
            }
            self.tickets[rec["ticket_id"]] = rec
            if status == "PAID":
                self.paid_exits.append({
                    "date": exit_ts.date().isoformat(), "payment_mode": pmode,
                    "parking_and_fees": fee, "energy": 0.0, "gst": gst,
                    "total": total,
                })
            return

        bill = self.compute_bill(rec, exit_ts, is_lost=True, anpr_matched=anpr_matched)
        status = self.settle_payment(rec, exit_ts, pmode, wid, bill)
        self.finalize_exit(rec, exit_ts, pmode, bill, status)

    # -- print commands --------------------------------------------------------
    def cmd_print_receipt(self, parts):
        tkt = parts[1]
        rec = self.tickets.get(tkt)
        if not rec:
            return
        if rec["status"] == "REJECTED_ENTRY":
            self.summary_rows.append({
                "ticket_id": tkt, "plate": rec["plate"], "bay_id": "",
                "entry_ts": fmt_ts(rec["entry_ts"]), "exit_ts": "",
                "duration_min": "", "parking_fee": "", "pass_covered_min": "",
                "idle_fee": "", "energy_fee": "", "surcharges": "",
                "gst_total": "", "total": "", "payment_mode": "",
                "status": "REJECTED_ENTRY",
            })
            return
        if rec.get("exit_ts") is None:
            return  # still parked / never exited

        self.summary_rows.append({
            "ticket_id": rec["ticket_id"], "plate": rec["plate"],
            "bay_id": rec["bay_id"] or "",
            "entry_ts": fmt_ts(rec["entry_ts"]), "exit_ts": fmt_ts(rec["exit_ts"]),
            "duration_min": str(rec.get("duration_min", "")),
            "parking_fee": fmt_money(rec["parking_fee"]),
            "pass_covered_min": str(rec.get("pass_covered_min", "")),
            "idle_fee": fmt_money(rec["idle_fee"]),
            "energy_fee": fmt_money(rec["energy_fee"]),
            "surcharges": fmt_money(rec["surcharges"]),
            "gst_total": fmt_money(rec["gst_total"]),
            "total": fmt_money(rec["total"]),
            "payment_mode": rec.get("payment_mode", ""),
            "status": rec["status"],
        })
        for i, l in enumerate(rec["receipt_lines"], start=1):
            self.receipt_rows.append({
                "ticket_id": rec["ticket_id"], "line_no": i,
                "line_type": l["line_type"], "description": l["description"],
                "amount": fmt_money(l["amount"]),
                "gst_rate": fmt_money(l["gst_rate"]),
                "gst_amount": fmt_money(l["gst_amount"]),
            })

    def cmd_print_daily(self, parts):
        date_s = parts[1]
        agg = {}
        for e in self.paid_exits:
            if e["date"] != date_s:
                continue
            a = agg.setdefault(e["payment_mode"], {
                "receipts": 0, "parking_and_fees": 0.0, "energy": 0.0,
                "gst": 0.0, "total": 0.0})
            a["receipts"] += 1
            a["parking_and_fees"] += e["parking_and_fees"]
            a["energy"] += e["energy"]
            a["gst"] += e["gst"]
            a["total"] += e["total"]

        modes = [m for m in PAYMENT_MODES if m in agg]
        modes += sorted(m for m in agg if m not in PAYMENT_MODES)
        for m in modes:
            a = agg[m]
            self.daily_rows.append({
                "date": date_s, "payment_mode": m, "receipts": a["receipts"],
                "parking_and_fees": fmt_money(a["parking_and_fees"]),
                "energy": fmt_money(a["energy"]), "gst": fmt_money(a["gst"]),
                "total": fmt_money(a["total"]),
            })

    # -- main loop -------------------------------------------------------------
    def run(self):
        cmd_path = os.path.join(self.data_dir, "commands.txt")
        with open(cmd_path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("|")
                cmd = parts[0]
                if cmd == "ENTRY":
                    self.cmd_entry(parts)
                elif cmd == "CHARGE_START":
                    self.cmd_charge_start(parts)
                elif cmd == "CHARGE_COMPLETE":
                    self.cmd_charge_complete(parts)
                elif cmd == "EXIT":
                    self.cmd_exit(parts)
                elif cmd == "LOST_TICKET_EXIT":
                    self.cmd_lost_ticket_exit(parts)
                elif cmd == "ISSUE_PASS":
                    self.cmd_issue_pass(parts)
                elif cmd == "PRINT_RECEIPT":
                    self.cmd_print_receipt(parts)
                elif cmd == "PRINT_DAILY":
                    self.cmd_print_daily(parts)

    # -- output ------------------------------------------------------------------
    def write_outputs(self):
        d = self.data_dir
        with open(os.path.join(d, "pass_sales.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["pass_id", "plate", "issue_ts", "days_charged", "amount"])
            w.writeheader()
            w.writerows(self.pass_sales)

        with open(os.path.join(d, "receipts.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["ticket_id", "line_no", "line_type",
                                              "description", "amount", "gst_rate", "gst_amount"])
            w.writeheader()
            w.writerows(self.receipt_rows)

        with open(os.path.join(d, "receipt_summary.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=[
                "ticket_id", "plate", "bay_id", "entry_ts", "exit_ts", "duration_min",
                "parking_fee", "pass_covered_min", "idle_fee", "energy_fee",
                "surcharges", "gst_total", "total", "payment_mode", "status"])
            w.writeheader()
            w.writerows(self.summary_rows)

        with open(os.path.join(d, "daily_collection.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["date", "payment_mode", "receipts",
                                              "parking_and_fees", "energy", "gst", "total"])
            w.writeheader()
            w.writerows(self.daily_rows)


def run_simulation(data_dir=None):
    if data_dir is None:
        data_dir = os.path.dirname(os.path.abspath(__file__))
    g = Garage(data_dir)
    g.run()
    g.write_outputs()
    print("=" * 50)
    print("PS-041 Parking Garage Billing Engine")
    print("=" * 50)
    print(f"pass_sales.csv        : {len(g.pass_sales)} rows")
    print(f"receipts.csv          : {len(g.receipt_rows)} lines")
    print(f"receipt_summary.csv   : {len(g.summary_rows)} receipts")
    print(f"daily_collection.csv  : {len(g.daily_rows)} rows")


if __name__ == "__main__":
    run_simulation(sys.argv[1] if len(sys.argv) > 1 else None)
