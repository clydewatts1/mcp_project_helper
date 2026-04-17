import json

def test_system_and_info(isolated_server):
    s = isolated_server
    # Test ping
    assert s.ping() == "pong: ProjectLogicEngine is online."
    
    # Test info
    assert "Engine Status" in s.get_system_info()
    
    # Test constitution
    assert "# mcp-project-logic Constitution" in s.get_constitution()
    
    # Test schema resource
    schema_json = s.get_schema()
    schema = json.loads(schema_json)
    assert "nodes" in schema
    assert "Task" in schema["nodes"]

def test_project_reporting_tools(isolated_server):
    s = isolated_server
    s.create_project("P1", "2026-01-01", "Report Project")
    s.add_task("P1", "T1", 2, 100.0)
    
    # Test get_project_tasks
    tasks_table = s.get_project_tasks("P1")
    assert "| T1 |" in tasks_table
    
    # Test project graph image
    graph = s.get_project_graph("P1")
    assert graph["type"] == "image"
    assert graph["mimeType"] == "image/png"
    
    # Test Risk Report
    s.update_estimates("T1", 1, 5)
    s.run_pert_analysis("P1")
    risk_report = s.get_risk_report("P1")
    assert "PERT Risk Analysis" in risk_report
    assert "| T1 |" in risk_report

def test_integration_dispatchers(isolated_server):
    s = isolated_server
    s.create_project("P_DISP", "2026-01-01", "Dispatch Project")
    s.add_task("P_DISP", "T1", 2, 100.0, description="Execute code")
    s.baseline_project("P_DISP")
    
    # Test Briefing
    briefing = s.generate_briefing_webhook("P_DISP")
    assert "Project Pulse: P_DISP" in briefing
    
    # Test Agent Sub-Prompt
    s.add_skill("Coding", "Software development")
    s.require_skill("T1", "Coding")
    agent_prompt = s.generate_agent_sub_prompt("T1")
    assert "YOU ARE AN EXPERT AGENT" in agent_prompt
    assert "Coding" in agent_prompt

def test_negative_error_messages(isolated_server):
    s = isolated_server
    # Project not found
    assert "not found" in s.get_project_graph("NONEXISTENT")
    
    # Task not found errors
    assert "not found" in s.lock_task("None")
    assert "not found" in s.set_task_progress("None", 50)
    assert "not found" in s.update_task_actual_cost("None", 100)
    assert "not found" in s.update_estimates("None", 1, 2)
    assert "not found" in s.generate_agent_sub_prompt("None")
    
    # Empty project reports
    s.create_project("EMPTY", "2026-01-01", "Empty")
    assert "No activities found" in s.get_evm_report_internal("EMPTY")
    assert "No task data found" in s.get_risk_report("EMPTY")
    assert "No tasks found" in s.get_project_tasks("EMPTY")
    # get_critical_path returns "Critical Path for EMPTY: " if no tasks exist
    assert "Critical Path for EMPTY" in s.get_critical_path("EMPTY")

def test_skill_management(isolated_server):
    s = isolated_server
    s.add_resource("Expert", "HUMAN", 200.0)
    s.add_skill("Architect", "System design")
    
    # Test grant skill
    res = s.grant_skill("Expert", "Architect", "Senior")
    assert "Senior" in res
    
    # Verify via Cypher
    check = s.conn.execute("MATCH (r:Resource {name: 'Expert'})-[:HAS_SKILL]->(s:Skill) RETURN s.name").get_next()[0]
    assert check == "Architect"

def test_critical_path_logic(isolated_server):
    s = isolated_server
    s.create_project("PCP", "2026-01-01", "CP Project")
    s.add_task("PCP", "A", 2, 100.0)
    s.add_task("PCP", "B", 3, 100.0)
    s.create_dependency("A", "B")
    
    cp = s.get_critical_path("PCP")
    assert "A -> B" in cp

def test_resource_leveling_no_ops(isolated_server):
    s = isolated_server
    s.create_project("PNOP", "2026-01-01", "NoOp Project")
    s.add_task("PNOP", "T1", 2, 100.0)
    # No conflicts
    res = s.auto_level_schedule("PNOP")
    assert "No automated shifts were necessary" in res
