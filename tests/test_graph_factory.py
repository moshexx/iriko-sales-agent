"""
Unit tests for the graph factory (app/services/graphs/factory.py).

No LLM or DB needed — we test:
  1. Unknown graph_type raises ValueError
  2. DNG raises NotImplementedError (blocked on Biznness API)
  3. Iroko returns a compiled LangGraph (not None)
  4. The same graph object is returned on repeated calls (cache works)
"""

import pytest

import app.services.graphs.factory as factory_module
from app.services.graphs.factory import get_graph


@pytest.fixture(autouse=True)
def clear_graph_cache():
    """Clear the module-level cache before every test for isolation."""
    factory_module._graph_cache.clear()
    yield
    factory_module._graph_cache.clear()


class TestGetGraph:
    def test_unknown_type_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown graph_type"):
            get_graph("magic_graph")

    def test_dng_raises_not_implemented(self):
        """DNG is Phase 6 — must raise, not silently return None."""
        with pytest.raises(NotImplementedError, match="DNG graph"):
            get_graph("dng")

    def test_iroko_returns_compiled_graph(self):
        graph = get_graph("iroko")
        assert graph is not None

    def test_iroko_graph_is_cached(self):
        """Calling get_graph twice returns the exact same object (no recompilation)."""
        graph_1 = get_graph("iroko")
        graph_2 = get_graph("iroko")
        assert graph_1 is graph_2

    def test_cache_is_populated_after_first_call(self):
        assert "iroko" not in factory_module._graph_cache
        get_graph("iroko")
        assert "iroko" in factory_module._graph_cache
