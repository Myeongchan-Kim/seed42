"""DB 에 쌓인 관측으로 그래프를 세우고 성질을 잰다.

설정(graph_config)마다 다른 그래프가 나온다. k=12 그래프는 k=40 그래프의
부분그래프가 아니다 - 추출 순위가 65% 만 일치해서 앞 12개가 곧 k=12 가 아니다.
"""
from __future__ import annotations

import sqlite3

import networkx as nx

from . import db


def configs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT c.*,"
        " (SELECT COUNT(*) FROM edge e WHERE e.config_id=c.id) AS edges"
        " FROM graph_config c ORDER BY c.id").fetchall()


def build(conn: sqlite3.Connection, config_id: int) -> nx.DiGraph:
    g = nx.DiGraph()
    rows = conn.execute(
        "SELECT s.word AS src, d.word AS dst, e.rank"
        " FROM edge e JOIN node s ON s.id=e.src_id JOIN node d ON d.id=e.dst_id"
        " WHERE e.config_id=?", (config_id,)).fetchall()
    for r in rows:
        g.add_edge(r["src"], r["dst"], rank=r["rank"])
    return g


def core(g: nx.DiGraph) -> nx.DiGraph:
    """실제로 던져본 단어들만의 유도 부분그래프.

    프론티어 노드(이웃으로만 등장하고 확장은 안 된 단어)는 나가는 엣지가 있을 수
    없다. 전체 그래프에서 상호성·군집계수를 재면 그 노드들이 분모를 채워 값을
    0 쪽으로 희석시킨다. 관계의 대칭성은 양쪽 다 던져본 노드 사이에서만 물을 수 있다."""
    return g.subgraph([n for n, d in g.out_degree() if d > 0]).copy()


def stats(g: nx.DiGraph) -> dict:
    """발산이냐 그룹핑이냐를 가르는 수치들."""
    n, m = g.number_of_nodes(), g.number_of_edges()
    if n == 0:
        return {"nodes": 0}
    ug = g.to_undirected()
    wcc = max(nx.weakly_connected_components(g), key=len)
    outs = [d for _, d in g.out_degree()]
    ins = [d for _, d in g.in_degree()]
    # 확장된 노드(응답을 실제로 받은 것)만 out-degree 가 유효하다
    expanded = [d for d in outs if d > 0]
    return {
        "nodes": n,
        "edges": m,
        "expanded_nodes": len(expanded),          # 실제로 던져본 단어 수
        "frontier_nodes": n - len(expanded),      # 이웃으로만 등장한 단어 수
        "largest_wcc": len(wcc),
        "wcc_ratio": len(wcc) / n,
        "mean_in_degree": sum(ins) / n,
        "max_in_degree": max(ins),
        "clustering": nx.average_clustering(ug),  # 그룹핑 강도
        "reciprocity": nx.reciprocity(g) or 0.0,  # 관계의 대칭성
    }


def core_stats(g: nx.DiGraph) -> dict:
    """확장된 노드들 사이에서만 잰 값. 상호성·군집계수는 이쪽이 유효한 수치다."""
    c = core(g)
    n = c.number_of_nodes()
    if n < 2:
        return {"nodes": n, "edges": c.number_of_edges()}
    return {
        "nodes": n,
        "edges": c.number_of_edges(),
        "clustering": nx.average_clustering(c.to_undirected()),
        "reciprocity": nx.reciprocity(c) or 0.0,
        "density": nx.density(c),
        "largest_scc": len(max(nx.strongly_connected_components(c), key=len)),
    }


def hubs(conn: sqlite3.Connection, config_id: int, limit: int = 15):
    """진입차수가 높은 단어. 아무데나 붙는 총칭어가 남아 있으면 여기 뜬다."""
    return conn.execute(
        "SELECT n.word, COUNT(*) AS indeg FROM edge e JOIN node n ON n.id=e.dst_id"
        " WHERE e.config_id=? GROUP BY e.dst_id ORDER BY indeg DESC LIMIT ?",
        (config_id, limit)).fetchall()


def dead_ends(conn: sqlite3.Connection, config_id: int, limit: int = 15):
    """진입차수 1 이하인 단어. 마지막 홉이 어려운 대상들이다."""
    return conn.execute(
        "SELECT n.word, COUNT(*) AS indeg FROM edge e JOIN node n ON n.id=e.dst_id"
        " WHERE e.config_id=? GROUP BY e.dst_id HAVING indeg=1"
        " ORDER BY RANDOM() LIMIT ?", (config_id, limit)).fetchall()


def introspection_accuracy(conn: sqlite3.Connection, config_id: int) -> dict:
    """선행어 제안 중 실제로 성립한 비율. nonedge 는 검증에서 거짓으로 드러난 주장."""
    bad = conn.execute("SELECT COUNT(*) c FROM nonedge WHERE config_id=?",
                       (config_id,)).fetchone()["c"]
    return {"refuted": bad}


def mc_numbers(conn: sqlite3.Connection):
    """지금까지 측정된 MC number 들."""
    return conn.execute(
        "SELECT start_word, target_word, mode, policy, budget, found, hops,"
        " (SELECT k FROM graph_config g WHERE g.id=run.config_id) AS k, created_at"
        " FROM run ORDER BY id DESC").fetchall()
