import {test} from 'node:test';
import assert from 'node:assert/strict';
import {getSmoothStepPath,Position} from '@xyflow/react';
import {flowLayout,lanePath,returnPath,retryGeometry,mainRetryConnections} from '../src/lib/flowLayout.ts';
const motion={labelActive:false,labelScheduled:false,recoveryActive:false,recoveryScheduled:false};

test('main retries and label feedback are visible by default and AutoTriage follows them',()=>{
 const a=flowLayout(true,true,true);
 assert.ok(a.backfillY>a.mainY+158+40);
 assert.ok(a.labelY>a.backfillY+retryGeometry.backfillHeight+60);
 assert.ok(a.autoY>a.labelY+146+34);
 assert.ok(a.height>a.autoY+164+20);
});

test('main recovery reconnects preparation to verification; label updates feed back into collection',()=>{
 const links=mainRetryConnections(flowLayout(true,true,true),motion);
 assert.deepEqual(links.map(e=>[e.id,e.source,e.target]),[
  ['prepare-backfill','prepare','backfill-sync'],['backfill-verify','backfill-merge','verify'],
  ['collect-label-sync','collect','label-sync'],['label-apply-collect','label-apply','collect'],
 ]);
 assert.equal(links.find(e=>e.id==='label-apply-collect').data.returnLane,true);
 for(const e of links)assert.equal(e.animated,false);
 const running=mainRetryConnections(flowLayout(true,true,true),{...motion,recoveryActive:true});
 assert.deepEqual(running.filter(e=>e.animated).map(e=>e.id),['prepare-backfill','backfill-verify']);
});

test('only an absent mechanism is omitted; configured paths do not depend on a disclosure toggle',()=>{
 for(const auto of [true,false])for(const backfill of [true,false])for(const labels of [true,false]){
  const a=flowLayout(auto,backfill,labels), links=mainRetryConnections(a,motion);
  assert.equal(a.backfillY!=null,backfill);assert.equal(a.labelY!=null,labels);
  assert.equal(links.length,2*Number(backfill)+2*Number(labels));
  assert.ok(a.height>(auto?a.autoY+164:labels?a.labelY+146:backfill?a.backfillY+136:a.mainY+158)+20);
 }
});

function points(path){
 const result=[];let p=[0,0];
 for(const c of path.match(/[MLQ][^MLQ]*/g)||[]){
  const v=(c.slice(1).match(/[-+]?(?:\d*\.)?\d+(?:e[-+]?\d+)?/gi)||[]).map(Number);
  if(c[0]==='M'){p=v;result.push(p);continue;}
  const end=c[0]==='Q'?v.slice(2):v;
  for(let i=1;i<=20;i++){
   const t=i/20;
   result.push(c[0]==='Q'?[(1-t)**2*p[0]+2*(1-t)*t*v[0]+t*t*end[0],(1-t)**2*p[1]+2*(1-t)*t*v[1]+t*t*end[1]]:[p[0]+t*(end[0]-p[0]),p[1]+t*(end[1]-p[1])]);
  }
  p=end;
 }
 return result;
}
const smooth=(sx,sy,sp,tx,ty,tp)=>getSmoothStepPath({sourceX:sx,sourceY:sy,sourcePosition:sp,targetX:tx,targetY:ty,targetPosition:tp,borderRadius:6,offset:22})[0];

test('retry entry, result writeback and label feedback stay clear of every stage node',()=>{
 const a=flowLayout(true,true,true),g=retryGeometry;
 const nodes=[0,1,2,3,4].map(i=>({x:i*240,y:a.mainY,w:196,h:158}));
 nodes.push(...[0,1,2,3].map(i=>({x:g.backfillX+i*g.backfillPitch,y:a.backfillY,w:g.backfillWidth,h:g.backfillHeight})));
 nodes.push(...[0,1,2,3].map(i=>({x:i*240,y:a.labelY,w:196,h:114})));
 nodes.push(...[0,1,2,3,4].map(i=>({x:i*240,y:a.autoY,w:196,h:132})));
 const paths=[
  smooth(338,a.mainY+158,Position.Bottom,338,a.backfillY,Position.Top),
  smooth(818,a.backfillY,Position.Top,818,a.mainY+158,Position.Bottom),
  smooth(196*g.collectOut,a.mainY+158,Position.Bottom,98,a.labelY,Position.Top),
  returnPath(818,a.labelY+114,196*g.collectReturn,a.mainY+158,g.leftRail,a.labelY+146),
  lanePath(818,a.backfillY+g.backfillHeight,338,a.backfillY+g.backfillHeight,a.backfillY+136),
  lanePath(578,a.autoY+132,1058,a.autoY+132,a.autoY+164),
 ];
 for(const path of paths)for(const [x,y] of points(path))for(const n of nodes){
  assert.ok(!(x>n.x+1&&x<n.x+n.w-1&&y>n.y+1&&y<n.y+n.h-1),`Path crosses node at ${n.x},${n.y}: ${path}`);
 }
 // Place the outbound collection rail to the right of its return port.
 // This keeps the incoming and outgoing feedback connectors from crossing below collection.
 assert.ok(g.collectOut>g.collectReturn);
});

test('backfill endpoints align with their owning main stages, and reuse stays within AutoTriage',()=>{
 const g=retryGeometry,a=flowLayout(true,true,true);
 assert.equal(g.backfillX+g.backfillWidth/2,240+98);
 assert.equal(g.backfillX+3*g.backfillPitch+g.backfillWidth/2,720+98);
 assert.ok(a.autoY-34>a.labelY+146);
 assert.ok(a.height>a.autoY+164+20);
});
