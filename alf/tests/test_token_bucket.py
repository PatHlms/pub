"""
Unit tests for TokenBucket rate limiter.
"""
import time

import pytest

from src.fetcher import TokenBucket


class TestTokenBucket:
    def test_burst_available_immediately(self):
        bucket = TokenBucket(rate=1.0, burst=5)
        start = time.monotonic()
        for _ in range(5):
            bucket.consume()
        elapsed = time.monotonic() - start
        # All burst tokens should be consumed without meaningful delay
        assert elapsed < 0.5

    def test_rate_limits_beyond_burst(self):
        bucket = TokenBucket(rate=10.0, burst=1)
        bucket.consume()           # use burst token
        start = time.monotonic()
        bucket.consume()           # must wait ~0.1s for next token
        elapsed = time.monotonic() - start
        assert elapsed >= 0.05    # at 10 req/s, next token in 0.1s

    def test_tokens_not_zeroed_after_sleep(self):
        """
        After sleeping for a token, the bucket should not be hard-reset to 0.
        Consuming two tokens back-to-back should not require two full wait periods.
        """
        bucket = TokenBucket(rate=5.0, burst=1)
        bucket.consume()           # drain the burst
        # Sleep long enough for ~2 tokens to accrue
        time.sleep(0.5)
        # First consume should be instant (token already there from refill)
        start = time.monotonic()
        bucket.consume()
        elapsed = time.monotonic() - start
        assert elapsed < 0.15, "Token should have accrued during sleep"
