"""Qualification runner; synthetic data only, no product implementation."""
import argparse, hashlib, json, os, pathlib, shutil, subprocess, tempfile, time

ROOT = pathlib.Path(__file__).resolve().parent
TARGET = pathlib.Path(os.environ.get("CARGO_TARGET_DIR", ROOT/"target")).resolve()
LOG = ROOT / "logs"
LOG.mkdir(exist_ok=True)

def run(name, command, cwd=ROOT, env=None, timeout=900):
    start = time.monotonic()
    result = subprocess.run(command, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    (LOG / (name + ".log")).write_text(result.stdout)
    record = {"command":command, "cwd":str(cwd), "exit":result.returncode, "seconds":round(time.monotonic()-start,3)}
    (LOG / (name + ".json")).write_text(json.dumps(record, indent=2)+"\n")
    print(json.dumps(record), flush=True)
    if result.returncode: print(result.stdout[-6000:], flush=True); raise SystemExit(result.returncode)

def native():
    run("native-build", ["cargo", "build", "--locked", "-p", "dependency-native-probe"])
    binary = TARGET / "debug/dependency-native-probe"
    with tempfile.TemporaryDirectory(prefix="rdd-native-", dir=ROOT) as fixture:
        run("native-normal", [str(binary), "normal", str(pathlib.Path(fixture)/"normal.db")])
        observations=[]
        for mode, expected in [("before_commit",{0}),("during_commit_wal_sync",{0,1}),("after_ack",{1})]:
            for repetition in range(5):
                database=pathlib.Path(fixture)/f"{mode}-{repetition}.db"
                proc=subprocess.Popen([str(binary),mode,str(database)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                checkpoint=proc.stdout.readline().strip()
                assert checkpoint==f"checkpoint={mode}", (checkpoint,proc.stderr.read())
                proc.kill(); proc.wait(timeout=10)
                result=subprocess.run([str(binary),"check",str(database)],text=True,capture_output=True,timeout=10)
                assert result.returncode==0, result.stderr
                assert result.stdout.strip() in {f"count={n}" for n in expected}, result.stdout
                observations.append({"cut":mode,"repetition":repetition,"kill_exit":proc.returncode,"reopened":result.stdout.strip()})
        (LOG/"process-kill.json").write_text(json.dumps(observations,indent=2)+"\n")
        print("PASS 5 precommit + 5 actual commit-WAL-sync + 5 postack SIGKILL, independent reopened counts",flush=True)

def ui():
    run("wasm-build", ["cargo", "build", "--locked", "--release", "-p", "dependency-ui-probe", "--target", "wasm32-unknown-unknown"])
    dist=ROOT/"dist"; dist.mkdir(exist_ok=True)
    run("wasm-bindgen", [str(ROOT/"tools/bin/wasm-bindgen"),"--target","web","--out-dir",str(dist),str(TARGET/"wasm32-unknown-unknown/release/dependency_ui_probe.wasm")])
    for name in ["index.html","boot.js"]: shutil.copyfile(ROOT/"ui"/name,dist/name)

def package():
    run("tauri-package", [str(ROOT/"tools/bin/cargo-tauri"),"build","--bundles","app","--no-sign","--ci","--","--locked"],ROOT/"desktop")

def launch():
    binary=TARGET/"release/bundle/macos/RDD Dependency Probe.app/Contents/MacOS/dependency-desktop-probe"
    fixture=pathlib.Path(tempfile.mkdtemp(prefix="package-run-",dir=LOG))
    report_path=fixture/"report.txt"
    env=os.environ.copy(); env["RDD_PROBE_DB"]=str(fixture/"package.db"); env["RDD_PROBE_REPORT"]=str(report_path); env["RDD_PROBE_HOLD_SECONDS"]=os.environ.get("RDD_PROBE_HOLD_SECONDS","30")
    run("package-runtime",[str(binary)],env=env,timeout=60)
    report=report_path.read_text()
    assert report=="PASS packaged Rust WASM invoke + generated QueryRequest/QueryResponse + Turso commit",report
    (LOG/"package-report.txt").write_text(report)
    (LOG/"package-runtime-fixture.json").write_text(json.dumps({"fixture":str(fixture),"fresh_report":str(report_path),"fresh_database":str(fixture/"package.db")},indent=2)+"\n")
    print(report,flush=True)

def sign():
    app=TARGET/"release/bundle/macos/RDD Dependency Probe.app"
    run("package-sign",["/usr/bin/codesign","--force","--deep","--sign","-",str(app)])
    run("package-sign-verify",["/usr/bin/codesign","--verify","--deep","--strict",str(app)])
    run("package-sign-identity",["/usr/bin/codesign","--display","--verbose=4",str(app)])

if __name__=="__main__":
    parser=argparse.ArgumentParser(); parser.add_argument("stage",choices=["native","ui","package","sign","launch"])
    globals()[parser.parse_args().stage]()
