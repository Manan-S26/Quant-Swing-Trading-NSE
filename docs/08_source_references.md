# Source References

These are the official or primary references used when designing the build pack.

## Zerodha Kite Connect

- Kite Connect v3 API documentation: https://kite.trade/docs/connect/v3/
- Kite Connect orders documentation: https://kite.trade/docs/connect/v3/orders/
- Kite Connect WebSocket documentation: https://kite.trade/docs/connect/v3/websocket/
- Official Python client, pykiteconnect: https://github.com/zerodha/pykiteconnect

Design implications:

- Keep Zerodha-specific code behind a broker adapter.
- Treat order placement response as submission information, not execution certainty.
- Track orders, trades, and positions separately.
- Build reconciliation into live execution.
- Use WebSocket market data for live mode and historical candles for backtest data ingestion.

## SEBI and NSE retail algo framework

- SEBI circular, Safer participation of retail investors in Algorithmic trading, February 4, 2025: https://www.sebi.gov.in/legal/circulars/feb-2025/safer-participation-of-retail-investors-in-algorithmic-trading_91614.html
- NSE implementation standards circular PDF: https://nsearchives.nseindia.com/content/circulars/INVG67858.pdf
- Zerodha summary of NSE retail algo framework: https://zerodha.com/z-connect/general/a-comprehensive-overview-of-nses-circular-on-the-new-retail-algo-trading-framework

Design implications:

- Build static-IP-ready deployment.
- Add order-rate limiting well below relevant thresholds.
- Store audit logs.
- Maintain strategy, order, and risk event traceability.
- Include session handling in daily operations.

## Disclaimer

This repo is a software planning and engineering artifact. It is not legal, regulatory, tax, or financial advice. Before using automated trading live, review applicable rules with your broker and relevant professionals.
