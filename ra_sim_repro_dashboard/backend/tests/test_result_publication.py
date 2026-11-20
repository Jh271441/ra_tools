from copy import deepcopy
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.database import Base
from app.models import ReleaseSimulationBatch, ReleaseIssueSnapshot
from app.services.result_integration import import_executions
from app.services.result_publication import approve_publication, publication, validate_standard
from app.services.release_workflow import population_identity
from app.services.release_presentation import render_kpi, history_kpis, context
from test_result_integration import fixture_data, fail, TRIGGER


@pytest.fixture
def data():
    plan, exports = fixture_data()
    for i in range(3, 201):
        scene = {"scenario_id": str(i), "issue_id": f"i{i}", "cohort": "negative_auto"}
        plan["scenarios"].append(scene)
        plan["issues"].append({"issue_id": f"i{i}", "ra_type": 2, "ra_merge_result": "误触发"})
        for e in exports:
            e["rows"].append({**deepcopy(e["rows"][1]), **scene,
                              "task_id": f"{e['job_id']}-{i}", "argument_hash": f"args-{i}"})
    for e in exports:
        e["progress"].update(total=200, completed=200)
    plan["period"] = {"release": plan["release"], "binary_id": 123,
                      "verified": True, "status": "completed"}
    plan["population_hash"] = population_identity(plan)
    for e in exports:
        e["population_hash"] = plan["population_hash"]
    fail(exports[0], 1)
    exports[0]["progress"]["completed"] = 199
    exports[1]["rows"][0][TRIGGER] = -1
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(ReleaseIssueSnapshot(release=plan["release"], period_hash="original", payload=plan))
        for jid in (100, 200):
            db.add(ReleaseSimulationBatch(fingerprint=str(jid), release=plan["release"],
                                         status="failed", payload={**deepcopy(plan), "job_id": jid}))
        db.commit()
        import_executions(db, plan, exports, 100)
        yield db, db.get(ReleaseSimulationBatch, "100"), plan


def test_explicit_exclusion_publishes_primary_without_changing_audit(data, monkeypatch):
    db, batch, plan = data
    before = deepcopy(batch.payload)
    assert publication(batch) is None
    approve_publication(db, batch, plan["population_hash"], ["2"], "User authorized")
    metrics = publication(batch)
    assert metrics["eligible"] == 199 and metrics["precision"] == 1
    assert metrics["publication"]["comparison_conflicts"] == 1
    assert not metrics["quality_gate_passed"] and batch.status == "quality_failed"
    assert batch.payload["result_import"] == before["result_import"]
    assert batch.payload["scenario_results"]["2"]["status"] == "failed"
    kpi = render_kpi(plan["release"], metrics, metrics)
    assert kpi["dpe_coverage"] == .995 and not kpi["quality_gate_passed"]
    # Later source synchronization must not erase or relabel a frozen publication.
    newer = deepcopy(plan)
    newer["issues"].append({"issue_id": "new", "ra_type": 2, "ra_merge_result": "成功"})
    db.add(ReleaseIssueSnapshot(release=plan["release"], period_hash="new", payload=newer))
    db.commit()
    monkeypatch.setattr("app.services.release_presentation.effective_config", lambda _: {
        "periods": [{"release": plan["release"], "status": "completed"}]})
    assert history_kpis(db)[0]["evaluated_cases"] == 199
    monkeypatch.setattr("app.services.release_presentation.status", lambda _: {
        "current_version": plan["release"], "metrics": {"available": False}})
    assert context(db)["business_status"] == "published_with_exclusions"


@pytest.mark.parametrize("case", ["wrong_hash", "wrong_exclusions", "artifact_failure", "secondary"])
def test_unapproved_or_wrong_population_cannot_be_published(data, case):
    db, batch, plan = data
    h, exclusions = plan["population_hash"], ["2"]
    if case == "wrong_hash": h = "other"
    if case == "wrong_exclusions": exclusions = ["1"]
    if case == "secondary": batch = db.get(ReleaseSimulationBatch, "200")
    if case == "artifact_failure":
        p = deepcopy(batch.payload)
        p["result_import"]["failures"][0]["status"] = "quality_failed"
        batch.payload = p
    with pytest.raises(ValueError):
        approve_publication(db, batch, h, exclusions, "User authorized")


def test_changed_results_invalidate_existing_publication(data):
    db, batch, plan = data
    approve_publication(db, batch, plan["population_hash"], ["2"], "User authorized")
    p = deepcopy(batch.payload)
    p["results"]["1"]["sim_triggered"] = False
    batch.payload = p
    assert publication(batch) is None


def test_below_threshold_is_blocked(data):
    _, batch, _ = data
    p = deepcopy(batch.payload)
    p["scenarios"] = [s for s in p["scenarios"] if s["scenario_id"] != "200"]
    del p["results"]["200"]
    del p["scenario_results"]["200"]
    p["result_import"].update(scenario_count=199, valid_scenario_count=198)
    p["execution_progress"].update(total=199, completed=198)
    with pytest.raises(ValueError, match="99.5%"):
        validate_standard(p)


@pytest.mark.parametrize("field,value", [("state", "RUNNING"), ("queued", 1), ("cancelled", 1), ("unknown", 1)])
def test_unfinished_execution_blocked(data, field, value):
    _, batch, _ = data
    p = deepcopy(batch.payload)
    p["execution_progress"][field] = value
    with pytest.raises(ValueError):
        validate_standard(p)


def test_unverified_cycle_blocked(data):
    _, batch, _ = data
    p = deepcopy(batch.payload)
    p["period"]["verified"] = False
    with pytest.raises(ValueError, match="cycle"):
        validate_standard(p)


def ready_for_auto(data, grow=True):
    db, batch, plan = data
    p = deepcopy(batch.payload)
    p['result_import']['comparison']['conflicts'] = []
    for row in p['scenario_results'].values():
        row['conflict'] = False
    if grow:
        from app.services.release_metrics import summarize_population
        p['issues'].append({'issue_id': 'i201', 'ra_type': 2, 'ra_merge_result': '误触发'})
        p['scenarios'].append({**p['scenarios'][-1], 'scenario_id': '201', 'issue_id': 'i201'})
        p['results']['201'] = {**p['results']['200'], 'issue_id': 'i201'}
        p['scenario_results']['201'] = deepcopy(p['scenario_results']['200'])
        p['result_import'].update(scenario_count=201, valid_scenario_count=200, coverage=200/201)
        p['execution_progress'].update(total=201, completed=200)
        p['result_import']['subset_summary'] = summarize_population(
            [i for i in p['issues'] if i['issue_id'] != 'i2'],
            [s for s in p['scenarios'] if s['issue_id'] != 'i2'], p['results'])
        p['population_hash'] = population_identity(p)
        p['result_import']['population_hash'] = p['population_hash']
        db.add(ReleaseIssueSnapshot(release=p['release'], period_hash='grown', payload=deepcopy(p)))
    batch.payload = p
    db.commit()
    return db, batch, plan


def test_auto_publishes_above_threshold_and_is_idempotent(data):
    from app.services.result_publication import reconcile_publications
    db, batch, plan = ready_for_auto(data)
    before = deepcopy(batch.payload['result_import'])
    reconcile_publications(db, {})
    first = deepcopy(batch.payload)
    metrics = publication(batch)
    assert metrics['available'] and metrics['publication']['automatic']
    assert metrics['publication']['coverage'] == 200/201
    assert metrics['publication']['issue_coverage'] == 200/201
    assert batch.payload['result_import'] == before
    assert batch.status == 'quality_failed'
    reconcile_publications(db, {})
    assert batch.payload == first


def test_auto_tolerates_audited_artifact_failure(data):
    from app.services.result_publication import reconcile_publications
    db, batch, _ = ready_for_auto(data)
    p = deepcopy(batch.payload)
    p['scenario_results']['2'].update(status='quality_failed', errors=['unexpected_warning_count'], outcome='Done with warnings')
    p['result_import']['failures'][0].update(p['scenario_results']['2'])
    p['execution_progress'].update(completed=201, failed=0)
    batch.payload=p; db.commit()
    reconcile_publications(db, {})
    metrics=publication(batch)
    assert metrics['available'] and metrics['publication']['quality_failed_count']==1
    assert metrics['publication']['execution_failed_count']==0
    assert batch.payload['scenario_results']['2']['status']=='quality_failed'


@pytest.mark.parametrize('change', ['threshold', 'population', 'conflicts', 'details', 'runtime', 'identity', 'disabled'])
def test_auto_publication_blocks_missing_prerequisites_with_reason(data, change):
    from app.services.result_publication import reconcile_publications
    db,batch,plan=ready_for_auto(data)
    p=deepcopy(batch.payload);config={}
    if change=='threshold': config={'result_publication': {'minimum_coverage': .996}}
    if change=='disabled': config={'result_publication': {'enabled': False}}
    if change=='population':
        newer=deepcopy(plan);newer['issues'][0]['ra_merge_result']='误触发'
        db.add(ReleaseIssueSnapshot(release=plan['release'],period_hash='new',payload=newer))
    if change=='conflicts': p['result_import']['comparison']['conflicts']=['1']
    if change=='details': p['scenario_results']['1']['errors']=['dpe_missing']
    if change=='runtime': p['execution_progress']['state']='RUNNING'
    if change=='identity': p['result_import']['binary_id']=999
    batch.payload=p;db.commit();reconcile_publications(db,config)
    assert publication(batch) is None
    assert batch.payload['publication_decision']['status']=='blocked'
    assert batch.payload['publication_decision']['reason']


def test_policy_change_rechecks_and_does_not_mutate_manual_approval(data):
    from app.services.result_publication import reconcile_publications
    db,batch,plan=data
    approve_publication(db,batch,plan['population_hash'],['2'],'User authorized')
    before=deepcopy(batch.payload)
    reconcile_publications(db,{'result_publication':{'minimum_coverage':1}})
    assert batch.payload==before and publication(batch)


def test_auto_threshold_change_revokes_old_automatic_publication(data):
    from app.services.result_publication import reconcile_publications
    db,batch,_=ready_for_auto(data)
    reconcile_publications(db,{})
    assert publication(batch)
    reconcile_publications(db,{'result_publication':{'minimum_coverage':1}})
    assert not publication(batch)
    assert batch.payload['publication_decision']['status']=='blocked'


@pytest.mark.parametrize('threshold',[True,0,-1,1.1,'NaN','bad'])
def test_invalid_threshold_rejected(threshold):
    from app.services.result_publication import coverage_policy
    with pytest.raises(ValueError):
        coverage_policy({'result_publication':{'minimum_coverage':threshold}})


def test_multiple_scenarios_cannot_hide_missing_issue_coverage(data):
    from app.services.result_publication import validate_coverage_standard
    from app.services.release_metrics import summarize_population
    _,batch,_=ready_for_auto(data)
    p=deepcopy(batch.payload)
    for scene in p['scenarios']:
        if int(scene['scenario_id'])>100:
            scene['issue_id']='i1'
            p['results'][scene['scenario_id']]['issue_id']='i1'
    p['issues']=[i for i in p['issues'] if int(i['issue_id'][1:])<=100]
    p['result_import']['subset_summary']=summarize_population(
        [i for i in p['issues'] if i['issue_id']!='i2'],
        [s for s in p['scenarios'] if s['issue_id']!='i2'],p['results'])
    with pytest.raises(ValueError,match='Issue 覆盖率'):
        validate_coverage_standard(p)


def test_auto_rejects_exact_threshold(data):
    from app.services.result_publication import reconcile_publications
    db, batch, _ = ready_for_auto(data, grow=False)
    reconcile_publications(db, {})
    assert publication(batch) is None
    assert '99.5%' in batch.payload['publication_decision']['reason']


def test_legacy_auto_approval_remains_readable(data):
    from app.services.result_publication import validate_coverage_standard, audit_hash, reconcile_publications
    db, batch, _ = ready_for_auto(data, grow=False)
    p = deepcopy(batch.payload)
    p['publication_approval'] = {**validate_coverage_standard(p, issue_budget=False),
        'policy': 'audited_valid_samples', 'automatic': True, 'approved_at': '2026-10-22T00:00:00Z',
        'audit_hash': audit_hash(p), 'excluded_scenario_ids': ['2']}
    batch.payload = p; db.commit()
    before = deepcopy(p)
    reconcile_publications(db, {})
    assert publication(batch) and batch.payload == before
