"""Small stdlib harness runner with explicit suite scope and optional timings."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
import unittest


PORTABILITY_SELECTORS = (
    "test_portability.PortabilityTests",
    "test_adapters.RunArgvTests",
    "test_adapters.GitAdapterTests",
    "test_store.StoreTests",
    "test_branch_guards.BranchGuardTests.test_preflight_reads_latest_committed_live_wal_without_changing_its_files",
    "test_branch_guards.BranchGuardTests.test_preflight_recovers_wal_without_shm_only_in_the_temporary_copy",
)


def iter_tests(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from iter_tests(test)
        else:
            yield test


def load_suite(root: Path, suite: str):
    directory = root / "tests/harness"
    # Historical tests import test_engine and other fixture owners by bare name.
    for path in (str(root), str(directory)):
        if path not in sys.path:
            sys.path.insert(0, path)
    loader = unittest.TestLoader()
    if suite == "full":
        return loader.discover(str(directory), pattern="test_*.py")
    if suite == "portability":
        return loader.loadTestsFromNames(PORTABILITY_SELECTORS)
    raise ValueError(f"Unknown harness suite: {suite}")


class TimingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timings = []
        self.started = {}
        self.outcomes = {}

    def startTest(self, test):
        self.started[test] = time.perf_counter()
        super().startTest(test)

    def stopTest(self, test):
        self.timings.append(dict(id=test.id(), duration_seconds=time.perf_counter() - self.started.pop(test),
                                 outcome=self.outcomes.pop(test, "error")))
        super().stopTest(test)

    def addSuccess(self, test):
        self.outcomes[test] = "pass"
        super().addSuccess(test)

    def addFailure(self, test, err):
        self.outcomes[test] = "failure"
        super().addFailure(test, err)

    def addError(self, test, err):
        self.outcomes[test] = "error"
        super().addError(test, err)

    def addSkip(self, test, reason):
        self.outcomes[test] = "skip"
        super().addSkip(test, reason)

    def addExpectedFailure(self, test, err):
        self.outcomes[test] = "expected_failure"
        super().addExpectedFailure(test, err)

    def addUnexpectedSuccess(self, test):
        self.outcomes[test] = "unexpected_success"
        super().addUnexpectedSuccess(test)

    def addSubTest(self, test, subtest, err):
        if err is not None:
            outcome = "failure" if issubclass(err[0], test.failureException) else "error"
            if self.outcomes.get(test) != "error":
                self.outcomes[test] = outcome
        super().addSubTest(test, subtest, err)


def run(root: Path, suite: str = "full", timings: Path | None = None, *, stream=None):
    started = time.perf_counter()
    previous_directory = Path.cwd()
    try:
        os.chdir(root)
        result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=TimingResult).run(load_suite(root, suite))
    finally:
        os.chdir(previous_directory)
    successful = result.wasSuccessful()
    if timings is not None:
        timings.parent.mkdir(parents=True, exist_ok=True)
        with timings.open("w", encoding="utf-8", newline="\n") as output:
            json.dump(dict(schema_version=1, suite=suite, count=result.testsRun,
                           duration_seconds=time.perf_counter() - started, tests=result.timings,
                           successful=successful), output, indent=2, ensure_ascii=False)
            output.write("\n")
    return dict(status="passed" if successful else "failed",
                scope="harness_regression" if suite == "full" else "harness_portability",
                suite=suite, application_complete=False, returncode=0 if successful else 1,
                tests_run=result.testsRun)
