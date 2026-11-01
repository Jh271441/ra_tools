const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const src='ra_triage_dashboard/static/js/';
class El extends EventTarget {
 constructor(){super();this.dataset={};this.hidden=false;this.value='1';this.textContent='';this.attrs={};this.isConnected=true;}
 setAttribute(k,v){this.attrs[k]=v;} getAttribute(k){return this.attrs[k]||null;} removeAttribute(k){delete this.attrs[k];}
 focus(){} matches(s){return s==='video'&&this.isVideo;} closest(){return null;} querySelector(){return null;} querySelectorAll(){return [];}
 fire(name,properties={}){const event=new Event(name,{cancelable:true});Object.assign(event,properties);this.dispatchEvent(event);return event;}
}
function playerFixture({readyState=4,preference=false,initialTime=0,durationSec=40,...videoState}={}){
 const timers=new Map();let next=0;
 const elements=Object.fromEntries(['video','play','playback-state','seek','step','rate','time','relative-start','t0','track','status','status-text','retry'].map(k=>[k,new El()]));
 const video=elements.video;Object.assign(video,{isVideo:true,readyState,duration:40,paused:true,seeking:false,loads:0,plays:0,seeks:[],error:null},videoState);
 let pos=initialTime;Object.defineProperty(video,'currentTime',{get:()=>pos,set:v=>{pos=v;video.seeks.push(v);}});
 video.pause=()=>{video.paused=true;};video.play=()=>{video.plays++;video.paused=false;video.fire('play');return Promise.resolve();};
 video.load=()=>{video.loads++;video.readyState=0;};video.attrs.src='/clip.mp4';video.attrs.poster='/poster.jpg';
 const player=new El();player.dataset={durationSec:String(durationSec),t0PlayerSec:String(durationSec/2),startOffsetSec:String(-durationSec/2)};
 player.querySelector=s=>s==='video'?video:elements[s.replace('[data-video-','').replace(']','')];
 const root={querySelectorAll:s=>s==='video'?[video]:[player]};
 const ctx={console,URL,Event,Number,window:{setTimeout:(f,ms)=>{timers.set(++next,{f,ms});return next;},clearTimeout:id=>timers.delete(id),requestAnimationFrame:f=>f()},enhanceDashboardSelects(){},t:x=>x,uiText:x=>x,showToast(){},safeSameOriginAssetUrl:x=>String(x||'').split('#')[0]};
 vm.createContext(ctx);
 vm.runInContext(fs.readFileSync(src+'planning-constraints.js','utf8'),ctx);
 vm.runInContext(fs.readFileSync(src+'detail-media.js','utf8'),ctx);
 let textPosition;const bindText=ctx.bindPlanningConstraint;
 ctx.bindPlanningConstraint=(player,video,getPosition)=>{textPosition=getPosition;return bindText(player,video,getPosition);};
 vm.runInContext(`bevVideoPlaybackPreference = ${preference}`,ctx);
 ctx.bindBevVideoPlayers(root);
 const flush=ms=>{for(const [id,x] of [...timers])if(x.ms===ms){timers.delete(id);x.f();}};
 return {ctx,root,player,elements,video,timers,flush,textPosition};
}
(async()=>{
 const p=playerFixture(),v=p.video,e=p.elements;
 const undecoded=playerFixture({readyState:0,seeking:true});
 assert.equal(undecoded.video.currentTime,0);
 assert.equal(undecoded.elements.seek.value,'20','Initial controls show intended t0 before metadata');
 assert.equal(undecoded.textPosition(),20,'Text and controls share initial t0 independently of decoding');
 undecoded.elements.seek.value='21';undecoded.elements.seek.fire('input');
 assert.equal(undecoded.textPosition(),21,'Text immediately follows a queued timeline seek');
 assert.equal(undecoded.video.currentTime,0);
 undecoded.flush(75);assert.equal(undecoded.textPosition(),21,'Pending metadata retains the requested text position');
 assert.equal(undecoded.video.seeks.length,0,'No video decoding is needed to select text time');
 undecoded.ctx.releaseBevVideoPlayer(undecoded.root);
 const media={assets:{video:{url:'/bev.mp4',tracks:[{url:'/bev.mp4'},{url:'/api/assets/cn1/camera-video'},{url:'/api/assets/cn1/bev-closeup-video',source_id:'bev_closeup',label:'局部 BEV 视频',poster_url:'/closeup-t0.jpg'}]},frames:[{url:'/before.jpg',offset_ms:-1000},{url:'/full-bev.jpg',offset_ms:0}]},camera:{frames:[{url:'/full-camera.jpg',offset_ms:0}]}};
 const descriptor=p.ctx.videoWithFramePosters(media);
 p.ctx.escapeHtml=String;
 const markup=p.ctx.videoPlayerMarkup(descriptor);
 assert(p.ctx.videoPlayerMarkup({...descriptor,duration_ms:40000}).includes('src="/bev.mp4#t=20"'),'initial resource selection advertises t0 before metadata');
 assert.equal(p.ctx.videoPlaybackSourceUrl('/bev.mp4?version=2#t=1',23.45678),'/bev.mp4?version=2#t=23.457');
 assert.equal(p.ctx.videoPlaybackSourceUrl('/bev.mp4',0),'/bev.mp4#t=0');
 for(const position of [null,NaN,-1,Infinity])assert.equal(p.ctx.videoPlaybackSourceUrl('/bev.mp4',position),'/bev.mp4');
 assert(markup.indexOf('class="bev-video-progress-row"')<markup.indexOf('data-video-status role='),'warnings follow the timeline, never split it from playback controls');
 assert(markup.includes('data-video-status role="status" aria-live="polite" hidden'),'first paint has no loading status row');
 assert.equal(descriptor.poster_url,'/full-bev.jpg');assert.equal(descriptor.tracks[1].poster_url,'/full-camera.jpg');
 assert.equal(descriptor.tracks[2].poster_url,'/closeup-t0.jpg','closeup source keeps its own full-resolution t0 poster');
 assert.equal(p.ctx.videoWithFramePosters({assets:{video:media.assets.video.tracks[2],frames:media.assets.frames}}).poster_url,'/closeup-t0.jpg');
 assert(markup.includes('data-video-track-label="局部 BEV 视频"'));
 assert.equal(media.assets.video.poster_url,undefined,'cached descriptors stay unchanged');
 assert.equal(media.assets.video.tracks[1].poster_url,undefined);
 assert.equal(p.ctx.videoWithFramePosters({assets:{video:{url:'/bev.mp4'}}}).poster_url,'','missing images use native video, never Gallery thumbnails');
 // A late full image updates the existing active source without reloading it.
 const options=[{value:'/bev.mp4',dataset:{}},{value:'/api/assets/cn1/camera-video',dataset:{}}];
 p.player.querySelectorAll=()=>options;
 v.attrs.src='/api/assets/cn1/camera-video#t=20';
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
 assert.equal(v.src,'/camera.mp4#t=9.9');v.readyState=1;v.fire('loadedmetadata');assert.equal(v.seeks.length,2);assert.equal(v.seeks.at(-1),9.9);
 v.readyState=4;v.fire('loadeddata');assert.equal(p.player.dataset.loadState,'ready');
 e.rate.value='1.5';e.rate.fire('change');
 e.track.value='/api/assets/cn1/bev-closeup-video';e.track.selectedOptions=[{dataset:{poster:'/closeup-t0.jpg'}}];e.track.fire('change');
 assert.equal(v.attrs.poster,'/closeup-t0.jpg');v.readyState=1;v.fire('loadedmetadata');
 assert.equal(v.seeks.at(-1),9.9,'closeup switch retains the event-relative position');assert.equal(v.playbackRate,1.5);
 v.error={code:2};v.fire('error');assert.equal(p.player.dataset.loadState,'error');assert(!e.retry.hidden);
 v.error=null;e.retry.fire('click');assert.equal(v.loads,3);assert.equal(p.player.dataset.loadState,'loading');assert(e.status.hidden);p.flush(12000);assert.equal(p.player.dataset.loadState,'slow');assert(!e.status.hidden);
 e.seek.value='12';e.seek.fire('input');const count=v.seeks.length;p.ctx.releaseBevVideoPlayer(p.root);
 assert.equal(p.timers.size,0);v.readyState=4;v.fire('loadedmetadata');assert.equal(v.seeks.length,count);assert.equal(v.getAttribute('src'),null);
 assert(v.paused);
 const cachedError=playerFixture();cachedError.video.error={code:2};cachedError.video.fire('error');assert.equal(cachedError.player.dataset.loadState,'error');
 cachedError.ctx.releaseBevVideoPlayer(cachedError.root);
 const buffered=playerFixture();buffered.video.fire('loadeddata');buffered.video.fire('stalled');assert.equal(buffered.player.dataset.loadState,'ready','buffered paused video must not show slow-load warning');
 buffered.video._refreshBevPlayerLanguage();assert.equal(buffered.video.getAttribute('aria-label'),'复核视频');buffered.ctx.releaseBevVideoPlayer(buffered.root);
 // Rapid source changes before metadata arrives must retain playing intent.
 const rapid=playerFixture();rapid.elements.rate.value='1.5';rapid.video.currentTime=23;rapid.elements.play.fire('click');
 rapid.video._setBevVideoTrack('/closeup.mp4');rapid.video._setBevVideoTrack('/original.mp4');
 assert.equal(rapid.video.paused,false,'loading retains the early native play request');rapid.video.readyState=1;rapid.video.fire('loadedmetadata');
 assert.equal(rapid.video.paused,false,'playback resumes after both pending source changes');
 assert.equal(rapid.video.currentTime,23);assert.equal(rapid.video.playbackRate,1.5);rapid.ctx.releaseBevVideoPlayer(rapid.root);
 // Space acknowledges/cancels the latest intent while metadata is blocked.
 const pendingPlay=playerFixture({readyState:0}),pe=pendingPlay.elements,pv=pendingPlay.video;
 assert.equal(pendingPlay.player.dataset.playbackState,'paused');
 assert.equal(pe.seek.value,'20','show the intended t0 during metadata loading');
 pendingPlay.player.fire('keydown',{key:' '});
 assert.equal(pe.play.textContent,'media.pause');assert.equal(pendingPlay.player.dataset.playbackState,'waiting');
 assert.equal(pv.plays,1,'known t0 allows native asynchronous play before metadata');
 pendingPlay.player.fire('keydown',{key:' ',repeat:true});assert.equal(pe.play.getAttribute('aria-pressed'),'true');
 pendingPlay.player.fire('keydown',{key:' '});assert.equal(pendingPlay.player.dataset.playbackState,'paused');
 pv.readyState=4;pv.fire('loadedmetadata');assert.equal(pv.plays,1,'cancelled pending playback must not restart later');assert(pv.paused);
 pendingPlay.player.fire('keydown',{key:' '});assert.equal(pv.plays,2);pv.fire('playing');
 assert.equal(pendingPlay.player.dataset.playbackState,'playing');
 pv.fire('waiting');assert.equal(pendingPlay.player.dataset.playbackState,'buffering');
 pv.fire('seeked');assert.equal(pendingPlay.player.dataset.playbackState,'playing','a buffered seek can resume without another playing event');
 pv.fire('playing');
 pv._setBevVideoTrack('/source-one.mp4');pv._setBevVideoTrack('/source-two.mp4');
 assert.equal(pv.src,'/source-two.mp4#t=20','rapid source switches keep the native start hint');
 assert.equal(pendingPlay.player.dataset.playbackState,'waiting');
 assert.equal(pv.plays,4,'each new source submits asynchronous playback without waiting for metadata');
 pv.readyState=4;pv.fire('loadedmetadata');assert.equal(pv.plays,4,'metadata must not start a duplicate play attempt');
 pv._setBevVideoTrack('/source-three.mp4');pendingPlay.player.fire('keydown',{key:' '});
 pv.readyState=4;pv.fire('loadedmetadata');assert.equal(pv.plays,5,'Space cancels source-resume intent, not native paused');assert(pv.paused);
 pv._setBevVideoTrack('/source-four.mp4');assert.equal(pendingPlay.player.dataset.playbackState,'paused');
 pendingPlay.player.fire('keydown',{key:' '});
 pendingPlay.ctx.pauseBevVideoPlayers(pendingPlay.root);pv.readyState=4;pv.fire('loadedmetadata');
 assert.equal(pv.plays,6,'hiding a loading player cancels its pending startup');assert(pv.paused);
 assert.equal(vm.runInContext('bevVideoPlaybackPreference',pendingPlay.ctx),true,'system suspension does not overwrite the manual preference');
 pendingPlay.ctx.resumeBevVideoPlayers(pendingPlay.root);assert.equal(pv.plays,7);
 pendingPlay.ctx.releaseBevVideoPlayer(pendingPlay.root);
 const nextCase=playerFixture({preference:true,readyState:0});
 assert.equal(nextCase.player.dataset.playbackState,'waiting');assert.equal(nextCase.video.plays,1,'the next Case queues native playback immediately');nextCase.video.readyState=4;nextCase.video.fire('loadedmetadata');
 assert.equal(nextCase.video.plays,1,'the next Case follows the playing preference');
 nextCase.elements.play.fire('click');nextCase.video._setBevVideoTrack('/paused-source.mp4');
 nextCase.video.readyState=4;nextCase.video.fire('loadedmetadata');assert.equal(nextCase.video.plays,1);
 nextCase.ctx.releaseBevVideoPlayer(nextCase.root);
 const hinted=playerFixture({initialTime:20});
 assert.deepEqual(hinted.video.seeks,[],'native fragment positioning must not trigger a redundant seek');hinted.ctx.releaseBevVideoPlayer(hinted.root);
 const unknown=playerFixture({durationSec:0,readyState:0,preference:true});
 assert.equal(unknown.video.plays,0,'unknown midpoint still requires decoded metadata');
 unknown.video.readyState=4;unknown.video.fire('loadedmetadata');assert.deepEqual(unknown.video.seeks,[20]);assert.equal(unknown.video.plays,1);
 unknown.ctx.releaseBevVideoPlayer(unknown.root);
 // Deferred image/video resolution paints whichever is usable first.
 const state={activePage:'review',caseRequestSeq:1,selectedId:'cn1',selectedCase:{issue_id:'cn1',assets:{},camera:{}},detailMedia:{kind:'',userSelected:false}};
 const pending={};let paints=[];
 const s={state,AbortController,URLSearchParams,console,api:path=>new Promise(resolve=>pending[path.split('kind=')[1]]=resolve),hydrateDetailMedia:d=>{paints.push(state.detailMedia.kind);return true;},hydrateDetailMediaControls:()=>{paints.push('controls');return true;},renderDetail:()=>paints.push('empty')};
 s.document={activeElement:null};s.$=()=>null;
 vm.createContext(s);vm.runInContext(fs.readFileSync(src+'text-input.js','utf8'),s);vm.runInContext(fs.readFileSync(src+'review-form.js','utf8'),s);
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
