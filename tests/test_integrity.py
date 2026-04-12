import json

def test_kanban_aggregation(isolated_server):
    s = isolated_server
    s.create_project("P_KANBAN", "2026-07-01", "Kanban Project")
    s.add_task("P_KANBAN", "SharedTask", 3, 300.0)
    
    s.add_resource("Alice", "HUMAN", 100.0)
    s.add_resource("Bob", "HUMAN", 100.0)
    
    s.assign_resource("Alice", "SharedTask", 50)
    s.assign_resource("Bob", "SharedTask", 50)
    
    kanban_json = s.export_to_kanban("P_KANBAN")
    data = json.loads(kanban_json)
    
    # Should only have one card
    assert len(data["cards"]) == 1
    card = data["cards"][0]
    assert "Alice" in card["assignees"]
    assert "Bob" in card["assignees"]
    assert "," in card["assignees"]

def test_cloning_schema_drift(isolated_server):
    s = isolated_server
    s.create_project("P_SRC", "2026-08-01", "Source Project")
    s.add_task("P_SRC", "DataTask", 2, 200.0)
    
    # Manually set some metadata that should be cloned
    s.conn.execute("""
        MATCH (t:Task {name: 'DataTask'})
        SET t.total_float = 5,
            t.actual_cost = 150.0,
            t.leveling_delay = 3,
            t.optimistic_duration = 1,
            t.pessimistic_duration = 5
    """)
    
    # Clone
    s.clone_scenario("P_SRC", "P_SANDBOX")
    
    # Verify cloned task
    # Note: Cloned task name is prefixed with scenario ID
    res = s.conn.execute("""
        MATCH (t:Task {name: 'P_SANDBOX_DataTask'})
        RETURN t.total_float, t.actual_cost, t.leveling_delay, t.optimistic_duration, t.pessimistic_duration
    """).get_next()
    
    assert res[0] == 5
    assert res[1] == 150.0
    assert res[2] == 3
    assert res[3] == 1
    assert res[4] == 5
