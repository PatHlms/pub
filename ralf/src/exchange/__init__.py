from src.exchange.betdaq import BetdaqAdapter
from src.exchange.betfair import BetfairAdapter
from src.exchange.matchbook import MatchbookAdapter
from src.exchange.polymarket import PolymarketAdapter
from src.exchange.smarkets import SmarketsAdapter
from src.exchange.stub import StubAdapter

EXCHANGE_REGISTRY: dict = {
    "stub":       StubAdapter,
    "betfair":    BetfairAdapter,
    "smarkets":   SmarketsAdapter,
    "matchbook":  MatchbookAdapter,
    "betdaq":     BetdaqAdapter,
    "polymarket": PolymarketAdapter,
}
