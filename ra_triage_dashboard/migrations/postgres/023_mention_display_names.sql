-- Human-readable names remain presentation metadata; LDAP stays authoritative.

BEGIN;

ALTER TABLE mention_users
    ADD COLUMN IF NOT EXISTS display_name text NOT NULL DEFAULT '';

UPDATE mention_users SET display_name = '陈俊豪' WHERE username = 'jasperchen';
UPDATE mention_users SET display_name = '曹立文' WHERE username = 'caoliwen_i';
UPDATE mention_users SET display_name = '徐浩轩' WHERE username = 'xuhaoxuan_i';
UPDATE mention_users SET display_name = '杨超' WHERE username = 'chadyang';

COMMIT;
