"""Three formal label lanes; all reads are local and all writes are queued."""
import asyncio
import re
from functools import partial
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, StrictBool

from ..runtime import database,settings
from ..support.identity import _writer_identity,_admin_identity
from ..support.common import _detail
from ..auth import has_same_origin_mutation_marker
from ..human_publication_queue import preview,enqueue,publication_enabled

router=APIRouter()
Lane=Literal['rd','te','arbitrated']


class Selection(BaseModel):
    lane: Lane
    baselines: str=Field(min_length=1,max_length=2000)
    issue_ids: list[str]
    class Config:extra='forbid'


class Commit(BaseModel):
    request_id: str=Field(min_length=32,max_length=32)
    confirmed: StrictBool
    class Config:extra='forbid'


def datasets(baselines):
    ids=baselines.split(',')
    if not 1<=len(ids)<=50 or any(not re.fullmatch(r'version-20[0-9]{6}',i) or i[8:]<'20261106' for i in ids):
        raise ValueError('请选择1106起的版本数据集 / Select version datasets from 1106 onward')
    return ['release-'+i[8:]+'-odd2' for i in ids]


async def run(call):
    try:return await asyncio.to_thread(call)
    except ValueError as exc:raise _detail(409,str(exc)) from exc


def load_rows(baselines,lane,q,status,page,page_size):
    result=database.human_publication_rows(lane=lane,datasets=datasets(baselines),query=q,state=status,page=page,page_size=page_size)
    result.update(write_enabled=publication_enabled(settings),lane=lane)
    return result


@router.get('/api/human-publications')
async def rows(request: Request,baselines: str='',lane: Lane='rd',q: str='',status: str='all',page: int=1,page_size: int=20):
    await asyncio.to_thread(_writer_identity,request)
    return await run(partial(load_rows,baselines,lane,q,status,page,page_size))


@router.post('/api/human-publications/preview')
async def create_preview(request: Request,body: Selection):
    actor=await asyncio.to_thread(_admin_identity,request)
    if not has_same_origin_mutation_marker(request):raise _detail(403,'请求标记缺失 / Request marker required')
    return await run(lambda:preview(database,lane=body.lane,issue_ids=body.issue_ids,datasets=datasets(body.baselines),actor=actor.username))


@router.post('/api/human-publications/commit',status_code=202)
async def commit(request: Request,body: Commit):
    actor=await asyncio.to_thread(_admin_identity,request)
    if not has_same_origin_mutation_marker(request) or not body.confirmed:raise _detail(403,'提交未确认 / Submission not confirmed')
    if not await asyncio.to_thread(publication_enabled,settings):raise _detail(403,'真实写入未启用或字段能力尚未验收 / Publishing disabled or field capabilities unqualified')
    return await run(partial(enqueue,database,request_id=body.request_id,actor=actor.username))


def load_history(issue_id,lane,page,page_size):
    if not re.fullmatch(r'cn[0-9]+',issue_id) or page<1 or page_size not in {10,20,50,100}:raise ValueError('分页无效 / Invalid pagination')
    with database.connect() as conn:
        args=(issue_id,lane)
        total=conn.execute('SELECT COUNT(*) AS n FROM human_publication_attempts WHERE issue_id=? AND lane=?',args).fetchone()['n']
        pages=max(1,(total+page_size-1)//page_size);current=min(page,pages)
        items=[dict(r) for r in conn.execute('SELECT id,generation,action,desired,state,error_code,created_at,finished_at FROM human_publication_attempts WHERE issue_id=? AND lane=? ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?',(*args,page_size,(current-1)*page_size)).fetchall()]
        return dict(items=items,total=total,page=current,pages=pages,page_size=page_size)


@router.get('/api/human-publications/history')
async def history(request: Request,issue_id: str,lane: Lane='rd',page: int=1,page_size: int=20):
    await asyncio.to_thread(_writer_identity,request)
    return await run(partial(load_history,issue_id,lane,page,page_size))
