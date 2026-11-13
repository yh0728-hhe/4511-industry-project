"""Run synthetic closed-loop examples; no API key, model or internet required."""
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from closed_loop.fixtures import run_case


if __name__=='__main__':
    cases=dict(invest=run_case(),pass_case=run_case(good=False),
        no_new_evidence=run_case(empty=True),budget_exhausted=run_case(max_search_calls=2))
    expected={'invest':'INVEST','pass_case':'PASS','no_new_evidence':'MORE_DILIGENCE','budget_exhausted':'MORE_DILIGENCE'}
    assert all(cases[key]['decision']==value for key,value in expected.items())
    output=Path(sys.argv[1]) if len(sys.argv)>1 else Path('results/candidates/closed_loop_offline/fixture_runs.json')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(cases,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:dict(decision=value['decision'],stop=value['stop_reason']) for key,value in cases.items()}))
