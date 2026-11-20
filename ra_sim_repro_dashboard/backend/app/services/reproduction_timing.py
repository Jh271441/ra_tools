"""Behavior reproduction timing, separate from whole-window business counts."""
from collections import Counter

POLICY = 'manual_before_event_v1'
DEFAULT_BAND_MS = 100


def milliseconds(value):
    if type(value) is int and 10**12 <= value < 10**13:
        return value
    if isinstance(value, str) and value.isdecimal():
        return milliseconds(int(value))
    return None


def classify(ra_type, manual_timestamp, scenes, *, boundary_band_ms=DEFAULT_BAND_MS):
    """Scenes are already bound to audited execution inputs; events stay immutable.

    Each scene has start/end timestamps, its original sim_triggered boolean,
    and optional verified events with request_timestamp/publish_timestamp.
    Negative whole-window results imply no earlier request; positive results
    need timestamp evidence before declaring a manual case reproduced.
    """
    if type(boundary_band_ms) is not int or not 0 <= boundary_band_ms <= 1000:
        raise ValueError('reproduction_boundary_band_invalid')
    signals = [s.get('sim_triggered') for s in scenes]
    whole = any(v is True for v in signals) if signals and all(type(v) is bool for v in signals) else None
    def result(status, matched=None, **details):
        return {'policy':POLICY,'boundary_band_ms':boundary_band_ms,
                'whole_window_triggered':whole,'status':status,'matched':matched,**details}
    if whole is None:
        return result('result_missing')
    if type(ra_type) is not int or ra_type not in (2,3):
        return result('trigger_type_unverified')
    if ra_type == 2:
        return result('reproduced' if whole else 'not_reproduced', whole)
    cutoff = milliseconds(manual_timestamp)
    if cutoff is None:
        return result('manual_time_missing')
    windows = [(milliseconds(s.get('start_timestamp')),milliseconds(s.get('end_timestamp'))) for s in scenes]
    if not all(start is not None and end is not None and start <= cutoff < end for start,end in windows):
        return result('manual_window_unverified')
    early, late, edge, missing = [], [], [], False
    for scene,(start,end) in zip(scenes,windows):
        events = scene.get('trigger_events')
        if events is not None and not isinstance(events, list):
            return result('signal_unverified')
        if not scene['sim_triggered']:
            if events:
                return result('signal_conflict')
            continue
        if events is None:
            missing = True
            continue
        if not events:
            return result('signal_conflict')
        for event in events:
            if not isinstance(event,dict):
                return result('signal_unverified')
            request = milliseconds(event.get('request_timestamp'))
            source = event.get('timestamp_source', 'bag_request_and_publication')
            publish = milliseconds(event.get('publish_timestamp'))
            if source == 'dpe_request_event':
                if publish is not None or request is None or not start <= request <= end:
                    return result('signal_unverified')
                offsets = [request-cutoff]
            elif source == 'bag_request_and_publication':
                if request is None or publish is None or not start <= publish <= end:
                    return result('signal_unverified')
                offsets = [request-cutoff, publish-cutoff]
            else:
                return result('signal_unverified')
            detail = {'request_offset_ms':request-cutoff,'timestamp_source':source}
            if publish is not None:
                detail['publish_offset_ms'] = publish-cutoff
            if all(v < -boundary_band_ms for v in offsets):
                early.append(detail)
            elif all(v > boundary_band_ms for v in offsets):
                late.append(detail)
            else:
                edge.append(detail)
    if early:
        return result('before_manual_trigger',False,first_event=min(early,key=lambda e:e['request_offset_ms']))
    if edge:
        return result('boundary_review',first_event=min(edge,key=lambda e:e['request_offset_ms']))
    if missing:
        return result('timing_missing')
    if late:
        return result('after_manual_trigger',True,first_event=min(late,key=lambda e:e['request_offset_ms']))
    return result('reproduced',True)


def summarize(evaluations):
    values = list(evaluations)
    policies = {(v.get('policy'),v.get('boundary_band_ms')) for v in values}
    if len(policies) > 1 or any(policy != POLICY for policy,_ in policies):
        raise ValueError('reproduction_policy_mixed')
    known = [v for v in values if type(v.get('matched')) is bool]
    matched = sum(v['matched'] for v in known)
    complete = bool(values) and len(known) == len(values)
    return {'policy':POLICY,'boundary_band_ms':next(iter(policies))[1] if policies else DEFAULT_BAND_MS,
        'available':complete,'eligible':len(values),'evaluated':len(known),
        'matched':matched,'pending':len(values)-len(known),
        'rate':matched/len(values) if complete else None,
        'covered_rate':matched/len(known) if known else None,
        'statuses':dict(Counter(v['status'] for v in values))}
