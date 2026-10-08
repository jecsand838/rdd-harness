"""Include the generator's offline orchestration regressions in ./rdd selftest."""
import importlib.util
from pathlib import Path


def load_tests(loader, tests, pattern):
    path = Path(__file__).resolve().parents[2] / "tools/proto-codegen/tests/test_orchestration.py"
    spec = importlib.util.spec_from_file_location("rdd_proto_orchestration_regressions", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return loader.loadTestsFromModule(module)
