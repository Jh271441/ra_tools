const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const src='ra_triage_dashboard/static/js/';
class El extends EventTarget {
 constructor(){super();this.dataset={};this.hidden=false;this.value='1';this.textContent='';this.attrs={};this.isConnected=true;}
 setAttribute(k,v){this.attrs[k]=v;} getAttribute(k){return this.attrs[k]||null;} removeAttribute(k){delete this.attrs[k];}
 focus(){} matches(s){return s==='video'&&this.isVideo;} closest(){return null;} querySelector(){return null;} querySelectorAll(){return [];}
 fire(name,properties={}){const event=new Event(name,{cancelable:true});Object.assign(event,properties);this.dispatchEvent(event);return event;}
}
function playerFixture({readyState=4,context=null,initialTime=0,durationSec=40,...videoState}={}){
 const timers=new Map();let next=0;
 const elements=Object.fromEntries(['video','play','seek','step','rate','time','relative-start','t0','track','status','status-text','retry'].map(k=>[k,new El()]));
 const video=elements.video;Object.assign(video,{isVideo:true,readyState,duration:40,paused:true,seeking:false,loads:0,plays:0,seeks:[],error:null},videoState);
 let pos=initialTime;Object.defineProperty(video,'currentTime',{get:()=>pos,set:v=>{pos=v;video.seeks.push(v);}});
 video.pause=()=>{video.paused=true;};video.play=()=>{video.plays++;video.paused=false;video.fire('play');return Promise.resolve();};
 video.load=()=>{video.loads++;video.readyState=0;};video.attrs.src='/clip.mp4';video.attrs.poster='/poster.jpg';
 const player=new El();player.dataset={durationSec:String(durationSec),t0PlayerSec:String(durationSec/2),startOffsetSec:String(-durationSec/2)};
 player.querySelector=s=>s==='video'?video:elements[s.replace('[data-video-','').replace(']','')];
 const root={querySelectorAll:s=>s==='video'?[video]:[player]};
 const ctx=context||{console,URL,Event,Number,enhanceDashboardSelects(){},t:x=>x,uiText:x=>x,showToast(){},safeSameOriginAssetUrl:x=>String(x||'').split('#')[0]};
 ctx.document||={createElement:()=>({getContext:()=>({drawImage(){}}),setAttribute(){},remove(){}})};
 video.after=()=>{};
 ctx.window={setTimeout:(f,ms)=>{timers.set(++next,{f,ms});return next;},clearTimeout:id=>timers.delete(id),requestAnimationFrame:f=>f()};
 if(!context){
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(src+'planning-constraints.js','utf8'),ctx);
  vm.runInContext(fs.readFileSync(src+'detail-media.js','utf8'),ctx);
 }
 let textPosition;const bindText=ctx.bindPlanningConstraint;
 ctx.bindPlanningConstraint=(player,video,getPosition)=>{textPosition=getPosition;return bindText(player,video,getPosition);};
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
 assert(!markup.includes('data-video-playback-state'),'playback feedback stays in the existing button, with no status slot');
 assert(p.ctx.videoPlayerMarkup({...descriptor,duration_ms:40000}).includes('src="/bev.mp4?playback=short-gop-v1#t=20"'),'initial resource selection advertises t0 before metadata');
 assert.equal(p.ctx.videoPlaybackSourceUrl('/bev.mp4?version=2#t=1',23.45678),'/bev.mp4?version=2&playback=short-gop-v1#t=23.457');
 assert.equal(p.ctx.videoPlaybackSourceUrl('/bev.mp4',0),'/bev.mp4?playback=short-gop-v1#t=0');
 assert.equal(p.ctx.videoCanonicalAssetUrl('/bev.mp4?version=2&playback=short-gop-v1#t=20'),'/bev.mp4?version=2');
 assert.equal(p.ctx.videoPlaybackSourceUrl('/bev.mp4?playback=short-gop-v1#t=20',23),'/bev.mp4?playback=short-gop-v1#t=23','retry does not duplicate the playback query');
 for(const position of [null,NaN,-1,Infinity])assert.equal(p.ctx.videoPlaybackSourceUrl('/bev.mp4',position),'/bev.mp4?playback=short-gop-v1');
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
 assert.equal(v.src,'/camera.mp4?playback=short-gop-v1#t=9.9');v.readyState=1;v.fire('loadedmetadata');assert.equal(v.seeks.length,2);assert.equal(v.seeks.at(-1),9.9);
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
 // Native load may flash its new poster or frame0 before the retained
 // target is decoded. Keep exactly the last valid frame across rapid changes.
 const transition=playerFixture(),tv=transition.video,snapshots=[];let held=null;
 tv.videoWidth=32;tv.videoHeight=18;
 transition.ctx.document={createElement:()=>({getContext:()=>({drawImage:v=>snapshots.push(v.currentTime)}),setAttribute(){},remove(){held=null;}})};
 tv.after=canvas=>{held=canvas;};
 tv._setBevVideoTrack('/closeup.mp4','/closeup-t0.jpg');assert(held);assert.deepEqual(snapshots,[20]);
 tv.currentTime=0;tv.readyState=2;tv.fire('loadeddata');assert(held,'frame0 before metadata must stay covered');
 tv.readyState=1;tv.fire('loadedmetadata');assert(held,'metadata alone cannot replace the previous decoded frame');
 tv.readyState=4;tv.fire('seeked');assert.equal(held,null,'the correctly decoded target replaces the held frame');
 tv.currentTime=23;tv._setBevVideoTrack('/one.mp4');const firstHeld=held;
 tv._setBevVideoTrack('/two.mp4');assert.equal(held,firstHeld);assert.deepEqual(snapshots,[20,23],'rapid sources cannot snapshot an intermediate wrong frame');
 transition.ctx.releaseBevVideoPlayer(transition.root);assert.equal(held,null,'teardown releases the full-resolution snapshot');
 // currentTime/seeked can advance before a different decoded frame is
 // submitted. A source poster, frame0 or stale callback must never be revealed.
 const proof=playerFixture({videoWidth:32,videoHeight:18}),fv=proof.video,frames=new Map();let frameId=0,cover=null;
 proof.ctx.document={createElement:()=>({getContext:()=>({drawImage(){}}),setAttribute(){},remove(){cover=null;}})};
 fv.after=canvas=>{cover=canvas;};
 fv.requestVideoFrameCallback=callback=>{frames.set(++frameId,callback);return frameId;};
 fv.cancelVideoFrameCallback=id=>frames.delete(id);
 const present=time=>{assert.equal(frames.size,1,'only one frame callback per transition');const [id,callback]=frames.entries().next().value;frames.delete(id);callback(0,{mediaTime:time});};
 fv.currentTime=23;fv._setBevVideoTrack('/closeup.mp4','/closeup-t0.jpg');
 fv.currentTime=0;fv.readyState=1;fv.fire('loadedmetadata');fv.readyState=4;fv.fire('seeked');
 assert(cover,'seeked/currentTime alone cannot uncover an unconfirmed decoded frame');
 present(0);assert(cover,'a submitted frame0 must stay covered');
 present(20);assert(cover,'the t0 poster/frame is not the retained23s target');
 present(23);assert.equal(cover,null,'the submitted target frame is revealed');assert.equal(frames.size,0);
 proof.elements.seek.value='22';proof.elements.seek.fire('change');
 assert.equal(cover,null,'an ordinary native seek must not copy the video into a canvas');
 assert.equal(frames.size,0,'an ordinary native seek has no additional submitted-frame gate');
 fv._setBevVideoTrack('/back.mp4');fv.readyState=4;fv.fire('loadedmetadata');
 proof.elements.seek.value='21';proof.elements.seek.fire('change');fv.fire('seeked');
 present(23);assert(cover,'a stale later frame is invalid when seeking backwards');
 fv.readyState=1;fv.seeking=true;present(21);assert(cover,'frame submission can precede native ready/seeked');
 fv.readyState=4;fv.seeking=false;fv.fire('seeked');assert.equal(cover,null,'paused playback needs no second frame callback to reveal its confirmed frame');
 fv._setBevVideoTrack('/one.mp4');const obsolete=[...frames.values()][0];
 fv._setBevVideoTrack('/two.mp4');obsolete(0,{mediaTime:21});assert(cover,'a retired source callback cannot uncover the next source');
 assert.equal(frames.size,1);fv.readyState=4;fv.fire('loadedmetadata');fv.fire('seeked');present(21);assert.equal(cover,null);
 fv._setBevVideoTrack('/short.mp4');fv.duration=20;fv.currentTime=20;fv.readyState=4;fv.fire('loadedmetadata');present(19.9);
 assert.equal(cover,null,'a shorter source clamps its target to the last actual frame');
 fv.duration=40;proof.elements.seek.value='40';proof.elements.seek.fire('change');
 assert.equal(cover,null);assert.equal(frames.size,0);
 fv._setBevVideoTrack('/end.mp4');fv.readyState=4;fv.fire('loadedmetadata');fv.fire('seeked');present(39.9);
 assert.equal(cover,null,'seeking to duration must reveal the last frame, not await a nonexistent40s frame');
 fv._setBevVideoTrack('/replay.mp4');fv.readyState=4;fv.fire('loadedmetadata');
 fv.ended=true;proof.elements.play.fire('click');fv.currentTime=0;present(0);
 assert.equal(cover,null,'Play at the end may confirm the native restart at0');fv.ended=false;
 fv._setBevVideoTrack('/three.mp4');proof.ctx.releaseBevVideoPlayer(proof.root);assert.equal(frames.size,0);assert.equal(cover,null);
 // Discrete arrow jumps start decoding without the slider's75ms trailing
 // debounce, including key repeats. Native seeks require no canvas readback.
 const native=playerFixture({videoWidth:2560,videoHeight:1440,
  requestVideoFrameCallback(){throw Error('Native seeks must not add a frame gate');}});
 native.ctx.document={createElement(){throw Error('Native seeks must not copy full-resolution frames');}};
 for(let i=0;i<5;i++){
  native.player.fire('keydown',{key:'ArrowRight',repeat:i>0});native.flush(0);
  assert.equal(native.video.currentTime,21+i,'each repeated key can decode before key release');
 }
 native.player.fire('keydown',{key:'ArrowLeft'});native.flush(0);assert.equal(native.video.currentTime,24);
 const nativeSeeks=native.video.seeks.length;native.flush(75);assert.equal(native.video.seeks.length,nativeSeeks);
 native.ctx.releaseBevVideoPlayer(native.root);
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
 assert.equal(pv.src,'/source-two.mp4?playback=short-gop-v1#t=20','rapid source switches keep the native start hint');
 assert.equal(pendingPlay.player.dataset.playbackState,'waiting');
 assert.equal(pv.plays,4,'each new source submits asynchronous playback without waiting for metadata');
 pv.readyState=4;pv.fire('loadedmetadata');assert.equal(pv.plays,4,'metadata must not start a duplicate play attempt');
 pv._setBevVideoTrack('/source-three.mp4');pendingPlay.player.fire('keydown',{key:' '});
 pv.readyState=4;pv.fire('loadedmetadata');assert.equal(pv.plays,5,'Space cancels source-resume intent, not native paused');assert(pv.paused);
 pv._setBevVideoTrack('/source-four.mp4');assert.equal(pendingPlay.player.dataset.playbackState,'paused');
 pendingPlay.player.fire('keydown',{key:' '});
 pendingPlay.ctx.pauseBevVideoPlayers(pendingPlay.root);pv.readyState=4;pv.fire('loadedmetadata');
 assert.equal(pv.plays,6,'hiding a loading player cancels its pending startup');assert(pv.paused);
 pendingPlay.ctx.resumeBevVideoPlayers(pendingPlay.root);assert.equal(pv.plays,6,'returning to a hidden video requires another explicit Play');assert(pv.paused);
 pendingPlay.ctx.releaseBevVideoPlayer(pendingPlay.root);
 const nextCase=playerFixture({context:pendingPlay.ctx,readyState:0});
 assert.equal(nextCase.player.dataset.playbackState,'paused');assert.equal(nextCase.video.plays,0,'a new Case in the same page never inherits earlier Play');nextCase.video.readyState=4;nextCase.video.fire('loadedmetadata');
 assert.equal(nextCase.video.plays,0,'metadata leaves a new Case paused at t0');assert.equal(nextCase.video.currentTime,20);
 nextCase.elements.play.fire('click');assert.equal(nextCase.video.plays,1,'the new Case plays only after its own explicit choice');
 nextCase.elements.play.fire('click');nextCase.video._setBevVideoTrack('/paused-source.mp4');
 nextCase.video.readyState=4;nextCase.video.fire('loadedmetadata');assert.equal(nextCase.video.plays,1);
 nextCase.ctx.releaseBevVideoPlayer(nextCase.root);
 const hinted=playerFixture({initialTime:20});
 assert.deepEqual(hinted.video.seeks,[],'native fragment positioning must not trigger a redundant seek');hinted.ctx.releaseBevVideoPlayer(hinted.root);
 const unknown=playerFixture({durationSec:0,readyState:0});unknown.elements.play.fire('click');
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
