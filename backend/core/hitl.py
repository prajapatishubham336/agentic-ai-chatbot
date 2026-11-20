from typing import TypedDict, Any

from langgraph.graph import (
    StateGraph,
    START,
    END
)

from langgraph.checkpoint.memory import MemorySaver

from langgraph.types import interrupt, Command


class ApprovalState(TypedDict, total=False):

    action: str
    status: str
    decision: Any


def approval_node(state: ApprovalState):

    decision = interrupt({
        "type": "human_approval",
        "action": state.get("action", ""),
        "message": "Please approve or reject this action."
    })

    approved = (
        bool(decision.get("approved"))
        if isinstance(decision, dict)
        else bool(decision)
    )

    return {
        "decision": decision,
        "status": (
            "approved"
            if approved
            else "rejected"
        )
    }


builder = StateGraph(ApprovalState)

builder.add_node(
    "approval",
    approval_node
)

builder.add_edge(
    START,
    "approval"
)

builder.add_edge(
    "approval",
    END
)

approval_graph = builder.compile(
    checkpointer=MemorySaver()
)


def request_approval(action, thread_id):

    return approval_graph.invoke(
        {"action": action},
        config={
            "configurable": {
                "thread_id": thread_id
            }
        }
    )


def resolve_approval(approved, thread_id):

    return approval_graph.invoke(
        Command(
            resume={
                "approved": approved
            }
        ),
        config={
            "configurable": {
                "thread_id": thread_id
            }
        }
    )