BEGIN;
CREATE TABLE IF NOT EXISTS human_user_roles (
    username TEXT PRIMARY KEY, role TEXT NOT NULL CHECK(role IN ('rd','te')),
    updated_by TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS human_role_audit (
    id TEXT PRIMARY KEY, username TEXT NOT NULL, old_role TEXT, new_role TEXT NOT NULL,
    actor TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS human_vote_roles (
    revision_id BIGINT PRIMARY KEY REFERENCES label_revisions(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('rd','te')), captured_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS human_assignment_roles (
    campaign_id TEXT NOT NULL, issue_id TEXT NOT NULL, username TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('rd','te')), captured_at TEXT NOT NULL,
    PRIMARY KEY(campaign_id,issue_id,username)
);
CREATE TABLE IF NOT EXISTS human_label_scopes (
    issue_id TEXT PRIMARY KEY REFERENCES issues(issue_id), baseline_scope TEXT NOT NULL,
    dataset_id TEXT NOT NULL, campaign_id TEXT NOT NULL REFERENCES issue_work_splits(id),
    active INTEGER NOT NULL DEFAULT 1, publication_armed INTEGER NOT NULL DEFAULT 1, created_by TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS human_label_dirty (
    issue_id TEXT PRIMARY KEY, generation BIGINT NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS human_publications (
    issue_id TEXT NOT NULL, lane TEXT NOT NULL CHECK(lane IN ('rd','te','arbitrated')),
    generation BIGINT NOT NULL, fingerprint TEXT NOT NULL, desired TEXT,
    conclusion TEXT NOT NULL, source_json TEXT NOT NULL, objection_count INTEGER NOT NULL DEFAULT 0,
    sync_state TEXT NOT NULL, owned INTEGER NOT NULL DEFAULT 0, owned_value TEXT,
    observed_json TEXT NOT NULL DEFAULT '{}', published_generation BIGINT,
    attempts INTEGER NOT NULL DEFAULT 0, next_attempt DOUBLE PRECISION NOT NULL DEFAULT 0,
    error_code TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL, checked_at TEXT,
    PRIMARY KEY(issue_id,lane)
);
CREATE INDEX IF NOT EXISTS idx_human_publications_due ON human_publications(sync_state,next_attempt);
CREATE TABLE IF NOT EXISTS human_publication_attempts (
    id TEXT PRIMARY KEY, issue_id TEXT NOT NULL, lane TEXT NOT NULL,
    generation BIGINT NOT NULL, action TEXT NOT NULL, before_json TEXT NOT NULL,
    desired TEXT, state TEXT NOT NULL, error_code TEXT NOT NULL DEFAULT '',
    recovery_attempts INTEGER NOT NULL DEFAULT 0, next_attempt DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL, finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_human_attempt_issue ON human_publication_attempts(issue_id,created_at);
CREATE TABLE IF NOT EXISTS human_version_tasks (
    dataset_id TEXT NOT NULL, cohort TEXT NOT NULL CHECK(cohort IN ('sampling','low')),
    campaign_id TEXT NOT NULL UNIQUE REFERENCES issue_work_splits(id), seed TEXT NOT NULL,
    created_at TEXT NOT NULL, PRIMARY KEY(dataset_id,cohort)
);

CREATE OR REPLACE FUNCTION capture_human_vote() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE iid text;
BEGIN
  IF TG_OP = 'INSERT' THEN
    INSERT INTO human_vote_roles(revision_id,role,captured_at)
      SELECT NEW.id,role,NEW.created_at FROM human_user_roles WHERE username=lower(NEW.author);
    SELECT issue_id INTO iid FROM label_cases WHERE id=NEW.label_case_id;
  ELSE
    SELECT issue_id INTO iid FROM label_cases WHERE id=OLD.label_case_id;
  END IF;
  INSERT INTO human_label_dirty(issue_id,generation)
    SELECT iid,1 WHERE EXISTS(SELECT 1 FROM human_label_scopes WHERE issue_id=iid)
    ON CONFLICT(issue_id) DO UPDATE SET generation=human_label_dirty.generation+1;
  RETURN NULL;
END $$;
CREATE TRIGGER human_vote_insert AFTER INSERT ON label_revisions FOR EACH ROW EXECUTE FUNCTION capture_human_vote();
CREATE TRIGGER human_vote_delete AFTER DELETE ON label_revisions FOR EACH ROW EXECUTE FUNCTION capture_human_vote();
CREATE OR REPLACE FUNCTION capture_human_assignment() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE iid text;
BEGIN
  IF TG_OP IN ('DELETE','UPDATE') THEN
    DELETE FROM human_assignment_roles WHERE campaign_id=OLD.split_id AND issue_id=OLD.issue_id AND username=lower(OLD.assignee);
    iid := OLD.issue_id;
  END IF;
  IF TG_OP IN ('INSERT','UPDATE') THEN
    INSERT INTO human_assignment_roles(campaign_id,issue_id,username,role,captured_at)
      SELECT NEW.split_id,NEW.issue_id,lower(NEW.assignee),role,NEW.assigned_at
      FROM human_user_roles WHERE username=lower(NEW.assignee)
      ON CONFLICT(campaign_id,issue_id,username) DO NOTHING;
    iid := NEW.issue_id;
  END IF;
  INSERT INTO human_label_dirty(issue_id,generation)
    SELECT iid,1 WHERE EXISTS(SELECT 1 FROM human_label_scopes WHERE issue_id=iid)
    ON CONFLICT(issue_id) DO UPDATE SET generation=human_label_dirty.generation+1;
  RETURN NULL;
END $$;
CREATE TRIGGER human_assignment_insert AFTER INSERT ON review_work_assignments FOR EACH ROW EXECUTE FUNCTION capture_human_assignment();
CREATE TRIGGER human_assignment_delete AFTER DELETE ON review_work_assignments FOR EACH ROW EXECUTE FUNCTION capture_human_assignment();
CREATE TRIGGER human_assignment_update AFTER UPDATE OF assignee ON review_work_assignments FOR EACH ROW EXECUTE FUNCTION capture_human_assignment();

CREATE OR REPLACE FUNCTION capture_human_scope_change() RETURNS trigger LANGUAGE plpgsql AS $$
 BEGIN
 INSERT INTO human_label_dirty(issue_id,generation) SELECT issue_id,1 FROM (SELECT NEW.issue_id AS issue_id) AS affected WHERE true
 ON CONFLICT(issue_id) DO UPDATE SET generation=human_label_dirty.generation+1;
 RETURN NULL;
 END $$;
 CREATE TRIGGER human_scope_change AFTER UPDATE ON human_label_scopes FOR EACH ROW EXECUTE FUNCTION capture_human_scope_change();

CREATE OR REPLACE FUNCTION capture_human_campaign_state() RETURNS trigger LANGUAGE plpgsql AS $$
 BEGIN
 INSERT INTO human_label_dirty(issue_id,generation) SELECT issue_id,1 FROM (SELECT issue_id FROM human_label_scopes WHERE campaign_id=NEW.id) AS affected WHERE true
 ON CONFLICT(issue_id) DO UPDATE SET generation=human_label_dirty.generation+1;
 RETURN NULL;
 END $$;
 CREATE TRIGGER human_campaign_state AFTER UPDATE OF lifecycle ON issue_work_splits FOR EACH ROW EXECUTE FUNCTION capture_human_campaign_state();

CREATE OR REPLACE FUNCTION capture_human_scope_state() RETURNS trigger LANGUAGE plpgsql AS $$
 BEGIN
 INSERT INTO human_label_dirty(issue_id,generation) SELECT issue_id,1 FROM (SELECT issue_id FROM human_label_scopes WHERE baseline_scope=NEW.baseline_scope) AS affected WHERE true
 ON CONFLICT(issue_id) DO UPDATE SET generation=human_label_dirty.generation+1;
 RETURN NULL;
 END $$;
 CREATE TRIGGER human_scope_state AFTER UPDATE ON labeling_scope_state FOR EACH ROW EXECUTE FUNCTION capture_human_scope_state();

CREATE OR REPLACE FUNCTION capture_human_target_change() RETURNS trigger LANGUAGE plpgsql AS $$
 BEGIN
 INSERT INTO human_label_dirty(issue_id,generation) SELECT issue_id,1 FROM (SELECT issue_id FROM human_label_scopes WHERE issue_id=NEW.issue_id AND dataset_id=NEW.dataset_id) AS affected WHERE true
 ON CONFLICT(issue_id) DO UPDATE SET generation=human_label_dirty.generation+1;
 RETURN NULL;
 END $$;
 CREATE TRIGGER human_target_change AFTER UPDATE OF is_target ON version_dataset_items FOR EACH ROW EXECUTE FUNCTION capture_human_target_change();

CREATE OR REPLACE FUNCTION capture_human_suppression_insert() RETURNS trigger LANGUAGE plpgsql AS $$
 BEGIN
 INSERT INTO human_label_dirty(issue_id,generation) SELECT issue_id,1 FROM (SELECT c.issue_id FROM label_revisions r JOIN label_cases c ON c.id=r.label_case_id JOIN human_label_scopes h ON h.issue_id=c.issue_id WHERE r.id=NEW.revision_id) AS affected WHERE true
 ON CONFLICT(issue_id) DO UPDATE SET generation=human_label_dirty.generation+1;
 RETURN NULL;
 END $$;
 CREATE TRIGGER human_suppression_insert AFTER INSERT ON label_import_suppressed_revisions FOR EACH ROW EXECUTE FUNCTION capture_human_suppression_insert();

CREATE OR REPLACE FUNCTION capture_human_suppression_delete() RETURNS trigger LANGUAGE plpgsql AS $$
 BEGIN
 INSERT INTO human_label_dirty(issue_id,generation) SELECT issue_id,1 FROM (SELECT c.issue_id FROM label_revisions r JOIN label_cases c ON c.id=r.label_case_id JOIN human_label_scopes h ON h.issue_id=c.issue_id WHERE r.id=OLD.revision_id) AS affected WHERE true
 ON CONFLICT(issue_id) DO UPDATE SET generation=human_label_dirty.generation+1;
 RETURN NULL;
 END $$;
 CREATE TRIGGER human_suppression_delete AFTER DELETE ON label_import_suppressed_revisions FOR EACH ROW EXECUTE FUNCTION capture_human_suppression_delete();

CREATE OR REPLACE FUNCTION capture_human_decision_insert() RETURNS trigger LANGUAGE plpgsql AS $$
 BEGIN
 INSERT INTO human_label_dirty(issue_id,generation) SELECT issue_id,1 FROM (SELECT issue_id FROM human_label_scopes WHERE issue_id=NEW.issue_id) AS affected WHERE true
 ON CONFLICT(issue_id) DO UPDATE SET generation=human_label_dirty.generation+1;
 RETURN NULL;
 END $$;
 CREATE TRIGGER human_decision_insert AFTER INSERT ON issue_label_decisions FOR EACH ROW EXECUTE FUNCTION capture_human_decision_insert();

CREATE OR REPLACE FUNCTION capture_human_decision_delete() RETURNS trigger LANGUAGE plpgsql AS $$
 BEGIN
 INSERT INTO human_label_dirty(issue_id,generation) SELECT issue_id,1 FROM (SELECT issue_id FROM human_label_scopes WHERE issue_id=OLD.issue_id) AS affected WHERE true
 ON CONFLICT(issue_id) DO UPDATE SET generation=human_label_dirty.generation+1;
 RETURN NULL;
 END $$;
 CREATE TRIGGER human_decision_delete AFTER DELETE ON issue_label_decisions FOR EACH ROW EXECUTE FUNCTION capture_human_decision_delete();

CREATE TABLE IF NOT EXISTS human_publication_requests (
 id TEXT PRIMARY KEY, actor TEXT NOT NULL, lane TEXT NOT NULL,
 items_json TEXT NOT NULL, state TEXT NOT NULL, created_at TEXT NOT NULL,
 expires_at DOUBLE PRECISION NOT NULL, committed_at TEXT
);

CREATE TABLE IF NOT EXISTS human_campaign_redirects (
 campaign_id TEXT NOT NULL, issue_id TEXT NOT NULL, target_campaign_id TEXT NOT NULL,
 created_at TEXT NOT NULL, PRIMARY KEY(campaign_id,issue_id)
);

COMMIT;
