"""Actual adapted DIALECTIC nodes, fixture backend, two orchestration drivers."""
import json
import os
from pathlib import Path
import sys

for key in list(os.environ):
    if key.startswith(('LANGSMITH_','LANGCHAIN_')):os.environ.pop(key,None)
os.environ['LANGSMITH_TRACING']='false';os.environ['LANGCHAIN_TRACING_V2']='false'
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from closed_loop.offline_network import OfflineSocketGuard
from closed_loop.fixtures import request,FixtureProvider,FixtureLead
from closed_loop.guards import CallBudget,TemporalGateway
from closed_loop.runtime import ClosedLoopRuntime
from closed_loop.native_committee import NativeDialecticCommittee
from closed_loop.native_fixture import NativeFixtureBackend
from closed_loop.graph_driver import run_graph


def one(driver,good=True,empty=False,cap=40):
    req=request(max_model_calls=cap);provider=FixtureProvider(good,empty);budget=CallBudget(req)
    backend=NativeFixtureBackend();committee=NativeDialecticCommittee(backend,budget)
    runtime=ClosedLoopRuntime(req,TemporalGateway(req,provider.ledger),budget,FixtureLead(),committee,provider)
    result=runtime.run() if driver=='python' else run_graph(runtime)
    return dict(result=result,fixture_model_responses=len(backend.calls))


if __name__=='__main__':
    cases={}
    with OfflineSocketGuard() as guard:
        for name,args in {'invest':{},'pass':{'good':False},'unknown':{'empty':True},'nested_cap':{'cap':3}}.items():
            first=one('python',**args);second=one('langgraph',**args)
            if first!=second:raise AssertionError('Native driver mismatch '+name)
            cases[name]=dict(equal=True,**second)
        result=dict(status='ADAPTED_UPSTREAM_NODES_WITH_FIXTURE_RESPONSES_NOT_LIVE_MODEL',cases=cases,
            all_outputs_equal=True,actual_model_calls=0,actual_external_network_calls=0,
            process_owned_loopback_ipc_connections=guard.allowed_loopback_connections,
            blocked_external_operations=guard.blocked_operations)
    output=ROOT/'results/candidates/closed_loop_offline/native_graph_comparison.json'
    output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(cases=len(cases),all_outputs_equal=True,actual_model_calls=0)))
