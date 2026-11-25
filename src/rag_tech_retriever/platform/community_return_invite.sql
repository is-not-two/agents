BEGIN;
CREATE OR REPLACE FUNCTION community.return_member_invite(actor uuid, token_hash bytea)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF token_hash IS NULL OR octet_length(token_hash)<>32 THEN
  RAISE EXCEPTION 'invalid invitation' USING ERRCODE='22023';
 END IF;
 PERFORM 1 FROM community.members m WHERE m.id=actor AND m.subject='invited:'||actor::text
 AND m.role='member' FOR NO KEY UPDATE;
 IF NOT FOUND THEN RETURN NULL; END IF;
 DELETE FROM community.invitations WHERE member_id=actor;
 INSERT INTO community.invitations(digest,member_id,expires_at)
 VALUES(token_hash,actor,now()+interval '24 hours');
 RETURN actor;
END $$;
REVOKE ALL ON FUNCTION community.return_member_invite(uuid,bytea) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION community.return_member_invite(uuid,bytea) TO shilie_pvapp;
COMMIT;
