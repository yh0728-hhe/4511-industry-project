"""Export sealed development outputs for independent passage-support review.

No model calls, browsing, scoring, gold creation or label reads. Raw publisher
text and model prose remain in caller-selected ignored/private output folders.
"""
import argparse
import hashlib
import json
from pathlib import Path
import random


def sha(raw):return hashlib.sha256(raw).hexdigest()


def load(path,limit=524288):
    with Path(path).open('rb') as stream:raw=stream.read(limit+1)
    if len(raw)>limit:raise ValueError('REVIEW_INPUT_TOO_LARGE')
    return json.loads(raw.decode('utf-8')),raw


def context_from_wire(raw):
    text=raw.decode('utf-8')
    pos=text.find('\n{')
    if pos<0:raise ValueError('WIRE_CONTEXT_MISSING')
    value,_=json.JSONDecoder().raw_decode(text[pos+1:])
    if not isinstance(value,dict) or not isinstance(value.get('evidence'),list) or not value['evidence']:
        raise ValueError('NONEMPTY_CONTEXT_REQUIRED')
    return value


def prepare(pair_root,receipt_path,output_dir,*,mask_seed):
    if type(mask_seed) is not int or not 0<=mask_seed<2**32:
        raise ValueError('EXPLICIT_UINT32_MASK_SEED_REQUIRED')
    pair_root=Path(pair_root);root=Path(output_dir)
    receipt,_=load(receipt_path)
    expected=receipt.get('raw_sha256',{})
    names=('plan.json','result.json','arms.json','committee_draft_trace.json','single_analyst_raw.json')
    values={};hashes={}
    for name in names:
        value,raw=load(pair_root/name)
        hashes[name]=sha(raw)
        if expected.get(name)!=hashes[name]:raise ValueError('SEALED_INPUT_HASH_MISMATCH:'+name)
        values[name]=value
    arms=values['arms.json'];plan=values['plan.json']
    if len(arms)!=2 or {a['arm'] for a in arms}!={'single_analyst','committee'}:
        raise ValueError('TWO_COMPLETE_ARMS_REQUIRED')
    if any(a.get('status')!='EXECUTED_REVIEW_PENDING' for a in arms):
        raise ValueError('INCOMPLETE_PAIR_NOT_A_REVIEW_SAMPLE')
    if any(a.get('evidence_sha256')!=plan.get('evidence_sha256') for a in arms):
        raise ValueError('ARM_EVIDENCE_HASH_MISMATCH')
    journal=(pair_root/'dispatch.jsonl').read_text(encoding='utf-8')
    if len(journal)>524288:raise ValueError('JOURNAL_TOO_LARGE')
    events=[json.loads(line) for line in journal.splitlines() if line.strip()]
    first=next((e for e in events if e.get('status')=='DISPATCHING'),None)
    last=next((e for e in reversed(events) if e.get('status')=='DISPATCHING'),None)
    contexts=[];wire_hashes={}
    for entry in (first,last):
        if not isinstance(entry,dict) or type(entry.get('process_count')) is not int or entry['process_count']<1:
            raise ValueError('DISPATCH_PROOF_MISSING')
        name=f"call_{entry['process_count']:03d}.stdin"
        path=pair_root/'backend_wire'/name
        with path.open('rb') as stream:raw=stream.read(524289)
        if len(raw)>524288 or sha(raw)!=entry.get('prompt_hash'):
            raise ValueError('WIRE_HASH_MISMATCH')
        contexts.append(context_from_wire(raw));wire_hashes[name]=sha(raw)
    if contexts[0]!=contexts[1]:raise ValueError('MODEL_VISIBLE_CONTEXTS_DIFFER')
    context=contexts[0]
    if context.get('as_of')!=plan.get('as_of') or context.get('mandate')!=plan.get('mandate'):
        raise ValueError('CONTEXT_CUTOFF_OR_MANDATE_MISMATCH')
    final=[row for row in values['committee_draft_trace.json'] if row.get('stage')=='final_aggregation']
    if len(final)!=1:raise ValueError('EXACTLY_ONE_FINAL_AGGREGATION_REQUIRED')
    units=[]
    for row in final[0]['arguments']:
        units.append(dict(text=row['text'],citations=row['cited_fact_ids'],
            origin='committee_final_'+row['role']))
    for arm in arms:
        units.append(dict(text=arm['proposal']['rationale'],
            citations=arm['proposal']['admitted_fact_ids'],origin=arm['arm']+'_rationale'))
    if len(units)!=4 or any(not isinstance(u['text'],str) or not u['text'].strip() for u in units):
        raise ValueError('FOUR_NONEMPTY_REVIEW_UNITS_REQUIRED')
    fact_ids={row['fact_id'] for row in context['evidence']}
    if any(not set(u['citations'])<=fact_ids for u in units):raise ValueError('UNAVAILABLE_CITATION')
    random.Random(mask_seed).shuffle(units)
    root.mkdir(parents=True,exist_ok=False)
    reviewer=root/'reviewer';reviewer.mkdir()
    operator=root/'operator';operator.mkdir()
    def save(path,value):path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    save(reviewer/'source_context.json',context)
    references=dict(status='UNREVIEWED_NO_REFERENCE_LABELS',reviewer_name='',
        reviewed_at='',reviewer_independent_of_generation=None,
        source_only_reference_claims=[],limitations=[])
    save(reviewer/'reference_first.json',references)
    mapping={};records=[]
    for index,unit in enumerate(units,1):
        uid=f'passage_{index:02d}'
        mapping[uid]=dict(origin=unit['origin'],text_sha256=sha(unit['text'].encode()))
        records.append(dict(unit_id=uid,text=unit['text'],cited_fact_ids=unit['citations'],
            verdict=None,supported_passages=[],unsupported_spans=[],
            inference_or_normative_spans=[],reviewer_notes=''))
    save(reviewer/'outputs_second.json',dict(status='UNREVIEWED',reviewer_name='',units=records))
    save(operator/'arm_mapping.json',mapping)
    (reviewer/'README.md').write_text("""# Independent company passage review

This packet is a previously inspected development case, not a holdout or an
investment-success test. No reference labels have been filled by an agent.

1. Read source_context.json first. Treat publisher claims as attributed claims,
   not independently demonstrated performance or customer adoption. The supplied
   text is the model-visible admitted context, not newly recovered source text.
   Do not browse or use future knowledge for this passage-support task.
2. Before opening outputs_second.json, complete reference_first.json with the
   factual claims the supplied source supports, exact supporting quotes, and
   limits. Record your name, date and independence from output generation.
3. Then review all four passages in outputs_second.json. Allowed verdicts are
   SUPPORTED, PARTLY_SUPPORTED, UNSUPPORTED, or NOT_FACTUAL. Quote supporting
   passages, identify unsupported text, and separate hypotheses or investment
   judgments from factual assertions. Missing evidence is not a negative fact.
4. A second reviewer should work on a fresh copy independently. Preserve both
   original reviews, disagreements and adjudication. Do not silently rewrite a
   review into consensus or tune prompts using this scored development case.

Arm labels are removed from this folder, but writing style may reveal the
method. Four passages are not four independent companies; the two committee
arguments are correlated. Passage lengths differ, so do not count whole-passage
verdicts as comparable per-arm accuracy. The original arms had unequal compute.
No scorer is run by this exporter and no recommendation is certified.

The operator folder is for the coordinator only and contains the arm mapping.
Keep source text/model prose private; share only selected reviewed summaries.
""",encoding='utf-8')
    files={str(p.relative_to(root)).replace('\\','/'):sha(p.read_bytes()) for p in root.rglob('*') if p.is_file()}
    manifest=dict(status='PREPARED_NOT_REVIEWED',case_count=1,passage_count=len(units),
        source_record_count=len(context['evidence']),source_input_sha256=hashes,
        wire_sha256=wire_hashes,files_sha256=files,reference_labels_created=False,
        source_http_requests=0,model_cli_attempts=0,independent_review_completed=False,
        quality_score=None,investment_accuracy=None,Y_changed=False)
    save(root/'manifest.json',manifest)
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pair-root',required=True);parser.add_argument('--receipt',required=True)
    parser.add_argument('--output-dir',required=True);parser.add_argument('--mask-seed',type=int,required=True)
    args=parser.parse_args()
    print(json.dumps(prepare(args.pair_root,args.receipt,args.output_dir,mask_seed=args.mask_seed),indent=2))


if __name__=='__main__':main()
