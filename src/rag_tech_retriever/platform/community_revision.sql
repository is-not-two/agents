BEGIN;
SET LOCAL lock_timeout='1s';
ALTER TABLE community.reviews ADD COLUMN IF NOT EXISTS author_feedback text NOT NULL DEFAULT '' CHECK(length(author_feedback)<=2000);
CREATE TABLE IF NOT EXISTS community.post_revisions(
 post_id uuid NOT NULL REFERENCES community.posts(id),
 version integer NOT NULL,
 request_id uuid NOT NULL,
 title text NOT NULL,
 body text NOT NULL,
 state text NOT NULL,
 score smallint NOT NULL,
 published_at timestamptz,
 archived_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(post_id,version),
 UNIQUE(post_id,request_id)
);
GRANT SELECT(post_id,version,author_feedback) ON community.reviews TO shilie_pvapp;
GRANT SELECT,INSERT ON community.post_revisions TO shilie_pvapp;
GRANT UPDATE(title,body) ON community.posts TO shilie_pvapp;
COMMIT;
