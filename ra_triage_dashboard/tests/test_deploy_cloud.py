"""Deployment guard tests: no network calls or service mutations."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock
from contextlib import ExitStack, contextmanager

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

    def test_reviewed_comment_index_requires_exact_migration_and_explicit_mode(self):
        path = "ra_triage_dashboard/migrations/postgres/060_comment_submission_ids.sql"
        content = (Path(__file__).parents[2] / path).read_text()
        d.validate_additive_migration_sql(path, content)
        for changed_path, changed_content in (
            (path.replace("060_", "061_"), content),
            (path, content.replace("lower(author)", "author")),
            (path, content + "\n-- unreviewed change"),
            (path, "BEGIN; CREATE UNIQUE INDEX IF NOT EXISTS arbitrary ON issues(issue_id); COMMIT;"),
        ):
            with self.assertRaises(d.DeployError):
                d.validate_additive_migration_sql(changed_path, changed_content)

        def git(*args, **kwargs):
            if args[:2] == ("diff", "--name-only"):
                return path
            if args[:2] == ("diff", "--name-status"):
                return "A\t" + path
            if args[0] == "show":
                return content
            raise AssertionError(args)
        with patch.object(d, "git", side_effect=git):
            with self.assertRaises(d.DeployError):
                d.migration_changes("old", "new")
            self.assertEqual(d.migration_changes("old", "new", allow_additive=True), [path])

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

    def test_role_publication_triggers_require_exact_review_and_migration_mode(self):
        path = "ra_triage_dashboard/migrations/postgres/061_human_label_publication.sql"
        content = (Path(__file__).parents[2] / path).read_text()
        d.validate_additive_migration_sql(path, content)
        for changed_path, changed_content in ((path.replace('061_', '062_'), content),
                                               (path, content.replace('publication_armed INTEGER NOT NULL DEFAULT 1',
                                                                      'publication_armed INTEGER NOT NULL DEFAULT 0'))):
            with self.assertRaises(d.DeployError):
                d.validate_additive_migration_sql(changed_path, changed_content)
        def git(*args, **kwargs):
            if args[:2] == ('diff', '--name-only'):return path
            if args[:2] == ('diff', '--name-status'):return 'A\t' + path
            if args[0] == 'show':return content
            raise AssertionError(args)
        with patch.object(d, 'git', side_effect=git):
            with self.assertRaises(d.DeployError):d.migration_changes('old', 'new')
            self.assertEqual(d.migration_changes('old', 'new', allow_additive=True), [path])

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

    def test_gray_port_uses_isolated_override_and_rejects_production_port(self):
        with patch.dict(d.os.environ, {"RA_DASHBOARD_DEPLOY_GRAY_PORT": "18786"}):
            port = d.configured_gray_port()
        result = d.gray_env({}, Path("/candidate"), Path("/isolated"), "a" * 40, port=port)
        self.assertEqual(result["DASHBOARD_PORT"], "18786")
        self.assertEqual(result["DASHBOARD_HOST"], "127.0.0.1")
        with patch.dict(d.os.environ, {"RA_DASHBOARD_DEPLOY_GRAY_PORT": "8785"}):
            with self.assertRaises(d.DeployError):
                d.configured_gray_port()

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
        for changes in ({"build_commit": "b"*40}, {"storage": "postgresql"}, {"batch_prediction_enabled": True}, {"trail_rd_write_enabled": True}, {"human_label_write_enabled": True}, {"trail_te_write_enabled": True}, {"ok": False}):
            with self.assertRaises(d.DeployError):
                d.check_health(dict(health, **changes), "a"*40, "sqlite")
        legacy = dict(health); legacy.pop('trail_rd_write_enabled')
        self.assertEqual(d.policy(legacy), d.policy(health))
        self.assertNotEqual(d.policy(legacy), d.policy(dict(health, trail_rd_write_enabled=True)))
        self.assertNotEqual(d.policy(legacy), d.policy(dict(health, trail_te_write_enabled=True)))

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

    def test_shutdown_accepts_session_disappearing_between_checks(self):
        with patch.object(d,"process_alive",return_value=False), patch.object(d.subprocess,"run",side_effect=[
            subprocess.CompletedProcess([],0),subprocess.CompletedProcess([],1)]), patch.object(
                d,"git_pane_pid",side_effect=subprocess.CalledProcessError(1,['tmux','list-panes'])):
            d.wait_production_stopped(123)

    def test_shutdown_pane_failure_with_existing_session_is_not_ignored(self):
        with patch.object(d,"process_alive",return_value=False), patch.object(d.subprocess,"run",return_value=
            subprocess.CompletedProcess([],0)), patch.object(d,"git_pane_pid",side_effect=
                subprocess.CalledProcessError(1,['tmux','list-panes'])):
            with self.assertRaises(subprocess.CalledProcessError): d.wait_production_stopped(123)

    def simulate_release(self, fail_tests=False, fail_production=False, prepare_only=False, runtime_changed=False, fail_stop=False, isolated=False, branch_changed=False, checkout_changed=False, enable_rd=False, authorization_changed=False):
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
            health={"ok":True,"build_commit":old,"storage":"postgresql","trail_rd_write_enabled":False}
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
                return dict(health,build_commit=sha,storage=storage,
                            trail_rd_write_enabled=bool(enable_rd and port==8785 and sha==target))
            stack.enter_context(patch.object(d,"smoke",side_effect=smoke))
            options=dict(isolated_ref="codex/layout-only",expected_live_sha=old) if isolated else {}
            options["enable_trail_rd_write"] = enable_rd
            if authorization_changed:
                release_id = d.prepare_release(target, **options)
                with self.assertRaisesRegex(d.DeployError, "same explicit RD writer authorization"):
                    d.promote_release(release_id, target, **dict(options, enable_trail_rd_write=not enable_rd))
            elif fail_tests or fail_production or runtime_changed or fail_stop or branch_changed or checkout_changed:
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

    def test_explicit_rd_enable_only_changes_requested_writer_policy(self):
        stops, starts, record = self.simulate_release(enable_rd=True)
        self.assertEqual(record["status"], "success")
        self.assertEqual(len(stops), 1)
        self.assertEqual(starts[0].args[2]["DASHBOARD_TRAIL_RD_WRITE_ENABLED"], "true")
        self.assertTrue(record["enable_trail_rd_write"])
        self.assertEqual(record["policy"], record["requested_policy"])
        original = dict(record["policy"], trail_rd_write_enabled=False)
        self.assertEqual(d.requested_policy(original, True), record["policy"])

    def test_rd_enable_rolls_back_original_disabled_environment(self):
        _, starts, record = self.simulate_release(enable_rd=True, fail_production=True)
        self.assertEqual(record["rollback_status"], "healthy")
        self.assertEqual(starts[0].args[2]["DASHBOARD_TRAIL_RD_WRITE_ENABLED"], "true")
        self.assertNotIn("DASHBOARD_TRAIL_RD_WRITE_ENABLED", starts[1].args[2])

    def test_rd_enable_prepare_does_not_write_or_start_production(self):
        stops, starts, record = self.simulate_release(enable_rd=True, prepare_only=True)
        self.assertEqual((stops, starts), ([], []))
        self.assertFalse(record["policy"]["trail_rd_write_enabled"])
        self.assertTrue(record["requested_policy"]["trail_rd_write_enabled"])

    def test_rd_enable_authorization_must_match_prepare(self):
        for enable_rd in (False, True):
            stops, starts, record = self.simulate_release(enable_rd=enable_rd, authorization_changed=True)
            self.assertEqual((stops, starts), ([], []))
            self.assertEqual(record["status"], "prepared")

    def test_rd_enable_rejects_unknown_live_policy_and_preserves_other_writers(self):
        with self.assertRaisesRegex(d.DeployError, "RD writer policy is unavailable"):
            d.requested_policy({"ok": True}, True)
        health = {"trail_rd_write_enabled": False, "trail_write_enabled": True,
                  "trail_review_write_enabled": False, "autotriage_push_enabled": False}
        self.assertEqual(d.requested_policy(health, True), dict(d.policy(health), trail_rd_write_enabled=True))
        self.assertEqual(d.requested_policy(health), d.policy(health))

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

    def test_build_cloud_test_command_defaults_to_24_xdist_workers_and_falls_back_to_serial(self):
        with patch.dict(d.os.environ, {}, clear=False):
            d.os.environ.pop("RA_DASHBOARD_DEPLOY_TEST_WORKERS", None)
            with patch.object(d.os, "cpu_count", return_value=256), patch.object(
                d, "pytest_xdist_available", return_value=True
            ) as probe:
                cmd, workers, mode = d.build_cloud_test_command({})
                self.assertEqual(workers, 24)
                self.assertEqual(mode, "xdist")
                self.assertEqual(
                    cmd[1:],
                    ["-m", "pytest", "ra_triage_dashboard/tests", "-n", "24", "--dist", "load", "-q"],
                )
                probe.assert_called_once()

            # Missing xdist falls back cleanly to serial execution.
            with patch.object(d.os, "cpu_count", return_value=256), patch.object(
                d, "pytest_xdist_available", return_value=False
            ):
                cmd, workers, mode = d.build_cloud_test_command({})
                self.assertEqual(workers, 1)
                self.assertEqual(mode, "serial")
                self.assertEqual(cmd[1:], ["-m", "pytest", "ra_triage_dashboard/tests", "-q"])

            # Explicit RA_DASHBOARD_DEPLOY_TEST_WORKERS=1 forces serial without probing xdist.
            with patch.dict(d.os.environ, {"RA_DASHBOARD_DEPLOY_TEST_WORKERS": "1"}), patch.object(
                d, "pytest_xdist_available", return_value=True
            ) as probe:
                cmd, workers, mode = d.build_cloud_test_command({})
                self.assertEqual(workers, 1)
                self.assertEqual(mode, "serial")
                self.assertEqual(cmd[1:], ["-m", "pytest", "ra_triage_dashboard/tests", "-q"])
                probe.assert_not_called()

            # Invalid worker counts fail closed.
            for bad in ("0", "-2", "abc", "99"):
                with self.subTest(bad=bad), patch.dict(
                    d.os.environ, {"RA_DASHBOARD_DEPLOY_TEST_WORKERS": bad}
                ):
                    with self.assertRaises(d.DeployError):
                        d.configured_test_workers()

    def test_parallel_test_failure_blocks_deploy_without_starting_gray_or_stopping_production(self):
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            base = Path(temp)
            repo = base / "repo"
            repo.mkdir()
            python = base / "python"
            python.touch()
            env = {"DASHBOARD_DATABASE_URL_FILE": "/db", "DASHBOARD_DATA_DIR": str(base / "data")}
            target = "a" * 40
            old = "b" * 40
            stack.enter_context(patch.dict(d.os.environ, {}, clear=False))
            d.os.environ.pop("RA_DASHBOARD_DEPLOY_TEST_WORKERS", None)
            stack.enter_context(patch.object(d, "REPO", repo))
            stack.enter_context(patch.object(d, "STATE", base / "state"))
            stack.enter_context(patch.object(d, "PYTHON", python))
            stack.enter_context(patch.object(d.sys, "platform", "linux"))
            stack.enter_context(patch.object(d.os, "cpu_count", return_value=256))
            stack.enter_context(patch.object(d, "pytest_xdist_available", return_value=True))
            def fake_git(*args, **kwargs):
                if args[0] == "branch":
                    return "master"
                if args[0] == "rev-parse" and args[1].startswith("origin/"):
                    return target
                if args[0] == "rev-parse" and args[1] == "HEAD":
                    return old if kwargs.get("cwd") and Path(kwargs["cwd"]).name == "rollback" else old
                return ""
            stack.enter_context(patch.object(d, "git", side_effect=fake_git))
            stack.enter_context(patch.object(d, "read_live", return_value=(11, env)))
            stack.enter_context(
                patch.object(
                    d,
                    "get_json",
                    return_value={"ok": True, "build_commit": old, "storage": "postgresql", "trail_rd_write_enabled": False},
                )
            )
            stack.enter_context(patch.object(d.socket, "socket"))
            pytest_cmds = []
            def fake_run(*args, **kwargs):
                if args[:4] == ("git", "worktree", "add", "--detach"):
                    Path(args[4]).mkdir(parents=True)
                    return MagicMock()
                if "pytest" in args:
                    pytest_cmds.append(list(args))
                    raise subprocess.CalledProcessError(1, list(args))
                return MagicMock()
            stack.enter_context(patch.object(d, "run", side_effect=fake_run))
            gray_popen = stack.enter_context(patch.object(d.subprocess, "Popen"))
            stop_prod = stack.enter_context(patch.object(d, "stop_production"))
            start_prod = stack.enter_context(patch.object(d, "start_production"))
            with self.assertRaises(subprocess.CalledProcessError):
                d.deploy(target)
            self.assertEqual(len(pytest_cmds), 1)
            self.assertEqual(
                pytest_cmds[0][1:],
                ["-m", "pytest", "ra_triage_dashboard/tests", "-n", "24", "--dist", "load", "-q"],
            )
            gray_popen.assert_not_called()
            stop_prod.assert_not_called()
            start_prod.assert_not_called()
            release_dir = next((base / "state/releases").glob("*"))
            record = json.loads((release_dir / "result.json").read_text())
            self.assertEqual(record["status"], "failed")
            self.assertEqual(record["test_mode"], "xdist")
            self.assertEqual(record["test_workers"], 24)
            self.assertIn("test_mode=xdist test_workers=24", (release_dir / "tests.log").read_text())

    def test_live_rollback_requires_exact_healthy_private_recovery_receipt(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(d,'STATE',Path(temp)), patch.object(d,'validate_prepared_worktree') as validate:
            folder=Path(temp)/'releases'/'20261030T012606Z-aaaaaaaaaaaa'
            app=folder/'rollback'/'ra_triage_dashboard'; app.mkdir(parents=True)
            record=dict(status='failed',rollback_status='healthy',previous='b'*40,rollback=str(app.parent))
            d.save(folder/'result.json',record)
            d.validate_live_candidate(app,'b'*40)
            validate.assert_called_once_with(app.parent,'b'*40)
            for key,value in [('status','success'),('rollback_status','failed'),('previous','a'*40),('rollback','/tmp/other')]:
                d.save(folder/'result.json',dict(record,**{key:value}))
                with self.assertRaises(d.DeployError): d.validate_live_candidate(app,'b'*40)
            d.save(folder/'result.json',record)
            (folder/'result.json').chmod(0o644)
            with self.assertRaises(d.DeployError): d.validate_live_candidate(app,'b'*40)

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

    def test_065_labeling_idempotency_migration_requires_exact_review_and_additive_mode(self):
        path = "ra_triage_dashboard/migrations/postgres/065_labeling_idempotency_keys.sql"
        content = (Path(__file__).parents[2] / path).read_text()
        d.validate_additive_migration_sql(path, content)
        for changed_path, changed_content in (
            (path.replace("065_", "066_"), content),
            (path, content + "\n-- tampered"),
            (path, content.replace("lower(created_by)", "created_by")),
        ):
            with self.assertRaises(d.DeployError):
                d.validate_additive_migration_sql(changed_path, changed_content)

    def test_gray_port_rejects_bluegreen_slot_ports(self):
        for reserved in (8785, 18791, 18792):
            with patch.dict(d.os.environ, {"RA_DASHBOARD_DEPLOY_GRAY_PORT": str(reserved)}):
                with self.assertRaises(d.DeployError):
                    d.configured_gray_port()
        with patch.dict(d.os.environ, {}, clear=False):
            d.os.environ.pop("RA_DASHBOARD_DEPLOY_GRAY_PORT", None)
            self.assertEqual(d.configured_gray_port(), 19786)

    def test_render_nginx_conf_enforces_proxy_security_headers_and_no_next_upstream(self):
        with tempfile.TemporaryDirectory() as temp:
            conf = d.render_nginx_conf(Path(temp) / "nginx", public_port=8785)
        self.assertIn("listen 0.0.0.0:8785;", conf)
        self.assertIn("proxy_set_header X-Real-IP $remote_addr;", conf)
        self.assertIn("proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;", conf)
        self.assertIn("proxy_pass_request_headers on;", conf)
        self.assertIn("proxy_next_upstream off;", conf)
        self.assertIn("include ", conf)
        self.assertIn("maintenance_writes.conf;", conf)
        self.assertIn("active_upstream.conf;", conf)

    def test_render_maintenance_writes_conf_blocks_only_mutations_with_503_and_retry_after(self):
        disabled = d.render_maintenance_writes_conf(False)
        self.assertNotIn("return 503", disabled)
        enabled = d.render_maintenance_writes_conf(True, retry_after=20)
        self.assertIn("return 503", enabled)
        self.assertIn("add_header Retry-After 20 always;", enabled)
        self.assertIn("GET|HEAD|OPTIONS", enabled)
        self.assertIn('"maintenance":true', enabled)
        batch_only = d.render_maintenance_writes_conf("batch", retry_after=15)
        self.assertIn("api/prediction-batches", batch_only)
        self.assertIn('"scope":"batch"', batch_only)
        self.assertIn("GET|HEAD|OPTIONS", batch_only)
        self.assertIn("return 503", batch_only)

    def test_switch_nginx_upstream_restores_previous_config_on_validation_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp)
            d.ensure_nginx_layout(state, 18791)
            upstream_path = d.nginx_dir(state) / "active_upstream.conf"
            before = upstream_path.read_text()
            with patch.object(d, "reload_nginx", side_effect=d.DeployError("bad config")):
                with self.assertRaises(d.DeployError):
                    d.switch_nginx_upstream(state, 18792)
            self.assertEqual(upstream_path.read_text(), before)

    def test_validate_live_candidate_accepts_bluegreen_success_receipt(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(d, "STATE", Path(temp)), patch.object(d, "validate_prepared_worktree") as validate:
            folder = Path(temp) / "releases" / "20261126T100000Z-aaaaaaaaaaaa"
            app = folder / "candidate" / "ra_triage_dashboard"
            app.mkdir(parents=True)
            d.save(folder / "result.json", {
                "status": "success",
                "deploy_mode": "bluegreen",
                "target": "a" * 40,
                "candidate": str(app.parent),
            })
            d.validate_live_candidate(app, "a" * 40)
            validate.assert_called_once_with(app.parent, "a" * 40)

    def test_cleanup_preserves_active_bluegreen_slot_release(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp)
            folders = []
            for i in range(4):
                rid = f"20261126T10000{i}Z-aaaaaaaaaaaa"
                folder = state / "releases" / rid
                folder.mkdir(parents=True)
                for name in ("candidate", "rollback", "gray-data"):
                    (folder / name).mkdir()
                d.save(folder / "result.json", {
                    "status": "success",
                    "deploy_mode": "bluegreen",
                    "candidate": str(folder / "candidate"),
                    "rollback": str(folder / "rollback"),
                })
                folders.append(folder)
            d.save(state / "active_slot.json", {
                "slot": "blue",
                "port": 18791,
                "session": "ra_triage_dashboard_blue",
                "release_id": folders[0].name,
            })
            removed = []
            def fake_run(*args, **kwargs):
                p = Path(args[-1])
                removed.append(p)
                p.rmdir()
            with patch.object(d, "git", return_value=""), patch.object(d, "in_use", return_value=False), patch.object(d, "run", side_effect=fake_run):
                d.cleanup(state, folders[3])
            self.assertTrue((folders[0] / "candidate").exists())
            self.assertIn(folders[1] / "candidate", removed)

    def simulate_bluegreen_release(
        self,
        *,
        fail_candidate_smoke=False,
        fail_public_smoke=False,
        fail_post_stop_merge=False,
        schema_migration=False,
        already_applied_migration=False,
        old_supports_deferred=True,
        running_batch_jobs=0,
        initial_maintenance_writes=False,
        fail_migration_apply=False,
        out_meta=None,
    ):
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            base = Path(temp)
            repo = base / "repo"
            repo.mkdir()
            state = base / "state"
            python = base / "python"
            python.touch()
            env = {"DASHBOARD_DATABASE_URL_FILE": "/db", "DASHBOARD_DATA_DIR": str(base / "data")}
            target = "a" * 40
            old = "b" * 40
            d.ensure_nginx_layout(state, 18791)
            if initial_maintenance_writes:
                (d.nginx_dir(state) / "maintenance_writes.conf").write_text(
                    d.render_maintenance_writes_conf(initial_maintenance_writes),
                    encoding="utf-8",
                )
            d.save(state / "active_slot.json", {
                "slot": "blue",
                "port": 18791,
                "session": "ra_triage_dashboard_blue",
                "pid": 11,
                "sha": old,
                "release_id": "",
            })
            stack.enter_context(patch.object(d, "REPO", repo))
            stack.enter_context(patch.object(d, "STATE", state))
            stack.enter_context(patch.object(d, "PYTHON", python))
            stack.enter_context(patch.object(d.sys, "platform", "linux"))
            stack.enter_context(patch.object(d, "nginx_master_pid", return_value=999))
            stack.enter_context(patch.object(d, "supports_deferred_batch_recovery", return_value=old_supports_deferred))
            events = []
            def fake_running_batch(check_env, *, app_dir=None):
                events.append(("check_running_batch", running_batch_jobs))
                return running_batch_jobs
            stack.enter_context(patch.object(d, "read_running_batch_jobs", side_effect=fake_running_batch))
            def git(*args, **kwargs):
                if args[0] == "branch":
                    return "master"
                if args[0] == "rev-parse" and args[1].startswith("origin/"):
                    return target
                if args[0] == "rev-parse" and args[1] == "HEAD":
                    if "cwd" not in kwargs:
                        return old
                    return old if Path(kwargs["cwd"]).name == "rollback" else target
                return ""
            stack.enter_context(patch.object(d, "git", side_effect=git))
            stack.enter_context(patch.object(d, "read_live", return_value=(11, env)))
            health = {"ok": True, "build_commit": old, "storage": "postgresql", "trail_rd_write_enabled": False}
            applied_versions = [f"{i:03d}_m.sql" for i in range(1, 65)]
            if already_applied_migration:
                applied_versions.append("065_labeling_idempotency_keys.sql")
            def get_json(port, route):
                if route == "api/status":
                    return {
                        "database": {
                            "ok": True,
                            "persistent_data": True,
                            "migration_count": len(applied_versions),
                        },
                        "overall": {"status": "healthy"},
                    }
                return health
            stack.enter_context(patch.object(d, "get_json", side_effect=get_json))
            stack.enter_context(patch.object(d, "read_applied_postgres_migrations", return_value=list(applied_versions)))
            stack.enter_context(patch.object(d.socket, "socket"))
            if schema_migration:
                stack.enter_context(patch.object(d, "migration_changes", return_value=["ra_triage_dashboard/migrations/postgres/038_intent.sql"]))
                def fake_apply_migrations(*args, **kwargs):
                    events.append(("apply_additive_migrations",))
                    if fail_migration_apply:
                        raise d.DeployError("migration failed")
                    return ("/backup.dump", 65)
                stack.enter_context(patch.object(d, "apply_additive_migrations", side_effect=fake_apply_migrations))
            elif already_applied_migration:
                stack.enter_context(patch.object(
                    d,
                    "migration_changes",
                    return_value=["ra_triage_dashboard/migrations/postgres/065_labeling_idempotency_keys.sql"],
                ))
            def fake_run(*args, **kwargs):
                if args[:4] == ("git", "worktree", "add", "--detach"):
                    Path(args[4]).mkdir(parents=True)
                elif args[:2] == ("git", "merge"):
                    events.append(("git_merge", args[-1]))
                    if fail_post_stop_merge:
                        raise subprocess.CalledProcessError(1, ["git", "merge", "--ff-only", target])
                return MagicMock()
            stack.enter_context(patch.object(d, "run", side_effect=fake_run))
            stack.enter_context(patch.object(d.subprocess, "Popen"))
            stack.enter_context(patch.object(d.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)))
            stack.enter_context(patch.object(d, "stop_child"))
            def fake_start(record_dir, app, start_env, sha, name, **kw):
                events.append(("start", kw.get("session"), kw.get("port"), kw.get("enable_lease_gating"), Path(app).parent.name))
            stack.enter_context(patch.object(d, "start_production", side_effect=fake_start))
            stack.enter_context(patch.object(d, "git_pane_pid", side_effect=lambda session=d.SESSION: 22 if session == "ra_triage_dashboard_green" else 11))
            def fake_stop(pid, *, on_signal=None, session=d.SESSION):
                events.append(("stop", session, pid))
                if on_signal is not None:
                    on_signal()
            stack.enter_context(patch.object(d, "stop_production", side_effect=fake_stop))
            worker_gen = [777]
            def fake_workers(st=None):
                events.append(("snapshot_nginx_workers",))
                return list(worker_gen)
            stack.enter_context(patch.object(d, "nginx_worker_pids", side_effect=fake_workers))
            def fake_drain(pids, **kw):
                self.assertTrue(
                    set(pids).isdisjoint(worker_gen),
                    f"Attempted to drain live Nginx workers {pids} while active workers are {worker_gen}",
                )
                events.append(("drain_nginx_workers", list(pids)))
            stack.enter_context(patch.object(d, "wait_nginx_workers_drained", side_effect=fake_drain))
            def fake_switch(st, port, **kw):
                events.append(("switch_nginx", port))
                worker_gen[0] += 1
            stack.enter_context(patch.object(d, "switch_nginx_upstream", side_effect=fake_switch))
            def fake_maint(st, enabled, **kw):
                events.append(("maintenance_writes", enabled))
                (d.nginx_dir(st) / "maintenance_writes.conf").write_text(
                    d.render_maintenance_writes_conf(enabled),
                    encoding="utf-8",
                )
                worker_gen[0] += 1
            stack.enter_context(patch.object(d, "set_nginx_maintenance_writes", side_effect=fake_maint))
            stack.enter_context(patch.object(d, "cleanup", return_value=[]))
            def fake_smoke(port, sha, storage):
                events.append(("smoke", port, sha, storage))
                if fail_candidate_smoke and port == 18792:
                    raise d.DeployError("candidate slot failed")
                if fail_public_smoke and port == 8785 and sha == target:
                    raise d.DeployError("public entrance mismatch")
                return dict(health, build_commit=sha, storage=storage)
            stack.enter_context(patch.object(d, "smoke", side_effect=fake_smoke))
            opts = {}
            if schema_migration:
                opts["allow_schema_migrations"] = True
            elif already_applied_migration:
                opts["allow_additive_migrations"] = True
            if fail_candidate_smoke or fail_public_smoke or fail_post_stop_merge or (not old_supports_deferred and running_batch_jobs > 0):
                with self.assertRaises((d.DeployError, subprocess.CalledProcessError)):
                    d.deploy(target, **opts)
            else:
                d.deploy(target, **opts)
            record_path = next((state / "releases").glob("*/result.json"))
            record = json.loads(record_path.read_text())
            slot_after = json.loads((state / "active_slot.json").read_text())
            if out_meta is not None:
                out_meta["final_maint_mode"] = d.read_nginx_maintenance_writes(state)
            return events, record, slot_after, record_path.parent

    def test_bluegreen_promote_starts_standby_slot_switches_nginx_then_drains_old_slot(self):
        events, record, slot_after, _ = self.simulate_bluegreen_release()
        self.assertEqual(record["status"], "success")
        self.assertEqual(record["deploy_mode"], "bluegreen")
        self.assertEqual(record["slot"], "green")
        self.assertEqual(record["port"], 18792)
        self.assertEqual(slot_after["slot"], "green")
        self.assertEqual(slot_after["port"], 18792)
        # Critical zero-downtime ordering:
        # start green -> smoke green -> snapshot old nginx workers -> switch nginx ->
        # smoke 8785 -> drain pre-reload nginx workers -> stop old blue -> git merge
        order = [
            events.index(("start", "ra_triage_dashboard_green", 18792, True, "candidate")),
            events.index(("smoke", 18792, "a" * 40, "postgresql")),
            events.index(("snapshot_nginx_workers",)),
            events.index(("switch_nginx", 18792)),
            events.index(("smoke", 8785, "a" * 40, "postgresql")),
            events.index(("drain_nginx_workers", [777])),
            events.index(("stop", "ra_triage_dashboard_blue", 11)),
            events.index(("git_merge", "a" * 40)),
        ]
        self.assertEqual(order, sorted(order))

    def test_bluegreen_candidate_smoke_failure_leaves_nginx_and_old_slot_untouched(self):
        events, record, slot_after, _ = self.simulate_bluegreen_release(fail_candidate_smoke=True)
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["rollback_status"], "unchanged")
        self.assertEqual(slot_after["slot"], "blue")
        self.assertNotIn(("switch_nginx", 18792), events)
        self.assertNotIn(("stop", "ra_triage_dashboard_blue", 11), events)
        self.assertIn(("stop", "ra_triage_dashboard_green", 22), events)

    def test_bluegreen_post_switch_entrance_failure_verifies_old_slot_drains_workers_then_stops_green(self):
        events, record, slot_after, _ = self.simulate_bluegreen_release(fail_public_smoke=True)
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["rollback_status"], "healthy")
        self.assertEqual(slot_after["slot"], "blue")
        self.assertIn(("switch_nginx", 18792), events)
        self.assertIn(("smoke", 18791, "b" * 40, "postgresql"), events)
        rollback_order = [
            events.index(("smoke", 18791, "b" * 40, "postgresql")),
            events.index(("switch_nginx", 18791)),
            events.index(("smoke", 8785, "b" * 40, "postgresql")),
            events.index(("drain_nginx_workers", [778])),
            events.index(("stop", "ra_triage_dashboard_green", 22)),
        ]
        self.assertEqual(rollback_order, sorted(rollback_order))
        self.assertGreaterEqual(events.count(("snapshot_nginx_workers",)), 2)
        self.assertNotIn(("stop", "ra_triage_dashboard_blue", 11), events)

    def test_bluegreen_refuses_promotion_when_old_slot_lacks_deferred_batch_recovery_and_job_running(self):
        events, record, slot_after, _ = self.simulate_bluegreen_release(
            old_supports_deferred=False,
            running_batch_jobs=1,
        )
        self.assertEqual(record["status"], "failed")
        self.assertEqual(slot_after["slot"], "blue")
        # Must freeze Batch writes & drain workers BEFORE checking running jobs,
        # and lift the freeze cleanly on abort.
        order = [
            events.index(("maintenance_writes", "batch")),
            events.index(("drain_nginx_workers", [777])),
            events.index(("check_running_batch", 1)),
            events.index(("maintenance_writes", False)),
        ]
        self.assertEqual(order, sorted(order))
        self.assertFalse(any(e[0] == "start" for e in events))
        self.assertFalse(any(e[0] == "switch_nginx" for e in events))

    def test_bluegreen_old_slot_promotion_holds_batch_freeze_until_old_slot_stops(self):
        events, record, slot_after, _ = self.simulate_bluegreen_release(
            old_supports_deferred=False,
            running_batch_jobs=0,
        )
        self.assertEqual(record["status"], "success")
        self.assertEqual(slot_after["slot"], "green")
        order = [
            events.index(("maintenance_writes", "batch")),
            events.index(("drain_nginx_workers", [777])),
            events.index(("check_running_batch", 0)),
            events.index(("start", "ra_triage_dashboard_green", 18792, True, "candidate")),
            events.index(("switch_nginx", 18792)),
            events.index(("stop", "ra_triage_dashboard_blue", 11)),
            events.index(("maintenance_writes", False)),
        ]
        self.assertEqual(order, sorted(order))

    def test_bluegreen_post_stop_merge_failure_keeps_healthy_new_slot_without_reverting_nginx(self):
        events, record, slot_after, release_folder = self.simulate_bluegreen_release(
            fail_post_stop_merge=True,
        )
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["rollback_status"], "kept_new_slot")
        self.assertEqual(slot_after["slot"], "green")
        self.assertEqual(slot_after["port"], 18792)
        self.assertIn(("stop", "ra_triage_dashboard_blue", 11), events)
        self.assertNotIn(("switch_nginx", 18791), events)
        self.assertNotIn(("stop", "ra_triage_dashboard_green", 22), events)
        # Subsequent deploys must still recognize this kept new slot as an owned release.
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp)
            folder = state / "releases" / release_folder.name
            app = folder / "candidate" / "ra_triage_dashboard"
            app.mkdir(parents=True)
            d.save(folder / "result.json", dict(record, candidate=str(app.parent)))
            with patch.object(d, "STATE", state), patch.object(d, "validate_prepared_worktree"):
                d.validate_live_candidate(app, "a" * 40)

    def test_bluegreen_redeploy_succeeds_after_065_already_applied_in_prior_failed_attempt(self):
        events, record, slot_after, _ = self.simulate_bluegreen_release(
            already_applied_migration=True,
        )
        self.assertEqual(record["status"], "success")
        self.assertEqual(record["pending_migrations"], [])
        self.assertEqual(record["migration_count_before"], 65)
        self.assertEqual(record["migration_count_after"], 65)
        self.assertEqual(slot_after["slot"], "green")
        self.assertNotIn(("maintenance_writes", True), events)

    def test_bluegreen_schema_migration_enables_and_clears_maintenance_writes(self):
        events, record, _, _ = self.simulate_bluegreen_release(schema_migration=True)
        self.assertEqual(record["status"], "success")
        self.assertIn(("maintenance_writes", True), events)
        self.assertIn(("maintenance_writes", False), events)
        self.assertLess(events.index(("maintenance_writes", True)), events.index(("drain_nginx_workers", [777])))
        self.assertLess(events.index(("drain_nginx_workers", [777])), events.index(("switch_nginx", 18792)))
        self.assertLess(events.index(("switch_nginx", 18792)), events.index(("maintenance_writes", False)))

    def test_bluegreen_schema_migration_with_old_slot_drains_pre_maintenance_workers_only(self):
        events, record, slot_after, _ = self.simulate_bluegreen_release(
            schema_migration=True,
            old_supports_deferred=False,
            running_batch_jobs=0,
        )
        self.assertEqual(record["status"], "success")
        self.assertEqual(slot_after["slot"], "green")
        # Must snapshot gen-777 before maintenance_writes=True (reloading to 778),
        # drain ONLY 777 (never wait on live 778 without a reload), then keep
        # maintenance/batch freeze active through old-slot shutdown.
        order = [
            events.index(("snapshot_nginx_workers",)),
            events.index(("maintenance_writes", True)),
            events.index(("drain_nginx_workers", [777])),
            events.index(("check_running_batch", 0)),
            events.index(("start", "ra_triage_dashboard_green", 18792, True, "candidate")),
            events.index(("switch_nginx", 18792)),
            events.index(("maintenance_writes", "batch")),
            events.index(("drain_nginx_workers", [778])),
            events.index(("stop", "ra_triage_dashboard_blue", 11)),
            events.index(("maintenance_writes", False)),
        ]
        self.assertEqual(order, sorted(order))

    def _simulate_bootstrap_nginx(
        self,
        *,
        supports_deferred=False,
        legacy_lease_gating=False,
        running_batch_jobs=0,
        fail_legacy_stop=False,
        fence_drops_early=False,
        fence_lost_mid_drain=False,
        post_stop_running_batch=0,
        fail_audit_query=False,
        fail_receipt_save=False,
        out_meta=None,
    ):
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            base = Path(temp)
            repo = base / "repo"
            live_cwd = repo / "ra_triage_dashboard"
            live_cwd.mkdir(parents=True)
            state = base / "state"
            python = base / "python"
            python.touch()
            old_sha = "b" * 40
            env = {"DASHBOARD_DATABASE_URL_FILE": "/db", "DASHBOARD_DATA_DIR": str(base / "data")}
            if legacy_lease_gating:
                env["DASHBOARD_WORKER_LEASE_GATING"] = "true"
            health = {"ok": True, "build_commit": old_sha, "storage": "postgresql", "trail_rd_write_enabled": False}
            stack.enter_context(patch.object(d, "REPO", repo))
            stack.enter_context(patch.object(d, "STATE", state))
            stack.enter_context(patch.object(d, "PYTHON", python))
            stack.enter_context(patch.object(d.sys, "platform", "linux"))
            stack.enter_context(patch.object(d, "read_live_on_port", return_value=(101, env)))
            stack.enter_context(patch.object(d, "get_json", return_value=health))
            stack.enter_context(patch.object(d, "verify_port_free"))
            stack.enter_context(patch.object(d.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)))
            stack.enter_context(patch.object(d, "validate_nginx_config"))
            stack.enter_context(patch.object(d, "supports_deferred_batch_recovery", return_value=supports_deferred))
            events = []
            def fake_audit_batch(check_env, *, app_dir=None):
                events.append(("audit_running_batch", "error" if fail_audit_query else post_stop_running_batch))
                if fail_audit_query:
                    raise RuntimeError("pg audit query failed")
                return post_stop_running_batch
            stack.enter_context(patch.object(d, "read_running_batch_jobs", side_effect=fake_audit_batch))
            orig_save = d.save
            def maybe_fail_save(path, payload):
                if fail_receipt_save and Path(path).name == "bootstrap_failure.json":
                    raise OSError("disk full writing bootstrap_failure.json")
                return orig_save(path, payload)
            stack.enter_context(patch.object(d, "save", side_effect=maybe_fail_save))
            @contextmanager
            def fake_fence(fence_env, *, app_dir=None, timeout=60):
                events.append(("fence_enter", running_batch_jobs))
                try:
                    if running_batch_jobs > 0:
                        raise d.DeployError("Cannot bootstrap Nginx while a legacy Batch prediction or publish job is queued or running; wait for it to finish")
                    yield (lambda: not fence_drops_early)
                    if fence_lost_mid_drain:
                        raise d.FenceLostError("Legacy Batch write fence exited prematurely (rc=7)")
                finally:
                    events.append(("fence_exit",))
            stack.enter_context(patch.object(d, "legacy_batch_write_fence", side_effect=fake_fence))
            stack.enter_context(patch.object(d, "git_pane_pid", return_value=202))
            stack.enter_context(patch.object(d.Path, "resolve", return_value=live_cwd))
            def fake_start(record_dir, app, start_env, sha, name, **kw):
                events.append(("start", kw.get("session", d.SESSION), kw.get("port"), name))
            stack.enter_context(patch.object(d, "start_production", side_effect=fake_start))
            def fake_stop(pid, *, on_signal=None, session=d.SESSION):
                events.append(("stop", session, pid))
                if on_signal is not None:
                    on_signal()
                if fail_legacy_stop and session == d.SESSION:
                    raise d.DeployError("Interrupted after SIGTERM")
            stack.enter_context(patch.object(d, "stop_production", side_effect=fake_stop))
            def fake_wait(pid, *, session=d.SESSION):
                events.append(("wait_stopped", session, pid))
            stack.enter_context(patch.object(d, "wait_production_stopped", side_effect=fake_wait))
            def fake_start_nginx(st=None):
                events.append(("start_nginx",))
            stack.enter_context(patch.object(d, "start_nginx", side_effect=fake_start_nginx))
            def fake_stop_nginx(st=None, **kw):
                events.append(("stop_nginx",))
            stack.enter_context(patch.object(d, "stop_nginx", side_effect=fake_stop_nginx))
            stack.enter_context(patch.object(d, "check_metrics_blocked_via_proxy"))
            def fake_smoke(port, sha, storage):
                events.append(("smoke", port, sha))
                return health
            stack.enter_context(patch.object(d, "smoke", side_effect=fake_smoke))

            should_fail = (
                fail_legacy_stop
                or (not (supports_deferred and legacy_lease_gating) and (running_batch_jobs > 0 or fence_drops_early or fence_lost_mid_drain))
            )
            import io
            stderr_buf = io.StringIO()
            with patch.object(d.sys, "stderr", stderr_buf):
                if should_fail:
                    with self.assertRaises((d.DeployError, RuntimeError, OSError)):
                        d.bootstrap_nginx()
                else:
                    d.bootstrap_nginx()
            if out_meta is not None:
                out_meta["stderr"] = stderr_buf.getvalue()
                out_meta["active_slot_exists"] = (state / "active_slot.json").exists()
                failure_files = list(state.rglob("bootstrap_failure.json"))
                out_meta["failure_receipt"] = json.loads(failure_files[0].read_text()) if failure_files else None
            return events, old_sha

    def test_bootstrap_nginx_recovers_legacy_when_stop_fails_after_sigterm(self):
        events, old_sha = self._simulate_bootstrap_nginx(fail_legacy_stop=True)
        self.assertIn(("stop_nginx",), events)
        # Abnormal drain after SIGTERM must finish BEFORE releasing the Batch
        # write fence, and the fence must release BEFORE rollback restarts legacy.
        order = [
            events.index(("fence_enter", 0)),
            events.index(("stop", d.SESSION, 101)),
            events.index(("wait_stopped", d.SESSION, 101)),
            events.index(("fence_exit",)),
            events.index(("start", d.SESSION, None, "bootstrap-rollback")),
            events.index(("smoke", 8785, old_sha)),
        ]
        self.assertEqual(order, sorted(order))
        self.assertEqual(events.count(("wait_stopped", d.SESSION, 101)), 1)

    def test_bootstrap_nginx_old_sha_stops_legacy_before_starting_blue_and_blocks_running_batch(self):
        # Running Batch job on old legacy blocks bootstrap without touching legacy or blue.
        blocked_events, _ = self._simulate_bootstrap_nginx(
            supports_deferred=False,
            running_batch_jobs=1,
        )
        self.assertEqual(blocked_events, [("fence_enter", 1), ("fence_exit",)])

        # Early fence drop aborts cleanly before sending SIGTERM to legacy.
        dropped_events, _ = self._simulate_bootstrap_nginx(
            supports_deferred=False,
            running_batch_jobs=0,
            fence_drops_early=True,
        )
        self.assertEqual(dropped_events, [("fence_enter", 0), ("fence_exit",)])

        # With no running Batch job, old-SHA bootstrap holds the write fence
        # across count==0 and legacy shutdown, releases it only after legacy exits,
        # and then boots blue so no new Batch job can slip in before SIGTERM.
        events, old_sha = self._simulate_bootstrap_nginx(
            supports_deferred=False,
            running_batch_jobs=0,
        )
        order = [
            events.index(("fence_enter", 0)),
            events.index(("stop", d.SESSION, 101)),
            events.index(("fence_exit",)),
            events.index(("start", "ra_triage_dashboard_blue", 18791, "bootstrap-blue")),
            events.index(("smoke", 18791, old_sha)),
            events.index(("start_nginx",)),
            events.index(("smoke", 8785, old_sha)),
        ]
        self.assertEqual(order, sorted(order))

    def test_legacy_batch_write_fence_protocol_blocks_counts_and_releases_cleanly(self):
        # Verify the SQL fence locks batch_prediction_jobs exclusively, disables
        # idle-in-transaction timeout, keeps guard active with SELECT 1, checks
        # queued/running/publish_running, and cancels blocked writers.
        self.assertIn("LOCK TABLE batch_prediction_jobs IN EXCLUSIVE MODE", d.LEGACY_BATCH_FENCE_CODE)
        self.assertIn("SET LOCAL idle_in_transaction_session_timeout = '0'", d.LEGACY_BATCH_FENCE_CODE)
        self.assertIn('guard.execute("SELECT 1").fetchone()', d.LEGACY_BATCH_FENCE_CODE)
        self.assertIn("status IN ('queued', 'running') OR publish_status = 'running'", d.LEGACY_BATCH_FENCE_CODE)
        self.assertIn("pg_cancel_backend", d.LEGACY_BATCH_FENCE_CODE)

        # Exercise the real subprocess lifecycle of legacy_batch_write_fence().
        fake_ok_code = (
            "import json, sys\n"
            "print(json.dumps({'locked': True, 'running': 0}), flush=True)\n"
            "line = sys.stdin.readline().strip()\n"
            "assert line == 'release', f'unexpected command: {line!r}'\n"
            "print(json.dumps({'released': True}), flush=True)\n"
        )
        fake_busy_code = (
            "import json\n"
            "print(json.dumps({'locked': True, 'running': 1}), flush=True)\n"
        )
        fake_crash_mid_hold_code = (
            "import json, sys\n"
            "print(json.dumps({'locked': True, 'running': 0}), flush=True)\n"
            "sys.exit(7)\n"
        )
        fake_no_ack_code = (
            "import json, sys\n"
            "print(json.dumps({'locked': True, 'running': 0}), flush=True)\n"
            "sys.stdin.readline()\n"
        )
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(d, "PYTHON", Path(sys.executable)), patch.object(
                d, "LEGACY_BATCH_FENCE_CODE", fake_ok_code
            ):
                with d.legacy_batch_write_fence({}, app_dir=Path(temp)) as fence_alive:
                    self.assertTrue(fence_alive())
            with patch.object(d, "PYTHON", Path(sys.executable)), patch.object(
                d, "LEGACY_BATCH_FENCE_CODE", fake_busy_code
            ):
                with self.assertRaisesRegex(d.DeployError, "queued or running"):
                    with d.legacy_batch_write_fence({}, app_dir=Path(temp)):
                        pass
            with patch.object(d, "PYTHON", Path(sys.executable)), patch.object(
                d, "LEGACY_BATCH_FENCE_CODE", fake_crash_mid_hold_code
            ):
                with self.assertRaises(d.FenceLostError):
                    with d.legacy_batch_write_fence({}, app_dir=Path(temp)):
                        time.sleep(0.15)
            with patch.object(d, "PYTHON", Path(sys.executable)), patch.object(
                d, "LEGACY_BATCH_FENCE_CODE", fake_no_ack_code
            ):
                with self.assertRaises(d.FenceLostError):
                    with d.legacy_batch_write_fence({}, app_dir=Path(temp)):
                        pass

    def test_bootstrap_nginx_mid_drain_fence_loss_audits_db_writes_failure_receipt_and_never_starts_blue(self):
        # Case 1: Fence lost mid-drain, DB audit finds 0 running Batch jobs ->
        # records explicit bootstrap_failure.json, never starts blue, safely rolls back legacy.
        meta_clean = {}
        events_clean, old_sha = self._simulate_bootstrap_nginx(
            supports_deferred=False,
            running_batch_jobs=0,
            fence_lost_mid_drain=True,
            post_stop_running_batch=0,
            out_meta=meta_clean,
        )
        self.assertFalse(meta_clean["active_slot_exists"])
        self.assertIsNotNone(meta_clean["failure_receipt"])
        self.assertEqual(meta_clean["failure_receipt"]["status"], "failed")
        self.assertEqual(meta_clean["failure_receipt"]["reason"], "legacy_batch_write_fence_lost")
        self.assertEqual(meta_clean["failure_receipt"]["post_stop_running_batch"], 0)
        self.assertEqual(meta_clean["failure_receipt"]["recovery_action"], "rollback_legacy")
        self.assertNotIn(("start", "ra_triage_dashboard_blue", 18791, "bootstrap-blue"), events_clean)
        self.assertIn(("audit_running_batch", 0), events_clean)
        self.assertIn(("start", d.SESSION, None, "bootstrap-rollback"), events_clean)
        self.assertIn(("smoke", 8785, old_sha), events_clean)

        # Case 2: Fence lost mid-drain AND DB audit sees a Batch job slipped in ->
        # refuses both blue AND automatic legacy restart (old legacy would mark it failed).
        meta_dirty = {}
        events_dirty, _ = self._simulate_bootstrap_nginx(
            supports_deferred=False,
            running_batch_jobs=0,
            fence_lost_mid_drain=True,
            post_stop_running_batch=1,
            out_meta=meta_dirty,
        )
        self.assertFalse(meta_dirty["active_slot_exists"])
        self.assertIsNotNone(meta_dirty["failure_receipt"])
        self.assertEqual(meta_dirty["failure_receipt"]["status"], "failed")
        self.assertEqual(meta_dirty["failure_receipt"]["reason"], "legacy_batch_write_fence_lost")
        self.assertEqual(meta_dirty["failure_receipt"]["post_stop_running_batch"], 1)
        self.assertEqual(meta_dirty["failure_receipt"]["recovery_action"], "hold_for_manual_inspection")
        self.assertFalse(any(e[0] == "start" for e in events_dirty))

    def test_bluegreen_preserves_operator_manual_maintenance_writes_on_success_and_rollback(self):
        # 1) Manual full write-maintenance ("all") must NEVER be downgraded to "batch"
        # or cleared to False on either success or rollback.
        for fail_smoke in (False, True):
            meta = {}
            events, record, _, _ = self.simulate_bluegreen_release(
                schema_migration=True,
                old_supports_deferred=False,
                running_batch_jobs=0,
                fail_candidate_smoke=fail_smoke,
                initial_maintenance_writes=True,
                out_meta=meta,
            )
            self.assertEqual(record["status"], "failed" if fail_smoke else "success")
            self.assertNotIn(("maintenance_writes", "batch"), events)
            self.assertNotIn(("maintenance_writes", False), events)
            self.assertEqual(meta["final_maint_mode"], "all")

        # 2) Pre-existing "batch" freeze tightens to "all" for schema migration,
        # then restores to "batch" (never loosening to False).
        meta_batch = {}
        events_batch, record_batch, _, _ = self.simulate_bluegreen_release(
            schema_migration=True,
            old_supports_deferred=True,
            initial_maintenance_writes="batch",
            out_meta=meta_batch,
        )
        self.assertEqual(record_batch["status"], "success")
        self.assertIn(("maintenance_writes", True), events_batch)
        self.assertIn(("maintenance_writes", "batch"), events_batch)
        self.assertNotIn(("maintenance_writes", False), events_batch)
        self.assertEqual(meta_batch["final_maint_mode"], "batch")

    def test_bootstrap_nginx_fence_lost_forbids_restart_on_audit_or_receipt_error_and_recovers_only_on_verified_zero(self):
        # 1) Audit query raises error -> NEVER starts blue OR bootstrap-rollback.
        meta_audit_err = {}
        events_audit_err, _ = self._simulate_bootstrap_nginx(
            supports_deferred=False,
            running_batch_jobs=0,
            fence_lost_mid_drain=True,
            fail_audit_query=True,
            out_meta=meta_audit_err,
        )
        self.assertFalse(meta_audit_err["active_slot_exists"])
        self.assertFalse(any(e[0] == "start" for e in events_audit_err))

        # 2) Audit returns 1 running/queued job -> NEVER starts blue OR bootstrap-rollback.
        meta_one = {}
        events_one, _ = self._simulate_bootstrap_nginx(
            supports_deferred=False,
            running_batch_jobs=0,
            fence_lost_mid_drain=True,
            post_stop_running_batch=1,
            out_meta=meta_one,
        )
        self.assertFalse(meta_one["active_slot_exists"])
        self.assertFalse(any(e[0] == "start" for e in events_one))

        # 3) Audit returns 0, but writing bootstrap_failure.json fails ->
        # NEVER starts blue OR bootstrap-rollback, AND stderr explains why.
        meta_save_err = {}
        events_save_err, _ = self._simulate_bootstrap_nginx(
            supports_deferred=False,
            running_batch_jobs=0,
            fence_lost_mid_drain=True,
            post_stop_running_batch=0,
            fail_receipt_save=True,
            out_meta=meta_save_err,
        )
        self.assertFalse(meta_save_err["active_slot_exists"])
        self.assertIsNone(meta_save_err["failure_receipt"])
        self.assertFalse(any(e[0] == "start" for e in events_save_err))
        self.assertIn("disk full", meta_save_err["stderr"])

        # 4) Audit returns 0 AND bootstrap_failure.json persists -> recovers legacy cleanly.
        meta_zero = {}
        events_zero, old_sha = self._simulate_bootstrap_nginx(
            supports_deferred=False,
            running_batch_jobs=0,
            fence_lost_mid_drain=True,
            post_stop_running_batch=0,
            out_meta=meta_zero,
        )
        self.assertFalse(meta_zero["active_slot_exists"])
        self.assertEqual(meta_zero["failure_receipt"]["recovery_action"], "rollback_legacy")
        self.assertIn(("start", d.SESSION, None, "bootstrap-rollback"), events_zero)
        self.assertIn(("smoke", 8785, old_sha), events_zero)

    def test_toggle_maintenance_writes_on_drains_pre_reload_workers_under_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp)
            d.ensure_nginx_layout(state, 18791)
            d.save(state / "active_slot.json", {
                "slot": "blue",
                "port": 18791,
                "session": "ra_triage_dashboard_blue",
            })
            events = []
            worker_gen = [501]
            def fake_workers(st=None):
                events.append(("snapshot_workers", list(worker_gen)))
                return list(worker_gen)
            def fake_set(st, enabled, **kw):
                events.append(("set_maint", enabled))
                worker_gen[0] += 1
            def fake_drain(pids, **kw):
                self.assertTrue(set(pids).isdisjoint(worker_gen))
                events.append(("drain_workers", list(pids)))
            with patch.object(d, "STATE", state), patch.object(
                d, "nginx_master_pid", return_value=999
            ), patch.object(
                d, "nginx_worker_pids", side_effect=fake_workers
            ), patch.object(
                d, "set_nginx_maintenance_writes", side_effect=fake_set
            ), patch.object(
                d, "wait_nginx_workers_drained", side_effect=fake_drain
            ):
                d.toggle_maintenance_writes("on")
            self.assertEqual(
                events,
                [
                    ("snapshot_workers", [501]),
                    ("set_maint", True),
                    ("drain_workers", [501]),
                ],
            )

    def test_bluegreen_promote_with_preexisting_manual_maintenance_drains_inflight_old_worker_before_checks(self):
        # Even when maintenance_writes="all" is already enabled on disk (e.g. an
        # earlier manual --maintenance-writes on exited before draining), promote
        # must preserve "all", reload once to establish a drain boundary, and wait
        # for pre-reload workers (carrying an in-flight slow request) BEFORE
        # running schema migration or checking running Batch jobs.
        meta = {}
        events, record, _, _ = self.simulate_bluegreen_release(
            schema_migration=True,
            old_supports_deferred=False,
            running_batch_jobs=0,
            initial_maintenance_writes=True,
            out_meta=meta,
        )
        self.assertEqual(record["status"], "success")
        self.assertEqual(meta["final_maint_mode"], "all")
        self.assertNotIn(("maintenance_writes", "batch"), events)
        self.assertNotIn(("maintenance_writes", False), events)
        order = [
            events.index(("snapshot_nginx_workers",)),
            events.index(("maintenance_writes", True)),
            events.index(("drain_nginx_workers", [777])),
            events.index(("apply_additive_migrations",)),
            events.index(("check_running_batch", 0)),
        ]
        self.assertEqual(order, sorted(order))

    def test_supports_deferred_batch_recovery_requires_graceful_drain_support(self):
        self.assertTrue(d.supports_deferred_batch_recovery(Path(__file__).parents[1]))
        with tempfile.TemporaryDirectory() as temp:
            app_dir = Path(temp)
            (app_dir / "app").mkdir(parents=True)
            (app_dir / "app/main.py").write_text(
                "recover_interrupted_jobs=not defer_batch_recovery\n_batch_prediction_leader\n",
                encoding="utf-8",
            )
            self.assertFalse(d.supports_deferred_batch_recovery(app_dir))

    def test_migration_apply_code_runs_migrations_only_and_backup_scripts_use_snapshot(self):
        self.assertIn("apply_postgres_migrations()", d.MIGRATION_APPLY_CODE)
        self.assertNotIn("database.init()", d.MIGRATION_APPLY_CODE)
        scripts_dir = Path(__file__).parents[1] / "scripts"
        backup_src = (scripts_dir / "backup_cloud_postgres.sh").read_text(encoding="utf-8")
        verify_src = (scripts_dir / "verify_cloud_postgres_backup.sh").read_text(encoding="utf-8")
        self.assertIn("pg_export_snapshot()", backup_src)
        self.assertIn("--snapshot", backup_src)
        self.assertIn(".counts", backup_src)
        self.assertIn(".counts", verify_src)

    def test_wait_nginx_workers_drained_waits_until_all_pre_reload_workers_exit(self):
        alive_checks = iter([True, True, False, False])
        with patch.object(d, "process_alive", side_effect=lambda pid: next(alive_checks)), patch.object(
            d.time, "sleep"
        ) as sleep_mock:
            d.wait_nginx_workers_drained([301], timeout=10)
        sleep_mock.assert_called()

    def test_verify_port_free_allows_time_wait_and_rejects_active_listeners(self):
        # 1. Active LISTEN on 127.0.0.1 (with SO_REUSEADDR, like uvicorn) must be rejected.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            with self.assertRaisesRegex(d.DeployError, f"Gray port {port} is occupied"):
                d.verify_port_free(port, "Gray")

        # 2. Active LISTEN on 0.0.0.0 (wildcard with SO_REUSEADDR) must also be rejected.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as wildcard:
            wildcard.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            wildcard.bind(("0.0.0.0", 0))
            wildcard.listen(1)
            port = wildcard.getsockname()[1]
            with self.assertRaisesRegex(d.DeployError, f"Gray port {port} is occupied"):
                d.verify_port_free(port, "Gray")

        # 3. Real server-closed loopback connection leaves TIME_WAIT with no listener:
        #    bare bind without SO_REUSEADDR fails, while verify_port_free succeeds immediately.
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.listen(1)
        client = socket.create_connection(("127.0.0.1", port))
        server_conn, _ = listener.accept()
        try:
            server_conn.close()  # Active close on server side places 127.0.0.1:port in TIME_WAIT.
            client.recv(1)
        finally:
            client.close()
            listener.close()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as bare:
            with self.assertRaises(OSError):
                bare.bind(("127.0.0.1", port))
        d.verify_port_free(port, "Gray")

    def test_promote_release_does_not_probe_gray_port(self):
        # --prepare probes gray port once, while --promote does not start gray
        # and passes check_gray_port=False so a busy or TIME_WAIT gray port
        # cannot block production cutover.
        preflight_calls = []
        port_probes = []
        orig_preflight = d.preflight
        orig_verify_port_free = d.verify_port_free

        def spy_preflight(*args, **kwargs):
            preflight_calls.append(kwargs.get("check_gray_port", True))
            return orig_preflight(*args, **kwargs)

        def spy_verify_port_free(port, label):
            port_probes.append((label, port))
            if label == "Gray" and len(preflight_calls) >= 2:
                raise d.DeployError(f"Gray port {port} is occupied; preserve its existing service")
            return orig_verify_port_free(port, label)

        with patch.object(d, "preflight", side_effect=spy_preflight), patch.object(
            d, "verify_port_free", side_effect=spy_verify_port_free
        ):
            _, record, _, _ = self.simulate_bluegreen_release()
        self.assertEqual(record["status"], "success")
        self.assertEqual(preflight_calls, [True, False])
        self.assertEqual(
            port_probes,
            [("Gray", d.DEFAULT_GRAY_PORT), ("Blue-green target slot (green)", 18792)],
        )

if __name__ == "__main__": unittest.main()
