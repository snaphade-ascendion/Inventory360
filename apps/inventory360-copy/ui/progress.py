"""
ui/progress.py
================
Friendly progress labels shown in the st.status() box while a turn runs,
tied to the REAL LangGraph node currently executing (via
graph.build_graph.stream_turn()) — not a fake decorative timer. Keeping
this mapping separate from app.py means the wording can be tuned without
touching the streaming/rendering logic.
"""

NODE_LABELS = {
    "genie_call": "🧞 Dispatching the right Agent…",
    "validate": "🔍 Double-checking numbers…",
    "synthesize": "🧵 Synthesizing a response…",
    "clarify": "🙋 Double-checking what you meant…",
    "decline": "🧭 Confirming this is in scope…",
    "direct_answer": "📚 Pulling from the glossary…",
}


def label_for_node(node_name: str, router_visit_count: int) -> str:
    """
    router_visit_count is the number of times "router" has been seen so
    far THIS turn (1 for the first visit). The first router visit reads
    as "understanding" the question; later visits (after a Genie result
    comes back and the router re-evaluates) read as "deciding next step".
    """
    if node_name == "router":
        return "🗺️ Mapping out your question…" if router_visit_count <= 1 else "🔀 Deciding the next stop…"
    return NODE_LABELS.get(node_name, f"🛠️ Working on it ({node_name})…")