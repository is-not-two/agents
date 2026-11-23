BEGIN;
SET LOCAL lock_timeout='1s';
ALTER TABLE community.reviews ADD COLUMN IF NOT EXISTS rationale_public boolean NOT NULL DEFAULT false;
CREATE OR REPLACE VIEW community.public_review_evidence WITH (security_barrier=true) AS
 SELECT r.post_id,r.score,r.rationale,r.created_at AS reviewed_at
 FROM community.reviews r JOIN community.public_topics p
 ON p.id=r.post_id AND p.version=r.version+1 AND p.score=r.score
 WHERE r.rationale_public=true;
GRANT SELECT ON community.public_review_evidence TO shilie_pvapp;
COMMIT;
