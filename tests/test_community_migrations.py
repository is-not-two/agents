"""Packaged community migration plan contracts. No database required."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from rag_tech_retriever.platform.community_migrations import MIGRATIONS, psql_script


class MigrationContract(unittest.TestCase):
    def test_all_resources_exist_and_have_single_ordered_markers(self):
        script=psql_script()
        self.assertEqual(len(MIGRATIONS),13)
        positions=[script.index("-- "+name) for name in MIGRATIONS]
        self.assertEqual(positions,sorted(positions))
        for name in MIGRATIONS:self.assertEqual(script.count("-- "+name),1)

    def test_preview_guard_precedes_any_schema_writes(self):
        script=psql_script()
        self.assertTrue(script.startswith(chr(92)+"set ON_ERROR_STOP on"))
        self.assertLess(script.index("current_database()"),script.index("CREATE SCHEMA"))
        self.assertIn("'shilie_preview_20261104'",script)
        self.assertIn("current_setting('port') <> '55433'",script)

    def test_dependency_order_protects_published_search_and_private_review_defaults(self):
        script=psql_script()
        self.assertLess(MIGRATIONS.index("community_search.sql"),MIGRATIONS.index("community_search_rank.sql"))
        self.assertLess(MIGRATIONS.index("community_attachment_storage.sql"),MIGRATIONS.index("community_scan_permissions.sql"))
        self.assertIn("rationale_public boolean NOT NULL DEFAULT false",script)
        self.assertIn("security_barrier=true",script)

if __name__=="__main__":unittest.main()
