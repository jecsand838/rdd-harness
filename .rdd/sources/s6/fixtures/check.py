"""Portable Python smoke: reproduce D1 and inspect frozen independent Unicode inputs."""
from pathlib import Path
import hashlib,json,platform,shutil,subprocess,sys,tempfile
ROOT=Path(__file__).resolve().parents[4];HERE=Path(__file__).parent
assert sys.platform=='darwin','this check declares the portable macOS environment'
assert sys.version_info[:3]==(3,14,7),'Python 3.14.7 is the frozen fixture-tool pin'
manifest=json.loads((HERE.parent/'manifest.json').read_text())
names=('d1/D1A.json','d1/D1A.oracle.json','d1/D1B.json','d1/D1B.oracle.json',
       'd1/generate.py','d1/manifest.json','unicode/CaseFolding.txt',
       'unicode/CompositionExclusions.txt','unicode/NormalizationTest.txt',
       'unicode/PropList.txt','unicode/UnicodeData.txt','unicode/unicode-vectors.json',
       'unicode/white-space-vectors.json')
expected={str((HERE/name).relative_to(ROOT)) for name in names}
rows=[row for row in manifest['copies'] if row['path'] in expected]
assert len(rows)==len(expected) and {row['path'] for row in rows}==expected,'fixture inventory is incomplete or duplicated'
inputs=[]
for row in rows:
 p=ROOT/row['path'];data=p.read_bytes();actual=hashlib.sha256(data).hexdigest()
 if actual!=row['sha256']:raise SystemExit('immutable input differs: '+row['path']+' expected='+row['sha256']+' observed='+actual)
 inputs.append({'path':row['path'],'bytes':len(data),'sha256':actual})
runtime=ROOT/'.rdd/runtime/s6';runtime.mkdir(parents=True,exist_ok=True)
work=Path(tempfile.mkdtemp(prefix='fixtures-',dir=runtime))
shutil.copyfile(HERE/'d1/generate.py',work/'generate.py')
generated=subprocess.run([sys.executable,str(work/'generate.py')],capture_output=True,timeout=90)
(work/'generate.stdout').write_bytes(generated.stdout);(work/'generate.stderr').write_bytes(generated.stderr)
generated.check_returncode()
for name in ('D1A.json','D1B.json','D1A.oracle.json','D1B.oracle.json','manifest.json'):
 assert (work/name).read_bytes()==(HERE/'d1'/name).read_bytes(),name
normalization=[line.split('#',1)[0].strip() for line in (HERE/'unicode/NormalizationTest.txt').read_text().splitlines()]
normalization=[line for line in normalization if line and not line.startswith('@')]
assert len(normalization)>10000
for line in normalization:
 columns=line.split(';');assert len(columns)>=5
 for col in columns[:5]:assert all(0<=int(cp,16)<=0x10ffff for cp in col.split())
folding=[line.split('#',1)[0].strip().split(';') for line in (HERE/'unicode/CaseFolding.txt').read_text().splitlines() if line.split('#',1)[0].strip()]
full=[r for r in folding if r[1].strip() in ('C','F')];assert len(full)==1606
for name in ('unicode-vectors.json','white-space-vectors.json'):
 assert json.loads((HERE/'unicode'/name).read_text()),name
report={'fixture_reproduction':'pass','variants':2,'tasks':20000,'full_normalization_rows':len(normalization),'default_full_casefold_rows':len(full),'inputs':inputs,'work':str(work),'scope':'independent frozen inputs and provided Python smoke; no application conformance, hosted provisioning or native acceptance'}
(work/'result.json').write_text(json.dumps(report,indent=2)+'\n')
report['resources']={'R-PYTHON-PORTABLE':{'environment':'macos-portable','version':platform.python_version(),'observation':'Pinned Python reproduced both 10000-task D1 variants, their independent identity/order oracles and manifest byte-for-byte, hashed all 13 inputs, and inspected full normalization/casefold inputs. executable='+str(Path(sys.executable).resolve())+'; machine='+platform.machine()}}
print(json.dumps(report))
