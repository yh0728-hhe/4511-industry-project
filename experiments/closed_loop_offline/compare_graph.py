"""Compare stage-level installed LangGraph against the stdlib fixture driver.

Network sockets and tracing are disabled before framework imports. This runs our
fixture nodes plus an attributed pure upstream aggregation function, not live
DIALECTIC model/research stages.
"""
import json
import os
from pathlib import Path
import socket
import sys

for key in list(os.environ):
    if key.startswith(('LANGSMITH_','LANGCHAIN_')):os.environ.pop(key,None)
os.environ['LANGSMITH_TRACING']='false'
os.environ['LANGCHAIN_TRACING_V2']='false'
def no_network(*args,**kwargs):raise RuntimeError('Network forbidden in offline graph comparison')
socket.socket.connect=no_network
socket.socket.connect_ex=no_network
socket.create_connection=no_network
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))

from importlib.metadata import version
from closed_loop.fixtures import run_case,stamp


def compare():
    scenarios={
        'invest':{},'pass':{'good':False},'no_new':{'empty':True},
        'call_cap':{'max_search_calls':2},'no_model_budget':{'max_model_calls':0},
        'expired':{'deadline':stamp('2020-01-01T00:00:00Z')},
        'one_pass':{'max_research_passes':1},
    }
    cases={}
    for name,args in scenarios.items():
        regular=run_case(driver='python',**args)
        graph=run_case(driver='langgraph',**args)
        if regular!=graph:raise AssertionError('Driver mismatch: '+name)
        cases[name]=dict(equal=True,decision=graph['decision'],stop=graph['stop_reason'],
            fact_revision=graph['fact_revision'],argument_revision=graph['argument_revision'],
            logical_call_budget=graph['logical_call_budget'],trace=graph['trace'])
    return dict(status='OFFLINE_STAGE_GRAPH_COMPARISON_NOT_REAL_PREDICTIONS',
        langgraph_version=version('langgraph'),pydantic_version=version('pydantic'),
        scenarios=cases,all_driver_outputs_equal=True,actual_model_calls=0,actual_network_calls=0,
        framework_installed_before_run=True,package_installs=0,
        upstream_reuse='Pure DIALECTIC aggregation function only; real generation/critique/search not invoked',
        os_sandbox_certified=False,network_guard='socket connections blocked; tracing disabled')


if __name__=='__main__':
    result=compare()
    output=Path(sys.argv[1]) if len(sys.argv)>1 else Path('results/candidates/closed_loop_offline/graph_comparison.json')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(scenarios=len(result['scenarios']),all_driver_outputs_equal=True,actual_model_calls=0,actual_network_calls=0)))
