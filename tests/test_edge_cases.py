import pytest

def test_invalid_resource_assignment(isolated_server):
    s = isolated_server
    s.create_project("P_ERR", "2026-01-01", "Error Project")
    s.add_task("P_ERR", "T1", 1, 100.0)
    
    res = s.assign_resource("Ghost", "T1", 100)
    assert "not found" in res

def test_invalid_date_format(isolated_server):
    s = isolated_server
    res = s.create_project("P_DATE", "01-01-2026", "Bad Date")
    assert "Invalid date format" in res

def test_auto_leveler_failure_locked(isolated_server):
    s = isolated_server
    s.create_project("P_LOCK", "2026-06-01", "Locked Project")
    s.add_task("P_LOCK", "T1", 2, 100.0)
    s.add_task("P_LOCK", "T2", 2, 100.0)
    
    # Lock both
    s.lock_task("T1")
    s.lock_task("T2")
    
    s.add_resource("Worker", "HUMAN", 100.0)
    s.assign_resource("Worker", "T1", 100)
    s.assign_resource("Worker", "T2", 100)
    
    # Run leveler
    res = s.auto_level_schedule("P_LOCK")
    assert "No automated shifts were necessary or possible" in res
