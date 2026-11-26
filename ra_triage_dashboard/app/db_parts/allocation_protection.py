"""Derive protected work and a preview snapshot from existing records only."""
from collections import Counter, defaultdict

from ..allocation_coverage import coverage_summary
from .campaigns import _fingerprint
from .shared import LABELS, _json_load


class AllocationProtectionMixin:
    @staticmethod
    def _validate_allocation_revision(value):
        if value is not None and (type(value) is not int or value < 1):
            raise ValueError("分配版本必须是正整数 / Allocation revision must be a positive integer")

    def _lock_task_work(self, conn):
        """Exclusive transaction gate for structural campaign and role changes.

        Acquire before dataset/issue/head locks. PostgreSQL's exclusive
        advisory lock serializes against in-flight shared per-issue submissions;
        SQLite acquires its writer reservation before reading.
        """
        if self.backend == "postgresql":
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(?))", ("campaign-work-allocation-v1",))
        elif not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")

    def _lock_task_work_shared(self, conn):
        """Shared transaction gate for per-issue reviewer/labeler submissions.

        On PostgreSQL, acquires the shared advisory lock so concurrent
        submissions on distinct Issues run in parallel (paired with row-level
        ``FOR UPDATE`` on the target Issue/Case), while still serializing
        cleanly against exclusive structural reallocations. Falls back to
        ``self._lock_task_work(conn)`` on SQLite or when tests patch
        ``_lock_task_work`` on the instance.
        """
        if self.backend == "postgresql" and "_lock_task_work" not in self.__dict__:
            conn.execute("SELECT pg_advisory_xact_lock_shared(hashtext(?))", ("campaign-work-allocation-v1",))
            return
        self._lock_task_work(conn)

    def _allocation_protection(self, conn, split, assignments):
        cid = split["id"]
        members = [dict(r) for r in conn.execute(
            "SELECT * FROM campaign_issue_members WHERE campaign_id=? ORDER BY ordinal,issue_id", (cid,),
        ).fetchall()]
        by_issue = defaultdict(set)
        for r in assignments:
            by_issue[r["issue_id"]].add(r["assignee"])
        if any(len(by_issue[m["issue_id"]]) != m["required_submitter_count"] for m in members):
            raise ValueError("任务人数与现有分配不一致，请先核对任务 / Task coverage does not match its assignments")
        if set(by_issue) != {m["issue_id"] for m in members}:
            raise ValueError("任务 Case 范围与分配不一致 / Task Cases and assignments do not match")
        pairs = {(r["issue_id"], r["assignee"]) for r in assignments}
        models = [dict(r) for r in conn.execute(
            "SELECT * FROM model_review_revisions WHERE campaign_id=? OR work_split_id=? ORDER BY id", (cid, cid),
        ).fetchall()]
        heads = [dict(r) for r in conn.execute(
            "SELECT h.* FROM model_review_heads h JOIN model_review_revisions r ON r.id=h.revision_id "
            "WHERE h.campaign_id=? OR r.work_split_id=? ORDER BY h.issue_id,h.reviewer", (cid, cid),
        ).fetchall()]
        progress = [dict(r) for r in conn.execute(
            "SELECT * FROM combined_review_progress WHERE campaign_id=? ORDER BY issue_id,reviewer", (cid,),
        ).fetchall()]
        labels = [dict(r) for r in conn.execute(
            """SELECT r.*,c.issue_id,c.task_id,c.source_run_id,c.baseline_scope,
                      s.revision_id AS suppressed,v.role AS captured_role
               FROM label_revisions r JOIN label_cases c ON c.id=r.label_case_id
               LEFT JOIN label_import_suppressed_revisions s ON s.revision_id=r.id
               LEFT JOIN human_vote_roles v ON v.revision_id=r.id
               WHERE c.task_id=? OR r.id IN (
                 SELECT case_label_revision_id FROM combined_review_progress WHERE campaign_id=?
               ) OR EXISTS (
                 SELECT 1 FROM human_label_scopes hs
                 WHERE hs.campaign_id=? AND hs.issue_id=c.issue_id AND hs.baseline_scope=c.baseline_scope
               ) ORDER BY r.id""", (cid, cid, cid),
        ).fetchall()]
        resolutions = [dict(r) for r in conn.execute(
            "SELECT r.*,c.issue_id FROM label_resolutions r JOIN label_cases c ON c.id=r.label_case_id "
            "WHERE c.task_id=? ORDER BY r.id", (cid,),
        ).fetchall()]
        decisions = [dict(r) for r in conn.execute(
            "SELECT d.* FROM issue_label_decisions d JOIN campaign_issue_members m "
            "ON m.issue_id=d.issue_id AND m.baseline_scope=d.baseline_scope "
            "WHERE m.campaign_id=? ORDER BY d.id", (cid,),
        ).fetchall()]
        captured = [dict(r) for r in conn.execute(
            "SELECT * FROM human_assignment_roles WHERE campaign_id=? ORDER BY issue_id,username", (cid,),
        ).fetchall()]
        protected, completed, history = set(), set(), set()
        problems = set()
        role_map = {(r["issue_id"], r["username"]): r["role"] for r in captured}
        model_by_id = {r["id"]: r for r in models}
        label_by_id = {r["id"]: r for r in labels}
        run = split["evaluation_run_id"] or split["model_run_id"]
        reference = split["reference_id"]
        for row in models:
            pair = (row["issue_id"], row["reviewer"].lower())
            history.add(pair)
            if row["model_run_id"] != run or row["reference_id"] != reference or row["campaign_id"] != cid:
                # Legacy migrated evidence is retained, but not guessed complete.
                if pair in pairs:
                    problems.add(row["issue_id"])
        head_ids = {h["revision_id"] for h in heads}
        for row in heads:
            model = model_by_id.get(row["revision_id"])
            pair = (row["issue_id"], row["reviewer"].lower())
            if (split["workflow_mode"] != "model_review_and_case_label" and model
                    and model["status"] == "completed" and model["model_run_id"] == run
                    and row["campaign_id"] == cid and row["reference_id"] == reference):
                completed.add(pair)
        latest_labels = {}
        expected_source = conn.execute(
            "SELECT selection_source_run_id FROM review_worksets WHERE id=?", (split["workset_id"],),
        ).fetchone()
        source = (expected_source["selection_source_run_id"] if expected_source else "") or split["selection_source_run_id"] or ""
        for row in labels:
            pair = (row["issue_id"], row["author"].lower())
            history.add(pair)
            if row["task_id"] == cid and source and row["source_run_id"] != source:
                if pair in pairs:
                    problems.add(row["issue_id"])
            if row["revision_kind"] in {"submission", "legacy"} and not row["suppressed"]:
                latest_labels[pair] = row
        if split["purpose"] == "labeling":
            for pair, row in latest_labels.items():
                if row["task_id"] == cid and row["expected_output"] in LABELS and (not source or row["source_run_id"] == source):
                    completed.add(pair)
        for row in progress:
            pair = (row["issue_id"], row["reviewer"].lower())
            history.add(pair)
            model = model_by_id.get(row["model_review_revision_id"])
            label = label_by_id.get(row["case_label_revision_id"])
            valid = (model and label and model["campaign_id"] == cid and model["model_run_id"] == run
                     and model["reference_id"] == reference and model["issue_id"] == row["issue_id"]
                     and label["issue_id"] == row["issue_id"] and not label["suppressed"]
                     and model["reviewer"].lower() == pair[1] and label["author"].lower() == pair[1]
                     and model["id"] in head_ids)
            if row["model_review_submitted"] and row["case_label_acknowledged"]:
                if valid:
                    completed.add(pair)
                elif pair in pairs:
                    problems.add(row["issue_id"])
        # Preserve all existing authors with any saved work, including an empty
        # label draft or only one half of a combined submission.
        protected.update(history & pairs)
        protected.update(completed & pairs)
        completed.intersection_update(pairs)
        if problems:
            raise ValueError("已有标注的任务、Run 或参考关联不明确，请先核对 / Saved evidence has ambiguous task, Run or reference links")
        adjudicated_cases = {r["issue_id"] for r in [*resolutions, *decisions]}
        frozen_cases = {r["issue_id"] for r in resolutions}
        source_task = _json_load(split["filter_json"], {}).get("source_legacy_split_id")
        if source_task and split["workflow_mode"] == "model_review_and_case_label":
            # A migrated joint task still points at revisions from its original labeling task.
            original = conn.execute("""
                SELECT DISTINCT lc.issue_id,lc.baseline_scope FROM label_resolutions r
                JOIN label_cases lc ON lc.id=r.label_case_id
                JOIN campaign_issue_members m ON m.issue_id=lc.issue_id AND m.baseline_scope=lc.baseline_scope
                WHERE m.campaign_id=? AND lc.task_id=? AND lc.source_run_id=?
            """, (cid, source_task, run)).fetchall()
            by_scope = defaultdict(set)
            for r in original:
                by_scope[r["baseline_scope"]].add(r["issue_id"])
            for r in decisions:
                by_scope[r["baseline_scope"]].add(r["issue_id"])
            for scope, ids in by_scope.items():
                states = self.project_issue_label_states(scope, sorted(ids), include_sources=False, connection=conn)
                adjudicated_cases.difference_update(ids)
                adjudicated_cases.update(iid for iid in ids if states.get(iid, {}).get("state") == "resolved")
            frozen_cases.update(r["issue_id"] for r in original)
        if decisions:
            # Issue decisions can come entirely from another labeling context.
            # Keep unknown provenance and decisions using any task evidence locked.
            external_sources = defaultdict(set)
            for row in conn.execute(
                "SELECT c.issue_id,c.id FROM label_cases c JOIN campaign_issue_members m "
                "ON m.issue_id=c.issue_id AND m.baseline_scope=c.baseline_scope "
                "WHERE m.campaign_id=? AND COALESCE(c.task_id,'')<>?", (cid, cid),
            ).fetchall():
                external_sources[row["issue_id"]].add(row["id"])
            linked_cases = {r["label_case_id"] for r in labels}
            for decision in decisions:
                iid = decision["issue_id"]
                sources = set(_json_load(decision["source_case_ids_json"], []))
                if not sources or not sources <= external_sources[iid] or sources & linked_cases:
                    frozen_cases.add(iid)
        outputs = defaultdict(set)
        case_outputs = {}
        for pair, row in latest_labels.items():
            if pair in pairs and row["expected_output"] in LABELS:
                outputs[pair[0]].add(row["expected_output"])
                case_outputs[pair] = row["expected_output"]
        frozen_cases.update(i for i, values in outputs.items() if len(values) > 1)
        protected.update(pair for pair in pairs if pair[0] in frozen_cases)
        security = [dict(r) for r in conn.execute(
            "SELECT a.username,a.role,h.role AS human_role FROM access_users a "
            "LEFT JOIN human_user_roles h ON h.username=a.username ORDER BY a.username",
        ).fetchall()]
        dataset_id = _json_load(split["filter_json"], {}).get("version_dataset_id")
        dataset = conn.execute("SELECT * FROM version_datasets WHERE id=?", (dataset_id,)).fetchone() if dataset_id else None
        targets = [dict(r) for r in conn.execute(
            "SELECT issue_id,is_target,updated_at FROM version_dataset_items WHERE dataset_id=? ORDER BY issue_id",
            (dataset_id,),
        ).fetchall()] if dataset_id else []
        snapshot = _fingerprint(dict(
            split=split, members=members, assignments=assignments, models=models, heads=heads,
            progress=progress, labels=labels, resolutions=resolutions, decisions=decisions,
            captured=captured, security=security, dataset=dict(dataset) if dataset else None, targets=targets,
        ))
        return dict(protected=protected, completed=completed, forbidden=history - pairs,
                    model_submitted={(r["issue_id"], r["reviewer"].lower()) for r in progress if r["model_review_submitted"]},
                    coverage_locked={iid for iid, _ in history} | frozen_cases, frozen_cases=frozen_cases,
                    adjudicated_cases=adjudicated_cases, case_outputs=case_outputs,
                    captured_roles=role_map, snapshot=snapshot, members=members,
                    has_evidence=bool(models or progress or labels or resolutions or decisions))

    @staticmethod
    def _allocation_progress_summary(assignments, evidence, *, role_required=False):
        counts = Counter(r["assignee"] for r in assignments)
        done = Counter(p for _, p in evidence["completed"])
        locked = Counter(p for _, p in evidence["protected"])
        case_counts = Counter(r["issue_id"] for r in assignments)
        coverage_locked = case_counts if role_required and evidence["has_evidence"] else evidence["coverage_locked"]
        coverage = coverage_summary(case_counts, coverage_locked)
        summary = dict(
            total_slots=len(assignments), completed_slots=sum(done.values()),
            saved_pending_slots=sum(locked.values()) - sum(done.values()),
            movable_slots=len(assignments) - sum(locked.values()),
            coverage_editable=not evidence["has_evidence"],
            coverage=coverage,
            progress_members=[dict(name=p, before=counts[p], completed=done[p],
                                   saved_pending=locked[p] - done[p]) for p in sorted(counts)],
            cross_case_count=coverage["cross_cases"],
        )
        if role_required:
            available = Counter(
                evidence["captured_roles"].get((row["issue_id"], row["assignee"]))
                for row in assignments
                if (row["issue_id"], row["assignee"]) not in evidence["protected"]
            )
            summary["role_movable_slots"] = {role: available[role] for role in ("rd", "te")}
        return summary
