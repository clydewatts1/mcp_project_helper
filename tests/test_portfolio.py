import numpy as np

def test_inter_project_cascading(isolated_server):
    s = isolated_server
    # Project 1: Starts Monday 2026-09-07
    s.create_project("P1", "2026-09-07", "Project A")
    s.add_task("P1", "Alpha", 2, 100.0) # ends Tue 2026-09-08
    
    # Project 2: Starts Monday 2026-09-07
    s.create_project("P2", "2026-09-07", "Project B")
    s.add_task("P2", "Beta", 2, 100.0)
    
    # Link P1.Alpha -> P2.Beta
    s.create_dependency("Alpha", "Beta")
    
    # Verify Beta starts Wed 2026-09-09
    res = s.conn.execute("MATCH (t:Task {name: 'Beta'}) RETURN t.est_date").get_next()[0]
    assert res == "2026-09-09"
    
    # Change Alpha duration to 5 days (Mon-Fri)
    # This should trigger cascade to P2
    s.conn.execute("MATCH (t:Task {name: 'Alpha'}) SET t.duration = 5")
    s.check_timeline("P1")
    
    # Verify Beta now starts next Monday 2026-09-14
    res2 = s.conn.execute("MATCH (t:Task {name: 'Beta'}) RETURN t.est_date").get_next()[0]
    assert res2 == "2026-09-14"

def test_global_over_allocation(isolated_server):
    s = isolated_server
    # Projects on same week
    s.create_project("P1", "2026-10-05", "Project 1")
    s.add_task("P1", "T1", 5, 100.0)
    
    s.create_project("P2", "2026-10-05", "Project 2")
    s.add_task("P2", "T2", 5, 100.0)
    
    s.add_resource("MultiTasker", "HUMAN", 100.0)
    s.assign_resource("MultiTasker", "T1", 100)
    s.assign_resource("MultiTasker", "T2", 50)
    
    report = s.get_portfolio_allocation_report()
    assert "Resource: MultiTasker" in report
    assert "Allocation: 150%" in report
    assert "T1 (P1)" in report
    assert "T2 (P2)" in report
