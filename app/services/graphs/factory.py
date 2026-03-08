"""
Graph factory — returns the right LangGraph compiled graph for a given tenant.

Design: Factory Pattern
  Each client type (graph_type) gets its own LangGraph graph definition.
  The factory maps graph_type → graph builder function.

Why a factory?
  - The worker doesn't need to know which graph it's running.
  - Adding a new client type = add one entry to GRAPH_REGISTRY.
  - Graphs are compiled once and cached at module level (compile is expensive).

Usage:
    from app.services.graphs.factory import get_graph
    graph = get_graph("iroko")
    result = await graph.ainvoke(state)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.models.tenant import GraphType

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph


# ─── Registry ────────────────────────────────────────────────────────────────

# Lazy imports: graphs are imported (and compiled) only on first access.
# This avoids paying compilation cost for graph types that aren't used by
# any tenant in the current worker process.

_graph_cache: dict[str, CompiledStateGraph] = {}


def get_graph(graph_type: str) -> CompiledStateGraph:
    """
    Return the compiled LangGraph graph for the given graph_type.

    The graph is compiled once and cached in memory.

    Raises:
        ValueError: if graph_type is not registered.
    """
    if graph_type in _graph_cache:
        return _graph_cache[graph_type]

    if graph_type == GraphType.IROKO:
        from app.services.graphs.iroko_graph import build_graph
        graph = build_graph()

    elif graph_type == GraphType.PASHUTOMAZIA:
        # Pashutomazia uses the same Iroko-style conversational graph.
        # The 6-stage flow is managed by the system prompt + conversation history.
        # A dedicated graph with explicit stage nodes is future work.
        from app.services.graphs.iroko_graph import build_graph
        graph = build_graph()

    elif graph_type == GraphType.DNG:
        # Phase 6 — DNG Medical graph (blocked: needs Biznness API)
        raise NotImplementedError(
            "DNG graph is not implemented yet. Waiting for Biznness API access."
        )

    else:
        raise ValueError(
            f"Unknown graph_type '{graph_type}'. "
            f"Valid types: {[t.value for t in GraphType]}"
        )

    _graph_cache[graph_type] = graph
    return graph
