"""Score frozen, independently adjudicated claim IDs; no model, network or Y join.

This is structural citation scoring, not entailment verification. A human or
separate blinded adjudication process must supply exact gold claim/source pairs.
Never pass the gold file to a model or derive it from that model's output.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def rate(numerator, denominator):
    return {'numerator': numerator, 'denominator': denominator,
            'rate': numerator/denominator if denominator else None}


def keyed(items, key):
    if not isinstance(items, list) or not all(isinstance(x, dict) for x in items):
        raise ValueError('Expected list of records')
    ids = [x.get(key) for x in items]
    if not all(isinstance(x, str) and x.strip() for x in ids) or len(ids) != len(set(ids)):
        raise ValueError('Missing or duplicate IDs')
    return dict(zip(ids, items))


def score(gold, submission):
    if gold.get('version') != 'claim-scorecard-v1' or submission.get('version') != 'claim-scorecard-v1':
        raise ValueError('Unsupported scorecard version')
    cases = keyed(gold.get('cases'), 'case_id')
    answers = keyed(submission.get('cases'), 'case_id')
    if not cases or set(answers) != set(cases):
        raise ValueError('Require identical nonempty frozen case IDs; no dropping failures')
    counts = Counter(); rows = []
    for cid, case in cases.items():
        facts = keyed(case.get('facts'), 'claim_id')
        for fact in facts.values():
            if type(fact.get('admissible')) is not bool or not isinstance(fact.get('source_id'), str) or not fact['source_id'].strip():
                raise ValueError('Gold requires reviewed admissibility and source ID')
        answer = answers[cid]
        if answer.get('status') not in ('COMPLETED', 'ABSTAINED', 'FAILED'):
            raise ValueError('Explicit completion/abstention/failure required')
        claims = keyed(answer.get('claims'), 'claim_id')
        if answer['status'] != 'COMPLETED' and claims:
            raise ValueError('Abstained/failed cases cannot submit factual claims')
        if any(not isinstance(x.get('source_id'), str) for x in claims.values()):
            raise ValueError('Claims require explicit citation IDs, possibly empty')
        supported = {fid for fid, claim in claims.items() if fid in facts and
                     facts[fid]['admissible'] and claim['source_id'] == facts[fid]['source_id']}
        expected = sum(x['admissible'] for x in facts.values())
        row = dict(case_id=cid, status=answer['status'], expected_admissible_claims=expected,
                   submitted_claims=len(claims), structurally_supported_claims=len(supported),
                   unsupported_or_wrong_citation_claims=len(claims)-len(supported),
                   missed_admissible_claims=expected-len(supported))
        rows.append(row)
        counts.update(submitted=len(claims), supported=len(supported), expected=expected,
                      completed=answer['status']=='COMPLETED', abstained=answer['status']=='ABSTAINED',
                      failed=answer['status']=='FAILED', appropriate_abstention=(not expected and answer['status']=='ABSTAINED'),
                      no_evidence_cases=not expected, evidence_cases=expected>0, excess_abstention=(expected>0 and answer['status']=='ABSTAINED'))
    return {'version': 'claim-scorecard-v1', 'mode': 'OFFLINE_STRUCTURAL_SCORING_ONLY',
            'cases': rows, 'case_count': len(cases),
            'metrics': {'structural_citation_precision': rate(counts['supported'], counts['submitted']),
                        'admissible_claim_recall': rate(counts['supported'], counts['expected']),
                        'unsupported_or_wrong_citation_rate': rate(counts['submitted']-counts['supported'],counts['submitted']),
                        'completion_rate': rate(counts['completed'],len(cases)),
                        'abstention_rate': rate(counts['abstained'],len(cases)),
                        'failure_rate': rate(counts['failed'],len(cases)),
                        'appropriate_abstention_rate': rate(counts['appropriate_abstention'],counts['no_evidence_cases']),
                        'excess_abstention_rate': rate(counts['excess_abstention'],counts['evidence_cases'])},
            'limitations': ['Gold must be independently adjudicated and frozen before predictions.',
                           'Exact claim/source IDs do not verify free-text entailment or source truth.',
                           'Appropriate abstention credits ABSTAINED only; COMPLETED with zero claims is not an abstention.',
                           'This is not investment accuracy, a trained model, or a financing negative label.',
                           'No model comparison or statistical generalization follows from scoring synthetic test fixtures.']}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--gold',type=Path,required=True)
    p.add_argument('--submission',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    output=a.output.resolve()
    if output in (a.gold.resolve(),a.submission.resolve()) or output.exists():
        p.error('Output must be new and cannot overwrite inputs')
    raw_gold=a.gold.read_bytes();raw_submission=a.submission.read_bytes()
    result=score(json.loads(raw_gold),json.loads(raw_submission))
    result['input_sha256']={'gold':hashlib.sha256(raw_gold).hexdigest(),
                            'submission':hashlib.sha256(raw_submission).hexdigest()}
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x',encoding='utf-8') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps({'mode':result['mode'],'case_count':result['case_count'],'output':str(output)}))


if __name__=='__main__':main()
