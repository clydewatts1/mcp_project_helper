import pytest
import time
import uuid

def setup_large_project(s, num_tasks=1000, num_edges=2500):
    pid = "BENCH_P"
    s.create_project(pid, "2026-01-01", "Large Project")
    
    # 1. Bulk creation of tasks
    # We use Cypher UNWIND for faster insertion if possible, 
    # but for simplicity/reliability we'll use a loop of direct Cypher execution
    for i in range(num_tasks):
        name = f"T{i}"
        s.conn.execute(f"CREATE (t:Task {{name: '{name}', duration: 1, cost: 100.0, status: 'AI_DRAFT', leveling_delay: 0}})")
        s.conn.execute(f"MATCH (p:Project {{id: '{pid}'}}), (t:Task {{name: '{name}'}}) CREATE (p)-[:CONTAINS]->(t)")
    
    # 2. Random dependencies to create a dense graph (avoiding cycles)
    # We'll just link T_i to T_{i+1} and some random ones
    for i in range(num_tasks - 1):
        s.conn.execute(f"MATCH (s:Task {{name: 'T{i}'}}), (t:Task {{name: 'T{i+1}'}}) CREATE (s)-[:DEPENDS_ON {{lag: 0}}]->(t)")
    
    # Add extra edges to reach num_edges
    # Link T_i to T_{i+k} for various i, k
    extra_edges = num_edges - (num_tasks - 1)
    for j in range(extra_edges):
        src = j % (num_tasks - 5)
        target = src + 2 + (j % 3)
        if target < num_tasks:
            s.conn.execute(f"MATCH (s:Task {{name: 'T{src}'}}), (t:Task {{name: 'T{target}'}}) CREATE (s)-[:DEPENDS_ON {{lag: 0}}]->(t)")

def test_benchmark_critical_path(isolated_server, benchmark):
    s = isolated_server
    setup_large_project(s, num_tasks=300, num_edges=700) # Reduced count for faster test run during development
    
    # Benchmark the Critical Path calculation
    res = benchmark(s.get_critical_path, "BENCH_P")
    assert "T299" in res

def test_benchmark_auto_leveler(isolated_server, benchmark):
    s = isolated_server
    pid = "BENCH_L"
    s.create_project(pid, "2026-01-01", "Leveling Bench")
    
    # 50 overlapping tasks
    for i in range(50):
        name = f"L{i}"
        s.add_task(pid, name, 2, 100.0)
    
    s.add_resource("Admin", "HUMAN", 10.0)
    for i in range(50):
        s.assign_resource("Admin", f"L{i}", 100)
    
    # Benchmark the leveler
    # We expect it to hit the iteration limit or resolve
    res = benchmark(s.auto_level_schedule, pid)
    assert res is not None
