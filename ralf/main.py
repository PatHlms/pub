"""
ralf — Exchange wager client.

Reads auction data produced by alf, applies a pluggable wager strategy,
and manages a high-frequency place/cashout lifecycle against a configured
betting exchange.

Modules (exchange adapters)
---------------------------
  stub        — Dry-run; logs all actions, no real API calls (default)

Modules (strategies)
--------------------
  passthrough — Logs all new records, places no wagers (default)

Usage
-----
    # Run continuously (poll interval from config/settings.json)
    python main.py

    # Run one poll cycle then exit
    python main.py --run-once

    # Override config file
    python main.py --config /etc/ralf/settings.json

    # Verbose (DEBUG) logging
    python main.py --verbose
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ralf",
        description="Exchange wager client for alf auction data",
    )
    parser.add_argument(
        "--config",
        default="config/settings.json",
        metavar="FILE",
        help="Path to settings JSON (default: config/settings.json)",
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
        default=False,
        help="Execute a single poll cycle then exit",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Enable DEBUG logging",
    )
    return parser.parse_args()


def _configure_logging(verbose: bool, log_level: str = "INFO") -> None:
    level = logging.DEBUG if verbose else getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _load_settings(config_path: str) -> dict:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_engine(settings: dict):
    from src.engine import Engine
    from src.exchange import EXCHANGE_REGISTRY
    from src.reader import DataReader
    from src.strategy import STRATEGY_REGISTRY
    from src.wager_manager import WagerManager

    data_dir  = settings.get("data_dir", "../alf/data")
    state_dir = settings.get("state_dir", "state")

    strategy_name = settings.get("strategy", {}).get("name", "passthrough")
    strategy_cls  = STRATEGY_REGISTRY.get(strategy_name)
    if strategy_cls is None:
        raise ValueError(
            f"Unknown strategy {strategy_name!r}. Available: {list(STRATEGY_REGISTRY)}"
        )

    exchange_name = settings.get("exchange", {}).get("name", "stub")
    exchange_cls  = EXCHANGE_REGISTRY.get(exchange_name)
    if exchange_cls is None:
        raise ValueError(
            f"Unknown exchange {exchange_name!r}. Available: {list(EXCHANGE_REGISTRY)}"
        )

    reader   = DataReader(data_dir=data_dir, state_dir=state_dir)
    strategy = strategy_cls(settings.get("strategy", {}))
    adapter  = exchange_cls(settings.get("exchange", {}))
    manager  = WagerManager(config=settings.get("wager", {}), state_dir=state_dir)

    return Engine(
        settings=settings,
        reader=reader,
        strategy=strategy,
        adapter=adapter,
        manager=manager,
    )


def main() -> int:
    args = _parse_args()
    load_dotenv()

    try:
        settings = _load_settings(args.config)
    except FileNotFoundError as exc:
        logging.basicConfig(level=logging.ERROR)
        logging.error("%s", exc)
        return 1

    _configure_logging(args.verbose, settings.get("log_level", "INFO"))

    try:
        engine = _build_engine(settings)
    except (ValueError, KeyError) as exc:
        logging.error("Startup error: %s", exc)
        return 1
    except Exception as exc:
        logging.error("Unexpected startup error: %s", exc)
        return 1

    if args.run_once:
        stats = engine.run_once()
        return 0

    engine.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
