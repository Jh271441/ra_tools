from copy import deepcopy
import sqlite3

import pytest

from app.services import evaluation_pipeline as pipeline
from app.services import metric_profiles as profiles
from app.services import recall_comparison as comparison


def sample_rows():
    values = [
        (2, '成功', True, 'reused'),
        (2, '正确触发', False, 'reused'),
        (3, '正确触发', True, 'reused'),
        (3, '成功', True, 'reused'),
        (3, '成功', None, 'missing_result'),
        (2, '误触发', False, 'reused'),
        (2, None, True, 'reused'),
    ]
    return [dict(issue_id=str(i), issue_topic='', ra_type=road, auto_label=label,
                 sim_triggered=triggered, result_status=status, eligible=label is not None,
                 changed=False) for i, (road, label, triggered, status) in enumerate(values)]


def test_paired_delta_matches_independent_sql_and_keeps_missing_results_unknown():
    rows = sample_rows()
    original = deepcopy(rows)
    with sqlite3.connect(':memory:') as db:
        db.execute('CREATE TABLE rows(road INT, label TEXT, sim INT, status TEXT)')
        db.executemany('INSERT INTO rows VALUES(?,?,?,?)',
                       [(r['ra_type'], r['auto_label'], r['sim_triggered'], r['result_status']) for r in rows])
        source_n, sim_n, denominator = db.execute("""
            SELECT SUM(road=2), SUM(sim=1), COUNT(*) FROM rows
            WHERE status='reused' AND label NOT IN ('误触发','out_of_scope','未接起','未填写')
        """).fetchone()
    value = comparison.compare(rows, profiles.DEFAULT_CONFIG)
    assert (value['road_numerator'], value['sim_numerator']) == (source_n, sim_n) == (2, 3)
    assert value['road_denominator'] == value['sim_denominator'] == denominator == 4
    assert (value['gains'], value['losses'], value['net']) == (2, 1, 1)
    assert value['gap'] == pytest.approx(.25)
    assert value['covered'] == 5 and not value['behavior_validated']
    assert [comparison.transition(r, profiles.DEFAULT_CONFIG) for r in rows] == [
        None, 'recall_loss', 'recall_gain', 'recall_gain', None, None, None]
    assert rows == original


def test_custom_trigger_dependent_denominator_does_not_claim_net_divided_by_count():
    config = deepcopy(profiles.DEFAULT_CONFIG)
    config['memberships']['recall_denominator']['triggers'] = [2]
    value = comparison.compare(sample_rows(), config)
    assert value['road_denominator'] == 2 and value['sim_denominator'] == 1
    assert value['denominator_changed'] == 1
    assert value['net'] == -1 and value['gap'] == 0
    assert value['gains'] == 0


def test_difference_filters_paginate_and_never_include_missing_or_negative_cases(monkeypatch):
    rows = sample_rows()
    rows += [dict(rows[2], issue_id=f'gain-{i}') for i in range(20)]
    monkeypatch.setattr(pipeline, 'current_revision', lambda *a, **k: {'rows': rows, 'revision_key': 'immutable'})
    monkeypatch.setattr(pipeline.profiles, 'get', lambda *a: profiles.BUILTIN)
    page = pipeline.issue_page(None, coverage='recall_gain', page=2, page_size=10)
    assert (page['total'], page['pages'], len(page['items'])) == (22, 3, 10)
    assert all(row['ra_type'] == 3 and row['sim_triggered'] is True for row in page['items'])
    losses = pipeline.issue_page(None, coverage='recall_loss', page_size=10)
    assert [row['issue_id'] for row in losses['items']] == ['1']
    assert pipeline.issue_page(None, coverage='recall_gain', query='gain-19', page_size=10)['total'] == 1
    with pytest.raises(ValueError, match='invalid_pagination'):
        pipeline.issue_page(None, coverage='unknown')
