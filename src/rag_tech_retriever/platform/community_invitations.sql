BEGIN;
CREATE TABLE IF NOT EXISTS community.invitations(
 digest bytea PRIMARY KEY CHECK(octet_length(digest)=32),
 member_id uuid NOT NULL REFERENCES community.members(id) ON DELETE CASCADE,
 expires_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS invitations_expiry ON community.invitations(expires_at);
COMMIT;
