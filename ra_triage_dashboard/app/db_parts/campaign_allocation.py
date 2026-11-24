"""Atomic, audited editing of a task's allocation without changing its evidence."""
from __future__ import annotations

from collections import Counter, defaultdict
import time
from typing import Any

from .allocation_preview import AllocationPreviewMixin
from .campaigns import CampaignConflictError, CampaignReadOnlyError, _fingerprint
from .shared import _json, _json_load, utc_now
from ..human_label_policy import allocate_role_pairs, initial_role
from ..group_allocation import convergence_summary, group_projection, group_rules, grouped_config, normalize_groups, normalize_pairing_mode, plan_groups
from ..task_allocation_policy import allocate_percentages, percentage_weights, review_percent, validate_percentages
from ..task_reallocation import bounded_shares
from ..allocation_coverage import CoverageConstraintError
from ..work_split import distribute_issue_ids, normalize_overlap_ratio


class DatabaseCampaignAllocationMixin(AllocationPreviewMixin):
    def _task_allocation(self, conn, campaign_id):
        row = conn.execute("SELECT * FROM issue_work_splits WHERE id=?", (campaign_id,)).fetchone()
        if row is None:
            raise ValueError("任务不存在 / Task not found")
        split = dict(row)
        filters = _json_load(split["filter_json"], {})
        assignments = [dict(r) for r in conn.execute(
            "SELECT * FROM review_work_assignments WHERE split_id=? ORDER BY issue_id,ordinal,assignee",
            (campaign_id,),
        ).fetchall()]
        saved = filters.get("task_allocation")
        if saved:
            config = saved
        else:
            snapshot = _json_load(split["assignees_json"], [])
            names = list(dict.fromkeys(
                [str(r.get("name") or "").lower() for r in snapshot if r.get("name")]
                + [r["assignee"].lower() for r in assignments]
            ))
            config = dict(
                assignees=[dict(name=name, count=None) for name in names],
                reviewers_per_issue=int(split["reviewers_per_issue"] or 1),
                overlap_ratio=float(split["overlap_ratio"] or 0),
            )
        role_task = conn.execute(
            "SELECT dataset_id FROM human_version_tasks WHERE campaign_id=?", (campaign_id,),
        ).fetchone()
        users = [dict(r) for r in conn.execute(
            "SELECT a.username,a.role,h.role AS human_role FROM access_users a "
            "LEFT JOIN human_user_roles h ON h.username=a.username ORDER BY a.username"
        ).fetchall()]
        eligible = [u for u in users if u["role"] in {"writer", "admin"}
                    and (not role_task or u["human_role"] in {"rd", "te"})]
        config = {**config, "quota_basis": config.get("quota_basis", "remaining"),
                  "cross_groups": config.get("cross_groups", []),
                  "pairing_mode": normalize_pairing_mode(config.get("pairing_mode"))}
        return dict(
            campaign_id=campaign_id, name=split["campaign_name"],
            purpose=split["purpose"], workflow_mode=split["workflow_mode"],
            expected_revision=int(split["config_revision"] or 1),
            editable=split["lifecycle"] == "active" and not split["legacy_read_only"] and bool(split["purpose"]),
            role_required=bool(role_task), appendable=bool(filters.get("version_live")),
            member_count=int(split["total_count"] or 0), eligible_members=eligible,
            assignment_counts=dict(Counter(r["assignee"] for r in assignments)),
            **config,
        ), split, filters, assignments

    def get_campaign_allocation(self, campaign_id):
        campaign_id = self.resolve_version_campaign(str(campaign_id))
        with self.connect() as conn:
            current, split, _, rows = self._task_allocation(conn, campaign_id)
            evidence = self._allocation_protection(conn, split, rows)
        groups, owners = self._group_history(current, rows, evidence)
        case_ids = [m["issue_id"] for m in evidence["members"]]
        projection = group_projection(groups, owners, evidence["completed"], case_ids=case_ids)
        progress = self._allocation_progress_summary(rows, evidence, role_required=current["role_required"])
        if current.get("groups"):
            progress["active_slots"] = projection["active_slots"]
            progress["active_completed_slots"] = projection["active_completed_slots"]
            progress["movable_slots"] = max(
                0, projection["active_slots"] - projection["active_completed_slots"] - progress["saved_pending_slots"]
            )
        return {
            **current,
            **progress,
            "active_assignment_counts": dict(Counter(name for m in owners.values() for name in m.values())),
            "groups": groups,
            "group_rules": group_rules(current["cross_groups"], owners),
            "group_coverage": projection,
            "convergence": convergence_summary(case_ids, evidence),
        }

    def _allocation_without_member(self, conn, campaign_id, assignee):
        """Normalize the remaining roster; retain coverage and all saved authors."""
        current = self._task_allocation(conn, campaign_id)[0]
        name = str(assignee or "").strip().lower()
        if not any(p["name"] == name for p in current["assignees"]):
            raise ValueError("此人不在当前接收成员中 / This person is not a current recipient")
        if current.get("groups"):
            groups = []
            for group in current["groups"]:
                weights = percentage_weights([p for p in group["members"] if p["name"] != name])
                if not sum(weights.values()):
                    raise ValueError("请为每个组保留接收人员 / Keep a recipient in each group")
                shares = bounded_shares(weights, 10000)
                groups.append({**group, "members": [dict(name=p, review_percent=share / 100) for p, share in shares.items()]})
            return dict(assignees=None, reviewers_per_issue=None, overlap_ratio=None, groups=groups,
                        cross_groups=[rule for rule in current["cross_groups"] if name not in {p["name"] for p in rule["members"]}])
        people = [p for p in current["assignees"] if p["name"] != name]
        if not people:
            raise ValueError("请先补充接收成员，或删除整条分配 / Add a recipient first, or delete the whole allocation")
        if any("review_percent" in p or p.get("count") is not None for p in people):
            weights = {p["name"]: int(round(100 * p["review_percent"])) if "review_percent" in p
                       else p.get("count") if p.get("count") is not None
                       else current["assignment_counts"].get(p["name"], 0) for p in people}
            if not sum(weights.values()):
                raise ValueError("剩余成员的比例为零，请先调整接收成员 / Remaining members have zero shares; update the recipients first")
            shares = bounded_shares(weights, 10000)
            people = [dict(name=p["name"], count=None, review_percent=shares[p["name"]] / 100) for p in people]
        else:
            people = [dict(name=p["name"], count=None) for p in people]
        return dict(assignees=people, reviewers_per_issue=current["reviewers_per_issue"],
                    overlap_ratio=current["overlap_ratio"],
                    cross_groups=[group for group in current["cross_groups"] if name not in group["members"]])

    def preview_campaign_member_removal(self, *, campaign_id, assignee, expected_revision,
                                        quota_basis="remaining"):
        campaign_id = self.resolve_version_campaign(str(campaign_id))
        with self.connect() as conn:
            config = self._allocation_without_member(conn, campaign_id, assignee)
            current, split, filters, old_rows, evidence, all_roles = self._load_reallocation_snapshot(
                conn, campaign_id, expected_revision=expected_revision, quota_basis=quota_basis,
            )
        preview = self._compute_task_reallocation(
            current, split, filters, old_rows, evidence,
            config["assignees"], config["reviewers_per_issue"], config["overlap_ratio"],
            expected_revision, quota_basis, int(time.time()),
            config.get("cross_groups"), config.get("groups"),
            all_roles=all_roles,
        )[-1]
        return {**preview, "removed_assignee": str(assignee).strip().lower()}

    def delete_campaign_allocation_member(self, *, campaign_id, assignee, expected_revision,
                                          idempotency_key, actor, actor_source="legacy",
                                          actor_verified=False, quota_basis="remaining", preview_token=""):
        if not preview_token:
            raise CampaignConflictError("取消个人分配需要先预览 / Preview the member removal first")
        return self.update_campaign_allocation(
            campaign_id=campaign_id, assignees=None, reviewers_per_issue=None, overlap_ratio=None,
            expected_revision=expected_revision, idempotency_key=idempotency_key,
            actor=actor, actor_source=actor_source, actor_verified=actor_verified,
            quota_basis=quota_basis, preview_token=preview_token,
            remove_assignee=str(assignee or "").strip().lower(),
        )

    @staticmethod
    def _validate_task_allocation(config, assignees, reviewers_per_issue, overlap_ratio, *,
                                  protected=False, quota_basis="remaining"):
        if quota_basis not in {"remaining", "total"}:
            raise ValueError("分配基数无效 / Invalid allocation basis")
        if not isinstance(assignees, list) or not 1 <= len(assignees) <= 100:
            raise ValueError("请选择 1–100 名成员 / Select 1–100 members")
        if type(reviewers_per_issue) is not int or not 1 <= reviewers_per_issue <= (100 if protected else len(assignees)):
            raise ValueError("复核人数必须在 1 到成员数之间 / Reviewer count must be between 1 and the member count")
        allowed = {u["username"]: u for u in config["eligible_members"]}
        proportional = any(isinstance(item, dict) and "review_percent" in item for item in assignees)
        people = []
        for item in assignees:
            if not isinstance(item, dict):
                raise ValueError("成员格式无效 / Invalid member")
            name = str(item.get("name") or "").strip().lower()
            count = item.get("count")
            if name not in allowed:
                raise ValueError("成员需要有效的标注权限 / Member needs annotation access: " + name)
            if name in {p["name"] for p in people}:
                raise ValueError("成员不能重复 / Duplicate member")
            if count is not None and (type(count) is not int or count < 0):
                raise ValueError("个人数量必须是非负整数 / Quota must be a non-negative integer")
            if config["appendable"] and count is not None:
                raise ValueError("持续追加任务使用均衡分配 / Appendable tasks use balanced allocation")
            person = dict(name=name, count=count)
            if proportional:
                if count is not None:
                    raise ValueError("个人比例和固定数量不能混用 / Percentages and fixed quotas cannot be mixed")
                person["review_percent"] = review_percent(item.get("review_percent"))
            people.append(person)
        ratio = normalize_overlap_ratio(overlap_ratio, reviewers_per_issue=reviewers_per_issue)
        ratio = ratio if reviewers_per_issue > 1 else 0
        if config["role_required"]:
            roles = {allowed[p["name"]]["human_role"] for p in people}
            if (not protected and roles != {"rd", "te"}) or reviewers_per_issue < 2 or ratio != 1:
                raise ValueError("正式版本任务每个 Case 需至少一名 RD 和一名 TE / Formal version tasks require RD and TE on every Case")
        if proportional:
            if protected:
                if sum(percentage_weights(people).values()) != 10000:
                    raise ValueError("个人 review 比例合计须为 100% / Review percentages must total 100%")
            else:
                validate_percentages(people, reviewers=reviewers_per_issue, overlap=ratio,
                    roles={p["name"]: allowed[p["name"]]["human_role"] for p in people} if config["role_required"] else None)
        if config["appendable"]:
            recipients = [p for p in people if p.get("review_percent", 100) > 0]
            if config["role_required"] and {allowed[p["name"]]["human_role"] for p in recipients} != {"rd", "te"}:
                raise ValueError("RD 和 TE 各需至少一位正比例接收成员，才能覆盖后续新增 Case / New Cases require at least one positive-share recipient in each of RD and TE")
            if ratio > 0 and len(recipients) < reviewers_per_issue:
                raise ValueError("持续追加任务需要足够的正比例成员覆盖新 Case / Appendable tasks need enough positive-share members for new Cases")
        return dict(assignees=people, reviewers_per_issue=reviewers_per_issue, overlap_ratio=ratio)

    def _plan_task_allocation(self, conn, config, issue_ids, *, seed, role_required=False, previous=(), roles=None):
        """Also used by incremental tasks so saved membership governs future appends."""
        people = config["assignees"]
        if any("review_percent" in p for p in people):
            resolved_roles = (
                roles if roles is not None
                else ({r["username"]: r["role"] for r in conn.execute("SELECT username,role FROM human_user_roles").fetchall()} if role_required else None)
            )
            return allocate_percentages(issue_ids, people, reviewers=config["reviewers_per_issue"],
                overlap=config["overlap_ratio"], seed=seed, roles=resolved_roles, previous=previous)
        if role_required:
            resolved_roles = (
                roles if roles is not None
                else {r["username"]: r["role"] for r in conn.execute("SELECT username,role FROM human_user_roles").fetchall()}
            )
            rows = allocate_role_pairs(
                issue_ids, seed=seed, previous=previous,
                rd_reviewers=tuple(p["name"] for p in people if resolved_roles.get(p["name"]) == "rd"),
                te_reviewers=tuple(p["name"] for p in people if resolved_roles.get(p["name"]) == "te"),
                reviewers_per_issue=config["reviewers_per_issue"],
            )
            return [
                dict(issue_id=row["issue_id"], assignee=owner,
                     assignment_kind="base" if index == 0 else "cross", ordinal=ordinal)
                for ordinal, row in enumerate(rows, 1)
                for index, owner in enumerate(row["assignees"])
            ]
        if previous:
            # Incremental packets may contain only one Case. Carry cumulative
            # quotas and overlap forward so packet size cannot bias the roster.
            names = [p["name"] for p in people]
            counts = Counter(p for item in previous for p in item["assignees"])
            bases = Counter(item["assignees"][0] for item in previous)
            cross_total = sum(len(item["assignees"]) > 1 for item in previous)
            total = len(previous)
            rows = []
            for iid in sorted(issue_ids, key=lambda value: _fingerprint([seed, value])):
                total += 1
                cross = config["reviewers_per_issue"] > 1 and cross_total < round(total * config["overlap_ratio"])
                owner = min(names, key=lambda name: (bases[name], counts[name], _fingerprint([seed, iid, name])))
                owners = [owner]
                if cross:
                    others = sorted((p for p in names if p != owner),
                                    key=lambda name: (counts[name], _fingerprint([seed, iid, name])))
                    owners.extend(others[:config["reviewers_per_issue"] - 1])
                    cross_total += 1
                bases[owner] += 1
                counts.update(owners)
                rows.extend(dict(issue_id=iid, assignee=name, ordinal=index + 1,
                                 assignment_kind="base" if index == 0 else "cross")
                            for index, name in enumerate(owners))
            return rows
        plan = distribute_issue_ids(
            issue_ids, people, seed=seed, reviewers_per_issue=config["reviewers_per_issue"],
            overlap_ratio=config["overlap_ratio"],
        )
        return [
            dict(assignee=p["name"], **item)
            for p in plan
            for item in (p.get("items") or [
                dict(issue_id=iid, assignment_kind="base", ordinal=index)
                for index, iid in enumerate(p["issue_ids"], 1)
            ])
        ]

    def _append_group_allocation(self, conn, campaign_id, issue_ids, *, seed, active_ids):
        """Add only new assignments against cumulative group targets."""
        current, _, filters, rows = self._task_allocation(conn, campaign_id)
        prior, history = self._group_history(current, rows, {})
        groups = normalize_groups(prior, {user["username"] for user in current["eligible_members"]})
        active_ids = set(active_ids)
        existing = {iid: owners for iid, owners in history.items() if iid in active_ids}
        protected_rows = [row for row in rows if row["issue_id"] in existing]
        mode = normalize_pairing_mode(current.get("pairing_mode"))
        planned, placed, _ = plan_groups(
            [*sorted(existing), *issue_ids], groups, [], seed=seed, old_groups=prior, history=existing,
            old_rows=protected_rows, evidence=dict(coverage_locked=set(existing),
                protected={(row["issue_id"], row["assignee"]) for row in protected_rows}),
            basis="total", append=True, pairing_mode=mode,
        )
        added = set(issue_ids)
        config = grouped_config(groups, {**history, **{iid: placed[iid] for iid in issue_ids}},
                                current["cross_groups"], current["quota_basis"], pairing_mode=mode)
        filters["task_allocation"] = config
        conn.execute("UPDATE issue_work_splits SET filter_json=?,reviewers_per_issue=?,overlap_ratio=?,mode=? WHERE id=?",
                     (_json(filters), config["reviewers_per_issue"], config["overlap_ratio"],
                      "blind" if config["reviewers_per_issue"] > 1 else "single", campaign_id))
        return [row for row in planned if row["issue_id"] in added]

    def update_campaign_allocation(
        self, *, campaign_id: str, assignees: list[dict[str, Any]], reviewers_per_issue: int,
        overlap_ratio: float, expected_revision: int, idempotency_key: str,
        actor: str, actor_source: str = "legacy", actor_verified: bool = False,
        quota_basis: str = "remaining", preview_token: str = "", remove_assignee: str | None = None,
        cross_groups: list[dict[str, Any]] | None = None,
        groups: list[dict[str, Any]] | None = None,
        pairing_mode: str | None = None,
    ):
        campaign_id = self.resolve_version_campaign(str(campaign_id))
        if type(expected_revision) is not int or expected_revision < 1 or not actor or not idempotency_key or len(idempotency_key) > 160:
            raise ValueError("缺少有效的版本或操作身份 / Invalid revision or actor")
        request_config = dict(
            assignees=assignees, reviewers_per_issue=reviewers_per_issue,
            overlap_ratio=overlap_ratio, expected_revision=expected_revision,
            quota_basis=quota_basis, preview_token=preview_token,
        )
        if remove_assignee is not None:
            request_config["remove_assignee"] = remove_assignee
        if cross_groups is not None:
            request_config["cross_groups"] = cross_groups
        if groups is not None:
            request_config["groups"] = groups
        if pairing_mode is not None:
            request_config["pairing_mode"] = pairing_mode
        fingerprint = _fingerprint(request_config)
        with self._write_lock, self.connect() as conn:
            self._lock_task_work(conn)
            if self.backend == "postgresql":
                # Same lock order as the version appender and publication worker.
                row = conn.execute("SELECT filter_json FROM issue_work_splits WHERE id=?", (campaign_id,)).fetchone()
                dataset_id = _json_load(row["filter_json"], {}).get("version_dataset_id") if row else None
                if dataset_id:
                    conn.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (dataset_id,))
                conn.execute("SELECT id FROM issue_work_splits WHERE id=? FOR UPDATE", (campaign_id,))
            replay = conn.execute(
                "SELECT config_json FROM campaign_config_revisions WHERE campaign_id=? AND idempotency_key=?",
                (campaign_id, idempotency_key),
            ).fetchone()
            if replay:
                if _json_load(replay["config_json"], {}).get("allocation_request_fingerprint") != fingerprint:
                    raise CampaignConflictError("请求标识已用于其他变更 / Request key was used for a different change")
                return dict(changed=False, replayed=True, allocation=self._task_allocation(conn, campaign_id)[0],
                            preview=_json_load(replay["config_json"], {}).get("allocation_receipt"))
            if remove_assignee is not None:
                removal = self._allocation_without_member(conn, campaign_id, remove_assignee)
                assignees = removal["assignees"]
                reviewers_per_issue = removal["reviewers_per_issue"]
                overlap_ratio = removal["overlap_ratio"]
                cross_groups = removal["cross_groups"]
                groups = removal.get("groups")
            issued_at = int(time.time())
            if preview_token:
                try:
                    issued_at = int(preview_token.split(":")[0])
                except (ValueError, AttributeError) as exc:
                    raise CampaignConflictError("预览无效，请重新预览 / Invalid preview; preview again") from exc
                if not 0 <= time.time() - issued_at <= 600:
                    raise CampaignConflictError("预览已过期，请重新预览 / Preview expired; preview again")
            try:
                current, split, filters, old_rows, config, new_rows, preview = self._prepare_task_reallocation(
                    conn, campaign_id, assignees, reviewers_per_issue, overlap_ratio,
                    expected_revision, quota_basis, issued_at, cross_groups, groups, pairing_mode)
            except CoverageConstraintError as exc:
                if preview_token:
                    raise CampaignConflictError("预览已失效，请保留输入并重新预览 / Preview is stale; keep your inputs and preview again") from exc
                raise
            if preview_token and preview_token != preview["preview_token"]:
                raise CampaignConflictError("标注、成员或任务已变化，请保留输入并重新预览 / Work, members or task changed; keep your inputs and preview again")
            if not preview_token and (preview["completed_slots"] or preview["saved_pending_slots"]):
                raise CampaignConflictError("已有保存的任务需要先预览调整 / Preview changes before updating a task with saved work")
            if remove_assignee is not None:
                preview["removed_assignee"] = remove_assignee
            old_config = {key: current.get(key) for key in config}
            if config == old_config and not preview["changed_cases"]:
                return dict(changed=False, replayed=False, allocation=current, preview=preview)
            before = {(r["issue_id"], r["assignee"]): r for r in old_rows}
            after = {(r["issue_id"], r["assignee"]): r for r in new_rows}
            revision = expected_revision + 1
            now = utc_now()
            for pair in sorted(before.keys() | after.keys()):
                old, new = before.get(pair), after.get(pair)
                if old and new and old["assignment_kind"] == new["assignment_kind"]:
                    continue
                if old and not new:
                    conn.execute("DELETE FROM review_work_assignments WHERE split_id=? AND issue_id=? AND assignee=?",
                                 (campaign_id, *pair))
                elif old and new:
                    conn.execute("UPDATE review_work_assignments SET assignment_kind=? WHERE split_id=? AND issue_id=? AND assignee=?",
                                 (new["assignment_kind"], campaign_id, *pair))
                else:
                    conn.execute(
                        "INSERT INTO review_work_assignments(split_id,issue_id,assignee,assignment_kind,ordinal,assigned_by,assigned_at) VALUES(?,?,?,?,?,?,?)",
                        (campaign_id, *pair, new["assignment_kind"], new["ordinal"], actor, now),
                    )
                conn.execute(
                    "INSERT INTO campaign_assignment_audit(campaign_id,issue_id,action,assignment_kind,from_assignee,to_assignee,"
                    "changed_by,changed_by_source,changed_by_verified,config_revision,idempotency_key,idempotency_fingerprint,reason,changed_at)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (campaign_id, pair[0], "reassigned" if old and new else "unassigned" if old else "assigned",
                     (new or old)["assignment_kind"], pair[1] if old else "", pair[1] if new else "",
                     actor, actor_source, bool(actor_verified), revision,
                     "allocation-" + _fingerprint([idempotency_key, pair]), fingerprint,
                     "Untouched work redistributed; saved ownership retained: " + quota_basis, now),
                )
            per_issue = defaultdict(list)
            for row in new_rows:
                per_issue[row["issue_id"]].append(row)
            for change in preview["changes"]:
                removed = sorted(set(change["before"]) - set(change["after"]))
                added = sorted(set(change["after"]) - set(change["before"]))
                for old_name, new_name in zip(removed, added):
                    conn.execute(
                        "INSERT INTO review_work_assignment_changes "
                        "(split_id,issue_id,from_assignee,to_assignee,changed_by,changed_at) VALUES(?,?,?,?,?,?)",
                        (campaign_id, change["issue_id"], old_name, new_name, actor, now),
                    )
            for iid, rows in per_issue.items():
                conn.execute(
                    "UPDATE campaign_issue_members SET required_submitter_count=?,reviewers_per_issue=?,assignment_kinds_json=?,"
                    "config_revision=? WHERE campaign_id=? AND issue_id=?",
                    (len(rows), len(rows), _json(sorted({r["assignment_kind"] for r in rows})), revision, campaign_id, iid),
                )
            filters["task_allocation"] = config
            filters["allocation_request_fingerprint"] = fingerprint
            conn.execute(
                "UPDATE issue_work_splits SET filter_json=?,mode=?,overlap_ratio=?,config_revision=?,updated_by=?,updated_by_source=?,"
                "updated_by_verified=?,updated_at=? WHERE id=?",
                (_json(filters), "blind" if config["reviewers_per_issue"] > 1 else "single", config["overlap_ratio"],
                 revision, actor, actor_source, bool(actor_verified), now, campaign_id),
            )
            self._campaign_refresh_compat_assignment_snapshot(conn, campaign_id)
            # Configured reviewer count may exceed actual count for a small/zero-overlap sample.
            conn.execute("UPDATE issue_work_splits SET reviewers_per_issue=? WHERE id=?", (config["reviewers_per_issue"], campaign_id))
            self._campaign_insert_revision(
                conn, campaign_id=campaign_id, revision_no=revision, changed_by=actor,
                changed_by_source=actor_source, changed_by_verified=bool(actor_verified),
                change_source="allocation", idempotency_key=idempotency_key, allocation_receipt=preview,
            )
            dataset_id = filters.get("version_dataset_id")
            if dataset_id:
                for item in conn.execute("SELECT issue_id,binding_json FROM version_dataset_items WHERE dataset_id=?", (dataset_id,)).fetchall():
                    binding = _json_load(item["binding_json"], {})
                    if binding.get("campaign_id") != campaign_id:
                        continue
                    owners = [r["assignee"] for r in sorted(per_issue[item["issue_id"]], key=lambda r: r["assignment_kind"] != "base")]
                    binding.update(assignee=owners[0], assignees=owners)
                    conn.execute("UPDATE version_dataset_items SET binding_json=? WHERE dataset_id=? AND issue_id=?",
                                 (_json(binding), dataset_id, item["issue_id"]))
                conn.execute("UPDATE version_datasets SET revision=revision+1,updated_at=? WHERE id=?", (now, dataset_id))
            self._mark_change_topic(conn, "review")
            self._mark_labeling_change(conn)
            allocation = self._task_allocation(conn, campaign_id)[0]
        return dict(changed=True, replayed=False, allocation=allocation, preview=preview)
