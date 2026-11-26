# T012-PS-041 — Parking Garage Billing with Slabs, Lost Tickets, Monthly Passes and EV Bays
# T012-PS-041 – Parking Garage Billing System

A Python-based, command-line billing engine for managing multi-level parking garage operations.

**Language:** Python 3.10+  
**Developed using:** Python 3.12  
**Interface:** Command-line / File-driven  
**Dependencies:** No external dependencies

**Team T012**
- Chinmayi R (1AT24CD024)
- Chitta Thanusha (1AT24CD025)

## How to Run

```powershell
python main.py
```

To use another data folder:

```powershell
python main.py <data_dir>
```

## Input Files

The application reads the following files:

- `bays.csv` – Parking bay configuration
- `tariffs.csv` – Parking rates
- `passes.csv` – Monthly passes
- `wallets.csv` – Wallet balances
- `reservations.csv` – Reserved bay details
- `opening_occupancy.csv` – Initial vehicle occupancy
- `anpr_log.csv` – Vehicle recognition records
- `commands.txt` – Commands to process
## test_suite.py

## decision_log.md

## Output Files

| File | Purpose |
|---|---|
| `receipts.csv` | Detailed receipt lines |
| `receipt_summary.csv` | Receipt totals, GST and payment status |
| `daily_collection.csv` | Collections grouped by payment mode |
| `pass_sales.csv` | Monthly pass sales records |

## Implemented Features

- Vehicle entry, exit and bay allocation by vehicle type.
- Parking slabs, 15-minute grace period and night rates.
- Lost-ticket handling using exact ANPR plate matching.
- Monthly passes, prorated pricing and misuse detection.
- EV charging and idle fee calculation.
- Overstay charges and reserved bay handling.
- GST calculation and payment through Cash, Card, UPI and Wallet.
- Receipt generation and daily collection reports.

## Run the Tests

From the project root directory:

```powershell
python -m unittest discover -s tests -p "test_suite.py" -v
```
The test suite covers parking allocation, tariff calculations, edge cases, EV charging, lost tickets, monthly passes, payments and daily collection.

## Project Documentation

- `design.md` – System design and business rules (BR-01 to BR-24).
- `decision_log.md` – Technical decisions.
- `docs/SAMPLE_DATA_README.md` – Input and output file formats.

## Demo Video
Final Project Demonstration – Team T012, PS-041
https://drive.google.com/file/d/1QtRttB3a-4wV6KDIltyIY-jZqAEcR9au/view?usp=drivesdk


