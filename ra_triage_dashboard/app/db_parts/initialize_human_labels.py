"""Additive schema and transactional event capture for human publication."""
from pathlib import Path

from .shared import utc_now


def seed_roles(conn):
    conn.execute("""INSERT INTO human_user_roles(username,role,updated_by,updated_at)
        SELECT username, CASE WHEN username IN ('yupuxue','zhangxuzhao','lishizhong','zhangyang')
        THEN 'te' ELSE 'rd' END, 'initial-directory', ? FROM access_users WHERE 1=1
        ON CONFLICT(username) DO NOTHING""", (utc_now(),))


def initialize_human_labels(self, conn):
    if self.backend == 'sqlite':
        conn.executescript((Path(__file__).with_name('sqlite_schema') / 'human_labels.sql').read_text())
        conn.executescript('''
        CREATE TRIGGER IF NOT EXISTS human_vote_insert AFTER INSERT ON label_revisions BEGIN
            INSERT INTO human_vote_roles(revision_id,role,captured_at)
                SELECT NEW.id,role,NEW.created_at FROM human_user_roles WHERE username=lower(NEW.author);
            INSERT INTO human_label_dirty(issue_id,generation)
                SELECT c.issue_id,1 FROM label_cases c JOIN human_label_scopes s ON s.issue_id=c.issue_id
                WHERE c.id=NEW.label_case_id
                ON CONFLICT(issue_id) DO UPDATE SET generation=generation+1;
        END;
        CREATE TRIGGER IF NOT EXISTS human_vote_delete AFTER DELETE ON label_revisions BEGIN
            INSERT INTO human_label_dirty(issue_id,generation)
                SELECT c.issue_id,1 FROM label_cases c JOIN human_label_scopes s ON s.issue_id=c.issue_id
                WHERE c.id=OLD.label_case_id
                ON CONFLICT(issue_id) DO UPDATE SET generation=generation+1;
        END;
        CREATE TRIGGER IF NOT EXISTS human_assignment_insert AFTER INSERT ON review_work_assignments BEGIN
            INSERT INTO human_assignment_roles(campaign_id,issue_id,username,role,captured_at)
                SELECT NEW.split_id,NEW.issue_id,lower(NEW.assignee),role,NEW.assigned_at
                FROM human_user_roles WHERE username=lower(NEW.assignee)
                ON CONFLICT(campaign_id,issue_id,username) DO NOTHING;
            INSERT INTO human_label_dirty(issue_id,generation)
                SELECT NEW.issue_id,1 FROM human_label_scopes WHERE issue_id=NEW.issue_id
                ON CONFLICT(issue_id) DO UPDATE SET generation=generation+1;
        END;
        CREATE TRIGGER IF NOT EXISTS human_assignment_delete AFTER DELETE ON review_work_assignments BEGIN
            DELETE FROM human_assignment_roles WHERE campaign_id=OLD.split_id AND issue_id=OLD.issue_id
                AND username=lower(OLD.assignee);
            INSERT INTO human_label_dirty(issue_id,generation)
                SELECT OLD.issue_id,1 FROM human_label_scopes WHERE issue_id=OLD.issue_id
                ON CONFLICT(issue_id) DO UPDATE SET generation=generation+1;
        END;
        CREATE TRIGGER IF NOT EXISTS human_assignment_update AFTER UPDATE OF assignee ON review_work_assignments BEGIN
            DELETE FROM human_assignment_roles WHERE campaign_id=OLD.split_id AND issue_id=OLD.issue_id
                AND username=lower(OLD.assignee);
            INSERT INTO human_assignment_roles(campaign_id,issue_id,username,role,captured_at)
                SELECT NEW.split_id,NEW.issue_id,lower(NEW.assignee),role,NEW.assigned_at
                FROM human_user_roles WHERE username=lower(NEW.assignee)
                ON CONFLICT(campaign_id,issue_id,username) DO NOTHING;
            INSERT INTO human_label_dirty(issue_id,generation)
                SELECT NEW.issue_id,1 FROM human_label_scopes WHERE issue_id=NEW.issue_id
                ON CONFLICT(issue_id) DO UPDATE SET generation=generation+1;
        END;
        ''')
        conn.executescript('''
CREATE TRIGGER IF NOT EXISTS human_scope_change AFTER UPDATE ON human_label_scopes BEGIN
 INSERT INTO human_label_dirty(issue_id,generation) SELECT issue_id,1 FROM (SELECT NEW.issue_id AS issue_id) WHERE 1=1
 ON CONFLICT(issue_id) DO UPDATE SET generation=generation+1;
 END;
CREATE TRIGGER IF NOT EXISTS human_campaign_state AFTER UPDATE OF lifecycle ON issue_work_splits BEGIN
 INSERT INTO human_label_dirty(issue_id,generation) SELECT issue_id,1 FROM (SELECT issue_id FROM human_label_scopes WHERE campaign_id=NEW.id) WHERE 1=1
 ON CONFLICT(issue_id) DO UPDATE SET generation=generation+1;
 END;
CREATE TRIGGER IF NOT EXISTS human_scope_state AFTER UPDATE ON labeling_scope_state BEGIN
 INSERT INTO human_label_dirty(issue_id,generation) SELECT issue_id,1 FROM (SELECT issue_id FROM human_label_scopes WHERE baseline_scope=NEW.baseline_scope) WHERE 1=1
 ON CONFLICT(issue_id) DO UPDATE SET generation=generation+1;
 END;
CREATE TRIGGER IF NOT EXISTS human_target_change AFTER UPDATE OF is_target ON version_dataset_items BEGIN
 INSERT INTO human_label_dirty(issue_id,generation) SELECT issue_id,1 FROM (SELECT issue_id FROM human_label_scopes WHERE issue_id=NEW.issue_id AND dataset_id=NEW.dataset_id) WHERE 1=1
 ON CONFLICT(issue_id) DO UPDATE SET generation=generation+1;
 END;
CREATE TRIGGER IF NOT EXISTS human_suppression_insert AFTER INSERT ON label_import_suppressed_revisions BEGIN
 INSERT INTO human_label_dirty(issue_id,generation) SELECT issue_id,1 FROM (SELECT c.issue_id FROM label_revisions r JOIN label_cases c ON c.id=r.label_case_id JOIN human_label_scopes h ON h.issue_id=c.issue_id WHERE r.id=NEW.revision_id) WHERE 1=1
 ON CONFLICT(issue_id) DO UPDATE SET generation=generation+1;
 END;
CREATE TRIGGER IF NOT EXISTS human_suppression_delete AFTER DELETE ON label_import_suppressed_revisions BEGIN
 INSERT INTO human_label_dirty(issue_id,generation) SELECT issue_id,1 FROM (SELECT c.issue_id FROM label_revisions r JOIN label_cases c ON c.id=r.label_case_id JOIN human_label_scopes h ON h.issue_id=c.issue_id WHERE r.id=OLD.revision_id) WHERE 1=1
 ON CONFLICT(issue_id) DO UPDATE SET generation=generation+1;
 END;
CREATE TRIGGER IF NOT EXISTS human_decision_insert AFTER INSERT ON issue_label_decisions BEGIN
 INSERT INTO human_label_dirty(issue_id,generation) SELECT issue_id,1 FROM (SELECT issue_id FROM human_label_scopes WHERE issue_id=NEW.issue_id) WHERE 1=1
 ON CONFLICT(issue_id) DO UPDATE SET generation=generation+1;
 END;
CREATE TRIGGER IF NOT EXISTS human_decision_delete AFTER DELETE ON issue_label_decisions BEGIN
 INSERT INTO human_label_dirty(issue_id,generation) SELECT issue_id,1 FROM (SELECT issue_id FROM human_label_scopes WHERE issue_id=OLD.issue_id) WHERE 1=1
 ON CONFLICT(issue_id) DO UPDATE SET generation=generation+1;
 END;
        ''')
    seed_roles(conn)
