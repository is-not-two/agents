"""A request must not hold one pooled connection while borrowing another."""
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rag_tech_retriever.api.routes.community import COOKIE, create_router


class PoolContract(unittest.TestCase):
    def client(self):
        active=[False]
        class Cursor:
            sql=""
            def execute(self,sql,args=()):self.sql=sql
            def fetchone(self):
                return {"member_id":"00000000-0000-0000-0000-000000000001"} if "SELECT member_id FROM community.sessions" in self.sql else None
            def fetchall(self):return []
        @contextmanager
        def transaction():
            if active[0]:raise RuntimeError("nested connection borrow")
            active[0]=True
            try:yield Cursor()
            finally:active[0]=False
        app=FastAPI()
        app.include_router(create_router(transaction,public_origin="https://preview.test",session_seconds=300))
        return TestClient(app,base_url="https://preview.test",headers={"Origin":"https://preview.test","Cookie":COOKIE+"="+"a"*43})
    def test_mine_never_nests_pool_borrows(self):
        self.assertEqual(self.client().get("/api/community/mine").status_code,200)
    def test_logout_never_nests_pool_borrows(self):
        self.assertEqual(self.client().delete("/api/community/session").status_code,204)
if __name__=="__main__":unittest.main()
