const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const src='ra_triage_dashboard/static/js/';
class El extends EventTarget {
 constructor(){super();this.dataset={};this.hidden=false;this.value='1';this.textContent='';this.attrs={};this.isConnected=true;}
 setAttribute(k,v){this.attrs[k]=v;} getAttribute(k){return this.attrs[k]||null;} removeAttribute(k){delete this.attrs[k];}
 focus(){} matches(s){return s==='video'&&this.isVideo;} querySelector(){return null;} querySelectorAll(){return [];}
 fire(name){this.dispatchEvent(new Event(name));}
}
function playerFixture(){
 const timers=new Map();let next=0;
 const elements=Object.fromEntries(['video','play','seek','step','rate','time','relative-start','t0','track','status','status-text','retry'].map(k=>[k,new El()]));
 const video=elements.video;Object.assign(video,{isVideo:true,readyState:4,duration:40,paused:true,seeking:false,loads:0,seeks:[],error:null});
 let pos=0;Object.defineProperty(video,'currentTime',{get:()=>pos,set:v=>{pos=v;video.seeks.push(v);}});
 video.pause=()=>{video.paused=true;};video.play=()=>{video.paused=false;return Promise.resolve();};
 video.load=()=>{video.loads++;video.readyState=0;};video.attrs.src='/clip.mp4';video.attrs.poster='/poster.jpg';
 const player=new El();player.dataset={durationSec:'40',t0PlayerSec:'20',startOffsetSec:'-20'};
 player.querySelector=s=>s==='video'?video:elements[s.replace('[data-video-','').replace(']','')];
 const root={querySelectorAll:s=>s==='video'?[video]:[player]};
 const ctx={console,URL,Event,Number,window:{setTimeout:(f,ms)=>{timers.set(++next,{f,ms});return next;},clearTimeout:id=>timers.delete(id),requestAnimationFrame:f=>f()},enhanceDashboardSelects(){},t:x=>x,uiText:x=>x,showToast(){},safeSameOriginAssetUrl:x=>x};
 vm.createContext(ctx);
 vm.runInContext(fs.readFileSync(src+'planning-constraints.js','utf8'),ctx);
 vm.runInContext(fs.readFileSync(src+'detail-media.js','utf8'),ctx);
 ctx.bindBevVideoPlayers(root);
 const flush=ms=>{for(const [id,x] of [...timers])if(x.ms===ms){timers.delete(id);x.f();}};
 return {ctx,root,player,elements,video,timers,flush};
}
(async()=>{
 const p=playerFixture(),v=p.video,e=p.elements;
 const media={assets:{video:{url:'/bev.mp4',tracks:[{url:'/bev.mp4'},{url:'/api/assets/cn1/camera-video'}]},frames:[{url:'/before.jpg',offset_ms:-1000},{url:'/full-bev.jpg',offset_ms:0}]},camera:{frames:[{url:'/full-camera.jpg',offset_ms:0}]}};
 const descriptor=p.ctx.videoWithFramePosters(media);
 p.ctx.escapeHtml=String;
 const markup=p.ctx.videoPlayerMarkup(descriptor);
 assert(markup.indexOf('class="bev-video-progress-row"')<markup.indexOf('data-video-status role='),'warnings follow the timeline, never split it from playback controls');
 assert(markup.includes('data-video-status role="status" aria-live="polite" hidden'),'first paint has no loading status row');
 assert.equal(descriptor.poster_url,'/full-bev.jpg');assert.equal(descriptor.tracks[1].poster_url,'/full-camera.jpg');
 assert.equal(media.assets.video.poster_url,undefined,'cached descriptors stay unchanged');
 assert.equal(media.assets.video.tracks[1].poster_url,undefined);
 assert.equal(p.ctx.videoWithFramePosters({assets:{video:{url:'/bev.mp4'}}}).poster_url,'','missing images use native video, never Gallery thumbnails');
 // A late full image updates the existing active source without reloading it.
 const options=[{value:'/bev.mp4',dataset:{}},{value:'/api/assets/cn1/camera-video',dataset:{}}];
 p.player.querySelectorAll=()=>options;
 v.attrs.src='/api/assets/cn1/camera-video';
 p.ctx.refreshVideoFramePosters(p.root,media);
 assert.equal(v.attrs.poster,'/full-camera.jpg');assert.equal(options[0].dataset.poster,'/full-bev.jpg');
 assert.equal(v.loads,0);assert.deepEqual(v.seeks,[20]);v.attrs.src='/clip.mp4';
 assert.deepEqual(v.seeks,[20],'cached metadata initializes t0 once');
 for(const event of ['loadstart','waiting','seeking']){
  v.fire(event);assert(e.status.hidden,'normal loading/seeking must not insert a status row');
  assert.equal(e['status-text'].textContent,'');assert(e.retry.hidden);
 }
 for(let i=0;i<100;i++){e.seek.value=String(i/10);e.seek.fire('input');}
 assert.equal(v.seeks.length,1,'drag coalesces network seeks');p.flush(75);assert.equal(v.seeks.at(-1),9.9);assert.equal(v.seeks.length,2);
 e.seek.value='32';e.seek.fire('input');e.track.value='/camera.mp4';e.track.selectedOptions=[{dataset:{poster:'/camera.jpg'}}];e.track.fire('change');
 assert.equal(v.attrs.poster,'/camera.jpg');p.flush(75);assert.equal(v.seeks.length,2,'source switch cancels queued old seek');
 v.readyState=1;v.fire('loadedmetadata');assert.equal(v.seeks.length,3);assert.equal(v.seeks.at(-1),9.9);
 v.readyState=4;v.fire('loadeddata');assert.equal(p.player.dataset.loadState,'ready');
 v.error={code:2};v.fire('error');assert.equal(p.player.dataset.loadState,'error');assert(!e.retry.hidden);
 v.error=null;e.retry.fire('click');assert.equal(v.loads,2);assert.equal(p.player.dataset.loadState,'loading');assert(e.status.hidden);p.flush(12000);assert.equal(p.player.dataset.loadState,'slow');assert(!e.status.hidden);
 e.seek.value='12';e.seek.fire('input');const count=v.seeks.length;p.ctx.releaseBevVideoPlayer(p.root);
 assert.equal(p.timers.size,0);v.readyState=4;v.fire('loadedmetadata');assert.equal(v.seeks.length,count);assert.equal(v.getAttribute('src'),null);
 assert(v.paused);
 const cachedError=playerFixture();cachedError.video.error={code:2};cachedError.video.fire('error');assert.equal(cachedError.player.dataset.loadState,'error');
 cachedError.ctx.releaseBevVideoPlayer(cachedError.root);
 const buffered=playerFixture();buffered.video.fire('loadeddata');buffered.video.fire('stalled');assert.equal(buffered.player.dataset.loadState,'ready','buffered paused video must not show slow-load warning');
 buffered.video._refreshBevPlayerLanguage();assert.equal(buffered.video.getAttribute('aria-label'),'复核视频');buffered.ctx.releaseBevVideoPlayer(buffered.root);
 // Deferred image/video resolution paints whichever is usable first.
 const state={activePage:'review',caseRequestSeq:1,selectedId:'cn1',selectedCase:{issue_id:'cn1',assets:{},camera:{}},detailMedia:{kind:'',userSelected:false}};
 const pending={};let paints=[];
 const s={state,AbortController,URLSearchParams,console,api:path=>new Promise(resolve=>pending[path.split('kind=')[1]]=resolve),hydrateDetailMedia:d=>{paints.push(state.detailMedia.kind);return true;},hydrateDetailMediaControls:()=>{paints.push('controls');return true;},renderDetail:()=>paints.push('empty')};
 vm.createContext(s);vm.runInContext(fs.readFileSync(src+'review-form.js','utf8'),s);
 const load=s.loadDeferredCaseMedia('cn1',1);
 pending.images({assets:{frames:[{url:'/frame.jpg'}]}});await new Promise(setImmediate);assert.equal(paints.length,1,'image paints without waiting for video');
 pending.video({assets:{video:{url:'/v.mp4',poster_url:'/thumb.jpg'}}});await load;assert.equal(state.detailMedia.kind,'video');assert.equal(state.selectedCase.assets.video.poster_url,'/thumb.jpg');
 paints=[];state.detailMedia.userSelected=true;state.detailMedia.kind='camera';const load2=s.loadDeferredCaseMedia('cn1',1);pending.video({assets:{video:{url:'/v.mp4'}}});pending.images({assets:{frames:[]}});await load2;assert.equal(state.detailMedia.kind,'camera','late video must not override user selection');
 paints=[];const stale=s.loadDeferredCaseMedia('cn1',1);state.activePage='labeling';pending.video({assets:{video:{url:'/old.mp4'}}});pending.images({assets:{frames:[]}});await stale;assert.equal(paints.length,0);
 // A fresh collaborative read reuses media, and rejects edits begun during the read.
 state.activePage='review';state.selectedCase={issue_id:'cn1',media_status:'ready',assets:{video:{url:'/keep.mp4'}}};state.pendingReviewImages=[];
 Object.assign(s,{capturePageContext:()=>({}),isPageContextCurrent:()=>true,caseRationaleUploadTask:()=>null,renderReview:()=>{},renderDetail:(data,options)=>{assert(options.preserveMedia);assert.equal(data.assets.video.url,'/keep.mp4');paints.push('retained');}});
 let resolve;s.api=()=>new Promise(r=>resolve=r);let refresh=s.refreshReviewCorePreservingMedia();resolve({issue_id:'cn1'});await refresh;assert.deepEqual(paints,['retained']);
 paints=[];refresh=s.refreshReviewCorePreservingMedia();state.reviewFormDirty=true;resolve({issue_id:'cn1'});await refresh;assert.equal(paints.length,0);assert(state.deferredDetailRefresh);
 console.log('PASS video cached metadata, coalesced seeking, source poster, teardown, retry, progressive paint, ownership and retained refresh');
})().catch(e=>{console.error(e);process.exitCode=1;});
