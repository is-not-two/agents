BEGIN;
CREATE TABLE IF NOT EXISTS community.attachment_content (
 attachment_id uuid PRIMARY KEY REFERENCES community.attachments(id) ON DELETE CASCADE,
 payload bytea NOT NULL CHECK(octet_length(payload) BETWEEN 1 AND 1048576)
);
CREATE OR REPLACE VIEW community.downloadable WITH (security_barrier=true) AS
 SELECT f.id,f.post_id,f.filename,f.media_type,c.payload FROM community.public_files f
 JOIN community.attachment_content c ON c.attachment_id=f.id;
GRANT SELECT, INSERT(id,post_id,object_key,filename,media_type,bytes) ON community.attachments TO shilie_pvapp;
GRANT INSERT ON community.attachment_content TO shilie_pvapp;
GRANT SELECT ON community.downloadable TO shilie_pvapp;
COMMIT;

