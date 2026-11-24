"""Bound limiter state without evicting active quotas; no external services."""

import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rag_tech_retriever.common.middleware.rate_limiter import (
    RateLimitMiddleware,
    SlidingWindowLimiter,
)


class LimiterBoundsContract(unittest.TestCase):
    def test_original_per_ip_window_semantics(self):
        limiter = SlidingWindowLimiter(2, 10)
        self.assertTrue(limiter.allow("a", now=0)[0])
        self.assertTrue(limiter.allow("a", now=1)[0])
        self.assertEqual(limiter.allow("a", now=2), (False, 9))
        self.assertFalse(limiter.allow("a", now=10)[0])
        self.assertTrue(limiter.allow("a", now=10.001)[0])

    def test_visitors_who_never_return_are_expired(self):
        limiter = SlidingWindowLimiter(600, 60)
        for n in range(1000):
            self.assertTrue(limiter.allow(str(n), now=0)[0])
        for n in range(1000, 2000):
            self.assertTrue(limiter.allow(str(n), now=61)[0])
        self.assertEqual(len(limiter._hits), 1000)
        self.assertEqual(len(limiter._events), 1000)

    def test_key_cap_rejects_without_erasing_active_quota(self):
        limiter = SlidingWindowLimiter(2, 10, max_clients=2, max_events=10)
        self.assertTrue(limiter.allow("a", now=0)[0])
        self.assertTrue(limiter.allow("b", now=0)[0])
        for n in range(100):
            self.assertFalse(limiter.allow("new-" + str(n), now=1)[0])
        self.assertEqual(set(limiter._hits), {"a", "b"})
        self.assertTrue(limiter.allow("a", now=2)[0])
        self.assertFalse(limiter.allow("a", now=3)[0])
        self.assertTrue(limiter.allow("c", now=11)[0])
        self.assertEqual(set(limiter._hits), {"a", "c"})

    def test_event_cap_and_expiry(self):
        limiter = SlidingWindowLimiter(100, 10, max_clients=10, max_events=3)
        for key in ("a", "a", "b"):
            self.assertTrue(limiter.allow(key, now=0)[0])
        self.assertFalse(limiter.allow("a", now=1)[0])
        self.assertFalse(limiter.allow("c", now=1)[0])
        self.assertNotIn("c", limiter._hits)
        self.assertEqual(sum(map(len, limiter._hits.values())), 3)
        self.assertTrue(limiter.allow("c", now=11)[0])
        self.assertEqual(len(limiter._events), 1)

    def test_concurrent_event_admission_is_atomic(self):
        limiter = SlidingWindowLimiter(3, 10, max_clients=12, max_events=25)
        with ThreadPoolExecutor(max_workers=16) as pool:
            accepted = list(pool.map(lambda n: limiter.allow(str(n % 10), now=0)[0], range(200)))
        self.assertEqual(sum(accepted), 25)
        self.assertEqual(len(limiter._events), 25)
        self.assertLessEqual(len(limiter._hits), 12)
        self.assertTrue(all(len(bucket) <= 3 for bucket in limiter._hits.values()))
        self.assertEqual(sum(map(len, limiter._hits.values())), 25)

    def test_concurrent_key_admission_is_atomic(self):
        limiter = SlidingWindowLimiter(10, 10, max_clients=12, max_events=25)
        with ThreadPoolExecutor(max_workers=16) as pool:
            accepted = list(pool.map(lambda n: limiter.allow(str(n), now=0)[0], range(200)))
        self.assertEqual(sum(accepted), 12)
        self.assertEqual(len(limiter._hits), 12)

    def test_invalid_configuration_rejected(self):
        for extra in (
            {"max_clients": 0},
            {"max_clients": 65537},
            {"max_events": 0},
            {"max_events": 1048577},
            {"window_seconds": 0},
            {"window_seconds": float("nan")},
            {"window_seconds": float("inf")},
        ):
            with self.assertRaises(ValueError):
                SlidingWindowLimiter(2, **extra)

    def test_http_429_shape_and_non_api_passthrough(self):
        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, limit=2, max_clients=1, max_events=2)

        @app.get("/api/test")
        def api_test():
            return {"ok": True}

        @app.get("/static/test")
        def static_test():
            return {"ok": True}

        with TestClient(app) as client:
            self.assertEqual(client.get("/api/test").status_code, 200)
            self.assertEqual(client.get("/api/test").status_code, 200)
            response = client.get("/api/test")
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.json()["code"], "RATE_LIMITED")
            self.assertGreaterEqual(int(response.headers["Retry-After"]), 1)
            self.assertEqual(client.get("/static/test").status_code, 200)

    def test_disabled_limiter_remains_off(self):
        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, limit=0)

        @app.get("/api/test")
        def api_test():
            return {"ok": True}

        with TestClient(app) as client:
            for _ in range(20):
                self.assertEqual(client.get("/api/test").status_code, 200)


if __name__ == "__main__":
    unittest.main()
