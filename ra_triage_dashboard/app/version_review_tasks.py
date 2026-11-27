"""Version task projections over physically consolidated, appendable Campaigns."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json

PREFIX='version:'
COLLECTION_ACTIVE_WINDOW_DAYS = 2


def _parse_iso_utc(value):
    text = str(value or '').strip()
    if not text:
        return None
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _dataset_target_rows(db, dataset_id):
    fn = db.version_dataset_gallery_rows
    try:
        rows = fn(dataset_id, targets_only=True)
    except TypeError:
        rows = fn(dataset_id)
    return [r for r in rows if r.get('is_target')]


def _version_last_target_added_at(db, dataset, *, preloaded_batches=None):
    batches = preloaded_batches
    if batches is None:
        batches_fn = getattr(db, 'version_dataset_batches', None)
        if callable(batches_fn):
            try:
                batches = batches_fn(dataset['id']) or []
            except Exception:
                batches = []
    if batches:
        best_dt = None
        best_raw = ''
        for batch in batches:
            try:
                added = int(batch.get('target_added') or 0)
            except (TypeError, ValueError):
                added = 0
            if added <= 0:
                continue
            raw = str(batch.get('created_at') or '').strip()
            parsed = _parse_iso_utc(raw)
            if parsed is not None and (best_dt is None or parsed > best_dt):
                best_dt = parsed
                best_raw = raw
            elif not best_raw and raw:
                best_raw = raw
        if best_raw:
            return best_raw
    return str(dataset.get('updated_at') or dataset.get('created_at') or '')


def _is_actively_appending(last_target_added_at, *, now=None, window_days=COLLECTION_ACTIVE_WINDOW_DAYS):
    parsed = _parse_iso_utc(last_target_added_at)
    if parsed is None:
        return True
    current = now if now is not None else datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return (current - parsed) <= timedelta(days=window_days)


def _task_sort_epoch(item):
    raw = (
        item.get('last_target_added_at') or item.get('updated_at') or item.get('created_at')
        if item.get('appendable')
        else item.get('created_at')
    )
    parsed = _parse_iso_utc(raw)
    return parsed.timestamp() if parsed is not None else None


def _version_family_rank(item):
    family = str(item.get('release_family') or '').strip()
    if family.isdigit():
        return (1, int(family), family)
    if family:
        return (1, 0, family)
    return (0, 0, '')


def _sort_version_parents(parents):
    if not parents or not any(item.get('release_family') for item in parents):
        return list(parents)
    return [
        item for _, item in sorted(
            enumerate(parents),
            key=lambda pair: (_version_family_rank(pair[1]), -pair[0]),
            reverse=True,
        )
    ]


def _sort_items_by_recency(items):
    epochs = [_task_sort_epoch(item) for item in items]
    if not any(epoch is not None for epoch in epochs):
        return list(items)
    return [
        item for _, item in sorted(
            enumerate(items),
            key=lambda pair: (epochs[pair[0]] is not None, epochs[pair[0]] or 0.0, -pair[0]),
            reverse=True,
        )
    ]


def merge_version_task_list(parents, items, *, version_only=False, manual_only=False):
    """Show migrated historical joint tasks after ordinary manual and version tasks."""
    parent_ids = {item['split_id'] for item in parents}
    parent_runs = {item['model_run_id'] for item in parents}
    retained = []
    for item in items:
        if item['split_id'] in parent_ids:
            continue
        same_version = item['model_run_id'] in parent_runs
        snapshot = item.get('filter_snapshot') or {}
        supplemental = snapshot.get('supplemental_review') is True
        manual_created = snapshot.get('manual_task') is True
        if manual_only:
            if (not same_version) or supplemental or manual_created:
                retained.append(item)
        elif version_only:
            if same_version and supplemental:
                retained.append(item)
        else:
            if (same_version and (supplemental or manual_created)) or (not same_version):
                retained.append(item)
    historical = []
    ordinary = []
    for item in retained:
        if item.get('workflow_mode') == 'model_review_and_case_label' and (
            item.get('source_split_id') or (item.get('filter_snapshot') or {}).get('merged_review_sources')
        ):
            historical.append(item)
        else:
            ordinary.append(item)
    ordered_retained = _sort_items_by_recency(ordinary)
    if manual_only:
        return ordered_retained + historical
    ordered_parents = _sort_version_parents(parents)
    if not ordered_retained:
        return ordered_parents + historical
    if not ordered_parents:
        return ordered_retained + historical
    # Stable two-pointer merge: automatic version tasks strictly keep version descending
    # order, manual tasks strictly keep recency descending order, and brand-new manual
    # tasks float above older versions without ever scrambling two versions.
    parent_epochs = [_task_sort_epoch(item) for item in ordered_parents]
    retained_epochs = [_task_sort_epoch(item) for item in ordered_retained]
    merged = []
    pi = 0
    ri = 0
    while pi < len(ordered_parents) and ri < len(ordered_retained):
        pe = parent_epochs[pi]
        re = retained_epochs[ri]
        if re is not None and (pe is None or re >= pe):
            merged.append(ordered_retained[ri])
            ri += 1
        else:
            merged.append(ordered_parents[pi])
            pi += 1
    if pi < len(ordered_parents):
        merged.extend(ordered_parents[pi:])
    if ri < len(ordered_retained):
        merged.extend(ordered_retained[ri:])
    return merged + historical


def supplemental_task_baseline_ids(db, task_id):
    """Resolve a frozen supplemental task to its registered version dataset."""
    return version_task_baseline_ids(db, task_id, supplemental_only=True)


def version_task_baseline_ids(db, task_id, *, supplemental_only=False):
    """Validate frozen membership for explicit supplemental or canonical tasks."""
    with db.connect() as conn:
        row = conn.execute('SELECT filter_json FROM issue_work_splits WHERE id=?', (task_id,)).fetchone()
        if row is None:
            return []
        filters = json.loads(row['filter_json'] or '{}')
        if filters.get('supplemental_review') is True:
            dataset_id = filters.get('dataset_id')
        elif not supplemental_only and filters.get('version_live') is True:
            dataset_id = filters.get('version_dataset_id')
            if not dataset_id or (db.version_campaign_id(dataset_id) != task_id and not conn.execute(
                'SELECT 1 FROM human_version_tasks WHERE dataset_id=? AND campaign_id=?', (dataset_id, task_id)).fetchone()):
                return []
        else:
            return []
        version = conn.execute('SELECT release_family FROM version_datasets WHERE id=?', (dataset_id,)).fetchone()
        if version is None:
            return []
        coverage = conn.execute('''
            SELECT COUNT(*) AS member_count,
                   SUM(CASE WHEN item.issue_id IS NULL THEN 1 ELSE 0 END) AS outside_count
            FROM campaign_issue_members member
            LEFT JOIN version_dataset_items item
              ON item.dataset_id=? AND item.issue_id=member.issue_id
            WHERE member.campaign_id=?
        ''', (dataset_id, task_id)).fetchone()
        if not coverage['member_count'] or coverage['outside_count']:
            raise ValueError('复核任务成员超出版本数据集 / Review task members outside version dataset')
        return ['version-' + version['release_family']]


def task(db, dataset, *, assignee='', status='all', query='', page=1, page_size=50, detail=False, campaign=None, preloaded_rows=None, preloaded_batches=None):
    if status not in {'all','pending','completed'}:raise ValueError('Invalid task status')
    rows=[r for r in (preloaded_rows if preloaded_rows is not None else _dataset_target_rows(db, dataset['id'])) if r.get('is_target')]
    if campaign:
        rows=[r for r in rows if r.get('binding',{}).get('campaign_id')==campaign['campaign_id']]
    def reviewers(row):
        return row.get('reviewers') if 'reviewers' in row else [dict(username=row.get('binding',{}).get('assignee',''),submitted=bool(row.get('review_submitted')),submitted_at=row.get('review_submitted_at',''))]
    counts=defaultdict(lambda:[0,0])
    for row in rows:
        for reviewer in reviewers(row):
            owner=reviewer['username']
            if owner:
                counts[owner][0]+=1;counts[owner][1]+=int(reviewer['submitted'])
    members=[dict(username=k,assigned_count=v[0],completed_count=v[1],pending_count=v[0]-v[1],completion_ratio=v[1]/v[0]) for k,v in sorted(counts.items())]
    assigned=sum(v[0] for v in counts.values());completed=sum(v[1] for v in counts.values())
    sources=sorted({r.get('binding',{}).get('campaign_id') for r in rows if r.get('binding',{}).get('campaign_id')})
    canonical=campaign['campaign_id'] if campaign else getattr(db,'version_campaign_id',lambda _: '')(dataset['id'])
    last_added=_version_last_target_added_at(db, dataset, preloaded_batches=preloaded_batches)
    actively_appending=_is_actively_appending(last_added)
    result=dict(split_id=canonical or PREFIX+dataset['id'],physically_merged=bool(canonical),dataset_id=dataset['id'],release_family=dataset['release_family'],kind='version_live',appendable=True,
                last_target_added_at=last_added,actively_appending=actively_appending,collection_status='appending' if actively_appending else 'collected',
                campaign_name=dataset['release_family'][4:],created_at=dataset['created_at'],updated_at=dataset['updated_at'],created_by='version-incremental-service',
                model_run_id=dataset['run_id'],workflow_mode='model_review_and_case_label',mode='single',reviewers_per_issue=1,overlap_ratio=0,
                lifecycle='active',is_current=True,legacy_read_only=False,total_count=len(rows),assignment_count=assigned,
                completed_count=completed,pending_count=assigned-completed,completion_ratio=completed/assigned if assigned else 0,
                members=members,baseline_ids=['version-'+dataset['release_family']],baseline_scopes=[],filter_snapshot={},change_count=0,
                source_count=len(sources))
    if campaign:
        sampling=campaign['cohort']=='sampling'
        result.update(role_cohort=campaign['cohort'],campaign_name=dataset['release_family'][4:]+' · '+('Sampling' if sampling else 'Low confidence'),
                      mode=campaign.get('mode', 'blind' if sampling else 'single'),
                      reviewers_per_issue=campaign.get('reviewers_per_issue', 2 if sampling else 1),
                      overlap_ratio=campaign.get('overlap_ratio', 1 if sampling else 0),
                      filter_snapshot=dict(version_live=True,version_dataset_id=dataset['id'],role_cohort=campaign['cohort']))
    if canonical:
        with db.connect() as conn:
            config = conn.execute("SELECT * FROM issue_work_splits WHERE id=?", (canonical,)).fetchone()
            if config:
                raw_cfg = dict(config)
                for key in ("mode", "reviewers_per_issue", "overlap_ratio", "lifecycle", "legacy_read_only", "config_revision"):
                    if key in raw_cfg:
                        result[key] = raw_cfg[key]
                result["is_current"] = raw_cfg["lifecycle"] == "active" and not raw_cfg["legacy_read_only"]
                groups = (json.loads(raw_cfg.get("filter_json") or "{}").get("task_allocation") or {}).get("groups") or []
                if groups:
                    result["allocation_group_count"] = len(groups)
                    active_by_issue = defaultdict(list)
                    for grp in groups:
                        for iid, owner in (grp.get("assignments") or {}).items():
                            if owner:
                                active_by_issue[iid].append(owner)
                    if active_by_issue:
                        done_by_person = defaultdict(int)
                        active_by_person = defaultdict(int)
                        pending_by_person = defaultdict(int)
                        active_total = 0
                        active_completed = 0
                        for row in rows:
                            iid = row["issue_id"]
                            revs = {r["username"]: bool(r["submitted"]) for r in reviewers(row) if r.get("username")}
                            for owner, sub in revs.items():
                                done_by_person[owner] += int(sub)
                            act_owners = active_by_issue.get(iid, [])
                            if act_owners:
                                for owner in act_owners:
                                    active_by_person[owner] += 1
                                    active_total += 1
                                    if revs.get(owner):
                                        active_completed += 1
                                    else:
                                        pending_by_person[owner] += 1
                            elif len(groups) == 1:
                                active_total += 1
                                active_completed += int(any(revs.values()))
                        all_owners = sorted(set(done_by_person) | set(active_by_person))
                        members = [
                            dict(
                                username=k,
                                assigned_count=active_by_person[k],
                                completed_count=done_by_person[k],
                                pending_count=pending_by_person[k],
                                extra_completed_count=max(0, done_by_person[k] - (active_by_person[k] - pending_by_person[k])),
                                completion_ratio=(
                                    1.0 if active_by_person[k] == 0 and done_by_person[k] > 0
                                    else min(1.0, done_by_person[k] / active_by_person[k]) if active_by_person[k]
                                    else 0.0
                                ),
                            )
                            for k in all_owners
                            if active_by_person[k] > 0 or done_by_person[k] > 0
                        ]
                        result.update(
                            members=members,
                            assignment_count=active_total,
                            completed_count=active_completed,
                            pending_count=max(0, active_total - active_completed),
                            extra_completed_count=max(0, sum(done_by_person.values()) - active_completed),
                            completion_ratio=active_completed / active_total if active_total else 0,
                        )
                queues = db._review_overlap_queues(conn, [canonical], assigned_only=False)[canonical]
                target_ids = {row["issue_id"] for row in rows}
                queues = {key: [iid for iid in ids if iid in target_ids] for key, ids in queues.items()}
                result.update(conflict_count=len(queues["conflict_issue_ids"]), **queues)
    if detail:
        items=[]
        for row in rows:
            binding=row.get('binding') or {}
            for reviewer in reviewers(row):
                owner=reviewer['username']
                if assignee and owner.lower()!=assignee.lower():continue
                if query and query.lower() not in row['issue_id'].lower():continue
                submitted=reviewer['submitted']
                if status=='completed' and not submitted or status=='pending' and submitted:continue
                items.append(dict(issue_id=row['issue_id'],assignee=owner,source_split_id=binding.get('campaign_id',''),split_model_run_id=dataset['run_id'],
                                  assignment_kind='base',submitted=submitted,submitted_at=reviewer['submitted_at'],title='',scenario=''))
        items.sort(key=lambda r:(r['assignee'],r['issue_id']))
        result.update(items=items[(page-1)*page_size:page*page_size],page=page,page_size=page_size,page_count=max(1,(len(items)+page_size-1)//page_size),filtered_count=len(items),changes=[],source_splits=sources,
                      additions=[b for b in db.version_dataset_batches(dataset['id']) if b.get('target_added',0)>0])
    return result


def version_tasks(db, *, assignee='', model_run_id='', lifecycle='current'):
    from .db_parts.task_lifecycle import TERMINAL_TASK_LIFECYCLES, normalize_task_lifecycle
    lifecycle = normalize_task_lifecycle(lifecycle)
    result=[]
    batches_fn = getattr(db, 'version_dataset_batches', None)
    for dataset in db.list_version_datasets():
        if model_run_id and dataset['run_id']!=model_run_id:continue
        campaigns=getattr(db,'role_version_campaigns',lambda _: [])(dataset['id']) or [None]
        preloaded_rows=_dataset_target_rows(db, dataset['id'])
        preloaded_batches=None
        if callable(batches_fn):
            try:
                preloaded_batches = batches_fn(dataset['id']) or []
            except Exception:
                preloaded_batches = []
        for campaign in campaigns:
            item=task(db,dataset,campaign=campaign,preloaded_rows=preloaded_rows,preloaded_batches=preloaded_batches)
            terminal = item['lifecycle'] in TERMINAL_TASK_LIFECYCLES
            if lifecycle == 'current' and terminal or lifecycle == 'history' and not terminal:
                continue
            if lifecycle not in {'current', 'history', 'all'} and item['lifecycle'] != lifecycle:
                continue
            if assignee and not any(m['username'].lower()==assignee.lower() for m in item['members']):continue
            result.append(item)
    return result


def version_task_detail(db, split_id, **options):
    did=split_id[len(PREFIX):] if split_id.startswith(PREFIX) else getattr(db,'version_campaign_dataset',lambda _: '')(split_id)
    dataset=next((d for d in db.list_version_datasets() if d['id']==did),None)
    if not dataset:return None
    campaigns=getattr(db,'role_version_campaigns',lambda _: [])(dataset['id'])
    campaign=next((c for c in campaigns if c['campaign_id']==split_id),None)
    return task(db,dataset,detail=True,campaign=campaign,**options)
