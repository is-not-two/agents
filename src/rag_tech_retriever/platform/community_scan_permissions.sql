BEGIN;
REVOKE INSERT ON community.attachments FROM shilie_pvapp;
GRANT INSERT(id,post_id,object_key,filename,media_type,bytes) ON community.attachments TO shilie_pvapp;
DO $$ BEGIN
 IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='shilie_pv_attachment_scanner') THEN
  CREATE ROLE shilie_pv_attachment_scanner NOLOGIN;
 END IF;
END $$;
GRANT USAGE ON SCHEMA community TO shilie_pv_attachment_scanner;
GRANT SELECT(id,scan_state) ON community.attachments TO shilie_pv_attachment_scanner;
GRANT SELECT ON community.attachment_content TO shilie_pv_attachment_scanner;
GRANT UPDATE(scan_state) ON community.attachments TO shilie_pv_attachment_scanner;
COMMIT;
