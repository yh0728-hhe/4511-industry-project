"""Inspect source text/AST without importing agent code or making model calls."""
import argparse
import ast
import hashlib
import json
from pathlib import Path


def literal(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return None


def read_tree(root, path):
    file = root/path
    return file, ast.parse(file.read_text(encoding='utf-8-sig'))


def audit(root):
    root=Path(root)
    findings=[]
    files={}
    def load(path):
        file,tree=read_tree(root,path)
        files[path]=hashlib.sha256(file.read_bytes()).hexdigest()
        return tree
    def finding(code,path,line,detail):
        findings.append(dict(code=code,path=path,line=line,detail=detail))
    graph_path='src/agent/pipeline/graph.py'
    graph=load(graph_path)
    edges=[]
    for node in ast.walk(graph):
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='add_edge' and len(node.args)>=2:
            start,end=map(literal,node.args[:2])
            if isinstance(start,str) and isinstance(end,str):edges.append((start,end))
    answering='src/agent/pipeline/stages/parallel_answering.py'
    tree=load(answering)
    for fn in ast.walk(tree):
        if isinstance(fn,(ast.FunctionDef,ast.AsyncFunctionDef)) and fn.name=='answer_all_trees':
            for node in ast.walk(fn):
                if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='_get_or_answer_tree':
                    values={k.arg:literal(k.value) for k in node.keywords}
                    if values.get('is_backtesting') is False and 'search_end_date' in values and values['search_end_date'] is None:
                        finding('LIVE_SEARCH_HARDCODED',answering,node.lineno,
                            'Main answering path explicitly disables backtesting and passes no historical cutoff.')
    cache='src/agent/pipeline/stages/cache.py'
    tree=load(cache)
    for fn in tree.body:
        if isinstance(fn,ast.FunctionDef) and fn.name in ('get_cache_key','get_answered_cache_key'):
            names={a.arg for a in fn.args.args}
            if not {'as_of','mandate','source_policy_version'} & names:
                finding('CACHE_CONTEXT_NOT_KEYED',cache,fn.lineno,
                    fn.name+' accepts no date, mandate or source-policy version; reuse across those contexts is unsafe.')
    cli='src/agent/cli.py'
    tree=load(cli)
    flags=[]
    for node in ast.walk(tree):
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='add_argument' and node.args:
            flags.append(literal(node.args[0]))
    if '--as-of' not in flags and '--search-end-date' not in flags:
        finding('CLI_HAS_NO_HISTORICAL_CUTOFF',cli,1,'Inspected CLI has no as-of/search-end-date option.')
    providers='src/agent/web_search/providers.py'
    tree=load(providers)
    for fn in ast.walk(tree):
        if isinstance(fn,ast.FunctionDef) and fn.name=='_format_results':
            assigned=[n for n in ast.walk(fn) if isinstance(n,ast.Name) and n.id=='date' and isinstance(n.ctx,ast.Store)]
            loaded=[n for n in ast.walk(fn) if isinstance(n,ast.Name) and n.id=='date' and isinstance(n.ctx,ast.Load)]
            if assigned and not loaded:
                finding('RESULT_DATE_DISCARDED',providers,assigned[0].lineno,
                    'Provider reads result date but does not use it in formatted output sent downstream.')
    text=(root/providers).read_text(encoding='utf-8')
    if 'timedelta(days=365)' in text:
        finding('ONE_YEAR_LOOKBACK_RESTRICTION',providers,1,
            'Both date filters use a one-year lookback; older founder and industry evidence can be omitted.')
    state='src/agent/pipeline/state/investment_story.py'
    tree=load(state)
    input_fields=[]
    for node in tree.body:
        if isinstance(node,ast.ClassDef) and node.name=='InputState':
            input_fields=[n.target.id for n in node.body if isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name)]
    if not {'all_qa_pairs','question_trees'} & set(input_fields):
        finding('GRAPH_INPUT_HIDES_RUNTIME_FACT_FIELDS',state,1,
            'InputState exposes company/config only; injecting pre-collected runtime facts needs an explicit compatible adapter/schema.')
    if 'Literal["invest", "not_invest"]' in (root/state).read_text(encoding='utf-8'):
        finding('MORE_DILIGENCE_NOT_IN_DECISION_SCHEMA',state,1,
            'Final decision schema is binary; the requested third outcome needs explicit representation.')
    return dict(status='STATIC_SOURCE_INSPECTION_ONLY_NOT_A_LIVE_AGENT_RUN',
        findings=findings,explicit_graph_edges=sorted(edges),input_fields=input_fields,cli_flags=flags,
        source_sha256=files,model_calls=0,network_calls=0)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-root',required=True)
    p.add_argument('--output',required=True)
    args=p.parse_args()
    result=audit(args.source_root)
    output=Path(args.output)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(json.dumps(dict(findings=len(result['findings']),model_calls=0,network_calls=0)))
