# T012-PS-041 — Parking Garage Billing with Slabs, Lost Tickets, Monthly Passes and EV Bays

Command-line / file-driven billing engine for a multi-level parking operator.
Python 3.10+ (developed on 3.12). No UI, no external dependencies.

Team: T012 — Chinmayi R (1AT24CD024), Chitta Thanusha (1AT24CD025)

## How to run

```powershell
python main.py            # uses the CSV/command files in this folder
python main.py <data_dir> # or point at another data pack with the same schema
```

The engine reads `bays.csv`, `tariffs.csv`, `passes.csv`, `wallets.csv`,
`reservations.csv`, `opening_occupancy.csv`, `anpr_log.csv` and `commands.txt`,
processes the command stream in order, and writes four output files:

| File | Contents |
|---|---|
| `receipts.csv` | one row per receipt line per `PRINT_RECEIPT` |
| `receipt_summary.csv` | one row per `PRINT_RECEIPT` (fee totals, GST, payment, status) |
| `daily_collection.csv` | one row per payment mode per `PRINT_DAILY` |
| `pass_sales.csv` | one row per `ISSUE_PASS` |

Column formats follow the "Output format expected at evaluation" section of the
sample-data README (`docs/SAMPLE_DATA_README.md`).

## Run the tests

```powershell
python -m unittest test_suite.py -v
```

26 tests: every planted edge case (EC-01 … EC-08), the extra traps (EV idle cap,
reserved bay, lost-ticket ANPR match/misread, overstay, wallet retry, pass misuse
and suspension), tariff/slab unit tests, allocation-order tests, and a
daily-collection reconciliation check.

## What is implemented

- Bay allocation by vehicle type with EV preference, non-EV-in-EV-bay surcharge,
  reserved-bay override and rejection when full (`REJECTED_ENTRY`).
- Time slabs per 24-hour block from entry, per-type tariffs, 15-minute grace,
  night flat rate (20:00–06:00 entry, exit before 09:00 next day, only if cheaper).
- Lost tickets: ANPR exact-match recovery → `max(actual slab fee, flat lost fee)`,
  otherwise flat fee; grace ignored.
- Monthly passes: plate binding, validity window, 06:00–23:00 coverage with
  slab billing for outside hours, mid-month pro-ration on a 30-day basis rounded
  up, misuse penalty (slab + ₹100) and suspension after 2 misuses in a month.
- EV charging: ₹18/kWh at 5% GST, idle fee ₹2/min after the first 120 minutes
  once charging completes, capped at ₹400.
- Overstay: ₹100/day from the 4th day beyond 72 h (pass holders exempt).
- GST: 18% on all parking-side fees, 5% on EV energy; shown per receipt line.
- Payments: CASH / CARD / UPI / WALLET; wallet is all-or-nothing and a failed
  attempt leaves the ticket open for a retry exit.
- `PRINT_RECEIPT` and `PRINT_DAILY` produce the evaluation CSVs.

See `design.md` (business-rule register BR-01 … BR-24) and `decision_log.md`.
