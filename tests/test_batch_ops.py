import json

def test_batch_assign_resources(isolated_server):
    s = isolated_server
    s.create_project("P_BATCH", "2026-09-01", "Batch Project")
    s.add_task("P_BATCH", "T1", 2, 100.0)
    s.add_task("P_BATCH", "T2", 2, 100.0)
    s.add_resource("Worker1", "HUMAN", 50.0)
    
    assignments = [
        {"resource_name": "Worker1", "task_name": "T1", "allocation": 50},
        {"resource_name": "Worker1", "task_name": "T2", "allocation": 50}
    ]
    
    res = s.batch_assign_resources(assignments)
    data = json.loads(res)
    assert data["status"] == "success"
    
    # Verify in DB
    check = s.conn.execute("MATCH (r:Resource)-[w:WORKS_ON]->(t:Task) RETURN count(*)").get_next()[0]
    assert check == 2

def test_batch_grant_skills(isolated_server):
    s = isolated_server
    s.add_resource("ExpertUser", "HUMAN", 100.0)
    s.add_skill("PyKuzu", "Graph Mastery")
    s.add_skill("Cypher", "Query Ninja")
    
    grants = [
        {"resource_name": "ExpertUser", "skill_name": "PyKuzu", "proficiency": "Expert"},
        {"resource_name": "ExpertUser", "skill_name": "Cypher", "proficiency": "Master"}
    ]
    
    res = s.batch_grant_skills(grants)
    data = json.loads(res)
    assert data["status"] == "success"
    
    # Verify in DB
    check = s.conn.execute("MATCH (r:Resource)-[h:HAS_SKILL]->(s:Skill) RETURN count(*)").get_next()[0]
    assert check == 2
