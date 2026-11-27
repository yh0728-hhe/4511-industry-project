"""Deterministic offline presentation bundle; never launch a model."""
import argparse
import hashlib
import html
import json
from pathlib import Path
import tempfile
from closed_loop.fixtures import run_case
from closed_loop.offline_network import OfflineSocketGuard
from .readiness import ROOT, training_assessment
from .scorecard import score

VERSION = 'presentation-demo-v1'
# Root-reviewed receipt committed at eb4884cd7084bd7bba41b2eebb636a39859026dc.
PINNED_HANDOFF_SHA256 = 'c9ff9136cf01cf622a8620c49994ac2c132a00013128a14a2030ab90ddba5095'
INPUTS = ('data/metadata/workflow_20261121/controller_rehearsal.json',
          'data/metadata/workflow_20261121/historical_gate_codex_review.json',
          'data/metadata/workflow_20261121/scorecard_validation.json',
          'results/candidates/funding_y_source_grace_v1/company_labels.csv',
          'results/candidates/outcome_coverage_v1/company_outcome_coverage.csv')


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)+'\n').encode('utf-8')


def scoring_example():
    """Injected arithmetic errors, NOT model predictions or an observed baseline."""
    gold = {'version':'claim-scorecard-v1','cases':[
        {'case_id':'SYNTHETIC_READABLE','facts':[
            {'claim_id':'old_claim','source_id':'old_source','admissible':True},
            {'claim_id':'future_claim','source_id':'new_source','admissible':False}]},
        {'case_id':'SYNTHETIC_NO_EVIDENCE','facts':[]}]}
    submitted = {'version':'claim-scorecard-v1','cases':[
        {'case_id':'SYNTHETIC_READABLE','status':'COMPLETED','claims':[
            {'claim_id':'old_claim','source_id':'old_source'},
            {'claim_id':'future_claim','source_id':'new_source'}]},
        {'case_id':'SYNTHETIC_NO_EVIDENCE','status':'ABSTAINED','claims':[]}]}
    return {'classification':'SYNTHETIC_INJECTED_ERROR_NOT_MODEL_OUTPUT',
            'gold':gold,'submission':submitted,'report':score(gold,submitted)}


def collect(root):
    raw = {name:(root/name).read_bytes() for name in INPUTS}
    receipt=json.loads(raw[INPUTS[0]]);gate=json.loads(raw[INPUTS[1]])
    prior_tests=json.loads(raw[INPUTS[2]])
    if hashlib.sha256(encoded(receipt)).hexdigest()!=PINNED_HANDOFF_SHA256:
        raise ValueError('Historical handoff differs from the pinned reviewed receipt')
    if (receipt.get('status')!='DONE' or receipt.get('invocations')!=2 or
        receipt.get('review_verdict')!='ACCEPT' or receipt.get('resume_verified_no_additional_invocation') is not True):
        raise ValueError('Historical handoff receipt is not validated')
    if gate.get('gate')!='HOLD_NO_VERIFIED_PRECUTOFF_BODY':
        raise ValueError('Historical gate changed: review framing before regeneration')
    cases={'synthetic_sufficient':run_case(),'synthetic_poor':run_case(good=False),
           'synthetic_missing':run_case(empty=True),'synthetic_cap':run_case(max_search_calls=2)}
    if [c['decision'] for c in cases.values()]!=['INVEST','PASS','MORE_DILIGENCE','MORE_DILIGENCE']:
        raise ValueError('Fixture behavior changed; no silently updated demo')
    if any(c['actual_model_calls'] or c['actual_network_calls'] for c in cases.values()):
        raise ValueError('Demo must remain offline')
    summary={'version':VERSION,'mode':'OFFLINE_REPLAY_AND_SYNTHETIC_DEMO',
        'coverage':training_assessment(root),
        'prior_real_cli_handoff':{'classification':'SAVED_HISTORICAL_RECEIPT_NOT_RERUN_NOW',
            'receipt_commit':'eb4884cd7084bd7bba41b2eebb636a39859026dc',
            'canonical_receipt_sha256':PINNED_HANDOFF_SHA256,
            'verification_scope':'Replay of root-reviewed committed receipt, not an independent audit of live execution',
            'run_id':receipt['run_id'],'status':receipt['status'],'invocations':receipt['invocations'],
            'review_verdict':receipt['review_verdict'],'resume_no_duplicate':True},
        'historical_gate':gate['gate'],
        'prior_test_receipt':{'classification':'SAVED_COUNTS_NOT_CURRENT_TEST_EXECUTION','validation':prior_tests['validation']},
        'generated_now':{'actual_model_calls':0,'network_calls':0,'training':False},
        'not_demonstrated':['Model-quality improvement','Investment prediction accuracy','Historical baseline completion',
                            'Quota-reset automatic recovery','Unattended travel scheduler']}
    artifacts={'summary.json':encoded(summary),'synthetic_traces.json':encoded(cases),
               'synthetic_scoring_example.json':encoded(scoring_example()),
               'index.html':render(summary,cases).encode('utf-8')}
    hashes={n:hashlib.sha256(b).hexdigest() for n,b in raw.items()}
    hashes.update({p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest()
                   for p in sorted((root/'src').rglob('*.py'))})
    artifacts['manifest.json']=encoded({'version':VERSION,'input_sha256':hashes,
        'artifact_sha256':{n:hashlib.sha256(b).hexdigest() for n,b in artifacts.items()},
        'reproduction':'PYTHONPATH=src python -m workflow_automation.presentation_demo --output NEW_DIRECTORY',
        'data_roles':'Y used for coverage display only, never model inputs; no models in builder.',
        'hash_policy':'Data hashes are exact checkout bytes; source hashes canonicalize LF. Byte-identical regeneration is tested for identical checkout inputs, not arbitrary newline conversions.'})
    return artifacts


def render(summary,cases):
    esc=html.escape;c=summary['coverage']
    rows=''.join('<tr><td>'+esc(k)+'</td><td>'+esc(v['decision'])+'</td><td>'+esc(v['stop_reason'])+
                 '</td><td>'+str(v['fact_revision'])+'</td></tr>' for k,v in cases.items())
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Guarded AI Research Workflow: Reproducible Demo</title><style>
body{font:17px/1.6 system-ui,sans-serif;background:#f5f7fb;color:#18273c;margin:0}main{max-width:1000px;margin:auto;padding:40px 24px}
h1{line-height:1.2}section{background:white;border:1px solid #dae1ec;border-radius:14px;padding:22px;margin:22px 0;overflow-x:auto}
.tag{font-size:14px;color:#654800;background:#fff1c6;padding:8px 12px;display:inline-block;border-radius:8px}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:10px;text-align:left;border-bottom:1px solid #e1e6ee}
a{color:#164f9d}code{background:#edf1f7;padding:2px 5px}p{max-width:85ch}</style><main>
<p class="tag">OFFLINE DEMO: synthetic traces + saved real-run evidence. No model launched now.</p>
<h1>Evidence → bounded research → review → reproducible receipt</h1>
<p>A research-engineering prototype for a 240-company YC cohort. Coverage measures ascertainment; it is not investment success or model accuracy.</p>
<section><h2>1. Current audited dataset</h2><p>Composite coverage: <b>'''+str(c['composite_observed'])+''' / 240</b>; financing observed: <b>'''+str(c['financing_observed'])+''' / 240</b>.
Missing observations remain UNKNOWN; verified financing negatives: '''+str(c['verified_financing_negatives'])+'''. This is not a two-class training dataset.</p></section>
<section><h2>2. Runtime demonstration: synthetic only</h2><p>These invented cases execute the actual deterministic runtime. INVEST and PASS below are fixture decisions, not real recommendations or model predictions.</p>
<table><tr><th>Invented case</th><th>Fixture decision</th><th>Stop reason</th><th>Evidence revision</th></tr>'''+rows+'''</table>
<p><a href="synthetic_traces.json">Inspect generated trace</a>. Zero actual model/network calls; logical reservations are not billing.</p></section>
<section><h2>3. A real handoff was previously verified</h2><p>Saved receipt: Codex drafted a rubric, Claude accepted it; 2 CLI invocations. Completed-run resume dispatched neither again. This builder does not rerun those models.</p>
<p><a href="summary.json">View source-linked summary</a>. No quota-reset recovery or unattended scheduler has been verified.</p></section>
<section><h2>4. Evaluate claims without hiding failures</h2><p>The scorecard preserves failed-case denominators, separates UNKNOWN and checks exact independently adjudicated claim/source pairs. Its hand-authored error-injection example contains one deliberately inadmissible claim. Its numbers verify arithmetic, not model performance.</p>
<p><a href="synthetic_scoring_example.json">Inspect synthetic scoring example</a></p></section>
<section><h2>5. Honest boundary</h2><p>Historical evidence gate: <code>'''+esc(summary['historical_gate'])+'''</code>. Model-quality comparison and historical investment evaluation have not run. Current edited pages cannot silently inherit an old creation date.</p>
<p>No training, investment-accuracy or production-readiness claim is supported by this demo.</p></section>
<p><a href="manifest.json">Input and artifact hashes</a>. Standalone files: no CDN, JavaScript, API key or external asset required.</p></main></html>'''


def build(output,root=ROOT):
    output=Path(output).resolve()
    if output.exists():raise ValueError('Output exists; preserve prior run and choose a new directory')
    protected=[root/n for n in ('src','data','docs','tests','coordination','sources','.git','.codex')]
    if output==root.resolve() or any(output.is_relative_to(p.resolve()) for p in protected):
        raise ValueError('Cannot replace source directories')
    with OfflineSocketGuard():artifacts=collect(root)
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.demo-',dir=output.parent) as temp:
        bundle=Path(temp)/'bundle';bundle.mkdir()
        for name,data in artifacts.items():(bundle/name).write_bytes(data)
        if output.exists():raise ValueError('Output appeared during build')
        bundle.rename(output)
    return output/'index.html'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    try:print(str(build(a.output)))
    except (ValueError,OSError) as e:p.error(str(e))


if __name__=='__main__':main()
