"""Version task projections over physically consolidated, appendable Campaigns."""
from collections import defaultdict
import json

PREFIX='version:'


def merge_version_task_list(parents, items, *, version_only=False):
    """Keep explicit supplemental reviews beside their canonical version task."""
    parent_ids = {item['split_id'] for item in parents}
    parent_runs = {item['model_run_id'] for item in parents}
    retained = []
    for item in items:
        if item['split_id'] in parent_ids:
            continue
        same_version = item['model_run_id'] in parent_runs
        supplemental = (item.get('filter_snapshot') or {}).get('supplemental_review') is True
        if (same_version and supplemental) or (not version_only and not same_version):
            retained.append(item)
    return parents + retained


def supplemental_task_baseline_ids(db, task_id):
    """Resolve a frozen supplemental task to its registered version dataset."""
    with db.connect() as conn:
        row = conn.execute('SELECT filter_json FROM issue_work_splits WHERE id=?', (task_id,)).fetchone()
        if row is None:
            return []
        filters = json.loads(row['filter_json'] or '{}')
        if filters.get('supplemental_review') is not True:
            return []
        dataset_id = filters.get('dataset_id')
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


def task(db, dataset, *, assignee='', status='all', query='', page=1, page_size=50, detail=False):
    if status not in {'all','pending','completed'}:raise ValueError('Invalid task status')
    rows=[r for r in db.version_dataset_gallery_rows(dataset['id']) if r.get('is_target')]
    counts=defaultdict(lambda:[0,0])
    for row in rows:
        owner=(row.get('binding') or {}).get('assignee','')
        if owner:
            counts[owner][0]+=1;counts[owner][1]+=int(bool(row.get('review_submitted')))
    members=[dict(username=k,assigned_count=v[0],completed_count=v[1],pending_count=v[0]-v[1],completion_ratio=v[1]/v[0]) for k,v in sorted(counts.items())]
    assigned=sum(v[0] for v in counts.values());completed=sum(v[1] for v in counts.values())
    sources=sorted({r.get('binding',{}).get('campaign_id') for r in rows if r.get('binding',{}).get('campaign_id')})
    canonical=getattr(db,'version_campaign_id',lambda _: '')(dataset['id'])
    result=dict(split_id=canonical or PREFIX+dataset['id'],physically_merged=bool(canonical),dataset_id=dataset['id'],release_family=dataset['release_family'],kind='version_live',appendable=True,
                campaign_name=dataset['release_family'][4:],created_at=dataset['created_at'],updated_at=dataset['updated_at'],created_by='version-incremental-service',
                model_run_id=dataset['run_id'],workflow_mode='model_review_and_case_label',mode='single',reviewers_per_issue=1,overlap_ratio=0,
                lifecycle='active',is_current=True,legacy_read_only=False,total_count=len(rows),assignment_count=assigned,
                completed_count=completed,pending_count=assigned-completed,completion_ratio=completed/assigned if assigned else 0,
                members=members,baseline_ids=['version-'+dataset['release_family']],baseline_scopes=[],filter_snapshot={},change_count=0,
                source_count=len(sources))
    if detail:
        items=[]
        for row in rows:
            binding=row.get('binding') or {};owner=binding.get('assignee','')
            if assignee and owner.lower()!=assignee.lower():continue
            if query and query.lower() not in row['issue_id'].lower():continue
            submitted=bool(row.get('review_submitted'))
            if status=='completed' and not submitted or status=='pending' and submitted:continue
            items.append(dict(issue_id=row['issue_id'],assignee=owner,source_split_id=binding.get('campaign_id',''),split_model_run_id=dataset['run_id'],
                              assignment_kind='base',submitted=submitted,submitted_at=row.get('review_submitted_at',''),title='',scenario=''))
        items.sort(key=lambda r:(r['assignee'],r['issue_id']))
        result.update(items=items[(page-1)*page_size:page*page_size],page=page,page_size=page_size,page_count=max(1,(len(items)+page_size-1)//page_size),filtered_count=len(items),changes=[],source_splits=sources,
                      additions=[b for b in db.version_dataset_batches(dataset['id']) if b.get('target_added',0)>0])
    return result


def version_tasks(db, *, assignee='', model_run_id=''):
    result=[]
    for dataset in db.list_version_datasets():
        if model_run_id and dataset['run_id']!=model_run_id:continue
        item=task(db,dataset)
        if assignee and not any(m['username'].lower()==assignee.lower() for m in item['members']):continue
        result.append(item)
    return result


def version_task_detail(db, split_id, **options):
    did=split_id[len(PREFIX):] if split_id.startswith(PREFIX) else getattr(db,'version_campaign_dataset',lambda _: '')(split_id)
    dataset=next((d for d in db.list_version_datasets() if d['id']==did),None)
    return task(db,dataset,detail=True,**options) if dataset else None
