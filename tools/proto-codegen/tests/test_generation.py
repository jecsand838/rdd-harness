"""Actual multi-package compiler qualification; missing tools fail this target.

Run separately from offline harness selftests:
python3 tools/proto-codegen/tests/test_generation.py
"""
from pathlib import Path
from contextlib import contextmanager
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from tools.rdd.proto_traits import run_contracts, ContractCheckError
from tools.rdd.readiness import verify_canonical_contract_receipts


def preserve_evidence(root, inputs_name="inputs"):
    """Retain real inputs, receipts and raw logs before disposable cleanup."""
    destination = Path(os.environ.get("RDD_CONTRACT_EVIDENCE", REPO / ".rdd/evidence/harness-contracts"))
    destination.mkdir(parents=True, exist_ok=True)
    for path in (root / ".rdd/runtime").glob("contracts-*"):
        shutil.copytree(path, destination / path.name, dirs_exist_ok=True)
    inputs = destination / inputs_name
    inputs.mkdir(exist_ok=True)
    for relative in ("contracts", "gen/rust", "tools/proto-codegen", "buf.yaml", "rust-toolchain.toml"):
        source = root / relative
        target = inputs / relative
        if source.is_dir():
            shutil.copytree(source,target,dirs_exist_ok=True,ignore=shutil.ignore_patterns("target","__pycache__"))
        elif source.is_file():
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,target)


@contextmanager
def qualification_fixture():
    with tempfile.TemporaryDirectory(prefix="rdd-multimodule-") as directory:
        root = Path(directory)
        try:
            yield root
        finally:
            preserve_evidence(root,"final-inputs")


class DescriptorCompilerQualification(unittest.TestCase):
    def test_real_multi_package_provider_consumer_and_each_negative_signature(self):
        with qualification_fixture() as root:
            shutil.copytree(REPO / "tools/proto-codegen", root / "tools/proto-codegen",
                ignore=shutil.ignore_patterns("target", "__pycache__"))
            shutil.copyfile(REPO / "rust-toolchain.toml", root / "rust-toolchain.toml")
            subprocess.run(["git", "init", "-q", "-b", "codex/qualification", str(root)], check=True)
            def write(relative, content):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content.encode("utf-8"))
            # Naming exceptions permit deliberately shared/cross-package RPC
            # shapes in this generator fixture; production lint is untouched.
            write("buf.yaml", "version: v2\nmodules:\n  - path: contracts\nlint:\n  use: [STANDARD]\n"
                "  except: [RPC_REQUEST_STANDARD_NAME, RPC_RESPONSE_STANDARD_NAME, RPC_REQUEST_RESPONSE_UNIQUE]\n"
                "breaking:\n  use: [FILE]\n")
            write("contracts/fixture/store/v1/read.proto", '''syntax = "proto3";
package fixture.store.v1;
import "google/protobuf/empty.proto";
import "google/protobuf/timestamp.proto";
service ReadService { rpc Read(google.protobuf.Empty) returns (ReadResponse); rpc Time(google.protobuf.Timestamp) returns (ReadResponse); }
message ReadResponse {
  message NestedResponse { oneof outcome { string accepted = 1; string error = 2; } }
  oneof outcome { NestedResponse found = 1; string error = 2; }
}
''')
            write("contracts/fixture/store/v1/write.proto", '''syntax = "proto3";
package fixture.store.v1;
import "google/protobuf/duration.proto";
service WriteService { rpc Write(google.protobuf.Duration) returns (WriteResponse); }
message WriteRequest { string value = 1; }
message WriteResponse { oneof outcome { bool accepted = 1; string error = 2; } }
''')
            write("contracts/fixture/query/v1/query.proto", '''syntax = "proto3";
package fixture.query.v1;
import "fixture/store/v1/read.proto";
import "fixture/store/v1/write.proto";
service QueryService { rpc Query(fixture.store.v1.WriteRequest) returns (fixture.store.v1.ReadResponse.NestedResponse); }
''')
            try:
                result = run_contracts(root, write=True, bootstrap_lock=True, targets=("wasm32-unknown-unknown",))
            except ContractCheckError:
                for log in sorted((root / ".rdd/runtime").glob("contracts-*/logs/*.log"))[-1:]:
                    print(log.read_text(encoding="utf-8"), file=sys.stderr)
                raise
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["boundary_provider"], "passed")
            self.assertEqual(result["boundary_consumer"], "passed")
            self.assertEqual(len(result["boundary_negative_proofs"]), 16)
            index = json.loads((root / "gen/rust/.rdd-generated.json").read_bytes())["contract_index"]
            self.assertEqual(set(index["source_hashes"]), {
                "contracts/fixture/store/v1/read.proto", "contracts/fixture/store/v1/write.proto", "contracts/fixture/query/v1/query.proto"})
            self.assertIn("google/protobuf/empty.proto", index["descriptor_dependencies"])
            self.assertNotIn("contracts/google/protobuf/empty.proto", index["source_hashes"])
            services = {service["symbol"]:service for service in index["services"]}
            self.assertEqual(services["fixture.store.v1.ReadService"]["generated_path"],
                             services["fixture.store.v1.WriteService"]["generated_path"])
            operation = services["fixture.query.v1.QueryService"]["operations"][0]
            self.assertEqual(operation["rust_input"], "rdd_contracts::fixture::store::v1::WriteRequest")
            self.assertEqual(operation["rust_output"], "rdd_contracts::fixture::store::v1::read_response::NestedResponse")
            self.assertEqual(operation["response_oneofs"][0]["fields"], ["accepted", "error"])
            baseline = root / Path(result["report_path"]).parent / "schema.bin"
            verified = run_contracts(root, targets=("wasm32-unknown-unknown",), against=str(baseline)+"#format=binpb")
            outer_log = ".rdd/runtime/canonical-qualification.log.json"
            write(outer_log,json.dumps({"stdout":json.dumps(verified),"stderr":""})+"\n")
            spec = dict(contract_index_path="gen/rust/.rdd-generated.json",
                generated_files=["gen/rust/"+p for p in verified["generated_files"]],contract_check_ids=["canonical"],
                checks=[dict(id="canonical",kind="contract",cwd=".",argv=["{python}","tools/rdd/proto_traits.py","--target","wasm32-unknown-unknown"])])
            verify_canonical_contract_receipts(root,spec,[dict(check_id="canonical",log_path=outer_log)])
            self.assertFalse(any(b"type Error" in p.read_bytes() for p in (root / "gen/rust/src/generated").glob("*.rs")))
            preserve_evidence(root)
            source = root / "contracts/fixture/store/v1/write.proto"
            source.write_bytes(source.read_bytes().replace(b"string value = 1;", b"string value = 2;"))
            with self.assertRaisesRegex(ContractCheckError,"buf-breaking failed"):
                run_contracts(root, against=str(baseline)+"#format=binpb")


if __name__ == "__main__":
    unittest.main()
