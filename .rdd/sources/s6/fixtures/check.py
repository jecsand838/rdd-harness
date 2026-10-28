"""Reproduce accepted D1 bytes; inventory complete independent Unicode data."""
from pathlib import Path
import hashlib,json,shutil,subprocess,sys,tempfile
ROOT=Path(__file__).resolve().parents[4];HERE=Path(__file__).parent
manifest=json.loads((HERE.parent/'manifest.json').read_text())
for row in manifest['copies']:
 p=ROOT/row['path']
 if hashlib.sha256(p.read_bytes()).hexdigest()!=row['sha256']:raise SystemExit('immutable input differs: '+row['path'])
work=Path(tempfile.mkdtemp(prefix='fixtures-',dir=ROOT/'.rdd/runtime'))
shutil.copyfile(HERE/'d1/generate.py',work/'generate.py')
subprocess.run([sys.executable,str(work/'generate.py')],check=True,capture_output=True,timeout=90)
for name in ('D1A.json','D1B.json','D1A.oracle.json','D1B.oracle.json'):
 assert (work/name).read_bytes()==(HERE/'d1'/name).read_bytes(),name
normalization=[line.split('#',1)[0].strip() for line in (HERE/'unicode/NormalizationTest.txt').read_text().splitlines()]
normalization=[line for line in normalization if line and not line.startswith('@')]
assert len(normalization)>10000
for line in normalization:
 columns=line.split(';');assert len(columns)>=5
 for col in columns[:5]:assert all(0<=int(cp,16)<=0x10ffff for cp in col.split())
folding=[line.split('#',1)[0].strip().split(';') for line in (HERE/'unicode/CaseFolding.txt').read_text().splitlines() if line.split('#',1)[0].strip()]
full=[r for r in folding if r[1].strip() in ('C','F')];assert len(full)==1606
print(json.dumps({'fixture_reproduction':'pass','variants':2,'tasks':20000,'full_normalization_rows':len(normalization),'default_full_casefold_rows':len(full),'scope':'independent frozen inputs, not application conformance'}))
