"""HTTP negotiation integration without database/model/network dependencies."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import starlette.middleware.gzip as gzip_middleware
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from rag_tech_retriever.common.middleware.compression import NegotiatedGZipMiddleware, accepts_gzip


class CompressionContract(unittest.TestCase):
    def test_weights(self):
        for value in ("", "identity", "gzip;q=0,*;q=1", "gzip;q=NaN", "gzip;q=2", "gzip;q=-1", "gzip;q=bad", "notgzip", "gzip;q=0,gzip"):
            self.assertFalse(accepts_gzip(value), value)
        for value in ("gzip", "GZIP; Q=0.8", "br, *;q=.5", "gzip;q=.5,identity;q=1"):
            self.assertTrue(accepts_gzip(value), value)

    def test_plain_response_and_wildcard(self):
        app = FastAPI()
        app.add_middleware(NegotiatedGZipMiddleware, minimum_size=10)

        @app.get("/")
        def body():
            return {"text": "real text " * 100}

        with TestClient(app) as client:
            for accept, expected in (("gzip;q=0", None), ("*", "gzip"), ("identity", None)):
                response = client.get("/", headers={"Accept-Encoding": accept})
                self.assertEqual(response.headers.get("content-encoding"), expected)
                self.assertEqual(response.json(), {"text": "real text " * 100})

    @unittest.skipUnless(hasattr(gzip_middleware, "DEFAULT_EXCLUDED_CONTENT_TYPES"),
                         "legacy local Starlette lacks SSE exclusion; run on pinned preview runtime")
    def test_sse_remains_uncompressed(self):
        app = FastAPI()
        app.add_middleware(NegotiatedGZipMiddleware, minimum_size=10)

        @app.get("/")
        def events():
            return Response("data: " + "x" * 100, media_type="text/event-stream")

        with TestClient(app) as client:
            response = client.get("/")
            self.assertNotIn("content-encoding", response.headers)
            self.assertTrue(response.text.startswith("data: "))


if __name__ == "__main__":
    unittest.main()
