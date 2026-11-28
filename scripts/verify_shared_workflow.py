"""Public workflow verification; no provider data, model calls or source retrieval."""
import argparse,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from closed_loop.cli_backend import ProcessExecutor

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--max-seconds',type=int,default=300);a=p.parse_args()
 if not 1<=a.max_seconds<=600:raise ValueError('BOUNDED_DEADLINE_REQUIRED')
 out=a.output_dir.resolve();out.mkdir(parents=True,exist_ok=False)
 temp=out/'temp';temp.mkdir();os.environ.update(PYTHONPATH=str(ROOT/'src'),PYTHONUTF8='1',TEMP=str(temp),TMP=str(temp))
 py=[sys.executable,'-X','utf8'];steps=[
 ('runtime_tests',py+['-m','unittest','discover','-s','tests','-p','test_*.py','-q']),
 ('snapshot_integrity',py+['data/team_snapshot_20261118/validate_snapshot.py']),
 ('synthetic_loop',py+['experiments/closed_loop_offline/run_fixtures.py',str(out/'fixtures.json')]),
 ('plan_only_preflight',py+['experiments/closed_loop_offline/weekly_smoke.py','--plan-output',str(out/'adagy_plan.json')]),
 ('injected_research_workflow',py+['-m','closed_loop.integration_debug','--output',str(out/'integration_debug.json')])]
 state=dict(profile='SHARED_WORKFLOW_ONLY',private_funding_suites_executed=False,model_calls_requested=0,source_http_requested=0,Y_changed=False,training=False,steps=[]);end=time.monotonic()+a.max_seconds;os.chdir(ROOT)
 for name,argv in steps:
  started=time.monotonic()
  try:
   remaining=end-started
   if remaining<=0:raise TimeoutError()
   code,stdout,stderr=ProcessExecutor().run(argv,b'',remaining)
   (out/(name+'.log')).write_bytes(stdout+stderr)
   state['steps'].append(dict(name=name,exit_code=code,elapsed_seconds=round(time.monotonic()-started,3)))
   if code:state['status']='FAILED';break
  except (subprocess.TimeoutExpired,TimeoutError):state['status']='STOPPED_DEADLINE';break
 else:state['status']='PASSED'
 (out/'receipt.json').write_text(json.dumps(state,indent=2)+'\n',encoding='utf-8');print(json.dumps(state,indent=2));return 0 if state['status']=='PASSED' else 2
if __name__=='__main__':raise SystemExit(main())
