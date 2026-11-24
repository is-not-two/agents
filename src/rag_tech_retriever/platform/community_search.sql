BEGIN;
SET LOCAL lock_timeout='1s';
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX IF NOT EXISTS community_public_text_trgm ON community.posts USING gin(lower(title || chr(10) || body) gin_trgm_ops) WHERE state='published';
CREATE OR REPLACE FUNCTION community.search_public(term text)
RETURNS TABLE(id uuid,title text,score smallint,excerpt text) LANGUAGE sql STABLE SECURITY INVOKER AS $$
 SELECT p.id,p.title,p.score,left(p.body,400) FROM community.posts p
 WHERE p.state='published' AND length(trim(term)) BETWEEN 1 AND 120
 AND lower(p.title || chr(10) || p.body) LIKE ('%' || replace(replace(replace(lower(term),'!','!!'),'%','!%'),'_','!_') || '%') ESCAPE '!'
 AND (strpos(lower(p.title),lower(term))>0 OR strpos(lower(p.body),lower(term))>0)
 ORDER BY (strpos(lower(p.title),lower(term))>0) DESC,p.score DESC,p.published_at DESC,p.id DESC LIMIT 20;
$$;
REVOKE ALL ON FUNCTION community.search_public(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION community.search_public(text) TO shilie_pvapp;
COMMIT;
