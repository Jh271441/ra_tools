"""Authenticated RD result summary and explicit publication workflow."""
import asyncio
import re
from typing import Literal
from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StrictBool, validator

from .. import rd_results as service
from ..runtime import database, settings
from ..auth import has_same_origin_mutation_marker
from ..support.common import _detail
from ..support.identity import _admin_identity, _writer_identity
from ..support.baselines import resolve_request_baseline_scopes, restrict_version_issue_ids
from ..support.baselines import resolve_request_baseline_ids
from ..version_workbench import te_snapshot
from ..te_correction_source import TEObservationStore, merge_observations
from ..label_publication_inputs import filter_issue_rows, parse_te_xlsx, MAX_QUERY_CHARS
from ..contracts import MAX_UPLOAD_BYTES
from ..upload_limits import read_upload_limited, UploadLimitExceeded

router = APIRouter()
PublicationMode = Literal['rd', 'te-correction']


class StrictBody(BaseModel):
    # Config is supported by both deployed Pydantic 1 and workstation Pydantic 2.
    class Config:
        extra = 'forbid'


class Selection(StrictBody):
    baselines: str = Field(min_length=1, max_length=2000)
    issue_ids: list[str]
    overwrite: StrictBool = False
    mode: PublicationMode = 'rd'

    @validator('issue_ids')
    def bounded_issue_ids(cls, value):
        if not 1 <= len(value) <= 100:
            raise ValueError('请选择 1 到 100 条 Issue / Select 1 to 100 Issues')
        return value


class Commit(StrictBody):
    operation_id: str
    confirmed: StrictBool

    @validator('operation_id')
    def valid_operation_id(cls, value):
        if not re.fullmatch(r'[0-9a-f]{32}', value):
            raise ValueError('操作 ID 无效 / Invalid operation ID')
        return value


class ScopeSelection(StrictBody):
    baselines: str = Field(min_length=1, max_length=2000)
    q: str = Field(default='', max_length=MAX_QUERY_CHARS)
    status: Literal['all', 'resolved', 'pending', 'conflict', 'same', 'blocked'] = 'all'
    overwrite: StrictBool = False
    mode: PublicationMode = 'rd'
    excluded_issue_ids: list[str] = Field(default_factory=list)

    @validator('excluded_issue_ids')
    def valid_exclusions(cls, value):
        if len(value) > 20000 or len(value) != len(set(value)) or any(not re.fullmatch(r'cn[0-9]+', iid) for iid in value):
            raise ValueError('排除项无效 / Invalid exclusions')
        return value


class TERefresh(StrictBody):
    baselines: str = Field(min_length=1, max_length=2000)


def store(actor=None):
    def refreshed(record, refresh):
        if record.get('mode') == service.TE_MODE:
            te_observation_store().record_readback(record, refresh)
    return service.PublicationStore(settings.data_dir, audit_database=database, actor=actor, on_refreshed=refreshed)


def validate_scope(request, baselines, mode):
    service.target_field(mode)
    if mode == service.TE_MODE:
        ids = resolve_request_baseline_ids(baselines, request=request)
        if len(ids) != 1 or not re.fullmatch(r'version-20[0-9]{6}', ids[0]) or baselines.strip() != ids[0]:
            raise _detail(400, 'TE 修正请选择一个版本数据集 / Select one version dataset for TE correction')
        return ids[0][8:]
    return ''


def trail_client(mode):
    return (service.adapter(settings.ra_auto_triage_root, mode=mode) if mode == service.TE_MODE
            else service.adapter(settings.ra_auto_triage_root))


def te_observation_store():
    return TEObservationStore(settings.data_dir, str(settings.ra_auto_triage_root))


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
    validate_scope(request, body.baselines, body.mode)
    ids = body.issue_ids
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
        raise _detail(503, '标注上传服务暂不可用，请重试 / Label publication unavailable; retry') from None


def filtered_rows(request, baselines, q, status, mode=service.RD_MODE, metadata=None):
    family = validate_scope(request, baselines, mode)
    allowed = {'all', 'resolved', 'same', 'blocked'} if mode == service.TE_MODE else {'all', 'resolved', 'pending', 'conflict'}
    if status not in allowed:
        raise _detail(400, '筛选无效 / Invalid filter')
    ids = members(request, baselines)
    rows = list(service.local_rows(database, ids).values())
    if {row['issue_id'] for row in rows} != set(ids):
        raise _detail(409, '标注范围已变化，请刷新 / Label scope changed; refresh')
    rows = filter_issue_rows(rows, q)
    if mode == service.TE_MODE:
        snapshot, observations = te_snapshot(settings.ra_auto_triage_root, family)
        saved, refresh_status = te_observation_store().read(baselines, ids)
        observed_metadata, observed = merge_observations(snapshot, observations, saved, refresh_status)
        observed_metadata, observed = te_observation_store().apply_readbacks(baselines, observed_metadata, observed)
        if metadata is not None:
            metadata.update(observed_metadata)
        counts = dict(total=len(rows), resolved=0, same=0, blocked=0)
        for row in rows:
            te = observed.get(row['issue_id'], {})
            value = te.get('te_value')
            valid_label = row['state'] == 'resolved' and row['label'] in service.VALUES
            if not valid_label:
                group, reason = 'blocked', 'label_conflict' if row['state'] in {'stale', 'conflict'} else 'label_pending'
            elif te.get('te_status') == 'unfilled':
                group, reason = 'blocked', 'te_empty'
            elif te.get('te_status') != 'filled' or not isinstance(value, str) or not value:
                group, reason = 'blocked', 'te_unknown'
            elif value == service.desired_value(row['label'], mode):
                group, reason = 'same', 'same'
            else:
                group, reason = 'resolved', 'candidate'
            row.update(group=group, correction_status=reason, te_current=value,
                       snapshot_at=observed_metadata.get('last_success_at'))
            counts[group] += 1
        return [r for r in rows if status == 'all' or r['group'] == status], counts
    counts = {'total': len(rows), 'resolved': 0, 'pending': 0, 'conflict': 0}
    for row in rows:
        key = 'resolved' if row['state'] == 'resolved' and row['label'] in service.VALUES else 'conflict' if row['state'] in {'conflict', 'stale'} else 'pending'
        row['group'] = key
        counts[key] += 1
    return [r for r in rows if status == 'all' or r['group'] == status], counts


@router.get('/api/rd-results')
async def summary(request: Request, baselines: str = '', q: str = '', status: str = 'all', page: int = 1, page_size: int = 20, mode: PublicationMode = 'rd'):
    await asyncio.to_thread(_writer_identity, request)
    if page_size not in {10, 20, 50, 100}:
        raise _detail(400, '每页数量无效 / Invalid page size')
    def load():
        metadata = {}
        rows, counts = filtered_rows(request, baselines, q, status, mode, metadata)
        pages = max(1, (len(rows) + page_size - 1) // page_size)
        current = min(max(page, 1), pages)
        return dict(items=rows[(current - 1)*page_size:current*page_size], counts=counts, total=len(rows), page=current, pages=pages, page_size=page_size,
                    mode=mode, field=service.target_field(mode), snapshot=metadata,
                    write_enabled=getattr(settings, 'trail_te_write_enabled', False) if mode == service.TE_MODE else settings.trail_rd_write_enabled)
    return await run(load)


@router.post('/api/rd-results/te-refresh')
async def refresh_te(request: Request, body: TERefresh):
    await asyncio.to_thread(_writer_identity, request)
    if not has_same_origin_mutation_marker(request):
        raise _detail(403, '请求标记缺失 / Request marker required')
    def start():
        validate_scope(request, body.baselines, service.TE_MODE)
        ids = members(request, body.baselines)
        _, status = te_observation_store().read(body.baselines, ids, refresh=True,
            read_remote=lambda batch: service.read_te_observations(trail_client(service.TE_MODE), batch))
        return status
    return JSONResponse(await run(start), status_code=202)


@router.get('/api/rd-results/te-refresh')
async def te_refresh_status(request: Request, baselines: str = ''):
    await asyncio.to_thread(_writer_identity, request)
    def load():
        validate_scope(request, baselines, service.TE_MODE)
        _, status = te_observation_store().read(baselines, members(request, baselines))
        return status
    return await run(load)


@router.post('/api/rd-results/preview-scope')
async def preview_scope(request: Request, body: ScopeSelection, background: bool = False):
    actor = await asyncio.to_thread(_admin_identity, request)
    if not has_same_origin_mutation_marker(request):
        raise _detail(403, '请求标记缺失 / Request marker required')
    def load(progress=None):
        rows, _ = filtered_rows(request, body.baselines, body.q, body.status, body.mode)
        excluded = set(body.excluded_issue_ids)
        if not excluded.issubset({r['issue_id'] for r in rows}):
            raise _detail(409, '选择范围已变化，请重新选择 / Selection scope changed; select again')
        valid = [r for r in rows if r['group'] == 'resolved']
        candidates = {r['issue_id']: r for r in valid if r['issue_id'] not in excluded}
        if progress:
            progress(0, len(candidates))
        remote = service.read_remote(trail_client(body.mode), list(candidates), parallel=True, mode=body.mode, **({'progress':progress} if progress else {})) if candidates else {}
        scope = dict(total=len(rows), blocked=len(rows) - len(valid), q=body.q, status=body.status)
        if excluded:
            scope['excluded'] = len(valid) - len(candidates)
        return candidates, remote, scope
    if background:
        result = await run(lambda: store().start_preview(actor.username, body.baselines, body.overwrite, load, mode=body.mode))
        return JSONResponse(result, status_code=202)
    rows, remote, scope = await run(load)
    return await run(lambda: store().preview(actor.username, rows, remote, body.overwrite, body.baselines, scope=scope, mode=body.mode))


@router.post('/api/rd-results/status')
async def remote_status(request: Request, body: Selection):
    await asyncio.to_thread(_writer_identity, request)
    def load():
        rows = selected(request, body)
        remote = service.read_remote(trail_client(body.mode), body.issue_ids, mode=body.mode)
        return {'items': [dict(issue_id=iid, current=remote[iid][service.target_field(body.mode)], status=service.classify(row, remote[iid], body.mode)) for iid, row in rows.items()]}
    return await run(load)


@router.post('/api/rd-results/preview')
async def preview(request: Request, body: Selection, background: bool = False):
    actor = await asyncio.to_thread(_admin_identity, request)
    if not has_same_origin_mutation_marker(request):
        raise _detail(403, '请求标记缺失 / Request marker required')
    def load(progress=None):
        rows = selected(request, body)
        if progress:
            progress(0, len(rows))
        remote = service.read_remote(trail_client(body.mode), body.issue_ids, parallel=True, mode=body.mode, **({'progress':progress} if progress else {}))
        return rows, remote, None
    if background:
        result = await run(lambda: store().start_preview(actor.username, body.baselines, body.overwrite, load, mode=body.mode))
        return JSONResponse(result, status_code=202)
    rows, remote, _ = await run(load)
    return await run(lambda: store().preview(actor.username, rows, remote, body.overwrite, body.baselines, mode=body.mode))


@router.post('/api/rd-results/te-excel-preview')
async def excel_preview(request: Request, file: UploadFile = File(...), baselines: str = Form(...),
                        overwrite: str = Form('false'), background: bool = False):
    actor = await asyncio.to_thread(_admin_identity, request)
    if not has_same_origin_mutation_marker(request) or overwrite not in {'true','false'}:
        raise _detail(403, '请求标记或确认参数无效 / Invalid request marker or confirmation')
    await run(validate_scope, request, baselines, service.TE_MODE)
    try:
        content, _ = await read_upload_limited(file, max_bytes=MAX_UPLOAD_BYTES)
    except UploadLimitExceeded:
        raise _detail(413, '文件超过 64 MiB / File exceeds 64 MiB') from None
    try:
        rows, source = await asyncio.to_thread(parse_te_xlsx, file.filename or '', content)
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    def load(progress=None):
        current = set(members(request, baselines))
        outside = [iid for iid in rows if iid not in current]
        if outside:
            raise _detail(409, '文件含版本范围外 Issue / File contains Issues outside this version: '+', '.join(outside[:10]))
        if progress: progress(0, len(rows))
        manual = service.local_rows(database, list(rows))
        preview_rows = {iid: {**row, 'manual_current': service.manual_label_snapshot(manual.get(iid, {}))}
                        for iid, row in rows.items()}
        remote = service.read_remote(trail_client(service.TE_MODE), list(rows), mode=service.TE_MODE,
            parallel=True, **({'progress':progress} if progress else {}))
        return preview_rows, remote, dict(total=len(rows), blocked=0, source=source)
    # Validate scope before queuing so a mismatched workbook has an actionable error.
    current = set(await run(members, request, baselines))
    outside = [iid for iid in rows if iid not in current]
    if outside:
        raise _detail(409, '文件含版本范围外 Issue / File contains Issues outside this version: '+', '.join(outside[:10]))
    if background:
        result = await run(lambda: store().start_preview(actor.username, baselines, False, load, mode=service.TE_MODE))
        return JSONResponse(result, status_code=202)
    selected_rows, remote, scope = await run(load)
    return await run(lambda: store().preview(actor.username, selected_rows, remote, False, baselines, scope=scope, mode=service.TE_MODE))


@router.post('/api/rd-results/commit')
async def commit(request: Request, body: Commit, background: bool = False):
    actor = await asyncio.to_thread(_admin_identity, request)
    if not has_same_origin_mutation_marker(request) or not body.confirmed:
        raise _detail(403, '写入未确认 / Writing not confirmed')
    def execute():
        record = store().get(body.operation_id)
        mode = record.get('mode', service.RD_MODE)
        validate_scope(request, record['baselines'], mode)
        enabled = getattr(settings, 'trail_te_write_enabled', False) if mode == service.TE_MODE else settings.trail_rd_write_enabled
        if not enabled:
            raise _detail(403, '写入未启用 / Publishing is disabled')
        publisher = store(actor)
        return (publisher.start_commit if background else publisher.commit)(body.operation_id, actor.username, database,
                              trail_client(mode), lambda: set(members(request, record['baselines'])))
    result = await run(execute)
    return JSONResponse(result, status_code=202) if background else result


@router.get('/api/rd-results/operations/{operation_id}')
async def operation(request: Request, operation_id: str, progress_only: bool = False):
    await asyncio.to_thread(_admin_identity, request)
    def load():
        receipt = store().receipt(operation_id)
        if progress_only:
            receipt.pop('items', None)  # Frozen rows are already held by the UI.
        return receipt
    return await run(load)


@router.get('/api/rd-results/operations')
async def operations(request: Request, mode: PublicationMode = 'rd'):
    await asyncio.to_thread(_admin_identity, request)
    def load():
        records = []
        for path in store().root.glob('*.json'):
            record = store().receipt(path.stem)
            if record['mode'] == mode and (record['state'] != 'preview' or record.get('background_preview')):
                records.append({k: record[k] for k in ('id', 'actor', 'created_at', 'state', 'mode', 'field', 'baselines')})
        return {'items': sorted(records, key=lambda r: r['created_at'], reverse=True)[:30]}
    return await run(load)
