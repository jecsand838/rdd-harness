"""Exact-input dispatcher; specification checks never execute product scenarios."""
from pathlib import Path
import json,os,subprocess,sys
ROOT=Path(__file__).resolve().parents[3]; HERE=Path(__file__).parent
commands={'boundaries':'boundary.py','joint':'joint.py','fixtures':'fixtures/check.py','tools':'provision.py','host':'host.py','transfer':'transfer.py','native':'native/replay.py'}
if len(sys.argv)!=2 or sys.argv[1] not in commands:raise SystemExit('choose declared qualification action')
env=os.environ.copy();env['PYTHONDONTWRITEBYTECODE']='1'
raise SystemExit(subprocess.call([sys.executable,str(HERE/commands[sys.argv[1]])],cwd=ROOT,env=env))
