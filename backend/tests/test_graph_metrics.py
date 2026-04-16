"""Unit tests for app/graph/ metrics — Phase 02."""
import pytest
import time


def test_graph_state_singleton():
    from app.graph import get_graph_state, set_graph_state, GraphState
    import networkx as nx
    # Reset state
    set_graph_state(None)
    assert get_graph_state() is None
    # Create minimal GraphState to verify set/get round-trip
    g = nx.DiGraph()
    state = GraphState(
        graph=g,
        dist_nodes=frozenset(),
        betweenness={},
        pagerank={},
        k_core={},
        single_source_component_ids=frozenset(),
        hhi_by_category={},
        fiedler=0.0,
        holdout_offer_pairs=frozenset(),
        n_distributors=0,
        n_components=0,
        n_edges=0,
    )
    set_graph_state(state)
    assert get_graph_state() is state
    set_graph_state(None)


def test_graph_builds_from_db(graph_db_session):
    from app.graph.builder import build_graph_state
    gs = build_graph_state(graph_db_session)
    assert gs.n_distributors == 3
    assert gs.n_components == 10
    assert gs.n_edges == 15


def test_graph_builds_under_2s(graph_db_session):
    from app.graph.builder import build_graph_state
    start = time.time()
    build_graph_state(graph_db_session)
    elapsed = time.time() - start
    assert elapsed < 2.0, f"Graph build took {elapsed:.2f}s, expected < 2s"


def test_betweenness_centrality(graph_db_session):
    pytest.skip("stub — implement in plan 02-02")


def test_pagerank_centrality(graph_db_session):
    pytest.skip("stub — implement in plan 02-02")


def test_fiedler_value(graph_db_session):
    pytest.skip("stub — implement in plan 02-02")


def test_kcore_decomposition(graph_db_session):
    pytest.skip("stub — implement in plan 02-02")


def test_hhi_per_category(graph_db_session):
    pytest.skip("stub — implement in plan 02-02")


def test_single_source_flags(graph_db_session):
    pytest.skip("stub — implement in plan 02-02")


def test_monte_carlo_returns_percentiles():
    pytest.skip("stub — implement in plan 02-03")


def test_monte_carlo_reproducible():
    pytest.skip("stub — implement in plan 02-03")


def test_evar_at_95th_percentile():
    pytest.skip("stub — implement in plan 02-03")


def test_surcharge_ceiling():
    pytest.skip("stub — implement in plan 02-04")
