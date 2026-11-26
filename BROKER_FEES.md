# Broker Fee Rules

## Zheshang Hong Kong equities

User-supplied rule, recorded 2026-11-02:

`automatic_fee_hkd = max(abs(shares * price_hkd) * 0.0002, 5.00)`

The rate is 0.02% of notional (two basis points), with a minimum of HKD 5 per transaction, for both purchases and sales. Round the computed fee to cents. No additional stamp duty or exchange levies are inferred from this rule. The confirmation dialog allows a statement's actual total charges to override the automatic fee. Previously saved explicit fees remain intact.

## Zheshang US equities

Commission: USD 0.008 per share, minimum USD 2 per contract note. Sell-side SEC and TAF follow the dated schedule in `zheshang_us_fee`; the three supplied August-October 2026 statements were checked against the implementation. A manual total fee overrides the estimate.

## Guotou

Rules reconciled on 2026-11-26 against every Guotou contract in the April-November
2026 statements (65 trades to end October plus four in November).

### Hong Kong equities (`guotou_hk_fee`)

Each item is computed on notional and rounded to cents on its own, then summed:

| Item | Rule |
| --- | --- |
| Commission | 0.1%, minimum HKD 100 per contract note |
| Stamp duty | 0.1%, rounded UP to the next whole dollar |
| Settlement fee | 0.0042% |
| Transaction levy | 0.0027% |
| AFRC levy | 0.00015% |
| Trading fee | 0.00565% |

Without the minimum and the rounding this is about 0.2127%, not the flat 0.21%
used before. Checked line by line against the itemised notes for the 2026-04-08
0386.HK buy (HKD 499.85) and the 2026-04-29 9618.HK sell (HKD 1,271.63); the
remaining statement totals match to the cent.

Not covered, so override with the statement total when they apply:
- Five April 2026 sells (0836.HK and 9618.HK on 04-16, 04-22, 04-27) were charged
  0.15% commission. Old records may have had a different commission arrangement;
  correct historical trades from statements instead of recalculating them.
- Products exempt from stamp duty (for example some ETFs).
- The statutory rates change from time to time; update `GUOTOU_HK_RATES`.

### US equities (`guotou_us_fee`)

Commission is 0.2% of notional, rounded to cents, minimum USD 20 per contract note.
US sells additionally include SEC at notional * 0.0000206, rounded UP to cents,
effective 2026-04-04; earlier 2026 is zero. No SEC on buys. Other years' rate
changes require updating the dated schedule; this is not a perpetual rate.
Do not infer Zheshang's TAF or per-share commission for Guotou.

Minimum commission seen on statements: 400 WEAT * 24.06 buy = 20.00;
1 LNG * 290.95 sell = 20.00 + 0.01; 30 COHR * 171.20 sell = 20.00 + 0.11;
20 AMAT * 340 sell = 20.00 + 0.15.

### Both markets

The minimum commission is charged once per contract note. Enter partial fills of
one contract note as a single trade, otherwise the minimum is counted more than once.
Explicit actual total fees still override automatic estimates.

Verified against Guotou's 2026-11-05 statement (2026-11-04 trades):
LNG 90 * 296: commission 53.28 + SEC 0.55 = 53.83;
MRVL 100 * 157: commission 31.40 + SEC 0.33 = 31.73.
https://www.sec.gov/rules-regulations/fee-rate-advisories/2026-2
