import pytest
from datetime import datetime, timedelta
import json
import numpy as np

def test_holiday_shift(isolated_server):
    s = isolated_server
    # Create project starting on Thursday
    s.create_project("P_HOL", "2026-05-07", "Holiday Test")
    # Add task with 2 day duration. 
    # Without holiday: Thu(7), Fri(8). EFT = 2026-05-08.
    s.add_task("P_HOL", "Task1", 2, 100.0)
    
    # 1. Verify no holiday baseline
    res = s.conn.execute("MATCH (t:Task {name: 'Task1'}) RETURN t.eft_date").get_next()[0]
    assert res == "2026-05-08"
    
    # 2. Add holiday on Friday (May 8)
    s.add_holiday("2026-05-08", "May Day Observed")
    
    # Recalculate - Note: In a real scenario, adding a holiday might trigger 
    # a system-wide recalculation, but here we call it for the project.
    s._recalculate_timeline("P_HOL")
    
    # New schedule: Thu(7), Mon(11). 
    # Fri(8) is holiday, Sat(9)/Sun(10) are weekends.
    res_h = s.conn.execute("MATCH (t:Task {name: 'Task1'}) RETURN t.eft_date").get_next()[0]
    assert res_h == "2026-05-11"

def test_gantt_export(isolated_server):
    s = isolated_server
    s.create_project("P_GANTT", "2026-06-01", "Gantt Project")
    s.add_task("P_GANTT", "T1", 2, 100.0)
    s.set_task_progress("T1", 100) # Should move to DONE
    
    gantt_res = s.export_to_gantt("P_GANTT")
    data = json.loads(gantt_res)
    
    assert data["status"] == "success"
    mermaid = data["data"]["mermaid"]
    assert "section DONE" in mermaid
    assert "T1 :" in mermaid
    assert "2026-06-01" in mermaid
