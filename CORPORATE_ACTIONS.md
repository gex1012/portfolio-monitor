# Split accounting

- Refresh loads FMP `/stable/splits?symbol=...` for every traded symbol, cached
  for one hour. The Refresh data button clears this cache. The last successful
  per-symbol snapshot is saved under ignored `data/`; Yahoo corporate actions
  is the fallback when FMP is unavailable. Both feeds failing shows a warning.
  Cloud local disk is not durable across redeploys, so FMP remains the source.
- Ratios are arbitrary positive numerator/denominator, including reverse splits.
  Events take effect at exchange open on the effective date, not announcement
  or record date. US uses New York (DST aware); HK/China uses local 09:30.
- Replay starts from original trades each time. The stable symbol/date event ID
  prevents repeated application. Each broker's then-existing shares multiply by
  the ratio. Total remaining cost, past fees and dividend records do not change.
  Sales on/after the effective date use the adjusted average cost. Purchases on
  the effective date are already in new-share units and are not multiplied.
- Undated opening imports are anchored to the earliest dated trade in the
  ledger (today if none), not company inception. Restore actual acquisition
  dates to account for any earlier corporate actions; they cannot be inferred.
- Fractional shares are retained and flagged. Cash-in-lieu requires the actual
  broker settlement; the app must not invent a fractional disposal or cash PnL.
- FMP full and Yahoo history are already split adjusted, so never apply another
  split factor. Tencent raw HK history is adjusted explicitly for charts/returns.
- Timestamped pre-split quotes pause valuation instead of combining old prices
  with new shares. Feeds with missing timestamps cannot provide this guarantee.
- Issuer-verified SOXX exception: 3:1 effective 2026-11-05; source:
  https://www.sec.gov/Archives/edgar/data/1100663/000119312526430480/d156277d497.htm
  This overrides conflicting provider dates around that event, not future ratios.

No Google Sheet schema or Apps Script deployment change is required. Do not
manually multiply the original trade quantities or add fake bonus-share buys.
