# Broker Fee Rules

## Zheshang Hong Kong equities

User-supplied rule, recorded 2026-11-02:

`automatic_fee_hkd = max(abs(shares * price_hkd) * 0.0002, 5.00)`

The rate is 0.02% of notional (two basis points), with a minimum of HKD 5 per transaction, for both purchases and sales. Round the computed fee to cents. No additional stamp duty or exchange levies are inferred from this rule. The confirmation dialog allows a statement's actual total charges to override the automatic fee. Previously saved explicit fees remain intact.

## Zheshang US equities

Commission: USD 0.008 per share, minimum USD 2 per contract note. Sell-side SEC and TAF follow the dated schedule in `zheshang_us_fee`; the three supplied August-October 2026 statements were checked against the implementation. A manual total fee overrides the estimate.

## Guotou

Hong Kong remains 0.21% of notional. US commission remains 0.2% of notional.
US sells additionally include SEC at notional * 0.0000206, rounded UP to cents,
effective 2026-04-04; earlier 2026 is zero. No SEC on buys. Other years' rate
changes require updating the dated schedule; this is not a perpetual rate.
Do not infer Zheshang's TAF or per-share commission for Guotou.
Explicit actual total fees still override automatic estimates.

Verified against Guotou's 2026-11-05 statement (2026-11-04 trades):
LNG 90 * 296: commission 53.28 + SEC 0.55 = 53.83;
MRVL 100 * 157: commission 31.40 + SEC 0.33 = 31.73.
https://www.sec.gov/rules-regulations/fee-rate-advisories/2026-2
