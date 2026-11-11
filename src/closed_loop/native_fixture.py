"""Deterministic model responses for testing actual adapted upstream nodes."""
import json

from .native_support import (ArgumentsOutput,ArgumentOutput,ArgumentCritique,SingleArgumentScore,
    CriterionScore,IndividualRefinedArgumentOutput,EvidenceReviewOutput)
from .model_lead import LeadPlanOutput,PlannedResearch


class NativeFixtureBackend:
    def __init__(self,argument_count=1):
        self.argument_count=argument_count;self.generation_count=0;self.calls=[]

    def generate(self,schema,messages,temperature):
        context=json.loads(messages[0].content.split('\n',1)[1])
        self.calls.append(dict(schema=schema.__name__,temperature=temperature,
            company_id=context['company_id'],fact_revision=context['fact_revision'],
            fact_ids=[row['fact_id'] for row in context['evidence']]))
        target=[row for row in context['evidence'] if row['subject_id']==context['company_id']]
        good=any(row['answer']=='SYNTHETIC_RETENTION_GOOD' for row in target)
        poor=any(row['answer']=='SYNTHETIC_RETENTION_POOR' for row in target)
        indices=list(range(len(context['evidence'])))
        if schema is LeadPlanOutput:
            plan=json.loads(messages[-1].content)
            gaps=plan['essential_gaps']
            return LeadPlanOutput([PlannedResearch('traction',gap,None) for gap in gaps] if gaps else
                [PlannedResearch('market','market',None),PlannedResearch('traction','traction',None)])
        if schema is ArgumentsOutput:
            side='PRO' if 'pro arguments why' in messages[-1].content else 'CONTRA'
            self.generation_count+=1
            return ArgumentsOutput([ArgumentOutput('SYNTHETIC_'+side+' argument '+str(i),indices) for i in range(self.argument_count)])
        if schema is ArgumentCritique:return ArgumentCritique('SYNTHETIC critique: verify retention against admitted facts.')
        if schema is SingleArgumentScore:
            pro='SYNTHETIC_PRO' in messages[-1].content
            preferred=(good and pro) or (poor and not pro)
            score=6 if preferred else 3
            return SingleArgumentScore([CriterionScore(score,'SYNTHETIC criterion feedback') for _ in range(14)])
        if schema is IndividualRefinedArgumentOutput:
            side='PRO' if 'SYNTHETIC_PRO' in messages[-1].content else 'CONTRA'
            return IndividualRefinedArgumentOutput('SYNTHETIC_'+side+' refined argument',indices)
        if schema is EvidenceReviewOutput:
            return EvidenceReviewOutput([] if good or poor else ['retention'],'Synthetic evidence review only; not a real investment claim.')
        raise ValueError('unsupported fixture schema')

    async def agenerate(self,schema,messages,temperature):return self.generate(schema,messages,temperature)
