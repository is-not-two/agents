BEGIN;
CREATE SCHEMA IF NOT EXISTS community;
CREATE TABLE IF NOT EXISTS community.members (
 id uuid PRIMARY KEY, subject text NOT NULL UNIQUE, display_name text NOT NULL,
 role text NOT NULL DEFAULT 'member' CHECK(role IN ('member','moderator')), created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS community.posts (
 id uuid PRIMARY KEY, author_id uuid NOT NULL REFERENCES community.members,
 request_id uuid NOT NULL, title text NOT NULL CHECK(length(trim(title)) BETWEEN 1 AND 120),
 body text NOT NULL CHECK(length(trim(body)) BETWEEN 1 AND 20000),
 state text NOT NULL DEFAULT 'pending' CHECK(state IN ('draft','pending','published','withdrawn','rejected')),
 score smallint NOT NULL DEFAULT 0 CHECK(score BETWEEN 0 AND 100),
 version integer NOT NULL DEFAULT 1 CHECK(version>0), created_at timestamptz NOT NULL DEFAULT now(),
 published_at timestamptz, CHECK(state <> 'published' OR published_at IS NOT NULL), UNIQUE(author_id,request_id)
);
CREATE INDEX IF NOT EXISTS posts_feed ON community.posts(published_at DESC,id DESC) WHERE state='published';
CREATE INDEX IF NOT EXISTS posts_owner ON community.posts(author_id,created_at DESC,id DESC);
CREATE INDEX IF NOT EXISTS posts_review ON community.posts(created_at,id) WHERE state='pending';
CREATE TABLE IF NOT EXISTS community.reviews (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, post_id uuid NOT NULL REFERENCES community.posts,
 reviewer_id uuid NOT NULL REFERENCES community.members, version integer NOT NULL,
 score smallint NOT NULL CHECK(score BETWEEN 0 AND 100), rationale text NOT NULL CHECK(length(trim(rationale))>0),
 rationale_public boolean NOT NULL DEFAULT false,
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(post_id,version)
);
CREATE TABLE IF NOT EXISTS community.attachments (
 id uuid PRIMARY KEY, post_id uuid NOT NULL REFERENCES community.posts, object_key uuid NOT NULL UNIQUE,
 filename text NOT NULL, media_type text NOT NULL, bytes bigint NOT NULL CHECK(bytes BETWEEN 1 AND 10485760),
 scan_state text NOT NULL DEFAULT 'pending' CHECK(scan_state IN ('pending','clean','rejected'))
);
CREATE INDEX IF NOT EXISTS attachments_post ON community.attachments(post_id);
CREATE OR REPLACE VIEW community.public_topics WITH (security_barrier=true) AS
 SELECT id,title,body,score,version,published_at FROM community.posts WHERE state='published' ORDER BY published_at DESC,id DESC;
CREATE OR REPLACE VIEW community.public_files WITH (security_barrier=true) AS
 SELECT a.id,a.post_id,a.filename,a.media_type,a.bytes FROM community.attachments a
 JOIN community.public_topics p ON p.id=a.post_id WHERE a.scan_state='clean';
COMMIT;

