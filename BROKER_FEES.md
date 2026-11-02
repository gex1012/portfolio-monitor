# Broker Fee Rules

## Zheshang Hong Kong equities

User-supplied rule, recorded 2026-11-02:

`automatic_fee_hkd = max(abs(shares * price_hkd) * 0.0002, 5.00)`

The rate is 0.02% of notional (two basis points), with a minimum of HKD 5 per transaction, for both purchases and sales. Round the computed fee to cents. No additional stamp duty or exchange levies are inferred from this rule. The confirmation dialog allows a statement's actual total charges to override the automatic fee. Previously saved explicit fees remain intact.

## Zheshang US equities

Commission: USD 0.008 per share, minimum USD 2 per contract note. Sell-side SEC and TAF follow the dated schedule in `zheshang_us_fee`; the three supplied August-October 2026 statements were checked against the implementation. A manual total fee overrides the estimate.

## Guotou

Existing automatic rules remain unchanged: Hong Kong 0.21% of notional, US 0.2% of notional, unless an explicit actual fee is recorded.
