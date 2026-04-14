import numpy as np
import json

def test_skill_mismatch(isolated_server):
    s = isolated_server
    s.create_project("P_SKILL", "2026-05-01", "Skill Project")
    s.add_task("P_SKILL", "CodeTask", 2, 500.0)
    s.add_skill("Python", "Programming language")
    s.require_skill("CodeTask", "Python")
    
    s.add_resource("Bob", "HUMAN", 100.0)
    # Bob doesn't have Python skill
    res_str = s.assign_resource("Bob", "CodeTask", 100)
    res = json.loads(res_str)
    assert res["status"] == "warning"
    assert any("Skill Mismatch" in w for w in res["warnings"])

def test_auto_leveler(isolated_server):
    s = isolated_server
    # Monday: 2026-06-01
    s.create_project("P_LEVEL", "2026-06-01", "Leveling Project")
    s.add_task("P_LEVEL", "TaskA", 2, 100.0) # Mon-Tue
    s.add_task("P_LEVEL", "TaskB", 2, 100.0) # Mon-Tue
    s.add_task("P_LEVEL", "TaskC", 6, 100.0) # Successor to A
    s.create_dependency("TaskA", "TaskC") # TaskA now has less float than TaskB
    
    s.add_resource("Alice", "HUMAN", 100.0)
    s.assign_resource("Alice", "TaskA", 100)
    s.assign_resource("Alice", "TaskB", 100)
    
    # Verify conflict in report
    report = s.get_allocation_report("P_LEVEL")
    assert "Conflict Window" in report
    
    # Run leveling
    level_res_str = s.auto_level_schedule("P_LEVEL")
    level_res = json.loads(level_res_str)
    assert level_res["status"] == "success"
    
    # Check TaskB new dates
    # TaskA: Mon-Tue
    # TaskB: should start Wed (2026-06-03)
    res = s.conn.execute("MATCH (t:Task {name: 'TaskB'}) RETURN t.est_date, t.leveling_delay").get_next()
    # Leveling happens 1 day at a time in the loop. 
    # To move from Mon to Wed, it needs 2 shifts of 1 day?
    # Actually, TaskA is Mon-Tue. So TaskB must start Wed.
    # Mon -> Tue (1 day delay), Tue -> Wed (2 days delay).
    assert res[1] >= 2
    assert res[0] == "2026-06-03"
