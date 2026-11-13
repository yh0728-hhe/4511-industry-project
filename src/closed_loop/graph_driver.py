"""Stage-level LangGraph driver; framework import is optional and lazy.

    plan -> research -> evaluate -> review --gap--> plan
                                    review --done--> finish
    Any bounded-stop condition routes to finish. There is no live model here.
"""
from typing import TypedDict

from .runtime import RunContext


class FlowState(TypedDict, total=False):
    context: RunContext
    result: dict


def build_graph(runtime):
    from langgraph.graph import START, END, StateGraph
    graph=StateGraph(FlowState)
    def stage_node(stage):
        def node(state):
            runtime.step(stage,state['context'])
            return {'context':state['context']}
        return node
    def route(next_stage):
        def router(state):return 'finish' if state['context'].stop else next_stage
        return router
    for stage in ('plan','research','evaluate','review'):
        graph.add_node(stage,stage_node(stage))
    graph.add_node('finish',lambda state:{'result':runtime.finish(state['context'])})
    graph.add_edge(START,'plan')
    for stage,next_stage in (('plan','research'),('research','evaluate'),('evaluate','review'),('review','plan')):
        graph.add_conditional_edges(stage,route(next_stage),{next_stage:next_stage,'finish':'finish'})
    graph.add_edge('finish',END)
    return graph.compile()


def run_graph(runtime):
    return build_graph(runtime).invoke({'context':RunContext()},
        config={'recursion_limit':4*runtime.request.max_research_passes+4})['result']
