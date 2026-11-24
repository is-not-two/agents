-- Keep the security barrier; expose index ordering so LIMIT does not sort every post.
BEGIN;
SET LOCAL lock_timeout='1s';
CREATE OR REPLACE VIEW community.public_topics WITH (security_barrier=true) AS
 SELECT id,title,body,score,version,published_at FROM community.posts
 WHERE state='published' ORDER BY published_at DESC,id DESC;
COMMIT;
