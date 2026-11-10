/* Target-first loading of the existing full-quality H264 samples. Native video
 * still owns decoding, currentTime, play/pause and presentation. No other track
 * is fetched. Unsupported/missing/failed streams retain progressive playback. */
function videoSegmentManifestUrl(url) {
  const safe = safeSameOriginAssetUrl(url);
  if (!safe || !/\/api\/assets\/[^/]+\/[^/]+$/.test(new URL(safe, location.origin).pathname)
      || typeof MediaSource === "undefined"
      || typeof MediaSource.isTypeSupported !== "function"
      || !MediaSource.isTypeSupported('video/mp4; codecs="avc1.640028"')) return "";
  const parsed = new URL(safe, location.origin);
  parsed.hash = "";
  parsed.searchParams.delete("playback");
  parsed.searchParams.set("stream", "segments-v1");
  return parsed.pathname + parsed.search;
}

function createVideoSegmentLoader(video, {
  url, position, attached, fallback, onBufferAppended = () => {}, frameStepSec = 0.1,
}) {
  const manifestUrl = videoSegmentManifestUrl(url);
  if (!manifestUrl) return null;
  let stopped = false, suspended = false, initialized = false, pumping = false;
  let mediaSource = null, buffer = null, objectUrl = "", index = null;
  let active = null, needsPump = false, resetParser = false;
  let boundarySeek = null;
  let secondsPerByte = Infinity, rewindAttempted = false;
  const forwardRetention = 12;
  const requests = new Set(), loaded = new Set(), touched = new Set(), listeners = [];
  const listen = (target, name, handler) => {
    target.addEventListener(name, handler);
    listeners.push(() => target.removeEventListener(name, handler));
  };
  const current = () => {
    const requested = position();
    return Math.min(index?.duration || Infinity,
      Math.max(0, requested === null ? (index?.duration || 0) / 2 : Number(requested) || 0));
  };
  const segmentAt = time => {
    const at = index.segments.findIndex(segment => time < segment.end - .000001);
    // A seek to duration still belongs to the final GOP. Do not turn its
    // unmatched exclusive end boundary into a request for the first GOP.
    return at < 0 ? index.segments.length - 1 : at;
  };
  const retryBoundarySeek = () => {
    if (boundarySeek === null || stopped || suspended || video.seeking
        || video.currentTime !== boundarySeek || !loaded.has(segmentAt(boundarySeek))) return;
    const target = boundarySeek;
    boundarySeek = null;
    video.currentTime = target;
  };
  const append = bytes => new Promise((resolve, reject) => {
    if (stopped) { resolve(); return; }
    const cleanup = () => {
      buffer.removeEventListener("updateend", done);
      buffer.removeEventListener("error", fail);
      buffer.removeEventListener("abort", fail);
    };
    const done = () => { cleanup(); resolve(); };
    const fail = () => { cleanup(); reject(Error("segment append failed")); };
    buffer.addEventListener("updateend", done);
    buffer.addEventListener("error", fail);
    buffer.addEventListener("abort", fail);
    try { buffer.appendBuffer(bytes); }
    catch (error) { cleanup(); reject(error); }
  });
  const dispose = () => {
    if (stopped) return;
    stopped = true;
    requests.forEach(request => request.abort());
    listeners.forEach(remove => remove());
    if (mediaSource?.readyState === "open") {
      try { buffer?.abort(); } catch { /* A source can close during teardown. */ }
    }
    if (objectUrl) URL.revokeObjectURL(objectUrl);
  };
  const recover = () => {
    if (stopped) return false;
    dispose();
    fallback();
    return true;
  };
  const request = async (url, options = {}) => {
    const controller = new AbortController();
    requests.add(controller);
    try { return { response: await fetch(url, { ...options, signal: controller.signal }), controller }; }
    catch (error) { requests.delete(controller); throw error; }
  };
  const segmentBytes = number => index.segments[number].last - index.segments[number].first + 1;
  const hasPlaybackReserve = (time, rewindBytes, transferCost = secondsPerByte) => {
    const ranges = video.buffered;
    for (let i = 0; i < (ranges?.length || 0); i++) {
      const end = ranges.end(i);
      if (time < ranges.start(i) || time >= end) continue;
      const nextBytes = end < index.duration - .000001 ? segmentBytes(segmentAt(end)) : 0;
      // Leave time for the next forward fetch and a second of margin.
      const required = Math.max(2, 1 + (rewindBytes + nextBytes) * transferCost);
      return (end - time) / Math.max(.25, video.playbackRate) >= required;
    }
    return false;
  };
  const nextSegment = () => {
    const time = current(), at = segmentAt(time);
    if (!loaded.has(at)) return at;
    const previous = at - 1;
    // Midpoint startup has no played data to retain on the left. Warm one
    // previous GOP once playback has enough contiguous forward data.
    if (!video.paused && !video.seeking && video.readyState >= 3 && previous >= 0
        && !loaded.has(previous) && !rewindAttempted
        && Number.isFinite(secondsPerByte) && hasPlaybackReserve(time, segmentBytes(previous))) return previous;
    // The next GOP can flush the target's final reordered frames. While
    // paused, stop there: backward prefetch competes with UI requests and is
    // unnecessary until the reviewer actually seeks backward.
    const candidates = video.paused ? [at + 1]
      : index.segments.map((_, i) => i).filter(i => i > at
        && index.segments[i].start < current() + Math.max(4, video.playbackRate * 4));
    return candidates.find(i => i >= 0 && i < index.segments.length && !loaded.has(i)) ?? -1;
  };
  const evict = async () => {
    const start = Math.max(0, current() - 6), end = Math.min(index.duration, current() + forwardRetention);
    for (const [first, last] of [[0, start], [end, index.duration]]) {
      const discarded = [...touched].filter(i => index.segments[i].start >= first
        && index.segments[i].end <= last);
      if (!discarded.length || stopped || buffer.updating) continue;
      // Whole GOPs only; never discard the current independent frame.
      const low = Math.min(...discarded.map(i => index.segments[i].start));
      const high = Math.max(...discarded.map(i => index.segments[i].end));
      await new Promise((resolve, reject) => {
        const done = () => { cleanup(); resolve(); };
        const fail = () => { cleanup(); reject(Error("segment eviction failed")); };
        const cleanup = () => {
          buffer.removeEventListener("updateend", done);
          buffer.removeEventListener("error", fail);
          buffer.removeEventListener("abort", fail);
        };
        buffer.addEventListener("updateend", done);
        buffer.addEventListener("error", fail);
        buffer.addEventListener("abort", fail);
        try { buffer.remove(low, high); } catch (error) { cleanup(); reject(error); }
      });
      discarded.forEach(i => { loaded.delete(i); touched.delete(i); });
    }
  };
  const fetchSegment = async (number, rewind) => {
    const segment = index.segments[number];
    const source = new URL(url, location.origin);
    source.hash = "";
    source.searchParams.delete("stream");
    source.searchParams.set("playback", "segments-v1");
    source.searchParams.set("fingerprint", index.fingerprint);
    const controller = new AbortController();
    requests.add(controller);
    const transfer = { number, controller, rewind, received: 0, started: performance.now() };
    active = transfer;
    if (rewind) rewindAttempted = true;
    let reader = null;
    try {
      const response = await fetch(source.pathname + source.search, {
        headers: { Range: `bytes=${segment.first}-${segment.last}` }, signal: controller.signal,
        priority: rewind || (video.paused && number !== segmentAt(current())) ? "low" : "auto",
      });
      if (stopped) return;
      const expected = `bytes ${segment.first}-${segment.last}/${index.size}`;
      if (response.status !== 206 || response.headers.get("Content-Range") !== expected || !response.body) {
        throw Error("unexpected segment range");
      }
      reader = response.body.getReader();
      touched.add(number);
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        if (stopped || controller.signal.aborted) break;
        transfer.received += value.byteLength;
        if (transfer.received > segmentBytes(number)) throw Error("oversized segment");
        // Streaming append lets the first decodable frames play immediately;
        // neither the rest of this GOP nor the entire clip is a readiness gate.
        await append(value);
        if (!stopped && !controller.signal.aborted) onBufferAppended();
      }
      if (!stopped && !controller.signal.aborted) {
        if (transfer.received !== segmentBytes(number)) throw Error("truncated segment");
        if (!rewind) secondsPerByte = Math.max(1, performance.now() - transfer.started) / (1000 * transfer.received);
        loaded.add(number);
        retryBoundarySeek();
      }
    } finally {
      controller.abort();
      requests.delete(controller);
      reader?.releaseLock();
      active = null;
    }
  };
  const pump = async () => {
    if (pumping || !initialized || stopped || suspended) return;
    pumping = true;
    try {
      do {
        needsPump = false;
        if (resetParser) {
          if (mediaSource.readyState === "open") buffer.abort();
          resetParser = false;
        }
        await evict();
        if (stopped || suspended) break;
        // Flush the last frame as soon as its GOP is complete; optional
        // backward buffering must not delay a paused end-of-clip switch.
        if (loaded.has(index.segments.length - 1) && current() >= index.segments.at(-1).start
            && mediaSource.readyState === "open") mediaSource.endOfStream();
        const next = nextSegment();
        if (next < 0) break;
        const rewind = next < segmentAt(current());
        try { await fetchSegment(next, rewind); }
        catch (error) {
          if (rewind && next !== segmentAt(current())) resetParser = true;
          else if (error.name !== "AbortError" || (!resetParser && !stopped)) throw error;
        }
        needsPump = true;
      } while (needsPump && !stopped && !suspended);
    } catch { recover(); }
    finally { pumping = false; }
  };
  const prioritize = () => {
    if (stopped || suspended) return;
    needsPump = true;
    const next = active ? nextSegment() : -1;
    if (active && next !== active.number) {
      const time = current(), at = segmentAt(time);
      if (!video.paused && loaded.has(at)) {
        if (active.rewind && active.number === at - 1) {
          const elapsed = (performance.now() - active.started) / 1000;
          const cost = Math.max(secondsPerByte, active.received > 0 ? elapsed / active.received : 0);
          if (hasPlaybackReserve(time, segmentBytes(active.number) - active.received, cost)) return;
        } else if (active.number > at && next < at && index.segments[active.number].end <= time + forwardRetention) {
          // A buffered rewind can shrink the lookahead window. The pending
          // forward fragment still belongs to this playback and can finish.
          return;
        }
      }
      // Abort only obsolete work. Repeated seeks inside the same GOP share
      // its in-flight response rather than restarting it with each key press.
      resetParser = true;
      active.controller.abort();
    }
    void pump();
  };
  const start = async () => {
    if (stopped) return;
    let manifestRequest;
    const timeout = setTimeout(() => recover(), 2000);
    // The server never waits for a cold remux. One fast native fallback keeps
    // first entry usable, with no polling or duplicate video download.
    try {
      manifestRequest = await request(manifestUrl);
      if (manifestRequest.response.status !== 200) throw Error("segments not ready");
      if (Number(manifestRequest.response.headers.get("Content-Length")) > 128 * 1024) throw Error("large index");
      const text = await manifestRequest.response.text();
      if (text.length > 128 * 1024) throw Error("large index");
      index = JSON.parse(text);
    } finally {
      clearTimeout(timeout);
      if (manifestRequest) requests.delete(manifestRequest.controller);
    }
    if (stopped) return;
    if (index.recipe !== "segments-v1" || !/^avc1\.[0-9a-f]{6}$/.test(index.codec)
        || !/^[0-9a-f]{64}$/.test(index.fingerprint) || !(index.duration > 0 && index.duration <= 120)
        || !Number.isSafeInteger(index.size) || index.size <= 0 || index.size > 1024 ** 3
        || typeof index.init !== "string" || index.init.length > 90 * 1024
        || !Array.isArray(index.segments) || !index.segments.length || index.segments.length > 7200
        || !MediaSource.isTypeSupported(`video/mp4; codecs="${index.codec}"`)) throw Error("unsupported index");
    let end = 0, last = -1;
    for (const segment of index.segments) {
      if (!Number.isFinite(segment.start) || Math.abs(segment.start - end) > .000001
          || !Number.isFinite(segment.end) || segment.end <= segment.start || segment.end - segment.start > 2.2
          || segment.end > index.duration + .001
          || !Number.isSafeInteger(segment.first) || !Number.isSafeInteger(segment.last)
          || segment.first <= last || segment.last < segment.first || segment.last >= index.size) throw Error("invalid index");
      end = segment.end; last = segment.last;
    }
    if (Math.abs(end - index.duration) > .001) throw Error("incomplete index");
    mediaSource = new MediaSource();
    objectUrl = URL.createObjectURL(mediaSource);
    const opened = new Promise((resolve, reject) => {
      listen(mediaSource, "sourceopen", resolve);
      listen(mediaSource, "sourceclose", () => reject(Error("source closed")));
    });
    video.src = objectUrl;
    video.load();
    video.currentTime = current();
    attached();
    await opened;
    if (stopped) return;
    buffer = mediaSource.addSourceBuffer(`video/mp4; codecs="${index.codec}"`);
    mediaSource.duration = index.duration;
    await append(Uint8Array.from(atob(index.init), char => char.charCodeAt(0)));
    if (stopped) return;
    initialized = true;
    listen(video, "seeking", () => {
      boundarySeek = null;
      const time = video.currentTime;
      if (!loaded.has(segmentAt(time))) {
        const ranges = video.buffered;
        for (let i = 0; i < (ranges?.length || 0); i++) {
          const gap = ranges.start(i) - time;
          // A backward seek just outside a cached range can settle on its
          // first frame. Retry once the preceding GOP has actually arrived.
          if (gap > 0 && gap <= frameStepSec) boundarySeek = time;
        }
      }
      prioritize();
    });
    listen(video, "seeked", retryBoundarySeek);
    ["play", "playing", "pause", "timeupdate", "ratechange", "waiting"].forEach(name => listen(video, name, prioritize));
    prioritize();
  };
  // Defer so the caller owns this controller before any fallback can run.
  Promise.resolve().then(start).catch(() => recover());
  return { prioritize, dispose, recover,
    segmentForTime: time => initialized ? segmentAt(time) : null,
    prepareUnbufferedSeek(time) {
      if (!initialized || stopped) return false;
      loaded.delete(segmentAt(time));
      return true;
    },
    suspend() {
      suspended = true;
      if (active) { resetParser = true; active.controller.abort(); }
    },
    resume() { suspended = false; prioritize(); },
  };
}
