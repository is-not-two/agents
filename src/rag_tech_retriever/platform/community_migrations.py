"""Packaged preview-only community schema plan; never executes DDL at startup."""
import argparse
import re
from importlib.resources import files

MIGRATIONS = (
    "community_schema.sql",
    "community_identity.sql",
    "community_invitations.sql",
    "community_preview_grants.sql",
    "community_attachment_storage.sql",
    "community_scan_permissions.sql",
    "community_search.sql",
    "community_search_rank.sql",
    "community_feed_order.sql",
    "community_review_evidence.sql",
    "community_workspace_owner.sql",
    "community_revision.sql",
    "community_public_epoch.sql",
    "community_issue_invite.sql",
    "community_return_invite.sql",
)


def psql_script(*, test_database: str | None = None) -> str:
    """Return a psql script guarded against accidental production application."""
    database = "shilie_preview_20261104"
    if test_database is not None:
        if not re.fullmatch(r"shilie_ci_[a-f0-9]{12}", test_database):
            raise ValueError("only generated shilie_ci_<12 hex> test databases are allowed")
        database = test_database
    guard = """
DO $guard$
BEGIN
 IF current_database() <> '__EXPECTED_DATABASE__' OR current_setting('port') <> '55433' THEN
  RAISE EXCEPTION 'Community preview migration refuses this database/port';
 END IF;
 IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='shilie_pvapp') THEN
  RAISE EXCEPTION 'Preview application role must be provisioned first';
 END IF;
END $guard$;
""".replace("__EXPECTED_DATABASE__", database)
    chunks = [chr(92)+"set ON_ERROR_STOP on", guard]
    root = files("rag_tech_retriever.platform")
    for name in MIGRATIONS:
        chunks.extend(["-- "+name, root.joinpath(name).read_text(encoding="utf-8-sig")])
    return chr(10).join(chunks)


def main() -> None:
    """List by default; --emit prints SQL without connecting to any database."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit",action="store_true",help="Print guarded SQL for psql; does not execute it.")
    parser.add_argument("--test-database", help="Explicit generated CI database; cannot name production")
    args = parser.parse_args()
    if args.test_database and not args.emit:
        parser.error("--test-database requires --emit; this command never connects")
    print(psql_script(test_database=args.test_database) if args.emit else chr(10).join(MIGRATIONS))


if __name__ == "__main__":
    main()
