"""Authenticated RD result summary and explicit publication workflow."""
import asyncio
from typing import Literal
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from .. import rd_results as service
from ..runtime import database, settings
from ..auth import has_same_origin_mutation_marker
from ..support.common import _detail
from ..support.identity import _admin_identity, _writer_identity
from ..support.baselines import resolve_request_baseline_scopes, restrict_version_issue_ids

router = APIRouter()


class Selection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    baselines: str = Field(min_length=1, max_length=2000)
    issue_ids: list[str] = Field(min_length=1, max_length=100)
    overwrite: StrictBool = False


class Commit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    confirmed: StrictBool


class ScopeSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    baselines: str = Field(min_length=1, max_length=2000)
    q: str = Field(default='', max_length=2000)
    status: Literal['all', 'resolved', 'pending', 'conflict'] = 'all'
    overwrite: StrictBool = False


def store():
    return service.PublicationStore(settings.data_dir)


def members(request, baselines):
    if not baselines.strip():
        raise _detail(400, '请选择数据集 / Select a dataset')
    scopes = resolve_request_baseline_scopes(baselines, request=request)
    scopes = sorted(set(scopes) & set(database.active_labeling_scopes()))
    ids = restrict_version_issue_ids(baselines, request=request)
    members = database.labeling_case_issue_ids(baseline_scopes=scopes, issue_ids=ids)
    if len(members) > 20000:
        raise _detail(400, '请缩小数据集范围（最多 20000 条） / Select fewer datasets (maximum 20000 Issues)')
    return members


def selected(request, body):
    ids = body.issue_ids
    import re
    if len(ids) != len(set(ids)) or any(not re.fullmatch(r'cn[0-9]+', iid) for iid in ids):
        raise _detail(400, 'Issue ID 无效或重复 / Invalid or duplicate Issue IDs')
    if not set(ids).issubset(members(request, body.baselines)):
        raise _detail(409, 'Issue 不在当前有效范围 / Issues outside active scope')
    rows = service.local_rows(database, ids)
    if set(rows) != set(ids):
        raise _detail(409, '标注范围已变化，请刷新 / Label scope changed; refresh')
    return rows


async def run(call, *args):
    try:
        return await asyncio.to_thread(call, *args)
    except ValueError as exc:
        raise _detail(409, str(exc)) from exc
    except HTTPException:
        raise
    except Exception:
        raise _detail(503, 'RD 服务暂不可用，请重试 / RD service unavailable; retry') from None


def filtered_rows(request, baselines, q, status):
    ids = members(request, baselines)
    rows = list(service.local_rows(database, ids).values())
    if {row['issue_id'] for row in rows} != set(ids):
        raise _detail(409, '标注范围已变化，请刷新 / Label scope changed; refresh')
    rows = [r for r in rows if q.strip().lower() in r['issue_id'].lower()]
    counts = {'total': len(rows), 'resolved': 0, 'pending': 0, 'conflict': 0}
    for row in rows:
        key = 'resolved' if row['state'] == 'resolved' and row['label'] in service.VALUES else 'conflict' if row['state'] in {'conflict', 'stale'} else 'pending'
        row['group'] = key
        counts[key] += 1
    return [r for r in rows if status == 'all' or r['group'] == status], counts


@router.get('/api/rd-results')
async def summary(request: Request, baselines: str = '', q: str = '', status: str = 'all', page: int = 1, page_size: int = 20):
    await asyncio.to_thread(_writer_identity, request)
    if status not in {'all', 'resolved', 'pending', 'conflict'}:
        raise _detail(400, '筛选无效 / Invalid filter')
    if page_size not in {10, 20, 50, 100}:
        raise _detail(400, '每页数量无效 / Invalid page size')
    def load():
        rows, counts = filtered_rows(request, baselines, q, status)
        pages = max(1, (len(rows) + page_size - 1) // page_size)
        current = min(max(page, 1), pages)
        return dict(items=rows[(current - 1)*page_size:current*page_size], counts=counts, total=len(rows), page=current, pages=pages, page_size=page_size,
                    write_enabled=settings.trail_rd_write_enabled)
    return await run(load)


@router.post('/api/rd-results/preview-scope')
async def preview_scope(request: Request, body: ScopeSelection):
    actor = await asyncio.to_thread(_admin_identity, request)
    if not has_same_origin_mutation_marker(request):
        raise _detail(403, '请求标记缺失 / Request marker required')
    def load():
        rows, _ = filtered_rows(request, body.baselines, body.q, body.status)
        candidates = {r['issue_id']: r for r in rows if r['group'] == 'resolved'}
        remote = service.read_remote(service.adapter(settings.ra_auto_triage_root), list(candidates)) if candidates else {}
        scope = dict(total=len(rows), blocked=len(rows) - len(candidates), q=body.q, status=body.status)
        return store().preview(actor.username, candidates, remote, body.overwrite, body.baselines, scope=scope)
    return await run(load)


@router.post('/api/rd-results/status')
async def remote_status(request: Request, body: Selection):
    await asyncio.to_thread(_writer_identity, request)
    def load():
        rows = selected(request, body)
        remote = service.read_remote(service.adapter(settings.ra_auto_triage_root), body.issue_ids)
        return {'items': [dict(issue_id=iid, current=remote[iid][service.FIELD], status=service.classify(row, remote[iid])) for iid, row in rows.items()]}
    return await run(load)


@router.post('/api/rd-results/preview')
async def preview(request: Request, body: Selection):
    actor = await asyncio.to_thread(_admin_identity, request)
    if not has_same_origin_mutation_marker(request):
        raise _detail(403, '请求标记缺失 / Request marker required')
    def load():
        rows = selected(request, body)
        remote = service.read_remote(service.adapter(settings.ra_auto_triage_root), body.issue_ids)
        return store().preview(actor.username, rows, remote, body.overwrite, body.baselines)
    return await run(load)


@router.post('/api/rd-results/commit')
async def commit(request: Request, body: Commit):
    actor = await asyncio.to_thread(_admin_identity, request)
    if not has_same_origin_mutation_marker(request) or not body.confirmed or not settings.trail_rd_write_enabled:
        raise _detail(403, 'RD 写入未启用或未确认 / RD writing disabled or not confirmed')
    def execute():
        record = store().get(body.operation_id)
        return store().commit(body.operation_id, actor.username, database,
                              service.adapter(settings.ra_auto_triage_root), lambda: set(members(request, record['baselines'])))
    return await run(execute)


@router.get('/api/rd-results/operations/{operation_id}')
async def operation(request: Request, operation_id: str):
    await asyncio.to_thread(_admin_identity, request)
    return await run(lambda: store().receipt(operation_id))


@router.get('/api/rd-results/operations')
async def operations(request: Request):
    await asyncio.to_thread(_admin_identity, request)
    def load():
        records = []
        for path in store().root.glob('*.json'):
            record = store().receipt(path.stem)
            if record['state'] != 'preview':
                records.append({k: record[k] for k in ('id', 'actor', 'created_at', 'state')})
        return {'items': sorted(records, key=lambda r: r['created_at'], reverse=True)[:30]}
    return await run(load)
