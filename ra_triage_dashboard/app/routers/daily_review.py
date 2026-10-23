from __future__ import annotations
import asyncio
from fastapi import APIRouter,HTTPException,Query
from fastapi.responses import JSONResponse,Response
from ..daily_review_source import project,export_csv,SnapshotChanged,daily_overview
from ..runtime import settings,database
from ..web_paths import with_base_path

router=APIRouter()

async def _projection(dataset,date,reason,te_status,page,size,revision,sort='added'):
    try:
        arrivals = await asyncio.to_thread(database.version_dataset_arrivals, '20261009' if dataset=='1009' else dataset) if dataset!='0821' else {}
        return await asyncio.to_thread(project,settings.ra_auto_triage_root,dataset,date,reason,te_status,page,size,revision,sort,arrivals)
    except SnapshotChanged:raise HTTPException(409,'Snapshot changed; refresh this scope.') from None
    except (ValueError,OSError,TypeError,KeyError):raise HTTPException(503,'TE snapshot unavailable or invalid.') from None

@router.get('/api/daily-review')
@router.get('/api/daily-review/cases')
async def daily_review(dataset:str=Query('1009',pattern=r'^(1009|0821|20\d{6})$'),date:str=Query('',pattern=r'^(\d{4}-\d{2}-\d{2})?$'),reason:str=Query('all',pattern='^(all|low|sample)$'),te_status:str=Query('all',pattern='^(all|filled|unfilled|unknown)$'),page:int=Query(1,ge=1,le=10000),size:int=Query(24,ge=1,le=100),revision:str=Query('',max_length=64),include_overview:bool=False,sort:str=Query('added',pattern='^(added|occurred|issue)$')):
    result,_=await _projection(dataset,date,reason,te_status,page,size,revision,sort)
    if include_overview:
        result['daily_overview']=await asyncio.to_thread(daily_overview,settings.ra_auto_triage_root,result,reason)
    for row in result['items']:
        iid=row['issue_id']
        row['thumbnail_url']=with_base_path(settings.base_path,f'/api/case-thumbnails/{iid}')
        row['media_url']=with_base_path(settings.base_path,f'/api/cases/{iid}/media')
    return JSONResponse(result,headers={'Cache-Control':'no-store'})

@router.get('/api/daily-review/export')
async def daily_review_export(dataset:str=Query('1009',pattern=r'^(1009|0821|20\d{6})$'),date:str=Query('',pattern=r'^(\d{4}-\d{2}-\d{2})?$'),reason:str=Query('all',pattern='^(all|low|sample)$'),te_status:str=Query('all',pattern='^(all|filled|unfilled|unknown)$'),revision:str=Query(...,min_length=64,max_length=64),sort:str=Query('added',pattern='^(added|occurred|issue)$')):
    _,rows=await _projection(dataset,date,reason,te_status,1,100,revision,sort)
    return Response(export_csv(rows),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="te-progress.csv"','Cache-Control':'no-store'})
