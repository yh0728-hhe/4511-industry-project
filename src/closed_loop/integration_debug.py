"""Core component integration debugger. Real coordinator/parser/stage code, injected I/O.
No live model, external HTTP, Y table, demo renderer or credential loader.
"""
import argparse
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from .archive_transport import ArchivedWebsiteProvider, HTTPResponse
from .contracts import ResearchRequest
from .fixtures import request
from .guards import CallBudget, TemporalGateway
from .model_lead import ModelLead, LeadPlanOutput, PlannedResearch
from .native_committee import NativeDialecticCommittee, NativeConfig
from .native_support import (ArgumentsOutput,ArgumentOutput,ArgumentCritique,SingleArgumentScore,
    CriterionScore,IndividualRefinedArgumentOutput,EvidenceReviewOutput)
from .offline_network import OfflineSocketGuard
from .research_backend import MeteredResearchProvider, ResearchNavigationPlan
from .runtime import ClosedLoopRuntime
from .thesis_synthesis import ThesisSynthesizer, ThesisSynthesis


class InjectedArchiveHTTP:
    def __init__(self,case):self.case=case;self.calls=[]

    def get(self,url,timeout,max_bytes,check_deadline=lambda:None):
        check_deadline();self.calls.append(url)
        if '/cdx/' in url:
            original='https://'+parse_qs(urlparse(url).query)['url'][0]
            ts='20250320000000' if self.case=='future_capture' and original.endswith('/cohort') else '20240320000000'
            body=json.dumps([['timestamp','original','statuscode','mimetype'],[ts,original,'200','text/html']]).encode()
            return HTTPResponse(200,url,{},body)
        if url.endswith('/cohort'):
            if self.case=='unreadable_capture':return HTTPResponse(403,url,{},b'')
            body=('Invented fixture cohort report. SYNTHETIC_RETENTION_GOOD. '
                  'This is an explicitly synthetic service and is not real company or investment data.').encode()
        else:
            body=('<html><body>Invented fixture service in a synthetic market, with no retention claim on this page. '
                  'This is a synthetic business description for testing only. '
                  '<a href="/cohort">Read customer cohort report</a></body></html>').encode()
        return HTTPResponse(200,url,{'Memento-Datetime':'Wed, 20 Mar 2024 00:00:00 GMT','Content-Type':'text/html'},body)


class InjectedModelBackend:
    """Responses depend on actually admitted evidence; no model-quality claim."""
    def __init__(self,case):self.case=case;self.calls=[]

    def generate(self,schema,messages,temperature):
        context=json.loads(messages[0].content.split('\n',1)[1])
        rows=context['evidence'];ids=[x['fact_id'] for x in rows]
        self.calls.append({'schema':schema.__name__,'fact_revision':context['fact_revision'],
                           'fact_ids':ids,'text_seen':'\n'.join(x['answer'] for x in rows)})
        good=any('SYNTHETIC_RETENTION_GOOD' in row['answer'] for row in rows)
        if schema is LeadPlanOutput:
            task=PlannedResearch('other','Inspect root context',None,'/') if not rows else PlannedResearch('traction','Verify retention',None,'/cohort')
            return LeadPlanOutput([task])
        if schema is ResearchNavigationPlan:
            return ResearchNavigationPlan('FETCH','/unseen') if self.case=='unobserved_navigation' else ResearchNavigationPlan('STOP',None)
        if schema is ArgumentsOutput:
            side='PRO' if 'pro arguments why' in messages[-1].content else 'CONTRA'
            return ArgumentsOutput([ArgumentOutput('SYNTHETIC_'+side+' argument',list(range(len(rows))))])
        if schema is ArgumentCritique:return ArgumentCritique('Synthetic critique: check retention against admitted records.')
        if schema is SingleArgumentScore:
            pro='SYNTHETIC_PRO' in messages[-1].content
            n=6 if good and pro else 3
            return SingleArgumentScore([CriterionScore(n,'Synthetic criterion rationale') for _ in range(14)])
        if schema is IndividualRefinedArgumentOutput:
            side='PRO' if 'SYNTHETIC_PRO' in messages[-1].content else 'CONTRA'
            return IndividualRefinedArgumentOutput('SYNTHETIC_'+side+' refined',list(range(len(rows))))
        if schema is EvidenceReviewOutput:
            return EvidenceReviewOutput([] if good else ['retention'],'Synthetic evidence review.')
        if schema is ThesisSynthesis:
            cited=['invented'] if self.case=='invalid_thesis' else ids
            return ThesisSynthesis('Synthetic supported conclusion.',['Synthetic evidence supplied.'],
                                   ['Synthetic fixture only.'],cited,['No real company inference.'],[],['Independent verification.'])
        raise ValueError('Unsupported integration schema')

    async def agenerate(self,schema,messages,temperature):return self.generate(schema,messages,temperature)


CASES=('complete','future_capture','unreadable_capture','unobserved_navigation','invalid_thesis','model_cap','full_stack_cap24')


def run_debug_case(case='complete'):
    if case not in CASES:raise ValueError('Unknown debug case')
    req=request(max_model_calls=3 if case=='model_cap' else (24 if case=='full_stack_cap24' else 40),max_search_calls=6,max_research_passes=2)
    budget=CallBudget(req);gateway=TemporalGateway(req,[])
    http=InjectedArchiveHTTP(case);backend=InjectedModelBackend(case)
    with OfflineSocketGuard():
        archive=ArchivedWebsiteProvider(req,gateway,budget,client=http,max_requests=6)
        provider=MeteredResearchProvider(req,gateway,budget,backend,archive,max_navigation_steps=1)
        committee=NativeDialecticCommittee(backend,budget,NativeConfig(selection_policy='balanced_per_side'))
        runtime=ClosedLoopRuntime(req,gateway,budget,ModelLead(backend,budget,max_specialists=1),committee,
                                  provider,thesis=ThesisSynthesizer(backend,budget))
        result=runtime.run()
    result.update(status='CORE_COMPONENT_INTEGRATION_INJECTED_IO_NOT_LIVE',case=case,
                  actual_model_calls=0,actual_network_calls=0,injected_http_calls=len(http.calls),
                  injected_backend_calls=len(backend.calls),archive_attempts=archive.attempts,
                  archive_receipts=archive.receipts,research_trace=provider.trace,
                  backend_calls=backend.calls,accounting_note='Counts are injected I/O dispatches, not real provider calls or billing.')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():p.error('Preserve existing debugging output; choose new filename')
    results={case:run_debug_case(case) for case in CASES}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x',encoding='utf-8',newline='\n') as f:json.dump(results,f,indent=2);f.write('\n')
    print(json.dumps({k:{'decision':v['decision'],'stop_reason':v['stop_reason'],
                        'model_dispatches':v['injected_backend_calls'],'http_dispatches':v['injected_http_calls'],
                        'thesis_present':v['thesis'] is not None} for k,v in results.items()},indent=2))


if __name__=='__main__':main()
