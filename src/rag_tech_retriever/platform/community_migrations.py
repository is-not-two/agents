"""Packaged preview-only community schema plan; never executes DDL at startup."""
import argparse
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
)


def psql_script() -> str:
    """Return a psql script guarded against accidental production application."""
    guard = """
DO $guard$
BEGIN
 IF current_database() <> 'shilie_preview_20261104' OR current_setting('port') <> '55433' THEN
  RAISE EXCEPTION 'Community preview migration refuses this database/port';
 END IF;
 IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='shilie_pvapp') THEN
  RAISE EXCEPTION 'Preview application role must be provisioned first';
 END IF;
END $guard$;
"""
    chunks = [chr(92)+"set ON_ERROR_STOP on", guard]
    root = files("rag_tech_retriever.platform")
    for name in MIGRATIONS:
        chunks.extend(["-- "+name, root.joinpath(name).read_text(encoding="utf-8-sig")])
    return chr(10).join(chunks)


def main() -> None:
    """List by default; --emit prints SQL without connecting to any database."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit",action="store_true",help="Print guarded SQL for psql; does not execute it.")
    args = parser.parse_args()
    print(psql_script() if args.emit else chr(10).join(MIGRATIONS))


if __name__ == "__main__":
    main()
