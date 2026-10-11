"""Native process doubles; real controller/Git gates. No hosted acceptance claims."""
import copy
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import unittest
import uuid
from unittest.mock import patch

import test_engine as fixture
from tools.rdd.common import RddError, RddStorageError, operation_lock
from tools.rdd.workflow import WorkflowRunner, attach, journal, launch_packet, update_runtime, validate_runtime
from tools.rdd.storage_failure import record_failure


class MetadataServer:
    def __init__(self, root, **kwargs):
        self.runtime_identity = dict(version="0.162.1", executable="fixture-codex", executable_sha256="a"*64)
        self.effective_config = dict(sandbox_mode="workspace-write", approval_policy="on-request", approvals_reviewer="user")
        self.closed, self.calls = False, []
    def __enter__(self): return self
    def __exit__(self, *args): self.closed = True
    def rpc(self, method, params):
        self.calls.append((method, params))
        if method == "model/list":
            return {"data": [dict(model=m, supportedReasoningEfforts=[dict(reasoningEffort=e)]) for m,e in
                (("gpt-6-astra","ultra"),("gpt-6.1-sol","xhigh"),("gpt-6-luna","xhigh"))]}
        if method == "account/read": return dict(requiresOpenaiAuth=True, account={"type":"fixture"})
        raise AssertionError("Coordinator must not make session/Goal RPCs: " + method)


class FakeTui:
    def __init__(self, c):
        self.c, self.calls = c, []
        self.identity = str(uuid.uuid4())
        self.action = lambda: None
        self.register, self.code, self.closed = True, 0, False
    def run(self, argv, root, poll):
        self.calls.append(argv)
        try:
            poll()
            if self.register:
                stage, nonce = re.search(r"workflow attach (\w+) --launch-id ([a-f0-9-]+)",argv[-1]).groups()
                with patch.dict(os.environ,CODEX_THREAD_ID=self.identity): attach(self.c,stage,nonce)
            self.action()
            poll()
            return self.code
        finally: self.closed = True


class TuiTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.EngineTests(methodName="runTest"); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.c,self.root=self.f.c,self.f.root
        self.f.write(".rdd/goals/implementation.txt", "Use $implementation-workflow and complete the fixture through real controller acceptance.")
        self.server=MetadataServer(self.root); self.tui=FakeTui(self.c); self.output=[]
        self.runner=WorkflowRunner(self.c,server_factory=lambda *a,**k:self.server,tui=self.tui,terminal=lambda:True,emit=self.output.append)
    def accepted_spec(self):
        self.f.stage_ready("specification"); self.c.spec_freeze(); self.f.commit("Freeze accepted fixture")
    def test_native_exit_zero_is_not_acceptance_and_policy_is_not_overridden(self):
        result=self.runner.run("specification")
        self.assertEqual(result["status"],"incomplete"); self.assertEqual(result["tui_exit_code"],0)
        args=self.tui.calls[0]
        self.assertIn("--no-daemon",args)
        self.assertTrue(any(a.startswith("developer_instructions=") for a in args))
        self.assertFalse(any(a in {"-a","--ask-for-approval","--full-auto","--sandbox"} for a in args))
        self.assertFalse(any("approval_policy=" in a for a in args))
        self.assertTrue(self.server.closed)
    def test_exit_recognizes_real_controller_acceptance(self):
        self.tui.action=self.accepted_spec
        self.assertEqual(self.runner.run("specification")["status"],"passed")
        self.assertEqual(journal(self.c,"specification")["connection"],"accepted")
    def test_accepted_stage_needs_no_terminal_or_runtime(self):
        self.accepted_spec(); before=copy.deepcopy(self.c.state())
        self.runner.terminal=lambda:False
        self.runner.server_factory=lambda *a,**k:self.fail("runtime not needed")
        self.assertEqual(self.runner.run("specification")["status"],"passed")
        self.assertEqual(self.c.state(),before)
    def test_unqualified_process_ownership_is_mutation_free(self):
        from tools.rdd.workflow import NativeTui
        before=copy.deepcopy(self.c.state()); self.runner.tui=NativeTui()
        with patch("tools.rdd.workflow.ProcessTable.preflight",side_effect=RddError("Unqualified ownership","environment")),self.assertRaisesRegex(RddError,"Unqualified ownership"):
            self.runner.run("specification")
        self.assertEqual(self.c.state(),before); self.assertFalse(self.server.calls)

    def test_no_terminal_or_failed_preflight_is_mutation_free(self):
        before=copy.deepcopy(self.c.state())
        for fault in ("terminal","sandbox","version"):
            with self.subTest(fault=fault):
                self.runner.terminal=lambda:fault!="terminal"
                self.server.effective_config["sandbox_mode"]="read-only" if fault=="sandbox" else "workspace-write"
                self.server.runtime_identity["version"]="0.161.0" if fault=="version" else "0.162.1"
                with self.assertRaises(RddError): self.runner.run("specification")
                self.assertEqual(self.c.state(),before); self.assertFalse(self.tui.calls)
    def test_real_cli_without_tty_and_pure_print(self):
        cli=Path(__file__).resolve().parents[2]/"tools/rdd/cli.py"; before=copy.deepcopy(self.c.state())
        for extra,expected in (([],2),(["--print"],0)):
            p=subprocess.run([sys.executable,str(cli),"--root",str(self.root),"workflow","specification","--mode","regenerate",*extra],capture_output=True,text=True)
            self.assertEqual(p.returncode,expected,p.stdout+p.stderr); self.assertEqual(self.c.state(),before)
    def test_resume_uses_exact_identity(self):
        self.runner.run("specification"); before=journal(self.c,"specification")
        self.runner.run("specification"); args=self.tui.calls[-1]
        self.assertEqual(args[args.index("resume")+1],self.tui.identity); self.assertNotIn("--last",args)
        self.assertEqual(journal(self.c,"specification")["thread_id"],before["thread_id"])
        self.assertNotEqual(journal(self.c,"specification")["launch_id"],before["launch_id"])
    def test_unattached_launch_is_uncertain_and_never_replaced(self):
        self.tui.register=False
        with self.assertRaisesRegex(RddError,"uncertain"): self.runner.run("specification")
        before=copy.deepcopy(self.c.state())
        with self.assertRaisesRegex(RddError,"uncertain"): self.runner.run("specification")
        self.assertEqual(self.c.state(),before); self.assertEqual(len(self.tui.calls),1)
    def test_attachment_rejects_wrong_nonce_session_and_replay(self):
        self.runner.run("specification"); row=journal(self.c,"specification"); before=copy.deepcopy(self.c.state())
        for nonce,tid in ((str(uuid.uuid4()),self.tui.identity),(row["launch_id"],str(uuid.uuid4())),(row["launch_id"],self.tui.identity)):
            with patch.dict(os.environ,CODEX_THREAD_ID=tid),self.assertRaises(RddError): attach(self.c,"specification",nonce)
            self.assertEqual(self.c.state(),before)
    def test_attachment_requires_live_driver(self):
        self.tui.register=False
        with self.assertRaises(RddError): self.runner.run("specification")
        update_runtime(self.c,"specification",connection="starting"); before=copy.deepcopy(self.c.state())
        with patch.dict(os.environ,CODEX_THREAD_ID=self.tui.identity),self.assertRaisesRegex(RddError,"active driver"):
            attach(self.c,"specification",journal(self.c,"specification")["launch_id"])
        self.assertEqual(self.c.state(),before)
    def test_resume_cannot_replace_session(self):
        self.runner.run("specification"); original=self.tui.identity; self.tui.identity=str(uuid.uuid4())
        with self.assertRaisesRegex(RddError,"attachment"): self.runner.run("specification")
        self.assertEqual(journal(self.c,"specification")["thread_id"],original)
    def test_runtime_drift_preserves_state(self):
        self.runner.run("specification"); before=copy.deepcopy(self.c.state())
        self.server.runtime_identity["executable_sha256"]="b"*64
        with self.assertRaisesRegex(RddError,"runtime identity"): self.runner.run("specification")
        self.assertEqual(self.c.state(),before)
    def test_duplicate_driver_excluded_while_controller_remains_usable(self):
        with operation_lock(self.root,workflow=True):
            with operation_lock(self.root): pass
            with self.assertRaisesRegex(RddError,"Another workflow driver"): self.runner.run("specification")
        self.assertFalse(self.tui.calls)
    def test_interruption_preserves_attached_identity(self):
        def interrupt(): raise KeyboardInterrupt
        self.tui.action=interrupt
        self.assertTrue(self.runner.run("specification")["interrupted"])
        self.assertTrue(self.tui.closed)
        self.assertEqual(journal(self.c,"specification")["thread_id"],self.tui.identity)
        self.assertEqual(journal(self.c,"specification")["connection"],"interrupted")
    def test_checkpoint_roundtrip_and_unique_session_validation(self):
        self.f.commit("Clean fixture"); self.runner.run("specification")
        path=self.root/".rdd/evidence/tui-checkpoint.json"; self.c.export_run(path)
        before=copy.deepcopy(self.c.state()["workflow_runtime"]); self.c.resume(path)
        self.assertEqual(self.c.state()["workflow_runtime"],before)
        state=self.c.state(); row=state["workflow_runtime"]["specification"]
        row["readonly"]={"live":dict(thread_id=row["thread_id"],requested_runtime=self.c.profile_settings("rdd_reviewer"))}
        with self.assertRaisesRegex(RddError,"reused"): validate_runtime(self.c,state)
    def test_historical_runtime_inspection_export_without_conversion(self):
        legacy=dict(connection="stopped",thread_id="historical-thread",runtime=self.server.runtime_identity,requested_runtime=self.c.profile_settings("rdd_coordinator"),readonly={})
        update_runtime(self.c,"specification",**legacy); before=copy.deepcopy(self.c.state())
        self.assertEqual(self.c.status()["run_id"],before["id"])
        self.assertEqual(self.c.state()["workflow_runtime"]["specification"],legacy)
        self.c.export_run(self.root/".rdd/evidence/history.json")
        with self.assertRaisesRegex(RddError,"Historical"): self.runner.run("specification")
        self.assertEqual(self.c.state(),before); self.assertFalse(self.tui.calls)
    def test_generated_goal_is_a_short_native_command_referencing_full_objective(self):
        objective = ("Complete the approved work and preserve every controller gate.\n" * 50).strip()
        self.f.write(".rdd/goals/implementation.txt", objective)
        packet = launch_packet(self.c, "implementation")
        self.assertEqual(packet["objective"], objective)
        command = packet["goal_command"]
        self.assertTrue(command.startswith("/goal "))
        self.assertNotIn("\n", command)
        self.assertLess(len(command), 256, "Large native pastes become ordinary text/attachments instead of slash commands")
        self.assertIn(".rdd/goals/implementation.txt", command)
        self.assertIn("application_complete=true", command)

    def test_manual_implementation_goal_is_never_activated_or_replaced_by_client(self):
        self.f.prepared()
        self.assertEqual(self.runner.run("implementation")["status"],"incomplete")
        self.assertIn(launch_packet(self.c,"implementation")["goal_command"],self.output[0])
        self.assertIn("wait for the user to paste",self.tui.calls[0][-1])
        self.assertNotIn("goal",journal(self.c,"implementation"))
        self.runner.run("implementation")
        self.assertIn("preserve its identity",self.tui.calls[-1][-1])
        self.assertFalse(any("goal" in m for m,_ in self.server.calls))
    def test_storage_failure_and_retry_preserve_terminal_enforcement(self):
        self.f.prepared()
        error=RddStorageError("edit",self.c.store.path,sqlite3.DatabaseError("fixture corruption"))
        def fail():
            record_failure(self.root,error,stage="implementation"); raise error
        self.tui.action=fail
        with patch.object(self.c,"export_run") as export,self.assertRaises(RddStorageError): self.runner.run("implementation")
        export.assert_not_called(); calls=len(self.tui.calls); saved=copy.deepcopy(self.c.state(allow_blocked=True))
        with self.assertRaisesRegex(RddError,"Critical"): self.runner.run("implementation")
        self.assertEqual(len(self.tui.calls),calls); self.assertEqual(self.c.state(allow_blocked=True),saved)
        self.assertTrue(self.tui.closed)

    def test_missing_runtime_and_interrupted_preflight_preserve_state(self):
        before=copy.deepcopy(self.c.state())
        self.runner.server_factory=lambda *a,**k: (_ for _ in ()).throw(RddError("Missing runtime","environment"))
        with self.assertRaisesRegex(RddError,"Missing runtime"): self.runner.run("specification")
        self.assertEqual(self.c.state(),before)
        self.runner.server_factory=lambda *a,**k:self.server
        self.server.rpc=lambda *a,**k: (_ for _ in ()).throw(KeyboardInterrupt())
        self.assertTrue(self.runner.run("specification")["interrupted"])
        self.assertTrue(self.server.closed); self.assertEqual(self.c.state(),before)

    def test_preparation_uses_real_local_gate_with_explicit_fake_external_evidence(self):
        from tools.rdd.common import write_json
        self.accepted_spec()
        def prepare():
            self.f.plan["spec_digest"]=self.c.state()["spec_digest"]
            self.c.plan_init(); write_json(self.root/".rdd/plan/plan.json",self.f.plan)
            self.f.stage_ready("plan"); self.c.plan_freeze(); self.c.prepare()
            self.f.commit("Materialized fixture")
            self.f.stage_ready("preparation",ci=True)  # Fixture adapters only; no hosted execution.
            self.c.gate_preparation()
        self.tui.action=prepare
        self.assertEqual(self.runner.run("preparation")["status"],"passed")

    def test_implementation_real_tasks_and_gates_with_fake_publication(self):
        self.f.prepared()
        def implement():
            self.c.phase_begin("P01"); self.f.live_review(); self.f.implement_all(); self.f.review()
            self.c.gate_phase("P01"); self.c.stack_publish("P01")  # Existing isolated fake GitHub adapter.
            self.c.phase_seal("P01"); self.c.gate_project()
        self.tui.action=implement
        result=self.runner.run("implementation")
        self.assertEqual(result["status"],"passed"); self.assertTrue(result["application_complete"])
        before=copy.deepcopy(self.c.state())
        for stage in ("specification","preparation","implementation"):
            self.assertEqual(self.runner.run(stage)["status"],"passed")
        self.assertEqual(self.c.state(),before); self.assertEqual(len(self.tui.calls),1)
        receipt=next(r for r in before["checks"].values() if r["check_id"]=="behavior" and r["outcome"]=="pass")
        (self.root/receipt["log_path"]).unlink()
        self.assertEqual(self.c.workflow_result("implementation")["status"],"failed")

    def test_terminal_failure_at_tui_close_preserves_primary_without_db_cleanup(self):
        self.f.prepared()
        original=self.tui.run
        for primary in (None,RddError("original failure","environment")):
            diagnostic=RddStorageError("edit",self.c.store.path,sqlite3.DatabaseError("close marker"))
            if primary is not None:
                # A separate fixture is unnecessary: restore only the test-created failure marker.
                (self.root/".rdd/runtime/failures/fixture-run.json").unlink()
            def run(*args):
                original(*args)
                record_failure(self.root,diagnostic,stage="implementation")
                if primary is not None: raise primary
                return 0
            self.tui.run=run
            with patch.object(self.c,"export_run") as export,self.assertRaises(RddError) as caught:
                self.runner.run("implementation")
            export.assert_not_called(); self.assertTrue(caught.exception.restart_required)
            if primary is not None: self.assertIs(caught.exception,primary)

    def test_tagged_cleanup_failures_never_write_journal_or_checkpoint(self):
        from tools.rdd import common,storage_failure
        self.f.prepared(); saved=[]; run_id=self.c.state()["id"]
        for primary in (RddError("primary body","environment"),ValueError("primary body"),KeyboardInterrupt("primary body")):
            original_connect=common.sqlite3.connect
            class CloseFault:
                def __init__(self,connection): self.connection=connection
                def __getattr__(self,name): return getattr(self.connection,name)
                def close(self):
                    self.connection.close(); raise sqlite3.DatabaseError("tagged close fault")
            def fail():
                with patch("tools.rdd.common.sqlite3.connect",side_effect=lambda *a,**k:CloseFault(original_connect(*a,**k))),patch("tools.rdd.storage_failure.atomic_write",side_effect=OSError("marker unavailable")):
                    try:
                        with self.c.store.edit(run_id): raise primary
                    finally: saved.append(edit.call_count)
            self.tui.action=fail
            with patch.object(self.c.store,"edit",wraps=self.c.store.edit) as edit,patch.object(self.c,"export_run") as export,self.assertRaises(type(primary)) as caught:
                self.runner.run("implementation")
            self.assertIs(caught.exception,primary); self.assertTrue(primary.restart_required)
            self.assertIn("tagged close fault",str(primary)); self.assertEqual(edit.call_count,saved[-1]); export.assert_not_called()
            self.assertTrue(self.tui.closed)

    def test_fresh_main_bootstraps_only_after_preflight_and_reentry_keeps_run(self):
        # Independent clean clone retains no ignored state from the source fixture.
        import tempfile
        from tools.rdd.engine import Controller
        self.f.commit("Seed clean fixture"); holder=tempfile.TemporaryDirectory(); self.addCleanup(holder.cleanup)
        root=Path(holder.name)/"repo"
        subprocess.run(["git","clone","-q",str(self.root),str(root)],check=True)
        self.f.g("switch","-c","main",root=root)
        c=Controller(root); self.addCleanup(c.close); tui=FakeTui(c)
        bad=MetadataServer(root); bad.effective_config["sandbox_mode"]="read-only"
        driver=WorkflowRunner(c,server_factory=lambda *a,**k:bad,tui=tui,terminal=lambda:True,emit=lambda _:None)
        with self.assertRaises(RddError): driver.run("specification","regenerate")
        self.assertFalse((root/".rdd/run.json").exists()); self.assertEqual(self.f.g("branch","--show-current",root=root),"main")
        bad.effective_config["sandbox_mode"]="workspace-write"
        first=driver.run("specification","regenerate"); second=driver.run("specification","regenerate")
        self.assertEqual(first["run_id"],second["run_id"])
        self.assertRegex(self.f.g("branch","--show-current",root=root),r"^codex/.+-baseline$")

    def test_later_blocker_does_not_reopen_accepted_upstream(self):
        self.f.prepared(); self.c.block("environment","Fixture native evidence unavailable")
        self.assertEqual(self.runner.run("specification")["status"],"passed")
        self.assertFalse(self.tui.calls)

    def test_wrong_stage_or_corrupt_prerequisite_stops_before_backend(self):
        before=copy.deepcopy(self.c.state())
        with self.assertRaises(RddError): self.runner.run("implementation")
        self.assertEqual(self.c.state(),before); self.assertFalse(self.server.calls)
        self.accepted_spec()
        receipt=next(iter(self.c.state()["checks"].values()))
        (self.root/receipt["log_path"]).write_text("corrupt\n")
        with self.assertRaises(RddError): self.runner.run("preparation")
        self.assertFalse(self.server.calls); self.assertFalse(self.tui.calls)

    def test_journal_reload_preserves_real_child_controller_mutation(self):
        cli=Path(__file__).resolve().parents[2]/"tools/rdd/cli.py"
        def child():
            result=subprocess.run([sys.executable,str(cli),"--root",str(self.root),"author","record","--stage","specification","--session-id","real-child-author"],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.tui.action=child
        self.assertEqual(self.runner.run("specification")["status"],"incomplete")
        self.assertIn("real-child-author",self.c.state()["authors"]["specification"])

    def test_tagged_interrupt_is_critical_not_ordinary_user_interrupt(self):
        def interrupted(*args):
            exc=KeyboardInterrupt(); exc.restart_required=True; raise exc
        with patch.object(self.runner,"_run",side_effect=interrupted),self.assertRaises(KeyboardInterrupt):
            self.runner.run("implementation")

    def test_real_child_terminal_failure_stops_owned_work_before_export(self):
        self.f.prepared(); repo=Path(__file__).resolve().parents[2]
        script='from pathlib import Path; import sqlite3,sys; from tools.rdd.common import RddStorageError; from tools.rdd.storage_failure import record_failure; root=Path(sys.argv[1]); record_failure(root,RddStorageError("edit",root/".rdd/runtime/state.sqlite",sqlite3.DatabaseError("child malformed")))'
        def child():
            subprocess.run([sys.executable,"-c",script,str(self.root)],cwd=repo,check=True,capture_output=True)
        self.tui.action=child
        with patch.object(self.c,"export_run") as export,self.assertRaisesRegex(RddError,"Critical"):
            self.runner.run("implementation")
        export.assert_not_called(); self.assertTrue(self.tui.closed)
        with self.assertRaisesRegex(RddError,"Critical"): self.runner.run("implementation")

    def test_early_storage_failure_is_not_returned_as_validation_failure(self):
        error=RddStorageError("read",self.c.store.path,sqlite3.DatabaseError("fixture malformed"))
        with patch.object(self.c,"state",side_effect=error),self.assertRaises(RddStorageError):
            self.runner.run("specification")
        self.assertFalse(self.server.calls); self.assertFalse(self.tui.calls)

    def test_export_storage_error_is_not_silenced(self):
        self.f.commit("Clean fixture")
        error=RddStorageError("read",self.c.store.path,sqlite3.DatabaseError("fixture malformed"))
        with patch.object(self.c,"export_run",side_effect=error),self.assertRaises(RddStorageError):
            self.runner.run("specification")
        self.assertTrue(self.tui.closed)


@unittest.skipUnless(os.name=="posix","POSIX foreground process ownership")
class NativeProcessTests(unittest.TestCase):
    def test_foreground_restored_even_if_owned_cleanup_fails(self):
        from tools.rdd.workflow import NativeTui
        from unittest.mock import Mock
        proc=Mock(); proc.wait.side_effect=RuntimeError("primary")
        tui=NativeTui(); tui.table=object(); groups=[]; tree=Mock(); tree.close.side_effect=RddError("cleanup","environment")
        with patch("tools.rdd.workflow.subprocess.Popen",return_value=proc),patch("tools.rdd.workflow.sys.stdin.fileno",return_value=9),patch("os.tcgetpgrp",return_value=100),patch.object(tui,"foreground",side_effect=lambda fd,g:groups.append(g)),patch("os.killpg"),patch("tools.rdd.workflow.OwnedProcessTree",return_value=tree):
            with self.assertRaisesRegex(RuntimeError,"primary.*cleanup"): tui.run(["fixture"],Path.cwd(),lambda:None)
        self.assertEqual(groups[-1],100)

    def test_terminal_restoration_cannot_mask_primary_failure(self):
        from tools.rdd.workflow import NativeTui
        from unittest.mock import Mock
        primary=RddError("primary terminal failure","environment")
        proc=Mock(); proc.wait.side_effect=primary
        tui=NativeTui(); tui.table=object()
        with patch("tools.rdd.workflow.subprocess.Popen",return_value=proc),patch("tools.rdd.workflow.sys.stdin.fileno",return_value=9),patch("os.tcgetpgrp",return_value=100),patch.object(tui,"foreground",side_effect=[None,OSError("terminal unavailable")]),patch("os.killpg"),patch("tools.rdd.workflow.OwnedProcessTree"),self.assertRaises(RddError) as caught:
            tui.run(["fixture"],Path.cwd(),lambda:None)
        self.assertIs(caught.exception,primary); self.assertIn("terminal unavailable",str(primary))

    def test_no_absolute_turn_deadline_while_process_is_running(self):
        from tools.rdd.workflow import NativeTui
        from unittest.mock import Mock
        proc=Mock(); proc.poll.return_value=0; proc.wait.side_effect=[subprocess.TimeoutExpired("fixture",.2)]*5000+[0]
        tui=NativeTui(); tui.table=object(); polls=[]
        with patch("tools.rdd.workflow.subprocess.Popen",return_value=proc),patch("tools.rdd.workflow.sys.stdin.fileno",return_value=9),patch("os.tcgetpgrp",return_value=100),patch.object(tui,"foreground"),patch("os.killpg"),patch("tools.rdd.workflow.OwnedProcessTree"):
            self.assertEqual(tui.run(["fixture"],Path.cwd(),lambda:polls.append(1)),0)
        self.assertEqual(len(polls),5001)

    def exercise_failed_identity_read(self, ignore_term=False, after_construction=False):
        from tools.rdd.workflow import NativeTui
        from unittest.mock import Mock
        import time
        original_popen = subprocess.Popen
        processes = []
        primary = RddError('process identity unavailable', 'environment')
        cleanup = RddError('descendant inspection unavailable during cleanup', 'environment')
        tui = NativeTui()
        tui.table = Mock()
        reads = []

        def read(pid):
            reads.append(pid)
            if after_construction and len(reads) == 1:
                from tools.rdd.native_process import ProcessIdentity
                return ProcessIdentity(pid, os.getpid(), os.getpgid(pid), (1, 0), pid, os.getpid(), 1)
            if after_construction and len(reads) > 2:
                raise cleanup
            raise primary

        tui.table.read.side_effect = read
        groups = []
        code = 'import signal,time;'
        if ignore_term:
            code += 'signal.signal(signal.SIGTERM,signal.SIG_IGN);'
        code += "print('ready',flush=True);time.sleep(30)"

        def launch(*args, **kwargs):
            process = original_popen(*args, **kwargs, stdout=subprocess.PIPE, text=True)
            processes.append(process)
            self.assertEqual(process.stdout.readline().strip(), 'ready')
            return process

        try:
            started = time.monotonic()
            with patch('tools.rdd.workflow.subprocess.Popen', side_effect=launch), patch(
                    'tools.rdd.workflow.sys.stdin.fileno', return_value=9), patch(
                    'os.tcgetpgrp', return_value=100), patch.object(
                    tui, 'foreground', side_effect=lambda fd, group: groups.append(group)), self.assertRaises(RddError) as caught:
                tui.run([sys.executable, '-c', code], Path.cwd(), lambda: None)
            self.assertIs(caught.exception, primary)
            self.assertIsNotNone(processes[0].poll(), 'identity inspection failure must stop and reap the direct owned child')
            self.assertLess(time.monotonic() - started, 3, 'direct-child cleanup must have bounded waits')
            self.assertEqual(groups, [processes[0].pid, 100] if after_construction else [100])
            if after_construction:
                self.assertIn('TUI cleanup', str(primary))
                self.assertIn('descendant inspection unavailable', str(primary))
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=2)
                process.stdout.close()

    def test_initial_identity_failure_stops_real_direct_child(self):
        self.exercise_failed_identity_read()

    def test_initial_identity_failure_escalates_stubborn_real_direct_child(self):
        self.exercise_failed_identity_read(ignore_term=True)

    def test_initial_identity_and_cleanup_failures_preserve_primary_and_foreground(self):
        from tools.rdd.workflow import NativeTui
        from unittest.mock import Mock
        primary = RddError('initial process identity unavailable', 'environment')
        proc = Mock()
        proc.wait.side_effect = subprocess.TimeoutExpired('fixture', .5)
        tui = NativeTui(); tui.table = object(); groups = []
        with patch('tools.rdd.workflow.subprocess.Popen', return_value=proc), patch(
                'tools.rdd.workflow.sys.stdin.fileno', return_value=9), patch(
                'os.tcgetpgrp', return_value=100), patch.object(
                tui, 'foreground', side_effect=lambda fd, group: groups.append(group)), patch(
                'tools.rdd.workflow.OwnedProcessTree', side_effect=primary), self.assertRaises(RddError) as caught:
            tui.run(['fixture'], Path.cwd(), lambda: None)
        self.assertIs(caught.exception, primary)
        self.assertIn('TUI cleanup', str(primary))
        self.assertEqual(groups, [100])

    def test_later_identity_failure_stops_real_direct_child(self):
        self.exercise_failed_identity_read(after_construction=True)

    def test_later_identity_failure_escalates_stubborn_real_direct_child(self):
        self.exercise_failed_identity_read(ignore_term=True, after_construction=True)
