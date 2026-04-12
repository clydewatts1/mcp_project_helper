import numpy as np

def test_circular_dependency(isolated_server):
    s = isolated_server
    s.create_project("P1", "2026-04-09", "Test Project") # Thursday
    s.add_task("P1", "A", 1, 100.0)
    s.add_task("P1", "B", 1, 100.0)
    
    # A -> B
    s.create_dependency("A", "B")
    
    # B -> A (Violation)
    res = s.create_dependency("B", "A")
    assert "Law I Violation" in res

def test_weekend_skips(isolated_server):
    s = isolated_server
    # Thursday: 2026-04-09
    s.create_project("P2", "2026-04-09", "Weekend Skip Project")
    s.add_task("P2", "LongTask", 4, 1000.0)
    
    # Thursday + 4 days (Thu, Fri, Mon, Tue) -> Ends Tue
    res = s.conn.execute("MATCH (t:Task {name: 'LongTask'}) RETURN t.eft_date").get_next()[0]
    # np.busday_offset('2026-04-09', 3) -> 2026-04-14 (Tuesday)
    assert res == "2026-04-14"
