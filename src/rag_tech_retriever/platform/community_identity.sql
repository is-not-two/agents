BEGIN;
CREATE TABLE IF NOT EXISTS community.sessions (
 token_digest bytea PRIMARY KEY CHECK(octet_length(token_digest)=32),
 member_id uuid NOT NULL REFERENCES community.members(id) ON DELETE CASCADE,
 expires_at timestamptz NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), CHECK(expires_at>created_at)
);
CREATE INDEX IF NOT EXISTS sessions_expiry ON community.sessions(expires_at);
CREATE INDEX IF NOT EXISTS sessions_member ON community.sessions(member_id);
CREATE OR REPLACE FUNCTION community.submit_post(session_hash bytea, req uuid, heading text, content text)
RETURNS uuid LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $$
DECLARE actor uuid; result uuid;
BEGIN
 SELECT member_id INTO STRICT actor FROM community.sessions WHERE token_digest=session_hash AND expires_at>clock_timestamp();
 INSERT INTO community.posts(id,author_id,request_id,title,body)
 VALUES(gen_random_uuid(),actor,req,heading,content)
 ON CONFLICT(author_id,request_id) DO UPDATE SET request_id=excluded.request_id
 WHERE community.posts.title=excluded.title AND community.posts.body=excluded.body
 RETURNING id INTO result;
 IF result IS NULL THEN RAISE EXCEPTION 'request id already used for different content' USING ERRCODE='22023'; END IF;
 RETURN result;
END $$;
REVOKE ALL ON FUNCTION community.submit_post(bytea,uuid,text,text) FROM PUBLIC;
COMMIT;
