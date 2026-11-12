"""Role-aware human conclusions. Pure rules; no I/O or implicit authority."""
from __future__ import annotations

from collections import Counter
import hashlib
import json

TE_USERS = frozenset({'yupuxue', 'zhangxuzhao', 'lishizhong', 'zhangyang'})
RD_REVIEWERS = ('jasperchen', 'liangxianghui')
TE_REVIEWERS = ('yupuxue', 'zhangxuzhao')
FIELDS = {'rd': 'ra_rd_review_result', 'te': 'ra_review_result_sampling',
          'arbitrated': 'ra_review_result_arbitrated'}
VALUES = {'正确触发': '成功', '误触发': '误触发', '无需协助': '无需协助'}
PRIORITY = (FIELDS['arbitrated'], FIELDS['te'], 'ra_review_result_new',
            FIELDS['rd'], 'ra_stuck_auto_result', 'ra_result')
POLICY = 'manual-role-publication-v1'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def initial_role(username):
    return 'te' if username.lower() in TE_USERS else 'rd'


def resolve_role(members, votes, role):
    """Only designated reviewers vote; supplementary opinions are objections.

    Members contain username/role/required. Votes are already current per-author
    heads, with the submission-time role and verified identity. Missing historical
    role evidence is never inferred from the user's current directory entry.
    """
    selected = [m for m in members if m['role'] == role]
    by_author = {v['author']: v for v in votes}
    formal = [by_author[m['username']] for m in selected if m['username'] in by_author]
    eligible = [v for v in formal if v.get('role') == role and v.get('verified')
                and v.get('label') in VALUES]
    outputs = {v['label'] for v in eligible}
    required = {m['username'] for m in selected if m.get('required', True)}
    complete = required <= {v['author'] for v in eligible}
    if not selected:
        state = 'unassigned'
    elif len(outputs) > 1:
        state = 'conflict'
    elif not complete or len(eligible) != len(formal) or not eligible:
        state = 'pending'
    else:
        state = 'resolved'
    label = next(iter(outputs)) if state == 'resolved' else None
    names = {m['username'] for m in members}
    supplemental = [v for v in votes if v['author'] not in names and v.get('role') == role
                    and v.get('verified') and v.get('label') in VALUES]
    sources = [dict(id=v['id'], author=v['author'], role=v.get('role'), label=v.get('label'),
                    label_case_id=v.get('label_case_id',''))
               for v in formal]
    source = dict(role=role, members=selected, votes=sources)
    return dict(state=state, label=label, required=len(required), submitted=len([v for v in eligible if v['author'] in required]),
                source=source, fingerprint=digest(source),
                objections=[v for v in supplemental if label and v['label'] != label],
                supplements=supplemental)


def allocate_role_pairs(issue_ids, *, sampled, seed, previous=(), fixed_rd=None):
    """Stable cumulative quotas with seeded tie breaks and balanced RD×TE pairs."""
    counts = Counter(); pairs = Counter()
    for item in previous:
        counts.update(item['assignees'])
        if len(item['assignees']) == 2:
            pairs[tuple(item['assignees'])] += 1
    result = []
    for iid in sorted(issue_ids, key=lambda x: digest([POLICY, seed, 'order', x])):
        rd_options = [(fixed_rd or {})[iid]] if iid in (fixed_rd or {}) else [p for p in RD_REVIEWERS if counts[p] == min(counts[x] for x in RD_REVIEWERS)]
        if sampled:
            te_options = [p for p in TE_REVIEWERS if counts[p] == min(counts[x] for x in TE_REVIEWERS)]
            rd, te = min(((r, t) for r in rd_options for t in te_options),
                         key=lambda pair: (pairs[pair], digest([seed, 'rd', iid, pair[0]]),
                                           digest([seed, 'te', iid, pair[1]])))
            owners = [rd, te]; pairs[(rd, te)] += 1
        else:
            owners = [min(rd_options, key=lambda p: digest([seed, 'rd', iid, p]))]
        counts.update(owners)
        result.append(dict(issue_id=iid, assignees=owners))
    return result


def effective_metric_label(values):
    """NULL alone falls through; preserve raw field enums and empty strings."""
    for field in PRIORITY:
        if field not in values:
            return dict(state='unknown', field=field, value=None)
        if values[field] is not None:
            return dict(state='observed', field=field, value=values[field])
    return dict(state='empty', field=None, value=None)
