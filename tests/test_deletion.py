import pytest
import kuzu

def test_delete_task_severs_dependencies(isolated_server):
    s = isolated_server
    s.create_project("P1", "2026-01-01", "Proj 1")
    s.add_task("P1", "TaskA", 2, 100.0)
    s.add_task("P1", "TaskB", 2, 100.0)
    s.create_dependency("TaskA", "TaskB", 0)
    
    # Verify dependency exists
    res = s.conn.execute("MATCH (a:Task {name: 'TaskA'})-[:DEPENDS_ON]->(b:Task {name: 'TaskB'}) RETURN count(*)")
    assert res.get_next()[0] == 1
    
    # Delete TaskA
    s.delete_task("TaskA")
    
    # Verify TaskA is gone and edge is gone
    res = s.conn.execute("MATCH (t:Task {name: 'TaskA'}) RETURN count(*)")
    assert res.get_next()[0] == 0
    res = s.conn.execute("MATCH ()-[r:DEPENDS_ON]->(b:Task {name: 'TaskB'}) RETURN count(*)")
    assert res.get_next()[0] == 0

def test_delete_resource_severs_assignments(isolated_server):
    s = isolated_server
    s.create_project("P1", "2026-01-01", "Proj 1")
    s.add_task("P1", "TaskA", 2, 100.0)
    s.add_resource("Worker1", "HUMAN", 500.0)
    s.assign_resource("Worker1", "TaskA", 100)
    
    # Verify assignment exists
    res = s.conn.execute("MATCH (r:Resource {name: 'Worker1'})-[:WORKS_ON]->(t:Task) RETURN count(*)")
    assert res.get_next()[0] == 1
    
    # Delete Resource
    s.delete_resource("Worker1")
    
    # Verify Resource is gone and edge is gone
    res = s.conn.execute("MATCH (r:Resource {name: 'Worker1'}) RETURN count(*)")
    assert res.get_next()[0] == 0
    res = s.conn.execute("MATCH ()-[:WORKS_ON]->(t:Task {name: 'TaskA'}) RETURN count(*)")
    assert res.get_next()[0] == 0

def test_delete_project_cascades(isolated_server):
    s = isolated_server
    s.create_project("P_DELETE", "2026-01-01", "Delete Me")
    s.add_task("P_DELETE", "T1", 1, 10.0)
    s.add_task("P_DELETE", "T2", 1, 10.0)
    
    # Verify project and tasks exist
    res = s.conn.execute("MATCH (p:Project {id: 'P_DELETE'}) RETURN count(*)")
    assert res.get_next()[0] == 1
    res = s.conn.execute("MATCH (p:Project {id: 'P_DELETE'})-[:CONTAINS]->(t:Task) RETURN count(*)")
    assert res.get_next()[0] == 2
    
    # Delete Project
    result_msg = s.delete_project("P_DELETE")
    assert "removed 2 tasks" in result_msg
    
    # Verify everything is gone
    res = s.conn.execute("MATCH (p:Project {id: 'P_DELETE'}) RETURN count(*)")
    assert res.get_next()[0] == 0
    res = s.conn.execute("MATCH (t:Task) WHERE t.name IN ['T1', 'T2'] RETURN count(*)")
    assert res.get_next()[0] == 0
