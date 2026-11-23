BEGIN;
SET LOCAL lock_timeout='1s';
CREATE INDEX IF NOT EXISTS community_public_rank ON community.posts(score DESC,published_at DESC,id DESC) WHERE state='published';
CREATE STATISTICS IF NOT EXISTS community_search_text_stats ON (lower(title || chr(10) || body)) FROM community.posts;
ANALYZE community.posts;
CREATE OR REPLACE FUNCTION community.search_public(term text)
RETURNS TABLE(id uuid,title text,score smallint,excerpt text) LANGUAGE sql STABLE SECURITY INVOKER AS $$
 WITH title_hits AS MATERIALIZED (
  SELECT p.id,p.title,p.score,p.body,p.published_at FROM community.posts p
  WHERE p.state='published' AND length(trim(term)) BETWEEN 1 AND 120
   AND lower(p.title || chr(10) || p.body) LIKE ('%' || replace(replace(replace(lower(term),'!','!!'),'%','!%'),'_','!_') || '%') ESCAPE '!'
   AND strpos(lower(p.title),lower(term))>0
  ORDER BY p.score DESC,p.published_at DESC,p.id DESC LIMIT 20
 ), body_hits AS (
  SELECT p.id,p.title,p.score,p.body,p.published_at FROM community.posts p
  WHERE p.state='published' AND length(trim(term)) BETWEEN 1 AND 120
   AND lower(p.title || chr(10) || p.body) LIKE ('%' || replace(replace(replace(lower(term),'!','!!'),'%','!%'),'_','!_') || '%') ESCAPE '!'
   AND NOT (strpos(lower(p.title),lower(term))>0)
   AND strpos(lower(p.body),lower(term))>0
  ORDER BY p.score DESC,p.published_at DESC,p.id DESC
  LIMIT greatest(0,20-(SELECT count(*) FROM title_hits))
 ), ranked AS (
  SELECT *,true AS title_match FROM title_hits
  UNION ALL SELECT *,false AS title_match FROM body_hits
 )
 SELECT r.id,r.title,r.score,left(r.body,400) FROM ranked r
 ORDER BY r.title_match DESC,r.score DESC,r.published_at DESC,r.id DESC LIMIT 20;
$$;
COMMIT;
