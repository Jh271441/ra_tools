"""Snapshot-bound, stateless preview for protected task redistribution."""
import time
from collections import Counter, defaultdict

from ..allocation_coverage import CoverageConstraintError, coverage_summary, plan_cross_coverage
from ..group_allocation import group_history, group_rules, grouped_config, grouped_preview, normalize_groups, normalize_pairing_mode, plan_groups
from .allocation_protection import AllocationProtectionMixin
from .campaigns import CampaignConflictError, CampaignReadOnlyError, _fingerprint
from ..task_allocation_policy import percentage_weights
from ..task_reallocation import reallocate_slots


class AllocationPreviewMixin(AllocationProtectionMixin):
    @staticmethod
    def _group_roles(current):
        if current["role_required"]:
            return {u["username"]: u["human_role"] for u in current["eligible_members"]}
        return None

    def _group_history(self, current, rows, evidence):
        return group_history({**current, "group_eligible_names": {u["username"] for u in current["eligible_members"]}},
                             rows, evidence, roles=self._group_roles(current))

    def _load_reallocation_snapshot(self, conn, campaign_id, *, expected_revision, quota_basis):
        current, split, filters, old_rows = self._task_allocation(conn, campaign_id)
        if not current["editable"]:
            raise CampaignReadOnlyError("只有当前有效任务可以修改分配 / Only active tasks can be edited")
        if type(expected_revision) is not int or current["expected_revision"] != expected_revision:
            raise CampaignConflictError("任务分配已更新，请重新预览 / Allocation changed; preview again")
        if quota_basis not in {"remaining", "total"}:
            raise ValueError("分配基数无效 / Invalid allocation basis")
        evidence = self._allocation_protection(conn, split, old_rows)
        if not evidence["members"]:
            raise ValueError("任务没有 Case / Task has no Cases")
        all_roles = (
            {r["username"]: r["role"] for r in conn.execute("SELECT username,role FROM human_user_roles").fetchall()}
            if current["role_required"]
            else None
        )
        return current, split, filters, old_rows, evidence, all_roles

    def _take_over_pending(self, current, rows, evidence, recipient):
        if current["purpose"] != "model_review" or current["role_required"]:
            raise ValueError("此入口适用于普通复核任务 / This action is for review tasks without role-based assignment")
        eligible = {u["username"]: u for u in current["eligible_members"]}
        if recipient not in eligible:
            raise ValueError("当前账号没有接手资格 / Your account is not an eligible reviewer")
        groups, history = self._group_history(current, rows, evidence)
        placed = {m["issue_id"]: dict(history.get(m["issue_id"], {})) for m in evidence["members"]}
        rules = group_rules(current["cross_groups"], history)
        pinned = {(iid, m["name"]) for rule in rules for iid in rule.get("issue_ids", [])
                  for m in rule["members"]}
        occupied = {r["issue_id"] for r in rows if r["assignee"] == recipient}
        by_group = {g["group_id"]: g for g in groups}
        memberships = {gid: {m["name"] for m in g["members"]} for gid, g in by_group.items()}
        projected = []
        remaining = []
        for row in rows:
            iid, owner = row["issue_id"], row["assignee"]
            pair = (iid, owner)
            projected.append(row)
            if pair in evidence["completed"]:
                continue
            gid = next((g for g, user in history.get(iid, {}).items() if user == owner), None)
            if pair in evidence["model_submitted"]:
                reason = "label_pending"
            elif pair in evidence["protected"]:
                reason = "saved"
            elif owner == recipient:
                reason = "mine"
            elif iid in occupied or (iid, recipient) in evidence["forbidden"]:
                reason = "other_slot"
            elif gid is None or pair in pinned or (len(placed[iid]) > 1 and current["pairing_mode"] == "paired"):
                reason = "pairing"
            else:
                reason = "transfer"
                projected[-1] = {**row, "assignee": recipient}
                placed[iid][gid] = recipient
                occupied.add(iid)
                if recipient not in memberships[gid]:
                    group = by_group[gid]
                    group["members"] = [*group["members"], dict(name=recipient, review_percent=0)]
                    memberships[gid].add(recipient)
            remaining.append(dict(issue_id=iid, owner=owner, reason=reason))
        # Preserve configured coverage and future weights. This action changes
        # the current binding only, with at most one seat per person per Issue.
        config = grouped_config(groups, placed, rules, current["quota_basis"], pairing_mode=current["pairing_mode"])
        preview = grouped_preview(groups, rows, projected, placed, evidence, old_placed=history)
        preview["remaining_assignments"] = remaining
        return config, projected, preview

    def _compute_task_reallocation(
        self, current, split, filters, old_rows, evidence,
        assignees, reviewers_per_issue, overlap_ratio, expected_revision,
        quota_basis, issued_at, cross_groups=None, groups=None,
        pairing_mode=None, *, all_roles=None, takeover_by=None,
    ):
        if takeover_by:
            config, new_rows, preview = self._take_over_pending(current, old_rows, evidence, takeover_by)
            preview.update(expected_revision=expected_revision, expires_at=issued_at + 600,
                           preview_token=str(issued_at) + ":" + _fingerprint(
                               [evidence["snapshot"], takeover_by, config, new_rows, issued_at]))
            return current, split, filters, old_rows, config, new_rows, preview
        if groups is not None:
            groups = normalize_groups(groups, {u["username"] for u in current["eligible_members"]})
            mode = normalize_pairing_mode(current.get("pairing_mode") if pairing_mode is None else pairing_mode)
            prior, history = self._group_history(current, old_rows, evidence)
            rules = cross_groups
            if rules is None:
                ids = {group["group_id"] for group in groups}
                rules = [rule for rule in group_rules(current["cross_groups"], history)
                         if all(person["group_id"] in ids for person in rule["members"])]
            new_rows, placed, rules = plan_groups(
                [m["issue_id"] for m in evidence["members"]], groups, rules, seed=int(split["seed"] or 0),
                old_groups=prior, history=history, old_rows=old_rows, evidence=evidence, basis=quota_basis,
                pairing_mode=mode,
            )
            config = grouped_config(groups, placed, rules, quota_basis, pairing_mode=mode)
            preview = grouped_preview(groups, old_rows, new_rows, placed, evidence, old_placed=history)
            preview.update(quota_basis=quota_basis, cross_groups=rules, pairing_mode=mode, expires_at=issued_at + 600,
                           expected_revision=expected_revision,
                           preview_token=str(issued_at) + ":" + _fingerprint([evidence["snapshot"], config, new_rows, issued_at]))
            return current, split, filters, old_rows, config, new_rows, preview
        if current.get("groups"):
            raise ValueError("此任务使用分组配置，请通过分组编辑器调整 / This task uses allocation groups; edit them in the group editor")
        config = self._validate_task_allocation(current, assignees, reviewers_per_issue, overlap_ratio,
                                                protected=evidence["has_evidence"])
        config["quota_basis"] = quota_basis
        coverage_changed = any(config[k] != current[k] for k in ("reviewers_per_issue", "overlap_ratio"))
        counts = Counter(row["issue_id"] for row in old_rows)
        locked = set(counts) if current["role_required"] and evidence["has_evidence"] else evidence["coverage_locked"]
        coverage_before = coverage_summary(counts, locked)
        if coverage_changed and coverage_before["locked_cases"] == len(counts):
            raise CoverageConstraintError("所有 Case 的交叉覆盖已受保护 / Cross-review coverage is protected on every Case")
        groups = current["cross_groups"] if cross_groups is None else cross_groups
        config["cross_groups"] = []
        required_counts = pinned = None
        templates = old_rows
        if coverage_changed and not evidence["has_evidence"] and groups == []:
            templates = self._plan_task_allocation(
                None, config, [m["issue_id"] for m in evidence["members"]],
                seed=int(split["seed"] or 0), role_required=current["role_required"], roles=all_roles)
            old_groups = defaultdict(list)
            new_groups = defaultdict(list)
            for row in old_rows:
                old_groups[row["issue_id"]].append(row)
            for row in templates:
                new_groups[row["issue_id"]].append(row)
            # For a coverage edit before work starts, fill the new positions
            # from the existing owners first. The planner then meets new quotas.
            for iid, group in new_groups.items():
                old = sorted(old_groups[iid], key=lambda r: (r["assignment_kind"] != "base", r["assignee"]))
                candidates = list(dict.fromkeys([r["assignee"] for r in old] + [r["assignee"] for r in group]))
                for row, owner in zip(sorted(group, key=lambda r: r["assignment_kind"] != "base"), candidates):
                    row["assignee"] = owner
        people = config["assignees"]
        if any("review_percent" in p for p in people):
            weights = percentage_weights(people)
        elif any(p["count"] is not None for p in people):
            if evidence["has_evidence"]:
                raise ValueError("接续任务请使用均分或个人比例 / Use equal shares or personal percentages for tasks with saved work")
            quota_rows = self._plan_task_allocation(
                None, config, [m["issue_id"] for m in evidence["members"]],
                seed=int(split["seed"] or 0), role_required=current["role_required"], roles=all_roles)
            weights = {p["name"]: sum(r["assignee"] == p["name"] for r in quota_rows) for p in people}
        else:
            weights = {p["name"]: 1 for p in people}
        if not sum(weights.values()):
            raise ValueError("至少需要一名接收人员 / At least one recipient is required")
        if groups != [] or (coverage_changed and evidence["has_evidence"]):
            target = (round(len(counts) * config["overlap_ratio"]) if coverage_changed
                      else coverage_before["cross_cases"])
            required_counts, pinned, config["cross_groups"] = plan_cross_coverage(
                counts, target=target, reviewers=config["reviewers_per_issue"], seed=int(split["seed"] or 0),
                groups=groups, recipients={name for name, weight in weights.items() if weight > 0},
                protected=evidence["protected"], locked=locked,
            )
        roles = {u["username"]: u["human_role"] for u in current["eligible_members"]} if current["role_required"] else None
        # For newly added positions, an unchanged existing author's captured
        # role is available; new rows take the recipient's current valid role.
        captured = dict(evidence["captured_roles"])
        if roles and coverage_changed:
            for row in templates:
                captured.setdefault((row["issue_id"], row["assignee"]), roles.get(row["assignee"]))
        preserve_primary = (coverage_changed and required_counts is None and not roles
            and {p["name"] for p in people} == {p["name"] for p in current["assignees"]}
            and all(p.get("count") is None and "review_percent" not in p for p in people + current["assignees"]))
        planning_protected = (evidence["protected"] | {(r["issue_id"], r["assignee"]) for r in templates
            if r["assignment_kind"] == "base"}) if preserve_primary else evidence["protected"]
        new_rows, summary = reallocate_slots(
            templates, weights, basis="total" if preserve_primary else quota_basis, protected=planning_protected,
            completed=evidence["completed"], roles=roles, captured_roles=captured,
            forbidden=evidence["forbidden"], required_counts=required_counts, pinned_members=pinned,
            fixed_quotas={p["name"]: p["count"] for p in people if p["count"] is not None} if pinned else None)
        before = {(r["issue_id"], r["assignee"]): r for r in old_rows}
        after = {(r["issue_id"], r["assignee"]): r for r in new_rows}
        before_counts = Counter(p for _, p in before)
        incoming = Counter(p for _, p in after.keys() - before.keys())
        outgoing = Counter(p for _, p in before.keys() - after.keys())
        cross_after = Counter(r["assignee"] for r in new_rows if r["assignment_kind"] == "cross")
        for item in summary:
            name = item["name"]
            item.update(before=before_counts[name], incoming=incoming[name], outgoing=outgoing[name],
                        cross_after=cross_after[name], base_after=item["total_after"] - cross_after[name],
                        requested_percent=next((p.get("review_percent") for p in people if p["name"] == name), None))
            if preserve_primary:
                item.update(saved_pending=0, movable_after=item["total_after"], pending_after=item["total_after"])
        old_by_issue, new_by_issue = defaultdict(list), defaultdict(list)
        for iid, p in before:
            old_by_issue[iid].append(p)
        for iid, p in after:
            new_by_issue[iid].append(p)
        changes = [dict(issue_id=iid, before=sorted(old_by_issue[iid]), after=sorted(new_by_issue[iid]))
                   for iid in sorted(old_by_issue) if set(old_by_issue[iid]) != set(new_by_issue[iid])]
        preview = dict(
            quota_basis=quota_basis, members=summary, changes=changes,
            total_slots=len(new_rows), completed_slots=len(evidence["completed"]),
            saved_pending_slots=len(evidence["protected"]) - len(evidence["completed"]),
            movable_slots=len(new_rows) - len(evidence["protected"]),
            moved_slots=sum(incoming.values()), changed_cases=len(changes),
            coverage_before=coverage_before,
            coverage_after=coverage_summary(Counter(iid for iid, _ in after), locked),
            cross_groups=config["cross_groups"],
            expires_at=issued_at + 600, expected_revision=expected_revision,
        )
        preview["preview_token"] = str(issued_at) + ":" + _fingerprint([
            evidence["snapshot"], config, new_rows, issued_at,
        ])
        return current, split, filters, old_rows, config, new_rows, preview

    def _prepare_task_reallocation(self, conn, campaign_id, assignees, reviewers_per_issue,
                                   overlap_ratio, expected_revision, quota_basis, issued_at, cross_groups=None,
                                   groups=None, pairing_mode=None, takeover_by=None):
        current, split, filters, old_rows, evidence, all_roles = self._load_reallocation_snapshot(
            conn, campaign_id, expected_revision=expected_revision, quota_basis=quota_basis,
        )
        return self._compute_task_reallocation(
            current, split, filters, old_rows, evidence,
            assignees, reviewers_per_issue, overlap_ratio, expected_revision,
            quota_basis, issued_at, cross_groups, groups, pairing_mode,
            all_roles=all_roles, takeover_by=takeover_by,
        )

    def preview_campaign_allocation(self, *, campaign_id, assignees, reviewers_per_issue,
                                    overlap_ratio, expected_revision, quota_basis="remaining", cross_groups=None,
                                    groups=None, pairing_mode=None, takeover_by=None):
        """Compute a snapshot-bound preview without holding global write locks.

        Optimistic validation in ``update_campaign_allocation`` re-verifies
        ``expected_revision`` and the signed ``preview_token`` under write locks
        before mutating any row.
        """
        campaign_id = self.resolve_version_campaign(str(campaign_id))
        with self.connect() as conn:
            current, split, filters, old_rows, evidence, all_roles = self._load_reallocation_snapshot(
                conn, campaign_id, expected_revision=expected_revision, quota_basis=quota_basis,
            )
        return self._compute_task_reallocation(
            current, split, filters, old_rows, evidence,
            assignees, reviewers_per_issue, overlap_ratio, expected_revision,
            quota_basis, int(time.time()), cross_groups, groups, pairing_mode,
            all_roles=all_roles, takeover_by=takeover_by,
        )[-1]
