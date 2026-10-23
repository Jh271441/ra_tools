"""Recover only exact original migrated exclusion notes, without modifying votes."""
import sqlite3
import unittest
from contextlib import contextmanager
from ra_triage_dashboard.app.db_parts.labeling_projection import LabelingProjectionMixin

class LegacyReasonSourceTest(unittest.TestCase):
    def test_exact_original_only_and_read_only_idempotence(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        class Reader(LabelingProjectionMixin):
            @contextmanager
            def connect(self):
                yield conn
        db = Reader()
        conn.executescript("""
            CREATE TABLE label_cases(id TEXT PRIMARY KEY,issue_id TEXT);
            CREATE TABLE label_revisions(id INTEGER PRIMARY KEY,label_case_id TEXT,source_annotation_id INTEGER,
              revision_kind TEXT,is_excluded BOOLEAN,author TEXT,rationale TEXT);
            CREATE TABLE annotations(id INTEGER PRIMARY KEY,issue_id TEXT,is_excluded BOOLEAN,author TEXT,note TEXT,created_at TEXT);
            CREATE TABLE model_review_revisions(legacy_annotation_id INTEGER,reason TEXT);
        """)
        for i in range(1,8):
            conn.execute("INSERT INTO label_cases VALUES (?,?)",(str(i),'cn'+str(i)))
            conn.execute("INSERT INTO label_revisions VALUES (?,?,?,?,?,?,?)",(i,str(i),i,'legacy',True,'alice',''))
            conn.execute("INSERT INTO annotations VALUES (?,?,?,?,?,?)",(i,'cn'+str(i),True,'Alice','original reason','2026-09-18T01:00:00Z'))
            conn.execute("INSERT INTO model_review_revisions VALUES (?,?)",(i,'original reason'))
        conn.execute("UPDATE label_revisions SET revision_kind='submission' WHERE id=2")
        conn.execute("UPDATE label_revisions SET rationale='new personal reason' WHERE id=3")
        conn.execute("UPDATE annotations SET is_excluded=false WHERE id=4")
        conn.execute("UPDATE annotations SET author='bob' WHERE id=5")
        conn.execute("UPDATE model_review_revisions SET reason='unrelated note' WHERE legacy_annotation_id=6")
        conn.execute("UPDATE annotations SET issue_id='another-issue' WHERE id=7")
        before=conn.total_changes
        for _ in range(2):
            result=db.legacy_exclusion_reason_sources(iter(range(1,8)))
            self.assertEqual(list(result),[1])
            self.assertEqual(result[1]['note'],'original reason')
            self.assertEqual(result[1]['source_annotation_id'],1)
            self.assertEqual(result[1]['original_created_at'],'2026-09-18T01:00:00Z')
        self.assertEqual(conn.total_changes,before)
        self.assertEqual(conn.execute('SELECT rationale FROM label_revisions WHERE id=1').fetchone()[0],'')
        conn.close()
