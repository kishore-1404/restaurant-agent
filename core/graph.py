from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from core.state import OrderState
from core.nodes import chatbot_node, tool_executor, should_use_tools, update_stage


def build_graph():
    """
    Compile the LangGraph conversation graph.

    Flow:
        START → chatbot → [tools? → chatbot again] → END

    The loop handles multi-step tool use:
    e.g. search_menu → add_item → get_summary all in one turn.
    """
    builder = StateGraph(OrderState)

    # Add nodes
    builder.add_node("chatbot", chatbot_node)
    builder.add_node("tools", tool_executor)
    builder.add_node("update_stage", update_stage)

    # Define edges
    builder.add_edge(START, "chatbot")
    builder.add_conditional_edges(
        "chatbot",
        should_use_tools,
        {
            "tools": "tools",
            "end": "update_stage",
        }
    )
    builder.add_edge("tools", "chatbot")   # after tool use, re-run LLM
    builder.add_edge("update_stage", END)

    # MemorySaver: keeps conversation state in memory per session.
    memory = MemorySaver()

    return builder.compile(checkpointer=memory)


# Single compiled graph instance shared across all sessions
graph = build_graph()
