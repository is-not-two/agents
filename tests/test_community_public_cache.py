"""Immutable public payload cache contract. No database or network."""
import gzip
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from rag_tech_retriever.platform.community_public_cache import PublicResponseCache


class PublicCacheContract(unittest.TestCase):
 def test_epoch_key_and_payload_immutability(self):
  cache=PublicResponseCache(2,65536);data={"items":[{"title":"public"}]}
  value=cache.put("epoch1",("feed",""),data);data["items"][0]["title"]="changed"
  self.assertEqual(json.loads(value[0])["items"][0]["title"],"public")
  self.assertEqual(gzip.decompress(value[1]),value[0])
  self.assertIsNone(cache.get("epoch2",("feed","")))
 def test_lru_and_byte_limits(self):
  cache=PublicResponseCache(2,65536)
  for key in ("a","b"):cache.put("epoch",key,{"data":key})
  cache.get("epoch","a");cache.put("epoch","c",{"data":"c"})
  self.assertIsNone(cache.get("epoch","b"))
  cache.put("epoch","huge",{"data":"x"*70000})
  self.assertIsNone(cache.get("epoch","huge"))
  self.assertLessEqual(cache.bytes,65536)
 def test_gzip_and_identity_variants(self):
  cache=PublicResponseCache();value=cache.put("e","k",{"items":[]})
  self.assertEqual(cache.response(value,"gzip").headers["content-encoding"],"gzip")
  self.assertNotIn("content-encoding",cache.response(value,"gzip;q=0").headers)
  self.assertEqual(cache.response(value,"identity").body,value[0])
 def test_concurrent_capacity_never_unbounded(self):
  from concurrent.futures import ThreadPoolExecutor
  cache=PublicResponseCache(3,65536)
  with ThreadPoolExecutor(max_workers=16) as pool:
   list(pool.map(lambda n:cache.put(str(n%2),str(n),{"title":"public"}),range(100)))
  self.assertLessEqual(len(cache.entries),3)
  self.assertEqual(cache.bytes,sum(len(a)+len(b) for a,b in cache.entries.values()))
 def test_opt_out_survives_global_compression_middleware(self):
  from fastapi import FastAPI, Request
  from fastapi.testclient import TestClient

  from rag_tech_retriever.common.middleware.compression import NegotiatedGZipMiddleware
  app=FastAPI();app.add_middleware(NegotiatedGZipMiddleware,minimum_size=10)
  cache=PublicResponseCache();value=cache.put("e","k",{"text":"readable "*100})
  @app.get("/")
  def public(request:Request):return cache.response(value,request.headers.get("accept-encoding",""))
  with TestClient(app) as client:
   response=client.get("/",headers={"Accept-Encoding":"gzip;q=0, identity"})
   self.assertNotEqual(response.headers.get("content-encoding"),"gzip")
   self.assertEqual(response.json(),{"text":"readable "*100})
   for encoding in ("gzip", "*;q=.5"):
    response=client.get("/",headers={"Accept-Encoding":encoding})
    self.assertEqual(response.headers.get("content-encoding"),"gzip")
    self.assertEqual(response.json(),{"text":"readable "*100})
if __name__=="__main__":unittest.main()
