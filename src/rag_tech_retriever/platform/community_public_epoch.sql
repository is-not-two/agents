BEGIN;
SET LOCAL lock_timeout='1s';
CREATE TABLE IF NOT EXISTS community.public_epoch(
 id boolean PRIMARY KEY DEFAULT true CHECK(id),
 token uuid NOT NULL DEFAULT gen_random_uuid()
);
INSERT INTO community.public_epoch(id) VALUES(true) ON CONFLICT(id) DO NOTHING;
CREATE OR REPLACE FUNCTION community.bump_public_epoch() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $fn$
BEGIN
 IF (TG_OP='INSERT' AND NEW.state='published') OR
    (TG_OP='DELETE' AND OLD.state='published') OR
    (TG_OP='UPDATE' AND (OLD.state='published' OR NEW.state='published')) THEN
  UPDATE community.public_epoch SET token=gen_random_uuid() WHERE id=true;
 END IF;
 RETURN NULL;
END $fn$;
REVOKE ALL ON FUNCTION community.bump_public_epoch() FROM PUBLIC;
DROP TRIGGER IF EXISTS community_public_changed ON community.posts;
CREATE TRIGGER community_public_changed AFTER INSERT OR UPDATE OR DELETE ON community.posts
 FOR EACH ROW EXECUTE FUNCTION community.bump_public_epoch();
GRANT SELECT ON community.public_epoch TO shilie_pvapp;
COMMIT;
