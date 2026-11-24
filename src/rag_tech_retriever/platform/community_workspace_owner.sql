BEGIN;
SET LOCAL lock_timeout='1s';
INSERT INTO community.members(id,subject,display_name,role)
VALUES(gen_random_uuid(),'system:workspace-owner','工作台所有者','moderator')
ON CONFLICT(subject) DO NOTHING;
DO $check$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM community.members WHERE subject='system:workspace-owner' AND role='moderator') THEN
  RAISE EXCEPTION 'Reserved workspace owner identity has an unexpected role';
 END IF;
END $check$;
COMMIT;
