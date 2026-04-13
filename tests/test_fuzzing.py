import pytest
from hypothesis import given, strategies as st, settings, HealthCheck
import numpy as np
import datetime

# Reuse the isolated_server fixture via conftest.py
# Note: hypothesis has some issues with yield fixtures, so we use s = isolated_server internally

@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(
    duration=st.integers(min_value=1, max_value=1000),
    lag=st.integers(min_value=-100, max_value=100),
    start_date=st.dates(min_value=datetime.date(1970, 1, 1), max_value=datetime.date(2100, 1, 1))
)
def test_temporal_fuzzing(isolated_server, duration, lag, start_date):
    s = isolated_server
    pid = "FUZZ_P"
    s.create_project(pid, str(start_date), f"Fuzz Project {start_date}")
    
    # Create two tasks with fuzzed parameters
    s.add_task(pid, "Task1", duration, 100.0)
    s.add_task(pid, "Task2", duration, 100.0)
    
    # Create dependency with fuzzed lag
    s.create_dependency("Task1", "Task2", lag=lag)
    
    # Trigger recalculation
    conflicts = s._recalculate_timeline(pid)
    
    # Verify Task2 exists and has dates
    res = s.conn.execute("MATCH (t:Task {name: 'Task2'}) RETURN t.est_date, t.eft_date").get_next()
    est, eft = res
    
    # Assert they are valid ISO dates
    assert datetime.date.fromisoformat(est)
    assert datetime.date.fromisoformat(eft)
    
    # Ensure EST of successor is >= EST of predecessor + 1 + lag (in busdays)
    # This is a core property that should hold unless locked
    res1 = s.conn.execute("MATCH (t:Task {name: 'Task1'}) RETURN t.eft_date").get_next()[0]
    expected_min_est = str(np.busday_offset(res1, 1 + lag, roll='following'))
    
    # Task2 est should be >= expected_min_est
    assert np.datetime64(est) >= np.datetime64(expected_min_est)

@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(
    alloc1=st.integers(min_value=1, max_value=200),
    alloc2=st.integers(min_value=1, max_value=200)
)
def test_leveler_fuzzing(isolated_server, alloc1, alloc2):
    s = isolated_server
    pid = "FUZZ_L"
    s.create_project(pid, "2026-01-01", "Leveling Fuzz")
    
    s.add_task(pid, "A", 2, 100.0)
    s.add_task(pid, "B", 2, 100.0)
    
    s.add_resource("FuzzBot", "HUMAN", 50.0)
    s.assign_resource("FuzzBot", "A", alloc1)
    s.assign_resource("FuzzBot", "B", alloc2)
    
    # Ensure tasks have dates or else over-allocation is skiped
    s._recalculate_timeline(pid)
    
    # Sweep-line should never crash regardless of allocation values
    # even if alloc1 + alloc2 > 100
    msg = s._check_over_allocation("FuzzBot")
    if (alloc1 + alloc2) > 100:
        # Sweep-line returns a specific warning string if over-allocated
        assert "[WARNING: Over-allocation]" in msg
    else:
        # Returns empty string if within capacity
        assert msg == ""
