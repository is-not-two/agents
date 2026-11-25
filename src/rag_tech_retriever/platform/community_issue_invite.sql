BEGIN;
CREATE OR REPLACE FUNCTION community.issue_member_invite(label text, token_hash bytea)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE actor uuid := gen_random_uuid();
BEGIN
 IF label IS NULL OR length(btrim(label)) NOT BETWEEN 1 AND 80
 OR token_hash IS NULL OR octet_length(token_hash) <> 32 THEN
  RAISE EXCEPTION 'invalid invitation' USING ERRCODE='22023';
 END IF;
 INSERT INTO community.members(id,subject,display_name,role)
 VALUES(actor,'invited:'||actor::text,btrim(label),'member');
 INSERT INTO community.invitations(digest,member_id,expires_at)
 VALUES(token_hash,actor,now()+interval '24 hours');
 RETURN actor;
END $$;
REVOKE ALL ON FUNCTION community.issue_member_invite(text,bytea) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION community.issue_member_invite(text,bytea) TO shilie_pvapp;
COMMIT;
