"""Prepare a narrowly rebound observer; never grant trust or perform UI actions."""
from pathlib import Path
import argparse,hashlib,json,subprocess,plistlib,re
p=argparse.ArgumentParser();p.add_argument('--app',required=True);p.add_argument('--output',required=True);p.add_argument('--observer-id',required=True);p.add_argument('--build',action='store_true');a=p.parse_args()
assert re.fullmatch(r'com\.rdd\.qualification\.axobserver\.r20261028\.s6\.[a-z0-9]+',a.observer_id)
app=Path(a.app).resolve();out=Path(a.output).resolve();assert not out.exists()
info=plistlib.loads((app/'Contents/Info.plist').read_bytes());binary=app/'Contents/MacOS'/info['CFBundleExecutable'];sha=hashlib.sha256(binary.read_bytes()).hexdigest()
source=Path(__file__).with_name('ax-observer.swift').read_text()
assert hashlib.sha256(source.encode()).hexdigest()=='95f52b6ac52f1a7deeaa2fa86d8118c48f6689ae96f7ec3e778df0661f49d0e0'
assert not any(c in str(binary) for c in ['\"','\\','\n','\r'])
old='/Users/connorsanders/Applications/RDD Qualification Carrier-R20261028T021552Z-CSP.app/Contents/MacOS/qualification-carrier'
assert source.count(old)==1 and source.count('6f7bf88dd53153287ae2c137694ab1b7c0c91193bca9b4f9fae63946b4d35bb9')==1
assert info['CFBundleIdentifier']=='com.rdd.qualification.r20261028'
source=source.replace(old,str(binary)).replace('6f7bf88dd53153287ae2c137694ab1b7c0c91193bca9b4f9fae63946b4d35bb9',sha).replace('com.rdd.qualification.axobserver.r20261028.v6',a.observer_id)
out.mkdir(parents=True);(out/'observer.swift').write_text(source)
identity={'target_app':str(app),'target_executable':str(binary),'target_sha256':sha,'target_bundle_identifier':info['CFBundleIdentifier'],'observer_bundle_identifier':a.observer_id,'source_sha256':hashlib.sha256(source.encode()).hexdigest(),'status':'prepared; requires explicit identity review, compilation and observed trust before actions'}
if a.build:
 observer=out/'RDD S6 Exact Observer.app';macos=observer/'Contents/MacOS';macos.mkdir(parents=True)
 plist=plistlib.loads(Path(__file__).with_name('Info.plist').read_bytes());plist['CFBundleIdentifier']=a.observer_id;plist['CFBundleDisplayName']='RDD S6 Exact Observer';plist['CFBundleName']='RDD S6 Exact Observer';(observer/'Contents/Info.plist').write_bytes(plistlib.dumps(plist))
 subprocess.run(['/usr/bin/xcrun','swiftc',str(out/'observer.swift'),'-o',str(macos/'ax-observer')],check=True,capture_output=True,timeout=90)
 subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(observer)],check=True,capture_output=True,timeout=30)
 identity.update(observer_executable=str(macos/'ax-observer'),observer_sha256=hashlib.sha256((macos/'ax-observer').read_bytes()).hexdigest(),status='built; exact identity requires review and actual trust before any UI action')
(out/'identity.json').write_text(json.dumps(identity,indent=2)+'\n');print(json.dumps(identity))
