from copy import deepcopy
from unittest.mock import Mock

import httpx
import pytest

from app.services import auto_triage_warehouse as source

SCOPE = {'release': 'gen4-release-20261016', 'date_start': '2026-09-19', 'date_end': '2026-10-28'}


def row(iid, label):
    values = {'成功': (1, 1, 1, 1), '正确触发': (0, 1, 1, 1), '误触发': (0, 1, 0, 0),
              None: (0, 0, 0, 0), '-': (0, 1, 1, 1)}[label]
    result = {'issue_id': iid, 'big_version': '1.' + SCOPE['release'], 'create_date': '2026-10-22',
              'ra_trigger_type': '自触发', 'merged_ra_result': '成功', 'merged_ra_auto_result': label,
              'trip_odd': 'ODD2', 'trip_category_name': 'Daily Cruise/稳定版本测试',
              'version_category': 'release版本', 'is_deleted': 0, 'auto_is_null': int(label is None),
              'baseline_is_null': 0, 'population_count': 1}
    for i, name in enumerate(('precision_numerator', 'precision_denominator', 'recall_numerator', 'recall_denominator')):
        result['auto_' + name] = values[i]
        result['baseline_' + name] = 1
    return result


class Report:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []
        self.total_delta_on_page2 = False

    def read(self, payload):
        self.calls.append(deepcopy(payload))
        sl = payload['slices'][0]
        if len(sl['dims']) == 1:
            selected = [{'big_version': '1.' + SCOPE['release'],
                         **{m['columnName']: sum(r[m['columnName']] for r in self.rows) for m in sl['metrics']}}]
        else:
            offset = (sl['pageIndex'] - 1) * sl['pageSize']
            selected = deepcopy(self.rows[offset:offset + sl['pageSize']])
            for r in selected:
                if r['merged_ra_auto_result'] is None:
                    r['merged_ra_auto_result'] = '-'
        nodes = [{c['dataSourceCode'] + '.' + c['columnCode']: r.get(c['columnName'])
                  for c in sl['dims'] + sl['metrics']} for r in selected]
        return {'dsDatas': {'nodes': nodes}, 'pagination': {'totalItems': len(self.rows) + int(self.total_delta_on_page2 and sl['pageIndex'] == 2)},
                'queryMeta': {'queryId': 'reference-' + str(len(self.calls))}, 'searchStatus': 'stop'}


def test_literal_correct_trigger_and_sql_null_are_independent_from_display():
    report = Report([row('correct', '正确触发'), row('null', None), row('literal-dash', '-')])
    receipt = source.fetch(SCOPE, report)
    rows = {r['issue_id']: r for r in receipt['rows']}
    assert rows['correct']['merged_ra_auto_result'] == '正确触发'
    assert rows['null']['merged_ra_auto_result'] is None
    assert rows['literal-dash']['merged_ra_auto_result'] == '-'
    assert receipt['counts']['auto_precision_numerator'] == 0
    assert receipt['counts']['auto_precision_denominator'] == 2
    assert receipt['counts']['auto_recall_numerator'] == 2
    filters = {f['columnName']: f['values'] for f in report.calls[0]['slices'][0]['filters']}
    assert filters['create_date'] == ['2026-09-19', '2026-10-28']
    assert filters['big_version'] == ['1.gen4-release-20261016']
    assert 'abnormal_behavior' not in filters and 'platform_gen' not in filters


def test_all_pages_required_and_backend_count_changes_fail_closed():
    report = Report([row(str(i), '成功') for i in range(2001)])
    receipt = source.fetch(SCOPE, report)
    assert len(receipt['rows']) == 2001 and len(receipt['references']) == 2
    report.total_delta_on_page2 = True
    with pytest.raises(ValueError, match='dashboard_query_incomplete'):
        source.fetch(SCOPE, report)


def test_duplicate_issues_and_wrong_sql_memberships_are_rejected():
    with pytest.raises(ValueError, match='dashboard_population_mismatch'):
        source.fetch(SCOPE, Report([row('same', '成功'), row('same', '成功')]))
    bad = row('correct', '正确触发')
    bad['auto_precision_numerator'] = 1
    with pytest.raises(ValueError, match='dashboard_membership_mismatch'):
        source.fetch(SCOPE, Report([bad]))


def test_missing_null_indicator_is_not_guessed_from_dash():
    bad = row('null', None)
    del bad['auto_is_null']
    with pytest.raises(ValueError, match='dashboard_null_projection_missing'):
        source.fetch(SCOPE, Report([bad]))


def test_query_continuation_uses_existing_query_and_not_new_sql(monkeypatch):
    client = source.Client.__new__(source.Client)
    client._post = Mock(side_effect=[{'searchStatus': 'continue', 'queryId': 'existing-query'},
                                     {'searchStatus': 'stop', 'dsDatas': {'nodes': []}}])
    monkeypatch.setattr(source.time, 'sleep', lambda _: None)
    client.read({'slices': ['original-query']})
    followup = client._post.call_args_list[1].args[0]
    assert followup['queryId'] == 'existing-query' and 'slices' not in followup
    assert followup['reportId'] == 288969 and followup['sliceId'] == 13096015


def test_missing_or_expired_login_never_follows_sso_redirect(monkeypatch, tmp_path):
    monkeypatch.setenv('AUTO_TRIAGE_SHUYI_STORAGE_STATE', str(tmp_path / 'missing.json'))
    with pytest.raises(ValueError, match='dashboard_login_required'):
        source.Client()
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(302, headers={'location': 'https://me.xiaojukeji.com/login'})
    client = source.Client.__new__(source.Client)
    client.http = httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=False)
    try:
        with pytest.raises(ValueError, match='dashboard_login_required'):
            client.read({})
        assert len(calls) == 1
    finally:
        client.close()


def test_scope_dates_are_inclusive_and_require_both_boundaries():
    period = {'release': SCOPE['release'], 'case_start': '2026-10-22T00:00:00+08:00', 'case_end_exclusive': '2026-10-29T00:00:00+08:00'}
    assert source.scope_for(period)['date_end'] == '2026-10-28'
    with pytest.raises(ValueError, match='dashboard_dates_required'):
        source.scope_for(period, '2026-10-22')
    with pytest.raises(ValueError, match='dashboard_dates_invalid'):
        source.scope_for(period, '2026-10-29', '2026-10-22')
