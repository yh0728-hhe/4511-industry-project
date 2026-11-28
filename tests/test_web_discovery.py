import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from closed_loop.fixtures import request
from closed_loop.contracts import ResearchRequest
from closed_loop.guards import CallBudget, BudgetStopped
from closed_loop.web_discovery import ManagedWebDiscoveryAgent

URL='https://example.org/historical-source'
def stream(urls=None, searches=1, error=False, extra=None):
    events=[]
    for i in range(searches):
        events.extend([
            {'type':'assistant','message':{'content':[{'type':'tool_use','id':str(i),'name':'WebSearch'}]}},
            {'type':'user','message':{'content':[{'type':'tool_result','tool_use_id':str(i),'is_error':error,'content':'Links: '+json.dumps([{'url':URL}])+'\nsummary'}]}}])
    if extra: events.extend(extra)
    events.append({'type':'result','is_error':False,'structured_output':{'status':'found','urls':[URL] if urls is None else urls}})
    return '\n'.join(json.dumps(e) for e in events).encode()
class Executor:
    def __init__(self, data=None, code=0):self.calls=[]; self.data=stream() if data is None else data;self.code=code
    def run(self,*args):self.calls.append(args);return self.code,self.data,b''
class DiscoveryTests(unittest.TestCase):
    def setup_agent(self, data=None, code=0, **caps):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        req=request(**caps); budget=CallBudget(req); executor=Executor(data,code)
        agent=ManagedWebDiscoveryAgent(req,budget,approved=True,executable_path='claude',output_dir=Path(temp.name)/'run',executor=executor)
        return agent,budget,executor,ResearchRequest('specialist','find original documentation',req.company.company_id)
    def test_search_prompt_uses_neutral_bookkeeping_identity(self):
        a,b,e,t=self.setup_agent()
        text=a._build_prompt(t).decode('utf-8')
        self.assertNotIn(a.request.company.company_id,text)
        self.assertIn(a.request.company.name,text)
        self.assertIn(a.request.company.domain,text)
        self.assertIn('subject_',text)

    def test_package_capability_is_optin_and_does_not_supply_a_package(self):
        a,b,e,t=self.setup_agent()
        original=a._build_prompt(t).decode('utf-8')
        self.assertNotIn('PyPI/npm',original)
        a.package_leads=True
        enabled=a._build_prompt(t).decode('utf-8')
        self.assertIn('PyPI/npm',enabled)
        self.assertIn('only if actually observed',enabled)
        self.assertNotIn('sample-sdk',enabled)
        self.assertEqual(b.used,{'model':0,'search':0})

    def test_nonboolean_package_capability_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as root:
            req=request();budget=CallBudget(req);out=Path(root)/'not-created'
            with self.assertRaises(ValueError):
                ManagedWebDiscoveryAgent(req,budget,approved=True,executable_path='fixture',
                    output_dir=out,package_leads='true')
            self.assertFalse(out.exists())

    def test_success_counts_and_raw_retention(self):
        a,b,e,t=self.setup_agent();r=a.discover(t)
        self.assertEqual(r.source_urls,(URL,));self.assertFalse(r.verified);self.assertEqual(r.admitted_fact_count,0)
        self.assertEqual(b.used,{'model':1,'search':1});self.assertEqual(b.active,0)
        self.assertTrue((a.output_dir/'raw_stream.jsonl').exists())
        argv=e.calls[0][0];self.assertEqual(argv[argv.index('--tools')+1],'WebSearch');self.assertIn('--safe-mode',argv)
    def test_fabricated_url_cannot_be_certified_by_structured_tool(self):
        fake='https://forged.example/claim'
        extra=[{'type':'assistant','message':{'content':[{'type':'tool_use','id':'s','name':'StructuredOutput'}]}},{'type':'user','message':{'content':[{'type':'tool_result','tool_use_id':'s','content':'Links: '+json.dumps([{'url':fake}])}]}}]
        a,b,e,t=self.setup_agent(stream([fake],extra=extra))
        with self.assertRaisesRegex(BudgetStopped,'UNOBSERVED_URL'):a.discover(t)
        self.assertTrue((a.output_dir/'result.json').exists())
    def test_zero_and_multiple_search_rejected(self):
        for count in (0,2):
            a,b,e,t=self.setup_agent(stream(searches=count))
            with self.assertRaisesRegex(BudgetStopped,'WEBSEARCH_COUNT'):a.discover(t)
    def test_error_search_rejected(self):
        a,b,e,t=self.setup_agent(stream(error=True))
        with self.assertRaises(BudgetStopped):a.discover(t)
    def test_nonzero_process_rejected(self):
        a,b,e,t=self.setup_agent(code=1)
        with self.assertRaisesRegex(BudgetStopped,'NONZERO'):a.discover(t)
    def test_malformed_json_rejected(self):
        a,b,e,t=self.setup_agent(b'not json')
        with self.assertRaisesRegex(BudgetStopped,'MALFORMED'):a.discover(t)
    def test_wrong_company_never_dispatches(self):
        a,b,e,t=self.setup_agent()
        with self.assertRaises(ValueError):a.discover(ResearchRequest('s','q','other'))
        self.assertFalse(e.calls);self.assertEqual(b.used['model'],0)
    def test_first_stop_preserved(self):
        a,b,e,t=self.setup_agent();b.stop('FIRST_CAUSE')
        with self.assertRaisesRegex(BudgetStopped,'FIRST_CAUSE'):a.discover(t)
        self.assertEqual(b.stop_reason,'FIRST_CAUSE');self.assertFalse(e.calls)
    def test_instance_not_replayed(self):
        a,b,e,t=self.setup_agent();a.discover(t)
        with self.assertRaisesRegex(BudgetStopped,'ALREADY_USED'):a.discover(t)
        self.assertEqual(len(e.calls),1)
    def test_zero_search_budget_no_process(self):
        a,b,e,t=self.setup_agent(max_search_calls=0)
        with self.assertRaises(BudgetStopped):a.discover(t)
        self.assertFalse(e.calls)
    def test_approval_required(self):
        req=request()
        with self.assertRaises(PermissionError):ManagedWebDiscoveryAgent(req,CallBudget(req),executable_path='claude',output_dir='unused')
    def test_invalid_url_rejected(self):
        for bad in ('https://user:secret@example.org','https://[bad','https://example.org/white space'):
            a,b,e,t=self.setup_agent(stream([bad]))
            with self.assertRaises(BudgetStopped):a.discover(t)
    def test_block_content_supported(self):
        events=[json.loads(s) for s in stream().decode().splitlines()]
        block=events[1]['message']['content'][0];block['content']=[{'type':'text','text':block['content']}]
        a,b,e,t=self.setup_agent('\n'.join(map(json.dumps,events)).encode());self.assertEqual(a.discover(t).source_urls,(URL,))
    def test_unexpected_tool_rejected(self):
        extra=[{'type':'assistant','message':{'content':[{'type':'tool_use','id':'bad','name':'Read'}]}}]
        a,b,e,t=self.setup_agent(stream(extra=extra))
        with self.assertRaisesRegex(BudgetStopped,'UNEXPECTED_TOOL'):a.discover(t)
    def test_duplicate_result_id_stops(self):
        events=[json.loads(line) for line in stream().decode().splitlines()]
        events.insert(2,events[1])
        a,b,e,t=self.setup_agent('\n'.join(map(json.dumps,events)).encode())
        with self.assertRaisesRegex(BudgetStopped,'DUPLICATE'):a.discover(t)
    def test_executor_exception_terminal_and_not_retried(self):
        a,b,e,t=self.setup_agent()
        def failed(*args):
            e.calls.append(args)
            raise TimeoutError('private provider detail')
        e.run=failed
        with self.assertRaisesRegex(BudgetStopped,'PROCESS_FAILED'):a.discover(t)
        self.assertEqual(len(e.calls),1)
        receipt=(a.output_dir/'result.json').read_text()
        self.assertNotIn('private provider detail',receipt)
        self.assertEqual(b.stop_reason,'WEB_DISCOVERY_PROCESS_FAILED')
    def test_missing_links_not_replaced_by_summary_urls(self):
        events=[json.loads(line) for line in stream().decode().splitlines()]
        events[1]['message']['content'][0]['content']='Summary contains '+URL
        a,b,e,t=self.setup_agent('\n'.join(map(json.dumps,events)).encode())
        with self.assertRaisesRegex(BudgetStopped,'LINKS_PARSE_FAILED'):a.discover(t)
    def test_receipt_budget_not_active_after_success(self):
        a,b,e,t=self.setup_agent();r=a.discover(t)
        self.assertEqual(r.budget_snapshot['active'],0)
        self.assertEqual(json.loads((a.output_dir/'result.json').read_text())['budget_snapshot']['active'],0)
    def test_primary_rate_limit_rejection_stops_quota_even_with_zero_returncode(self):
        events=[json.loads(line) for line in stream().decode().splitlines()]
        events.insert(0,{'type':'rate_limit_event','rate_limit_info':{'status':'rejected'}})
        a,b,e,t=self.setup_agent('\n'.join(map(json.dumps,events)).encode(),code=0)
        with self.assertRaisesRegex(BudgetStopped,'CLI_QUOTA_EXHAUSTED'):a.discover(t)
        self.assertEqual(b.stop_reason,'CLI_QUOTA_EXHAUSTED')
        self.assertEqual(json.loads((a.output_dir/'result.json').read_text())['status'],'QUOTA_EXHAUSTED')

    def test_primary_rate_limit_rejection_detected_with_nonzero_returncode(self):
        events=[{'type':'rate_limit_event','rate_limit_info':{'status':'rejected'}}]
        a,b,e,t=self.setup_agent('\n'.join(map(json.dumps,events)).encode(),code=1)
        with self.assertRaisesRegex(BudgetStopped,'CLI_QUOTA_EXHAUSTED'):a.discover(t)

    def test_final_result_errors_list_quota_signal_stops_even_without_websearch(self):
        events=[{'type':'result','is_error':True,'errors':['hit-your-limit for this account']}]
        a,b,e,t=self.setup_agent('\n'.join(map(json.dumps,events)).encode(),code=0)
        with self.assertRaisesRegex(BudgetStopped,'CLI_QUOTA_EXHAUSTED'):a.discover(t)

    def test_allowed_with_secondary_overage_rejected_still_succeeds(self):
        events=[json.loads(line) for line in stream().decode().splitlines()]
        events.insert(0,{'type':'rate_limit_event','rate_limit_info':{'status':'allowed'},
            'secondary_rate_limit_info':{'status':'rejected'}})
        a,b,e,t=self.setup_agent('\n'.join(map(json.dumps,events)).encode())
        self.assertEqual(a.discover(t).source_urls,(URL,))

    def test_allowed_warning_still_succeeds(self):
        events=[json.loads(line) for line in stream().decode().splitlines()]
        events.insert(0,{'type':'rate_limit_event','rate_limit_info':{'status':'allowed_warning'}})
        a,b,e,t=self.setup_agent('\n'.join(map(json.dumps,events)).encode())
        self.assertEqual(a.discover(t).source_urls,(URL,))

    def test_successful_result_mentioning_quota_in_narrative_does_not_stop(self):
        events=[json.loads(line) for line in stream().decode().splitlines()]
        events[-1]['structured_output']['status']='quota looks fine this quarter'
        a,b,e,t=self.setup_agent('\n'.join(map(json.dumps,events)).encode())
        self.assertEqual(a.discover(t).status,'HELD_FOR_VERIFICATION')

    def test_generic_error_without_quota_signal_is_not_classified_as_quota(self):
        events=[{'type':'result','is_error':True,'errors':['max-turns exceeded']}]
        a,b,e,t=self.setup_agent('\n'.join(map(json.dumps,events)).encode(),code=1)
        with self.assertRaisesRegex(BudgetStopped,'NONZERO_RETURNCODE'):a.discover(t)

    def test_quota_first_cause_never_overwritten_by_later_allowed_event(self):
        events=[{'type':'rate_limit_event','rate_limit_info':{'status':'rejected'}},
            {'type':'rate_limit_event','rate_limit_info':{'status':'allowed'}}]
        a,b,e,t=self.setup_agent('\n'.join(map(json.dumps,events)).encode())
        with self.assertRaisesRegex(BudgetStopped,'CLI_QUOTA_EXHAUSTED'):a.discover(t)
        self.assertEqual(b.stop_reason,'CLI_QUOTA_EXHAUSTED')
        self.assertTrue((a.output_dir/'raw_stream.jsonl').exists())

    def test_actual_allowed_shape_with_missing_utilization_not_false_quota(self):
        event={'type':'rate_limit_event','rate_limit_info':{'status':'allowed','overageStatus':'rejected'}}
        a,b,e,t=self.setup_agent(json.dumps(event).encode()+b'\n'+stream())
        self.assertEqual(a.discover(t).source_urls,(URL,))
        self.assertFalse(b.stopped)
    def test_primary_rejection_before_truncated_tail_preserves_quota_cause(self):
        first={'type':'rate_limit_event','rate_limit_info':{'status':'rejected'}}
        a,b,e,t=self.setup_agent(json.dumps(first).encode()+b'\n{truncated')
        with self.assertRaisesRegex(BudgetStopped,'CLI_QUOTA_EXHAUSTED'):a.discover(t)
        self.assertEqual(len(e.calls),1)
        self.assertTrue((a.output_dir/'raw_stream.jsonl').exists())

    def test_executor_stop_first_cause_survives_later_exception(self):
        a,b,e,t=self.setup_agent()
        def failed(*args):
            b.stop('EXTERNAL_STOP')
            raise TimeoutError('private diagnostic')
        e.run=failed
        with self.assertRaisesRegex(BudgetStopped,'EXTERNAL_STOP'):a.discover(t)
        receipt=json.loads((a.output_dir/'result.json').read_text())
        self.assertEqual(receipt['stop_reason'],'EXTERNAL_STOP')
        self.assertEqual(receipt['budget_snapshot']['active'],0)
    def test_timeout_before_deadline_classified_as_process_timeout(self):
        a,b,e,t=self.setup_agent()
        def failed(*args):
            e.calls.append(args)
            raise subprocess.TimeoutExpired(cmd=['claude'],timeout=2.51834,output=b'')
        e.run=failed
        with self.assertRaisesRegex(BudgetStopped,'PROCESS_TIMEOUT'):a.discover(t)
        self.assertEqual(b.stop_reason,'WEB_DISCOVERY_PROCESS_TIMEOUT')

    def test_timeout_after_injected_deadline_classified_as_stop_or_deadline(self):
        a,b,e,t=self.setup_agent()
        state={'expired':False}
        real_clock=b.clock
        b.clock=lambda:a.request.deadline if state['expired'] else real_clock()
        def failed(*args):
            e.calls.append(args)
            state['expired']=True
            raise subprocess.TimeoutExpired(cmd=['claude'],timeout=2.51834,output=b'')
        e.run=failed
        with self.assertRaisesRegex(BudgetStopped,'STOP_OR_DEADLINE'):a.discover(t)
        self.assertEqual(b.stop_reason,'STOP_OR_DEADLINE')

    def test_timeout_preserves_preexisting_first_stop(self):
        a,b,e,t=self.setup_agent()
        def failed(*args):
            b.stop('EARLIER_CAUSE')
            raise subprocess.TimeoutExpired(cmd=['claude'],timeout=2.5,output=b'')
        e.run=failed
        with self.assertRaisesRegex(BudgetStopped,'EARLIER_CAUSE'):a.discover(t)
        self.assertEqual(b.stop_reason,'EARLIER_CAUSE')

    def test_timeout_output_partial_rejection_then_malformed_tail_classified_quota(self):
        a,b,e,t=self.setup_agent()
        first={'type':'rate_limit_event','rate_limit_info':{'status':'rejected'}}
        output=json.dumps(first).encode()+b'\n{truncated'
        def failed(*args):
            e.calls.append(args)
            raise subprocess.TimeoutExpired(cmd=['claude'],timeout=2.5,output=output)
        e.run=failed
        with self.assertRaisesRegex(BudgetStopped,'CLI_QUOTA_EXHAUSTED'):a.discover(t)
        self.assertEqual(b.stop_reason,'CLI_QUOTA_EXHAUSTED')

    def test_timeout_output_allowed_primary_overage_and_nested_quota_text_not_quota(self):
        a,b,e,t=self.setup_agent()
        frame1={'type':'rate_limit_event','rate_limit_info':{'status':'allowed'},
            'secondary_rate_limit_info':{'status':'rejected'}}
        frame2={'type':'user','message':{'content':[{'type':'tool_result','tool_use_id':'x','is_error':False,
            'content':'nested tool text mentions quota exceeded deep inside'}]}}
        output=('\n'.join(json.dumps(f) for f in (frame1,frame2))).encode()
        def failed(*args):
            e.calls.append(args)
            raise subprocess.TimeoutExpired(cmd=['claude'],timeout=2.5,output=output)
        e.run=failed
        with self.assertRaisesRegex(BudgetStopped,'PROCESS_TIMEOUT'):a.discover(t)
        self.assertEqual(b.stop_reason,'WEB_DISCOVERY_PROCESS_TIMEOUT')

    def test_timeout_quota_frame_survives_invalid_utf8_tail(self):
        frame={'type':'rate_limit_event','rate_limit_info':{'status':'rejected'}}
        raw=json.dumps(frame).encode()+b'\n\xff'
        self.assertEqual(ManagedWebDiscoveryAgent._quota_signal_from_timeout_output(raw),'CLI_QUOTA_EXHAUSTED')
        self.assertIsNone(ManagedWebDiscoveryAgent._quota_signal_from_timeout_output(b'\xff\n'+json.dumps(frame).encode()))

    def test_timeout_partial_explicit_quota_error_does_not_override_existing_stop(self):
        a,b,e,t=self.setup_agent()
        raw=json.dumps({'type':'result','is_error':True,'errors':['hit your limit']}).encode()
        self.assertEqual(ManagedWebDiscoveryAgent._quota_signal_from_timeout_output(raw),'CLI_QUOTA_EXHAUSTED')
        def failed(*args):
            b.stop('FIRST_CAUSE')
            raise subprocess.TimeoutExpired('fixture',2,output=raw)
        e.run=failed
        with self.assertRaisesRegex(BudgetStopped,'FIRST_CAUSE'):a.discover(t)
        self.assertEqual(b.stop_reason,'FIRST_CAUSE')
        self.assertEqual(json.loads((a.output_dir/'result.json').read_text())['stop_reason'],'FIRST_CAUSE')

    def test_timeout_after_deadline_persists_zero_active_and_no_provider_detail(self):
        a,b,e,t=self.setup_agent()
        def failed(*args):
            e.calls.append(args);b.clock=lambda:a.request.deadline
            raise subprocess.TimeoutExpired('PRIVATE_EXECUTABLE_DETAIL',2,output=b'partial provider message')
        e.run=failed
        with self.assertRaisesRegex(BudgetStopped,'STOP_OR_DEADLINE'):a.discover(t)
        raw=(a.output_dir/'result.json').read_text();receipt=json.loads(raw)
        self.assertNotIn('PRIVATE_EXECUTABLE_DETAIL',raw)
        self.assertNotIn('partial provider message',raw)
        self.assertEqual(receipt['budget_snapshot']['active'],0)
        self.assertEqual(b.used,{'model':1,'search':1})
        self.assertEqual(len(e.calls),1)

if __name__=='__main__':unittest.main()
