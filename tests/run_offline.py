#!/usr/bin/env python3
"""Run every regression file in a separate process with sockets blocked.
Requires the project's regular pandas/numpy/openpyxl/requests dependencies.
No broker account activation, downloads or real orders. Logs: reports/verification.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]

def main():
    out=ROOT/'reports/verification';out.mkdir(parents=True,exist_ok=True)
    results=[]
    with tempfile.TemporaryDirectory(prefix='rb-offline-guard-') as tmp:
        Path(tmp,'sitecustomize.py').write_text("import socket\ndef blocked(*a,**k):\n    raise RuntimeError('OFFLINE REGRESSION GUARD: external connections blocked')\nsocket.socket.connect=blocked\nsocket.socket.connect_ex=blocked\nsocket.create_connection=blocked\n")
        env=dict(os.environ,PYTHONPATH=tmp+os.pathsep+str(ROOT)+os.pathsep+os.environ.get('PYTHONPATH',''))
        for f in sorted((ROOT/'tests').glob('test_*.py')):
            p=subprocess.run([sys.executable,str(f)],cwd=ROOT,env=env,capture_output=True,text=True,timeout=120)
            output=p.stdout+p.stderr;(out/(f.stem+'.txt')).write_text(output)
            count=re.search(r'(\d+)\s*/\s*(\d+) passed',output)
            unit=re.search(r'Ran (\d+) tests?',output)
            checks=int(count.group(2)) if count else int(unit.group(1)) if unit else None
            results.append(dict(file=f.name,exit_code=p.returncode,checks=checks,skipped_notes=[r.strip() for r in output.splitlines() if 'skipped' in r.lower()]))
            print(f.name, 'PASS' if p.returncode==0 else 'FAIL',checks if checks is not None else '?',flush=True)
        (out/'test_results.json').write_text(json.dumps(results,indent=2))
    print('TOTAL',sum(r['checks'] or 0 for r in results),'checks;',len(results),'groups; external sockets blocked')
    return int(any(r['exit_code'] for r in results))
if __name__=='__main__':sys.exit(main())
