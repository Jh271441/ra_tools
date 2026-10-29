"""Deployment guard tests: no network calls or service mutations."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from contextlib import ExitStack

spec = importlib.util.spec_from_file_location("deploy_cloud", Path(__file__).parents[1] / "scripts/deploy_cloud.py")
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)

class DeployTests(unittest.TestCase):
    def test_additive_migration_guard_accepts_only_new_safe_sql(self):
        path = "ra_triage_dashboard/migrations/postgres/036_safe.sql"
        safe = """BEGIN;
ALTER TABLE intent_case_comments
    ADD COLUMN IF NOT EXISTS mentions_json jsonb NOT NULL DEFAULT '[]'::jsonb;
CREATE TABLE IF NOT EXISTS intent_comment_notifications (id bigserial PRIMARY KEY);
CREATE INDEX IF NOT EXISTS idx_intent_comment_notifications
    ON intent_comment_notifications(id);
COMMIT;
"""
        d.validate_additive_migration_sql(path, safe)
        d.validate_additive_migration_sql(
            "ra_triage_dashboard/migrations/postgres/044_model_reviews.sql",
            """BEGIN;
CREATE VIEW review_records AS SELECT 1 AS id;
CREATE VIEW review_record_attachments AS SELECT 1 AS id;
COMMIT;
""",
        )
        for unsafe in (
            "BEGIN; DROP TABLE intent_case_comments; COMMIT;",
            "BEGIN; ALTER TABLE intent_case_comments RENAME TO old_comments; COMMIT;",
            "BEGIN; UPDATE intent_case_comments SET body = ''; COMMIT;",
        ):
            with self.assertRaises(d.DeployError):
                d.validate_additive_migration_sql(path, unsafe)

        def git(*args, **_kwargs):
            if args[:2] == ("diff", "--name-only"):
                return path
            if args[:2] == ("diff", "--name-status"):
                return f"A\t{path}"
            if args[0] == "show":
                return safe
            raise AssertionError(args)

        with patch.object(d, "git", side_effect=git):
            with self.assertRaises(d.DeployError):
                d.migration_changes("old", "new")
            self.assertEqual(
                d.migration_changes("old", "new", allow_additive=True),
                [path],
            )

    def test_schema_migration_guard_accepts_only_reviewed_intent_constraints(self):
        path = "ra_triage_dashboard/migrations/postgres/038_intent_lane_change_taxonomy.sql"
        safe = """BEGIN;
ALTER TABLE intent_label_revisions
    DROP CONSTRAINT IF EXISTS intent_label_revisions_lane_change_default_check;
ALTER TABLE intent_label_revisions
    ADD CONSTRAINT intent_label_revisions_lane_change_default_check
    CHECK (lane_change_default IS NULL OR lane_change_default IN ('lane_change'));
COMMIT;
"""
        d.validate_schema_migration_sql(path, safe)
        for unsafe in (
            "BEGIN; ALTER TABLE intent_label_revisions DROP COLUMN lane_change_default; COMMIT;",
            "BEGIN; ALTER TABLE other_table DROP CONSTRAINT IF EXISTS other_check; COMMIT;",
            "BEGIN; DELETE FROM intent_label_revisions; COMMIT;",
        ):
            with self.assertRaises(d.DeployError):
                d.validate_schema_migration_sql(path, unsafe)

    def test_additive_migration_runs_verified_backup_before_apply(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate = root / "candidate"
            scripts = candidate / "ra_triage_dashboard/scripts"
            scripts.mkdir(parents=True)
            record = root / "record"
            record.mkdir()
            data = root / "data"
            backup_root = data / "postgres_backups"
            backup_root.mkdir(parents=True)
            backup = backup_root / "ra_triage_dashboard-20260913T120000Z.dump"
            backup.touch()
            calls = []

            def run(*args, **kwargs):
                calls.append(args)
                if args[0] == "bash" and Path(args[1]).name == "backup_cloud_postgres.sh":
                    return MagicMock(stdout=f"{backup}\n".encode())
                if args[0] == d.PYTHON:
                    return MagicMock(stdout=b"36\n")
                return MagicMock(stdout=b"")

            with patch.object(d, "run", side_effect=run):
                result = d.apply_additive_migrations(
                    candidate,
                    {"DASHBOARD_DATA_DIR": str(data)},
                    ["ra_triage_dashboard/migrations/postgres/036_safe.sql"],
                    record,
                    35,
                )

            self.assertEqual(result, (str(backup.resolve()), 36))
            self.assertEqual(Path(calls[0][1]).name, "backup_cloud_postgres.sh")
            self.assertEqual(Path(calls[1][1]).name, "verify_cloud_postgres_backup.sh")
            self.assertEqual(calls[2][0], d.PYTHON)

    def test_gray_isolates_database_and_all_writers(self):
        env = {k: "true" for k in d.OFF}
        env.update(DASHBOARD_DATA_DIR="/production", DASHBOARD_DATABASE_URL_FILE="/production/postgres_url",
                   DASHBOARD_RA_MODEL_PROFILE_PATH=str(d.REPO / "ra_triage_dashboard/config/model_profiles.json"))
        result = d.gray_env(env, Path("/candidate"), Path("/isolated"), "a" * 40)
        self.assertEqual(result["DASHBOARD_DATABASE_URL"], "sqlite:////isolated/triage.sqlite3")
        self.assertEqual(result["DASHBOARD_DATABASE_URL_FILE"], "")
        self.assertEqual(result["DASHBOARD_RA_MODEL_PROFILE_PATH"], "/candidate/ra_triage_dashboard/config/model_profiles.json")
        self.assertTrue(all(result[k] == "false" for k in d.OFF))
        self.assertEqual(env["DASHBOARD_DATA_DIR"], "/production")

    def test_credentials_are_file_only(self):
        for key in ("DASHBOARD_DATABASE_URL", "DASHBOARD_API_KEY", "DASHBOARD_SECRET"):
            with self.assertRaises(d.DeployError):
                d.capture_env({"DASHBOARD_DATABASE_URL_FILE": "/db", key: "secret"})
        env = d.capture_env({"DASHBOARD_DATABASE_URL_FILE": "/db", "DASHBOARD_RA_MODEL_API_KEY_FILE": "/key", "UNRELATED_SECRET": "secret"})
        self.assertNotIn("UNRELATED_SECRET", env)
        self.assertEqual(env["DASHBOARD_RA_MODEL_API_KEY_FILE"], "/key")

    def test_runtime_policy_is_preserved(self):
        env = {"DASHBOARD_DATABASE_URL_FILE": "/db", "DASHBOARD_BASE_PATH": "/manual", "DASHBOARD_DEPLOYMENT_MODE": "development", "DASHBOARD_TRAIL_ATTRIBUTE_WRITE_ENABLED": "true"}
        self.assertEqual(d.capture_env(env), env)

    def test_health_rejects_wrong_version_backend_and_writers(self):
        health = dict(ok=True, build_commit="a"*40, storage="sqlite-mvp", trail_attribute_write_enabled=False, trail_rd_write_enabled=False,
                      trail_attribute_review_write_enabled=False, batch_prediction_enabled=False, autotriage_push_enabled=False)
        d.check_health(health, "a"*40, "sqlite")
        for changes in ({"build_commit": "b"*40}, {"storage": "postgresql"}, {"batch_prediction_enabled": True}, {"trail_rd_write_enabled": True}, {"ok": False}):
            with self.assertRaises(d.DeployError):
                d.check_health(dict(health, **changes), "a"*40, "sqlite")
        legacy = dict(health); legacy.pop('trail_rd_write_enabled')
        self.assertEqual(d.policy(legacy), d.policy(health))
        self.assertNotEqual(d.policy(legacy), d.policy(dict(health, trail_rd_write_enabled=True)))

    def test_lock_excludes_parallel_deployments(self):
        with tempfile.TemporaryDirectory() as temp:
            with d.deployment_lock(Path(temp)):
                with self.assertRaises(d.DeployError):
                    with d.deployment_lock(Path(temp)):
                        pass
            with d.deployment_lock(Path(temp)):
                pass

    def test_record_permissions(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"result.json"
            d.save(path, {"status": "ok"})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text()), {"status": "ok"})

    def test_release_ids_remain_unique_within_one_second(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(d, "STATE", Path(temp)), patch.object(d.time, "strftime", return_value="20260916T080000Z"):
            first_id, first = d.create_release_folder("a" * 40)
            second_id, second = d.create_release_folder("a" * 40)
        self.assertEqual(first_id, "20260916T080000Z-aaaaaaaaaaaa")
        self.assertEqual(second_id, "20260916T080000Z-aaaaaaaaaaaa-01")
        self.assertNotEqual(first, second)

    def test_cleanup_retains_latest_two_failed_and_busy(self):
        with tempfile.TemporaryDirectory() as temp:
            state=Path(temp); folders=[]
            for i in range(5):
                folder=state/"releases"/str(i); folder.mkdir(parents=True)
                for name in ("candidate","rollback","gray-data"): (folder/name).mkdir()
                d.save(folder/"result.json", {"status": "failed" if i==4 else "success", "candidate": str(folder/"candidate"), "rollback": str(folder/"rollback")})
                folders.append(folder)
            removed=[]
            def remove(*args, **kwargs):
                path=Path(args[-1]); removed.append(path); path.rmdir()
            with patch.object(d,"git",return_value=""), patch.object(d,"in_use",side_effect=lambda path: str(path).startswith(str(folders[1]))), patch.object(d,"run",side_effect=remove):
                d.cleanup(state,folders[3])
            self.assertEqual(set(removed),{folders[0]/"candidate",folders[0]/"rollback"})
            self.assertFalse((folders[0]/"gray-data").exists())
            for folder in folders[1:]: self.assertTrue((folder/"candidate").exists())

    def test_cleanup_preserves_noncache_ignored_files(self):
        with tempfile.TemporaryDirectory() as temp:
            state=Path(temp)
            for i in range(3):
                folder=state/"releases"/str(i); folder.mkdir(parents=True)
                for name in ("candidate","rollback"): (folder/name).mkdir()
                d.save(folder/"result.json",{"status":"success","candidate":str(folder/"candidate"),"rollback":str(folder/"rollback")})
            def git(*args,**kwargs): return "local.sqlite3" if args[0]=="ls-files" else ""
            with patch.object(d,"git",side_effect=git),patch.object(d,"in_use",return_value=False),patch.object(d,"run") as run:
                d.cleanup(state,folder)
            run.assert_not_called()

    def test_cleanup_skips_legacy_success_record_without_worktree_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp)
            legacy = state / "releases" / "20260909T042751Z-schema-e6d7ccdd3437"
            legacy.mkdir(parents=True)
            (legacy / "gray-data").mkdir()
            d.save(legacy / "result.json", {"status": "success", "target": "a" * 40})
            current = state / "releases" / "20260916T073312Z-dd5f248425ac"
            current.mkdir()
            d.save(current / "result.json", {
                "status": "success",
                "candidate": str(current / "candidate"),
                "rollback": str(current / "rollback"),
            })

            with patch.object(d, "run") as run:
                self.assertEqual(d.cleanup(state, current), [])

            run.assert_not_called()
            self.assertTrue((legacy / "gray-data").is_dir())

    def test_zombie_process_counts_as_stopped(self):
        with patch.object(d.Path,"read_text",return_value="27205 (python3) Z 17766 27205"):
            self.assertFalse(d.process_alive(27205))
        with patch.object(d.Path,"read_text",return_value="27205 (python3) S 17766 27205"):
            self.assertTrue(d.process_alive(27205))
        with patch.object(d.Path,"read_text",side_effect=FileNotFoundError):
            self.assertFalse(d.process_alive(27205))

    def test_stop_waits_for_tmux_session_cleanup(self):
        with patch.object(d,"git_pane_pid",return_value=123), patch.object(d.os,"kill"), patch.object(d,"process_alive",return_value=False), patch.object(d.subprocess,"run",side_effect=[type("R",(),{"returncode":0})(),type("R",(),{"returncode":1})()]), patch.object(d.time,"sleep") as sleep:
            d.stop_production(123)
            sleep.assert_called_once_with(0.1)

    def test_stop_refuses_changed_process(self):
        with patch.object(d,"git_pane_pid",return_value=456),patch.object(d.os,"kill") as kill:
            with self.assertRaises(d.DeployError): d.stop_production(123)
            kill.assert_not_called()

    def test_slow_shutdown_retains_ownership_past_30_seconds(self):
        signalled = MagicMock()
        with patch.object(d,"git_pane_pid",return_value=123), patch.object(d.os,"kill") as kill, patch.object(d,"process_alive",side_effect=[True,True,False]), patch.object(d.time,"monotonic",side_effect=[0,31,31,32]), patch.object(d.time,"sleep"), patch.object(d.subprocess,"run",return_value=type("R",(),{"returncode":1})()), patch("builtins.print") as output:
            d.stop_production(123,on_signal=signalled)
        kill.assert_called_once_with(123,d.signal.SIGTERM)
        signalled.assert_called_once_with()
        self.assertIn("retaining deployment ownership",output.call_args.args[0])

    def test_shutdown_never_takes_over_replaced_session(self):
        with patch.object(d,"process_alive",return_value=False), patch.object(d.subprocess,"run",return_value=type("R",(),{"returncode":0})()), patch.object(d,"git_pane_pid",return_value=456):
            with self.assertRaisesRegex(d.DeployError,"another process"):
                d.wait_production_stopped(123)

    def simulate_release(self, fail_tests=False, fail_production=False, prepare_only=False, runtime_changed=False, fail_stop=False, isolated=False, branch_changed=False, checkout_changed=False):
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            base=Path(temp); repo=base/"repo"; repo.mkdir(); python=base/"python"; python.touch()
            env={"DASHBOARD_DATABASE_URL_FILE":"/db", "DASHBOARD_DATA_DIR":str(base/"data")}
            target="a"*40; old="b"*40
            stack.enter_context(patch.object(d,"REPO",repo))
            stack.enter_context(patch.object(d,"STATE",base/"state"))
            stack.enter_context(patch.object(d,"PYTHON",python))
            stack.enter_context(patch.object(d.sys,"platform","linux"))
            reads = {}
            def git(*args, **kwargs):
                if args[0]=="branch": return "master"
                if args[0]=="rev-parse" and args[1].startswith("origin/"):
                    reads['ref'] = reads.get('ref', 0) + 1
                    return "c"*40 if branch_changed and reads['ref'] >= 3 else target
                if args[0]=="rev-parse" and args[1]=="HEAD":
                    if "cwd" not in kwargs:
                        reads['head'] = reads.get('head', 0) + 1
                        return "c"*40 if checkout_changed and reads['head'] >= 3 else old
                    return old if Path(kwargs["cwd"]).name == "rollback" else target
                return ""
            stack.enter_context(patch.object(d,"git",side_effect=git))
            live_calls = 0
            def read_live():
                nonlocal live_calls
                live_calls += 1
                return (12 if runtime_changed and live_calls >= 3 else 11, env)
            stack.enter_context(patch.object(d,"read_live",side_effect=read_live))
            health={"ok":True,"build_commit":old,"storage":"postgresql"}
            stack.enter_context(patch.object(d,"get_json",return_value=health))
            stack.enter_context(patch.object(d.socket,"socket"))
            def run(*args,**kwargs):
                if fail_tests and "pytest" in args: raise subprocess.CalledProcessError(1,["pytest"])
                if args[:4] == ("git", "worktree", "add", "--detach"):
                    Path(args[4]).mkdir(parents=True)
                return MagicMock()
            runner=stack.enter_context(patch.object(d,"run",side_effect=run))
            stack.enter_context(patch.object(d.subprocess,"Popen"))
            stack.enter_context(patch.object(d,"stop_child"))
            stack.enter_context(patch.object(d,"process_alive",return_value=False))
            def stopping(pid, *, on_signal=None):
                if on_signal:
                    on_signal()
                if fail_stop:
                    raise d.DeployError("Interrupted after SIGTERM")
            stop=stack.enter_context(patch.object(d,"stop_production",side_effect=stopping))
            wait=stack.enter_context(patch.object(d,"wait_production_stopped"))
            start=stack.enter_context(patch.object(d,"start_production"))
            stack.enter_context(patch.object(d,"git_pane_pid",return_value=22))
            stack.enter_context(patch.object(d,"cleanup",return_value=[]))
            def smoke(port,sha,storage):
                if fail_production and port==8785 and sha==target: raise d.DeployError("failed health")
                return dict(health,build_commit=sha,storage=storage)
            stack.enter_context(patch.object(d,"smoke",side_effect=smoke))
            options=dict(isolated_ref="codex/layout-only",expected_live_sha=old) if isolated else {}
            if fail_tests or fail_production or runtime_changed or fail_stop or branch_changed or checkout_changed:
                with self.assertRaises((d.DeployError,subprocess.CalledProcessError)): d.deploy(target, **options)
            elif prepare_only:
                d.prepare_release(target, **options)
            else: d.deploy(target, **options)
            if isolated:
                self.assertFalse(any(c.args[:2] == ('git','merge') for c in runner.call_args_list))
            record=json.loads(next((base/"state/releases").glob("*/result.json")).read_text())
            if fail_stop:
                wait.assert_called_once_with(11)
            return stop.call_args_list,start.call_args_list,record

    def test_isolated_release_uses_owned_candidate_without_merging_master(self):
        stops, starts, record = self.simulate_release(isolated=True)
        self.assertEqual(record['status'], 'success')
        self.assertEqual(record['isolated_ref'], 'codex/layout-only')
        self.assertEqual(starts[0].args[1], Path(record['candidate']) / 'ra_triage_dashboard')
        self.assertEqual(len(stops), 1)

    def test_isolated_gates_and_rollback_remain_enabled(self):
        for failure in ('fail_tests', 'runtime_changed', 'branch_changed', 'checkout_changed'):
            with self.subTest(failure=failure):
                stops, starts, _ = self.simulate_release(isolated=True, **{failure: True})
                self.assertEqual(stops, [])
                self.assertEqual(starts, [])
        _, starts, record = self.simulate_release(isolated=True, fail_production=True)
        self.assertEqual(record['rollback_status'], 'healthy')
        self.assertEqual(starts[-1].args[3], 'b'*40)

    def test_isolation_requires_explicit_safe_ref_and_live_pin(self):
        self.assertEqual(d.release_ref('codex/layout-only','b'*40), 'origin/codex/layout-only')
        for ref, sha in [('', 'b'*40), ('master','b'*40), ('codex/../main','b'*40), ('codex/x',''), ('codex/x','short')]:
            with self.subTest(ref=ref), self.assertRaises(d.DeployError):
                d.release_ref(ref, sha)

    def test_isolated_preflight_rejects_stale_live_pin_and_migrations(self):
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            repo=Path(temp); python=repo/'python'; python.touch()
            for name,value in [('REPO',repo),('PYTHON',python)]:
                stack.enter_context(patch.object(d,name,value))
            stack.enter_context(patch.object(d.sys,'platform','linux'))
            runner=stack.enter_context(patch.object(d,'run'))
            stack.enter_context(patch.object(d,'git',side_effect=lambda *a: 'master' if a[0]=='branch' else ('a'*40 if a[0]=='rev-parse' else '')))
            stack.enter_context(patch.object(d,'read_live',return_value=(11,{})))
            stack.enter_context(patch.object(d,'get_json',return_value=dict(ok=True,build_commit='c'*40,storage='postgresql')))
            with self.assertRaisesRegex(d.DeployError,'Production changed'):
                d.preflight('a'*40,isolated_ref='codex/layout-only',expected_live_sha='b'*40)
            runner.reset_mock()
            with self.assertRaisesRegex(d.DeployError,'do not permit migrations'):
                d.preflight('a'*40,allow_additive_migrations=True,isolated_ref='codex/layout-only',expected_live_sha='c'*40)
            runner.assert_not_called()

    def test_live_candidate_requires_matching_private_success_receipt(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(d,'STATE',Path(temp)), patch.object(d,'validate_prepared_worktree') as validate:
            folder=Path(temp)/'releases'/'20261028T120000Z-aaaaaaaaaaaa'
            app=folder/'candidate'/'ra_triage_dashboard'; app.mkdir(parents=True)
            record=dict(status='success',isolated_ref='codex/layout-only',target='a'*40,candidate=str(app.parent))
            d.save(folder/'result.json',record)
            d.validate_live_candidate(app,'a'*40)
            validate.assert_called_once_with(app.parent,'a'*40)
            with self.assertRaises(d.DeployError): d.validate_live_candidate(app,'b'*40)
            for key,value in [('status','prepared'),('isolated_ref',''),('candidate','/tmp/other')]:
                d.save(folder/'result.json',dict(record,**{key:value}))
                with self.assertRaises(d.DeployError): d.validate_live_candidate(app,'a'*40)
            d.save(folder/'result.json',record)
            (folder/'result.json').chmod(0o644)
            with self.assertRaises(d.DeployError): d.validate_live_candidate(app,'a'*40)

    def test_test_failure_never_stops_production(self):
        stops,starts,record=self.simulate_release(fail_tests=True)
        self.assertEqual(stops,[]); self.assertEqual(starts,[])
        self.assertEqual(record["status"],"failed")

    def test_prepare_stops_before_production_changes(self):
        stops, starts, record = self.simulate_release(prepare_only=True)
        self.assertEqual(stops, [])
        self.assertEqual(starts, [])
        self.assertEqual(record["status"], "prepared")
        self.assertEqual(record["migration_mode"], "none")

    def test_promote_rejects_runtime_change_after_prepare(self):
        stops, starts, record = self.simulate_release(runtime_changed=True)
        self.assertEqual(stops, [])
        self.assertEqual(starts, [])
        self.assertEqual(record["status"], "prepared")

    def test_failed_production_restores_previous_sha(self):
        stops,starts,record=self.simulate_release(fail_production=True)
        self.assertEqual([c.args[0] for c in stops],[11,22])
        self.assertEqual(starts[1].args[3],"b"*40)
        self.assertEqual(record["rollback_status"],"healthy")
        self.assertEqual(record["status"],"failed")

    def test_failure_after_signal_waits_then_recovers_previous_sha(self):
        stops,starts,record=self.simulate_release(fail_stop=True)
        self.assertEqual(len(stops),1)
        self.assertEqual(starts[0].args[3],"b"*40)
        self.assertEqual(record["rollback_status"],"healthy")

    def test_success_records_verified_target(self):
        stops,starts,record=self.simulate_release()
        self.assertEqual(len(stops),1); self.assertEqual(len(starts),1)
        self.assertEqual(record["target"],"a"*40)
        self.assertEqual(record["status"],"success")
        self.assertEqual(record["schema_version"], d.RECORD_SCHEMA_VERSION)
        self.assertIn("prepared_at", record)
        self.assertIn("promoted_at", record)

    def test_persistent_credential_files_are_not_rebased_to_untracked_release_files(self):
        env = {key: "/repo/private/value.json" for key in (
            "DASHBOARD_DCHAT_CREDENTIALS_FILE", "DASHBOARD_DATABASE_URL_FILE",
            "DASHBOARD_TRUSTED_INGRESS_TOKEN_FILE")}
        env["DASHBOARD_BASELINES_FILE"] = "/repo/config/baselines.json"
        rebased = d.rebase_env(env, "/repo", "/release")
        for key in env:
            self.assertEqual(rebased[key], "/release/config/baselines.json" if key == "DASHBOARD_BASELINES_FILE" else env[key])

    def test_smoke_rejects_enabled_notifications_with_missing_credentials(self):
        health = {"ok": True}
        status = {"database": {"ok": True, "persistent_data": True}, "overall": {"status": "healthy"},
                  "review_notifications": {"enabled": True, "delivery_mode": "openapi", "credentials": {"ready": False}}}
        response = MagicMock(); response.__enter__.return_value.status = 200
        opener = MagicMock(); opener.open.return_value = response
        with patch.object(d, "wait_health", return_value=health), patch.object(d, "get_json", return_value=status), patch.object(d.urllib.request, "build_opener", return_value=opener):
            with self.assertRaisesRegex(d.DeployError, "credentials"):
                d.smoke(8785, "a" * 40, "postgresql")
            # Explicit repair preflight may inspect the known-broken old service;
            # promotion always uses the default strict notification gate.
            self.assertEqual(d.smoke(8785, "a" * 40, "postgresql", require_notifications=False), health)
            status["review_notifications"]["credentials"]["ready"] = True
            self.assertEqual(d.smoke(8785, "a" * 40, "postgresql"), health)

    def test_rebase_only_changes_checkout_paths(self):
        env={"a":"/repo/app/file","b":"/repo-other/file","c":"/data/media"}
        self.assertEqual(d.rebase_env(env,"/repo","/gray"),{"a":"/gray/app/file","b":"/repo-other/file","c":"/data/media"})

if __name__ == "__main__": unittest.main()
