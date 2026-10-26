"""Explicit Trail adoption as an append-only personal Case vote, never a decision."""
from uuid import uuid4

from .shared import _json, _json_load, utc_now, LabelAnnotationConflictError
from .snapshots import _sha256_json


class TrailLocalImportMixin:
    def trail_local_import_members(self, *, scopes, after="", limit=100):
        """Scan dataset membership, not the exclusion-only/historical inventory."""
        if not scopes:
            return {"items": [], "total": 0, "next_cursor": None, "scanned": 0}
        placeholders = ",".join("?" for _ in scopes)
        with self.connect() as conn:
            rows = [dict(row) for row in conn.execute(
                f"SELECT issue_id, baseline_scope FROM issues WHERE baseline_scope IN ({placeholders}) ORDER BY issue_id", scopes).fetchall()]
        remaining = [row for row in rows if row["issue_id"] > after]
        page = remaining[:limit]
        projections = self.project_issue_exclusions([row["issue_id"] for row in page])
        for row in page:
            projection = projections.get(row["issue_id"])
            row["local_excluded"] = projection["is_excluded"] if projection else None
        return {"items": page, "total": len(rows), "scanned": len(rows) - len(remaining) + len(page),
                "next_cursor": page[-1]["issue_id"] if len(remaining) > limit else None}

    def _trail_import_context(self, conn, issue_id, actor, scopes):
        issue = conn.execute("SELECT issue_id, baseline_scope, gt_label, gt_source FROM issues WHERE issue_id=?", (issue_id,)).fetchone()
        if issue is None or issue["baseline_scope"] not in scopes:
            raise ValueError("Issue 不在所选数据集中 / Issue outside selected datasets")
        active = conn.execute("SELECT status FROM labeling_scope_state WHERE baseline_scope=?", (issue["baseline_scope"],)).fetchone()
        if not active or active["status"] != "active":
            raise ValueError("数据集未启用标注 / Labeling is not active")
        revisions = [dict(row) for row in conn.execute("""SELECT r.*, c.task_id, c.source_run_id
            FROM label_revisions r JOIN label_cases c ON c.id=r.label_case_id
            WHERE c.issue_id=? ORDER BY r.id""", (issue_id,)).fetchall()]
        decisions = conn.execute("SELECT id FROM issue_label_decisions WHERE issue_id=? LIMIT 1", (issue_id,)).fetchone()
        resolutions = conn.execute("""SELECT r.id FROM label_resolutions r JOIN label_cases c
            ON c.id=r.label_case_id WHERE c.issue_id=? LIMIT 1""", (issue_id,)).fetchone()
        if decisions or resolutions:
            raise ValueError("已有裁决，请在裁决中核对来源 / Existing adjudication; review the source in adjudication")
        own = [r for r in revisions if r["author"].lower() == actor.lower() and r["revision_kind"] in ("submission", "legacy")]
        head = own[-1] if own else None
        if head and head["task_id"]:
            raise ValueError("已有任务标注，请通过该任务修改 / Existing task vote; edit through that task")
        suppressed = [dict(row) for row in conn.execute("""SELECT s.* FROM label_import_suppressed_revisions s
            JOIN label_revisions r ON r.id=s.revision_id JOIN label_cases c ON c.id=r.label_case_id
            WHERE c.issue_id=? ORDER BY s.revision_id""", (issue_id,)).fetchall()]
        if head and any(row["revision_id"] == head["id"] for row in suppressed):
            raise ValueError("当前个人来源已停用，请先核对 / Current personal source is suppressed")
        return {"issue": dict(issue), "head": head,
                "fingerprint": _sha256_json({"issue": dict(issue), "revisions": revisions, "suppressed": suppressed})}

    def preview_trail_local_import(self, *, issue_ids, actor, scopes, remote):
        items = []
        with self._write_lock, self.connect() as conn:
            for issue_id in issue_ids:
                context = self._trail_import_context(conn, issue_id, actor, scopes)
                head = context["head"] or {}
                source = remote[issue_id]
                if source.get("should_exclude") is not True:
                    raise ValueError(f"{issue_id}: Trail 当前未明确排除 / Trail is not explicitly excluded")
                reason = source.get("should_exclude_comment")
                if reason is not None and not isinstance(reason, str):
                    raise ValueError("Trail 理由格式异常 / Invalid Trail reason")
                reason = reason or ""
                local = str(head.get("rationale") or "")
                if local.strip() and reason.strip() and local.strip() != reason.strip():
                    raise ValueError(f"{issue_id}: 本地理由与 Trail 不同，请先人工核对 / Local and Trail reasons differ; review first")
                adopted = local if local.strip() else reason
                if len(adopted) > 8000:
                    raise ValueError("理由超过 8000 字符 / Reason exceeds 8000 characters")
                items.append({"issue_id": issue_id, "baseline_scope": context["issue"]["baseline_scope"],
                    "local_fingerprint": context["fingerprint"], "previous_revision_id": head.get("id"),
                    "before": {"is_excluded": bool(head["is_excluded"]) if head else None, "rationale": local},
                    "after": {"is_excluded": True, "rationale": adopted}, "remote": source,
                    "expected_output": head.get("expected_output") or "",
                    "unchanged": bool(head and head["is_excluded"] and local == adopted)})
        return items

    def commit_trail_local_import(self, *, operation_id, actor, scopes, items):
        """Validate all rows before any append; audit and votes commit together."""
        with self._write_lock, self.connect() as conn:
            if self.backend == "sqlite":
                conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute("SELECT actor, result_json FROM trail_local_imports WHERE operation_id=?", (operation_id,)).fetchone()
            if existing:
                if existing["actor"] != actor:
                    raise PermissionError("导入属于其他用户 / Import belongs to another user")
                return _json_load(existing["result_json"], {})
            contexts = {}
            for item in items:
                ctx = self._trail_import_context(conn, item["issue_id"], actor, scopes)
                if ctx["fingerprint"] != item["local_fingerprint"]:
                    raise LabelAnnotationConflictError("本地标注已变化，请重新预览 / Local annotations changed; preview again")
                contexts[item["issue_id"]] = ctx
            now, results = utc_now(), []
            for item in items:
                ctx = contexts[item["issue_id"]]
                head, issue = ctx["head"] or {}, ctx["issue"]
                if item["unchanged"]:
                    results.append({"issue_id": item["issue_id"], "revision_id": head["id"], "status": "unchanged"})
                    continue
                case_id = head.get("label_case_id")
                if not case_id:
                    row = conn.execute("SELECT id FROM label_cases WHERE issue_id=? AND baseline_scope=? AND task_id='' AND source_run_id=''", (item["issue_id"], issue["baseline_scope"])).fetchone()
                    case_id = row["id"] if row else f"label-{uuid4().hex}"
                    if not row:
                        conn.execute("""INSERT INTO label_cases (id,baseline_scope,issue_id,task_id,source_run_id,seen_gt_label,seen_gt_source,created_at)
                            VALUES (?,?,?,'','',?,?,?)""", (case_id, issue["baseline_scope"], item["issue_id"], issue["gt_label"], issue["gt_source"], now))
                sql = """INSERT INTO label_revisions (label_case_id,expected_output,tags_json,evidence_gaps_json,
                    rationale,is_excluded,author,author_source,author_verified,revision_kind,supersedes_id,created_at)
                    VALUES (?,?,?,?,?,TRUE,?,'trail_import',TRUE,'submission',?,?)"""
                if self.backend == "postgresql":
                    sql += " RETURNING id"
                cursor = conn.execute(sql, (case_id, head.get("expected_output"), _json(_json_load(head.get("tags_json"), [])),
                    _json(_json_load(head.get("evidence_gaps_json"), [])), item["after"]["rationale"], actor, head.get("id"), now))
                revision_id = int(cursor.fetchone()["id"]) if self.backend == "postgresql" else cursor.lastrowid
                if head:
                    for image in conn.execute("SELECT * FROM label_attachments WHERE revision_id=?", (head["id"],)).fetchall():
                        conn.execute("""INSERT INTO label_attachments (id,revision_id,source_review_attachment_id,original_name,stored_name,
                            media_type,size_bytes,width,height,sha256,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                            (uuid4().hex, revision_id, None, image["original_name"], image["stored_name"],
                             image["media_type"], image["size_bytes"], image["width"], image["height"], image["sha256"], now))
                results.append({"issue_id": item["issue_id"], "revision_id": revision_id, "status": "imported"})
            result = {"ok": True, "operation_id": operation_id, "items": results,
                      "imported_count": sum(row["status"] == "imported" for row in results)}
            conn.execute("INSERT INTO trail_local_imports (operation_id,actor,source_json,result_json,created_at) VALUES (?,?,?,?,?)",
                         (operation_id, actor, _json(items), _json(result), now))
            if result["imported_count"]:
                self._mark_labeling_change(conn)
            return result

    def trail_local_import_result(self, operation_id, actor):
        with self.connect() as conn:
            row = conn.execute("SELECT actor,result_json FROM trail_local_imports WHERE operation_id=?", (operation_id,)).fetchone()
        if row and row["actor"] != actor:
            raise PermissionError("导入属于其他用户 / Import belongs to another user")
        return _json_load(row["result_json"], {}) if row else None
