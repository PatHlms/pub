# ralf

High-frequency exchange wager client for [ellis](../ellis) auction data.

ralf polls the vehicle auction pricing data produced by alf, applies a pluggable wager strategy, and manages a continuous place/cashout lifecycle against a configured betting exchange. Open Banking (Token.io PIS) is used to top up exchange accounts automatically when available funds fall below a configured threshold.

## How it works

```
alf data dir
    │  (JSON flat files)
    ▼
DataReader.poll()          ← scans for new AuctionRecords
    │
    ▼
Strategy.evaluate()        ← converts records → Signals
    │
    ▼
WagerManager               ← places wagers, tracks P&L,
    │  + FundsManager          cashes out at profit threshold,
    │                          blocks placement when funds low
    ▼
ExchangeAdapter            ← Betfair / Smarkets / Matchbook /
                               Betdaq / Polymarket / Stub
```

Each cycle (default: every 30 seconds):
1. Pending Open Banking transfers are polled and credited when complete.
2. Balance is checked; a top-up payment is initiated if below threshold.
3. New auction records are fetched from the alf data directory.
4. The strategy converts records to wager signals.
5. Open positions are reviewed — cashed out if the profit threshold is met.
6. New signals are placed as wagers on the exchange.

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure credentials
cp .env .env.local   # fill in exchange credentials
# edit config/settings.json to set exchange, strategy, and data_dir

# 3. Run (dry-run by default — exchange = "stub")
python main.py

# 4. Single poll cycle
python main.py --run-once

# 5. Verbose / debug logging
python main.py --verbose
```

## Configuration

`config/settings.json`:

| Key | Default | Description |
|-----|---------|-------------|
| `data_dir` | `../alf/data` | Path to alf's data directory |
| `poll_interval_seconds` | `30` | Seconds between engine cycles |
| `state_dir` | `state` | Directory for persisted state files |
| `log_level` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `strategy.name` | `passthrough` | Wager strategy to use |
| `exchange.name` | `stub` | Exchange adapter to use |
| `exchange.timeout_seconds` | `15` | HTTP request timeout for exchange calls |
| `wager.default_stake` | `10.0` | Default stake per wager in `wager.currency` |
| `wager.currency` | `GBP` | Currency for wagers |
| `wager.max_open_wagers` | `20` | Maximum number of simultaneously open wagers |
| `wager.cashout_profit_threshold_pct` | `10.0` | Cash out when P&L ≥ this % of stake |
| `wager.cashout_on_signal_refresh` | `true` | Cash out existing positions when a new signal arrives for the same record |
| `funds.initial_balance` | `1000.0` | Starting balance for the funds tracker |
| `funds.min_reserve` | `50.0` | Minimum balance to keep; blocks wager placement below this |
| `funds.top_up_threshold` | `200.0` | Initiate a top-up when balance drops below this |
| `funds.top_up_amount` | `500.0` | Amount to transfer per top-up |
| `banking.provider` | `token_io` | Open Banking provider (omit section to disable) |

## Exchanges

| Name | Protocol | Auth |
|------|----------|------|
| `stub` | None (dry-run) | None |
| `betfair` | Betfair APING REST | SSL cert + username/password |
| `smarkets` | Smarkets REST v3 | username/password → Bearer token |
| `matchbook` | Matchbook REST | username/password → session-token |
| `betdaq` | Betdaq SOAP APING | username/password in SOAP header |
| `polymarket` | Polymarket CLOB REST | HMAC-SHA256 signed headers |

To select an exchange, set `exchange.name` in `settings.json` and populate the corresponding credentials in `.env`.

### Betfair

```env
BETFAIR_APP_KEY=
BETFAIR_USERNAME=
BETFAIR_PASSWORD=
BETFAIR_CERT_PATH=certs/betfair.crt   # path to your SSL certificate
BETFAIR_KEY_PATH=certs/betfair.key    # path to your SSL private key
```

Register at [developer.betfair.com](https://developer.betfair.com). Cert-based login requires a self-signed certificate registered at [myaccount.betfair.com](https://myaccount.betfair.com/account/security).

### Smarkets

```env
SMARKETS_USERNAME=
SMARKETS_PASSWORD=
SMARKETS_APP_KEY=   # optional
```

### Matchbook

```env
MATCHBOOK_USERNAME=
MATCHBOOK_PASSWORD=
```

`signal.market_id` may be plain (`"12345"`) or dot-separated (`"67890.12345"`) to supply both the event ID and market ID required by the Matchbook API. Both parts must be numeric.

### Betdaq

```env
BETDAQ_USERNAME=
BETDAQ_PASSWORD=
BETDAQ_API_KEY=
```

Polarity: `BACK` → 1, `LAY` → 2 (mapped internally).

### Polymarket

```env
POLYMARKET_API_KEY=
POLYMARKET_API_SECRET=
POLYMARKET_API_PASSPHRASE=
POLYMARKET_FUNDER_ADDRESS=   # optional — your Polygon wallet address
```

Prices are expressed as probabilities (0.01–0.99). Stakes are in USDC.

## Strategies

| Name | Behaviour |
|------|-----------|
| `passthrough` | Logs all new records; places no wagers. Use as a scaffold for custom strategies. |

To implement a custom strategy, subclass `src.strategy.base.BaseStrategy`, implement `evaluate(records) -> list[Signal]`, and register it in `src.strategy.STRATEGY_REGISTRY`.

## Open Banking — Token.io

When `banking.provider` is set to `token_io`, ralf will automatically initiate a domestic payment to top up the exchange account whenever the tracked balance drops below `funds.top_up_threshold`.

```env
TOKEN_IO_CLIENT_ID=
TOKEN_IO_CLIENT_SECRET=
TOKEN_IO_MEMBER_ID=
TOKEN_IO_SANDBOX=true   # set false for production
```

Configure the destination account (exchange funding account) in `settings.json` under `funds.destination`:

```json
"destination": {
  "sort_code": "20-00-00",
  "account_number": "55779911",
  "account_name": "Betfair Exchange"
}
```

Omit the `banking` section entirely to disable Open Banking integration.

## Project structure

```
ralf/
├── main.py                     Entry point, CLI argument parsing
├── requirements.txt
├── .env                        Credential templates (never commit filled values)
├── config/
│   └── settings.json           Runtime configuration
├── state/                      Persisted runtime state (auto-created)
│   ├── seen_ids.json           IDs of processed auction records
│   ├── wagers.json             Open/settled wager registry
│   └── funds.json              Balance and pending transfer state
└── src/
    ├── engine.py               Main poll loop
    ├── reader.py               Polls alf data directory for new records
    ├── models.py               Signal, Wager, WagerStatus dataclasses
    ├── wager_manager.py        Position registry, P&L tracking, cashout logic
    ├── funds_manager.py        Balance tracking, top-up trigger, wager guard
    ├── exchange/
    │   ├── base.py             BaseExchangeAdapter abstract class
    │   ├── stub.py             Dry-run adapter
    │   ├── betfair.py
    │   ├── smarkets.py
    │   ├── matchbook.py
    │   ├── betdaq.py
    │   └── polymarket.py
    ├── strategy/
    │   ├── base.py             BaseStrategy abstract class
    │   └── passthrough.py      No-op reference strategy
    └── banking/
        ├── base.py             BaseBankingProvider abstract class
        └── token_io.py         Token.io PIS adapter
```

## Dependencies

| Package | Purpose |
|---------|---------|
| `requests` | HTTP client for all exchange and banking API calls |
| `python-dotenv` | Loads `.env` credential files |
| `filelock` | Thread-safe state file writes shared with alf |

Python 3.9+ required.
