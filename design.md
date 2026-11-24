# PS-041 — Design Document (summary)

## Glossary

| Term | Meaning |
|---|---|
| Bay | Parkable slot typed TWO_WHEELER / CAR / SUV / EV_CAR, identified `LEVEL-TYPE-nnn` |
| Ticket | Entry record (`TKT-nnnnn`) linking plate, vehicle type, EV flag, entry time, bay |
| Slab | Time tariff: first block fee + per-additional-hour fee, capped per 24 h block |
| Grace | First 15 minutes free (lost-ticket and pass cases ignore it) |
| Night flat | Flat night rate for qualifying overnight stays when cheaper than slabs |
| Pass | Monthly pass bound to one plate, valid for a calendar month, covers 06:00–23:00 |
| Misuse | Pass presented by a plate other than the bound plate |
| Lost ticket | Exit without a ticket; fee from ANPR log recovery or flat lost-ticket fee |
| EV session | CHARGE_START → CHARGE_COMPLETE; energy billed per kWh, idle fee after 100 % |
| Overstay | Continuous stay beyond 72 h; ₹100/day from the 4th day |
| Reservation | Pre-booked bay slot for a plate inside a time window; ₹20/hour when used |

## Class diagram (single-file engine, `main.py`)

```
Garage
 ├── bays: list[Bay]                 (bay_id, level, bay_type)
 ├── tariffs: dict[vtype -> Tariff]  (slab, cap, night, lost, pass fee)
 ├── passes: dict[pass_id -> Pass]   (plate, validity, status, misuse_count)
 ├── wallets: dict[wallet_id -> Wallet] (balance, owner_plate)
 ├── reservations: list[Reservation] (plate, bay_type, from_ts, to_ts, used)
 ├── anpr_plates: set[str]           (exact plate reads at ENTRY gate)
 ├── bay_occupied: dict[bay_id -> ticket_id]
 ├── tickets: dict[ticket_id -> Ticket]
 └── outputs: pass_sales, summary_rows, receipt_rows, daily_rows, paid_exits

Ticket: ticket_id, plate, vehicle_type, ev, entry_ts, exit_ts, bay_id, bay_type,
        pass_active, pass_misuse, charge_start_ts, charge_complete_ts, charge_kwh,
        ev_surcharge, reservation, status(OPEN/PAID/PAYMENT_FAILED/REJECTED_ENTRY),
        receipt_lines[]

ReceiptLine: line_type, description, amount, gst_rate, gst_amount
```

## State diagram — Ticket

```
            ENTRY (bay free / reservation / reject)
                 │                │
        bay allocated        no bay anywhere
                 │                │
              OPEN ──────────► REJECTED_ENTRY (terminal)
                 │
        EXIT / LOST_TICKET_EXIT
                 │
        payment OK? ──no──► PAYMENT_FAILED ──retry EXIT──► (re-bill)
                 │yes
              PAID (terminal; bay released, collection recorded)
```

## Business-rule register

| ID | Rule |
|---|---|
| BR-01 | Bay allocation: TWO_WHEELER→TWO_WHEELER only; SUV→SUV only; EV car→EV_CAR then CAR; non-EV car→CAR then SUV then EV_CAR |
| BR-02 | Non-EV car in EV_CAR bay pays ₹50 surcharge (EV_BAY_SURCHARGE) |
| BR-03 | When preferred bays are full, entry is rejected unless a matching reservation (plate + type + time window) exists; reservation fee ₹20/hour (or part) |
| BR-04 | Exit within 15 min 00 s of entry is free; 15 min 01 s is billed (grace ignored for lost-ticket and pass cases) |
| BR-05 | Slabs billed per 24-hour block from entry: full blocks at daily cap, remainder at first-block + additional-hour rates, each capped |
| BR-06 | Night flat: entry in [20:00, 06:00) and exit before 09:00 next calendar day → flat fee if lower than slab total |
| BR-07 | Lost ticket: ANPR exact plate match → max(computed slab fee, flat lost fee); no exact match → flat lost fee (CAR/SUV ₹500, TWO_WHEELER ₹200) |
| BR-08 | Monthly pass covers 06:00–23:00 daily; outside minutes billed at slab rates for the outside portion |
| BR-09 | Pass bound to one plate; valid only within valid_from–valid_to; mid-month issue pro-rated daily on 30 days, rounded up to the rupee |
| BR-10 | Pass presented by a different plate → rejected, billed at slab rate + ₹100; 2 misuses in a month → pass suspended |
| BR-11 | EV energy ₹18/kWh at 5% GST; idle fee ₹2/min after the first 120 min in bay once charging completes, capped ₹400/session |
| BR-12 | Stay > 72 h → ₹100/day from the 4th day; pass holders flagged but not surcharged |
| BR-13 | GST 18% on all parking-side fees (parking, night, lost, idle, surcharges, overstay); 5% on EV energy; shown per line |
| BR-14 | Payment CASH/CARD/UPI always succeed; WALLET only if balance covers the whole bill; no partial payment; failed attempt leaves ticket open for retry |
| BR-15 | Opening-occupancy vehicles are pre-loaded into bays and billed normally on exit |
| BR-16 | Commands processed strictly in file order; `#` comments and blank lines ignored |
| BR-17 | `PRINT_RECEIPT` emits summary + line rows; `PRINT_DAILY` emits one row per payment mode for the exit date |
| BR-18 | Bay allocated is the lowest free `bay_id` of the chosen type |
| BR-19 | EV car with no free EV_CAR bay takes a CAR bay (no EV-bay surcharge) |
| BR-20 | SUV tariff is 1.5× CAR (encoded in tariffs.csv); EV cars use the CAR tariff |
| BR-21 | Pass misuse count resets when the calendar month changes |
| BR-22 | Reservation is consumed only when it is actually needed for admission |
| BR-23 | Wallet balance is debited once, on the successful payment only |
| BR-24 | Rejected entries produce a `REJECTED_ENTRY` summary row if printed |
