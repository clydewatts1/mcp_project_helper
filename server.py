import re
import json
import base64
import datetime
import graphviz
import numpy as np
import kuzu
from collections import deque
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP
mcp = FastMCP("ProjectLogicEngine")

# Initialize Kuzu Database (Phase 1 Step 1)
db = kuzu.Database('./project_data.kuzu')
conn = kuzu.Connection(db)

def initialize_schema():
    """Initializes the database schema with Project, Task, and Relationship tables."""
    # Node Tables
    node_queries = [
        "CREATE NODE TABLE Project (id STRING, start_date STRING, name STRING, PRIMARY KEY (id))",
        "CREATE NODE TABLE Task (name STRING, description STRING, duration INT, cost DOUBLE, actual_cost DOUBLE, est_date STRING, eft_date STRING, status STRING, baseline_est_date STRING, baseline_eft_date STRING, baseline_cost DOUBLE, percent_complete INT, PRIMARY KEY (name))",
        "CREATE NODE TABLE Resource (name STRING, description STRING, type STRING, cost_rate DOUBLE, PRIMARY KEY (name))",
        "CREATE NODE TABLE Skill (name STRING, description STRING, PRIMARY KEY (name))"
    ]
    
    # Edge Tables
    rel_queries = [
        "CREATE REL TABLE CONTAINS (FROM Project TO Task)",
        "CREATE REL TABLE DEPENDS_ON (FROM Task TO Task, lag INT)",
        "CREATE REL TABLE WORKS_ON (FROM Resource TO Task, allocation INT)",
        "CREATE REL TABLE HAS_SKILL (FROM Resource TO Skill, proficiency STRING)",
        "CREATE REL TABLE REQUIRES_SKILL (FROM Task TO Skill)"
    ]
    
    for query in node_queries + rel_queries:
        try:
            conn.execute(query)
        except Exception:
            pass # Tables likely exist

    # Phase 3 Migrations (Idempotent)
    migration_queries = [
        "ALTER TABLE Task ADD status STRING DEFAULT 'AI_DRAFT'",
        "ALTER TABLE Task ADD baseline_est_date STRING",
        "ALTER TABLE Task ADD baseline_eft_date STRING",
        "ALTER TABLE Task ADD baseline_cost DOUBLE",
        "ALTER TABLE Task ADD actual_cost DOUBLE DEFAULT 0",
        "ALTER TABLE Task ADD percent_complete INT DEFAULT 0"
    ]
    
    for q in migration_queries:
        try:
            conn.execute(q)
        except:
            pass

# Run schema initialization on startup
initialize_schema()

def safe_cypher_read(query: str, params: dict = None) -> str:
    """
    Safely executes a Cypher query and returns the results as a string.
    If an error occurs, returns the error message prefixed with 'Kuzu Error:'.
    """
    try:
        if params:
            result = conn.execute(query, params)
        else:
            result = conn.execute(query)
            
        rows = []
        while result.has_next():
            rows.append(result.get_next())
        return str(rows)
    except Exception as e:
        return f"Kuzu Error: {str(e)}"

def _recalculate_timeline(project_id: str):
    """
    Temporal Engine: Topologically sorts tasks and calculates 
    early start/finish dates using numpy.busday_offset.
    Respects HUMAN_LOCKED status and reports critical conflicts.
    """
    # 1. Fetch Project Start Date
    proj_res = conn.execute("MATCH (p:Project {id: $id}) RETURN p.start_date", {"id": project_id})
    if not proj_res.has_next():
        return []
    project_start_date = proj_res.get_next()[0]

    # 2. Fetch all tasks in project (including status and current dates)
    task_res = conn.execute("""
        MATCH (p:Project {id: $id})-[:CONTAINS]->(t:Task) 
        RETURN t.name, t.duration, t.status, t.est_date, t.eft_date
    """, {"id": project_id})
    tasks = {}
    while task_res.has_next():
        row = task_res.get_next()
        tasks[row[0]] = {
            "duration": row[1], 
            "status": row[2], 
            "est": row[3], 
            "eft": row[4],
            "in_degree": 0, 
            "successors": [], 
            "predecessors": []
        }

    # 3. Fetch dependencies
    dep_res = conn.execute("""
        MATCH (p:Project {id: $id})-[:CONTAINS]->(s:Task)-[r:DEPENDS_ON]->(t:Task)
        RETURN s.name, t.name, r.lag
    """, {"id": project_id})
    while dep_res.has_next():
        s_name, t_name, lag = dep_res.get_next()
        if s_name in tasks and t_name in tasks:
            tasks[s_name]["successors"].append({"target": t_name, "lag": lag})
            tasks[t_name]["predecessors"].append({"source": s_name, "lag": lag})
            tasks[t_name]["in_degree"] += 1

    # 4. Topological Sort (Kahn's Algorithm)
    queue = deque([name for name, data in tasks.items() if data["in_degree"] == 0])
    sorted_tasks = []
    while queue:
        u = queue.popleft()
        sorted_tasks.append(u)
        for edge in tasks[u]["successors"]:
            v = edge["target"]
            tasks[v]["in_degree"] -= 1
            if tasks[v]["in_degree"] == 0:
                queue.append(v)

    # 5. Calendar Calculation
    task_dates = {}
    critical_conflicts = []
    
    for name in sorted_tasks:
        task = tasks[name]
        if not task["predecessors"]:
            proposed_est = np.busday_offset(project_start_date, 0, roll='following')
        else:
            candidate_dates = []
            for pred in task["predecessors"]:
                source_eft = task_dates[pred["source"]]["eft"]
                start_candidate = np.busday_offset(source_eft, 1 + pred["lag"], roll='following')
                candidate_dates.append(start_candidate)
            proposed_est = max(candidate_dates)
        
        if task["status"] == "HUMAN_LOCKED" and task["est"]:
            actual_est = np.datetime64(task["est"])
            if proposed_est > actual_est:
                critical_conflicts.append(f"[CRITICAL CONFLICT] Task '{name}' is locked at {task['est']} but dependencies push it to {proposed_est}")
            
            # Keep existing dates
            task_dates[name] = {"est": task["est"], "eft": task["eft"], "locked": True}
        else:
            # Normal calculation
            eft = np.busday_offset(proposed_est, task["duration"] - 1, roll='following')
            task_dates[name] = {"est": str(proposed_est), "eft": str(eft), "locked": False}

    # 6. Update Database (Skip locked tasks)
    for name, dates in task_dates.items():
        if not dates.get("locked"):
            conn.execute("""
                MATCH (t:Task {name: $name}) 
                SET t.est_date = $est, t.eft_date = $eft
            """, {"name": name, "est": dates["est"], "eft": dates["eft"]})
            
    return critical_conflicts

@mcp.tool()
def lock_task(task_name: str) -> str:
    """Locks a task's dates so the auto-scheduler won't move it."""
    res = conn.execute("""
        MATCH (t:Task {name: $name})
        SET t.status = 'HUMAN_LOCKED'
        RETURN t.name
    """, {"name": task_name})
    if res.has_next():
        return f"Task '{task_name}' is now LOCKED. Auto-scheduler will report conflicts instead of moving it."
    return f"Error: Task '{task_name}' not found."

@mcp.tool()
def baseline_project(project_id: str) -> str:
    """
    Captures the current schedule and cost as the baseline for the project.
    Copies est_date, eft_date, and cost to their baseline counterparts.
    """
    query = """
    MATCH (p:Project {id: $id})-[:CONTAINS]->(t:Task)
    SET t.baseline_est_date = t.est_date,
        t.baseline_eft_date = t.eft_date,
        t.baseline_cost = t.cost
    RETURN count(t)
    """
    res = conn.execute(query, {"id": project_id})
    if res.has_next():
        count = res.get_next()[0]
        return f"Successfully baselined {count} tasks for project '{project_id}'."
    return f"No tasks found for project '{project_id}'."

@mcp.tool()
def set_task_progress(task_name: str, percent_complete: int) -> str:
    """Updates the completion percentage of a task (0-100)."""
    if not (0 <= percent_complete <= 100):
        return "Error: percent_complete must be between 0 and 100."
    res = conn.execute("""
        MATCH (t:Task {name: $name})
        SET t.percent_complete = $pct
        RETURN t.name
    """, {"name": task_name, "pct": percent_complete})
    if res.has_next():
        return f"Task '{task_name}' progress updated to {percent_complete}%."
    return f"Error: Task '{task_name}' not found."

@mcp.tool()
def update_task_actual_cost(task_name: str, actual_cost: float) -> str:
    """Updates the actual cost spent on a task so far."""
    res = conn.execute("""
        MATCH (t:Task {name: $name})
        SET t.actual_cost = $cost
        RETURN t.name
    """, {"name": task_name, "cost": actual_cost})
    if res.has_next():
        return f"Task '{task_name}' actual cost updated to ${actual_cost:,.2f}."
    return f"Error: Task '{task_name}' not found."

@mcp.resource("project://{project_id}/reports/evm")
def get_evm_report(project_id: str) -> str:
    """
    Generates an Earned Value Management (EVM) report.
    Calculates PV, EV, AC, SPI, and CPI.
    """
    # 1. Fetch data
    query = """
    MATCH (p:Project {id: $id})-[:CONTAINS]->(t:Task)
    RETURN t.name, t.cost, t.actual_cost, t.percent_complete, t.status, 
           t.baseline_est_date, t.baseline_eft_date, t.baseline_cost
    """
    res = conn.execute(query, {"id": project_id})
    
    total_pv = 0.0
    total_ev = 0.0
    total_ac = 0.0
    today = np.datetime64(datetime.date.today())
    
    tasks_stats = []
    
    while res.has_next():
        row = res.get_next()
        name, cost, ac, pct, status, b_est, b_eft, b_cost = row
        
        # PV: Planned Value (How much work was scheduled to be done by today?)
        # For simplicity: if today > baseline_eft, PV = b_cost. If today < b_est, PV = 0. 
        # Else linear interpolation (simplified).
        pv = 0.0
        if b_est and b_eft and b_cost:
            b_est_dt = np.datetime64(b_est)
            b_eft_dt = np.datetime64(b_eft)
            if today >= b_eft_dt:
                pv = b_cost
            elif today >= b_est_dt:
                # Simple linear work distribution (calendar days for simplicity in EVM)
                total_days = (b_eft_dt - b_est_dt).astype(int) + 1
                elapsed_days = (today - b_est_dt).astype(int) + 1
                pv = b_cost * (elapsed_days / total_days)
        
        # EV: Earned Value (Value of work actually performed)
        # EV = % Complete * Baseline Cost
        ev = (pct / 100.0) * (b_cost if b_cost else 0.0)
        
        total_pv += pv
        total_ev += ev
        total_ac += ac
        
        tasks_stats.append({
            "name": name,
            "pv": pv,
            "ev": ev,
            "ac": ac,
            "pct": pct
        })

    if not tasks_stats:
        return f"No activities found in project {project_id}."

    spi = total_ev / total_pv if total_pv > 0 else 1.0
    cpi = total_ev / total_ac if total_ac > 0 else 1.0
    
    report = f"# EVM Report: Project {project_id} ({today})\n\n"
    report += f"- **Total Planned Value (PV)**: ${total_pv:,.2f}\n"
    report += f"- **Total Earned Value (EV)**: ${total_ev:,.2f}\n"
    report += f"- **Total Actual Cost (AC)**: ${total_ac:,.2f}\n"
    report += f"- **Schedule Performance Index (SPI)**: {spi:.2f} "
    report += "(Ahead of schedule)" if spi > 1.05 else "(Behind schedule)" if spi < 0.95 else "(On schedule)"
    report += "\n"
    report += f"- **Cost Performance Index (CPI)**: {cpi:.2f} "
    report += "(Under budget)" if cpi > 1.05 else "(Over budget)" if cpi < 0.95 else "(On budget)"
    report += "\n\n"
    
    report += "| Task | Progress | PV | EV | AC |\n"
    report += "| :--- | :--- | :--- | :--- | :--- |\n"
    for s in tasks_stats:
        report += f"| {s['name']} | {s['pct']}% | ${s['pv']:,.2f} | ${s['ev']:,.2f} | ${s['ac']:,.2f} |\n"
        
    return report

@mcp.resource("project://{project_id}/reports/budget")
def get_budget_report(project_id: str) -> str:
    """Generates a financial budget report for a project."""
    query = """
    MATCH (p:Project {id: $pid})-[:CONTAINS]->(t:Task)
    OPTIONAL MATCH (t)<-[w:WORKS_ON]-(r:Resource)
    RETURN t.name, t.cost, t.duration, r.name, r.cost_rate, w.allocation
    """
    res = conn.execute(query, {"pid": project_id})
    
    tasks_data = {}
    while res.has_next():
        row = res.get_next()
        t_name, t_cost, t_dur, r_name, r_rate, r_alloc = row[0], row[1], row[2], row[3], row[4], row[5]
        if t_name not in tasks_data:
            tasks_data[t_name] = {"fixed": t_cost, "duration": t_dur, "resources": []}
        if r_name:
            # Resource_Cost = Rate * Duration * (Allocation / 100)
            res_cost = r_rate * t_dur * (r_alloc / 100.0)
            tasks_data[t_name]["resources"].append({"name": r_name, "cost": res_cost})

    table = f"# Budget Report: Project {project_id}\n\n"
    table += "| Task Name | Fixed Cost | Resource Costs | Total Task Cost |\n"
    table += "| :--- | :--- | :--- | :--- |\n"
    
    grand_total = 0.0
    for t_name, data in tasks_data.items():
        res_total = sum(item["cost"] for item in data["resources"])
        task_total = data["fixed"] + res_total
        grand_total += task_total
        
        res_list = ", ".join([f"{item['name']} (${item['cost']:,.2f})" for item in data["resources"]]) or "None"
        table += f"| {t_name} | ${data['fixed']:,.2f} | {res_list} | **${task_total:,.2f}** |\n"
        
    table += f"| **TOTAL PROJECT BUDGET** | | | **${grand_total:,.2f}** |\n"
    return table

@mcp.resource("project://{project_id}/reports/allocation")
def get_allocation_report(project_id: str) -> str:
    """Generates a resource allocation conflict report."""
    # 1. Fetch all resources involved in the project
    res_query = """
    MATCH (p:Project {id: $pid})-[:CONTAINS]->(t:Task)<-[w:WORKS_ON]-(r:Resource)
    RETURN DISTINCT r.name
    """
    res_nodes = conn.execute(res_query, {"pid": project_id})
    resources = []
    while res_nodes.has_next():
        resources.append(res_nodes.get_next()[0])
    
    report = f"# Resource Allocation Conflict Report: Project {project_id}\n\n"
    conflicts_found = False
    
    for r_name in resources:
        query = """
        MATCH (r:Resource {name: $name})-[w:WORKS_ON]->(t:Task)
        RETURN t.name, t.est_date, t.eft_date, w.allocation
        """
        assign_nodes = conn.execute(query, {"name": r_name})
        events = []
        while assign_nodes.has_next():
            t_name, est, eft, alloc = assign_nodes.get_next()
            events.append((est, alloc, t_name, "START"))
            drop_date = str(np.busday_offset(eft, 1, roll='following'))
            events.append((drop_date, -alloc, t_name, "END"))
        
        events.sort()
        
        current_alloc = 0
        active_tasks = set()
        conflict_windows = []
        
        for i in range(len(events)):
            date, delta, task, event_type = events[i]
            current_alloc += delta
            if event_type == "START": active_tasks.add(task)
            else: active_tasks.remove(task)
            
            if current_alloc > 100:
                if i + 1 < len(events):
                    next_date = events[i+1][0]
                    if next_date != date:
                        conflict_windows.append({
                            "window": f"{date} to {next_date}",
                            "total": current_alloc,
                            "tasks": list(active_tasks)
                        })
        
        if conflict_windows:
            conflicts_found = True
            report += f"## Resource: {r_name}\n"
            for conflict in conflict_windows:
                report += f"- **Conflict Window**: {conflict['window']} (Allocation: {conflict['total']}%)\n"
                report += f"  - **Tasks Involved**: {', '.join(conflict['tasks'])}\n"
            report += "\n"
            
    if not conflicts_found:
        return report + "No resource allocation conflicts detected. All resources are within capacity."
    return report

def _check_over_allocation(resource_name: str) -> str:
    """Checks if a resource is over-allocated (>100%) in any date window."""
    query = """
    MATCH (r:Resource {name: $name})-[w:WORKS_ON]->(t:Task)
    RETURN t.est_date, t.eft_date, w.allocation
    """
    res = conn.execute(query, {"name": resource_name})
    intervals = []
    while res.has_next():
        intervals.append(res.get_next())
        
    if not intervals:
        return ""
        
    # Sweep-line algorithm
    events = []
    for est, eft, alloc in intervals:
        events.append((est, alloc))
        # Release happens the next business day after eft
        try:
            drop_date = str(np.busday_offset(eft, 1, roll='following'))
            events.append((drop_date, -alloc))
        except:
            pass # Handle invalid dates
        
    # Sort events by date
    events.sort()
    
    current_alloc = 0
    max_alloc = 0
    
    for i in range(len(events)):
        _, delta = events[i]
        current_alloc += delta
        if current_alloc > 100:
            max_alloc = max(max_alloc, current_alloc)
            
    if max_alloc > 100:
        return f"[WARNING: Over-allocation] {resource_name} exceeds 100% capacity (Max: {max_alloc}%)."
    return ""

@mcp.resource("system://schema")
def get_schema() -> str:
    """Returns the strict database schema."""
    schema = {
        "nodes": {
            "Project": ["id", "start_date", "name"],
            "Task": ["name", "description", "duration", "cost", "actual_cost", "est_date", "eft_date", "status", "baseline_est_date", "baseline_eft_date", "baseline_cost", "percent_complete"],
            "Resource": ["name", "description", "type", "cost_rate"],
            "Skill": ["name", "description"]
        },
        "relationships": {
            "CONTAINS": {"from": "Project", "to": "Task"},
            "DEPENDS_ON": {"from": "Task", "to": "Task", "properties": ["lag"]},
            "WORKS_ON": {"from": "Resource", "to": "Task", "properties": ["allocation"]},
            "HAS_SKILL": {"from": "Resource", "to": "Skill", "properties": ["proficiency"]},
            "REQUIRES_SKILL": {"from": "Task", "to": "Skill"}
        }
    }
    return json.dumps(schema, indent=2)

@mcp.resource("project://{project_id}/tasks")
def get_project_tasks(project_id: str) -> str:
    """Returns a markdown table of all tasks in a project."""
    query = """
    MATCH (p:Project {id: $project_id})-[:CONTAINS]->(t:Task)
    RETURN t.name, t.duration, t.cost, t.est_date, t.eft_date
    ORDER BY t.est_date
    """
    res = conn.execute(query, {"project_id": project_id})
    
    table = "| Task Name | Duration | Cost | Start Date | End Date |\n"
    table += "| :--- | :--- | :--- | :--- | :--- |\n"
    
    count = 0
    while res.has_next():
        row = res.get_next()
        table += f"| {row[0]} | {row[1]}d | ${row[2]:,.2f} | {row[3]} | {row[4]} |\n"
        count += 1
        
    if count == 0:
        return f"No tasks found for project {project_id}."
    return table

@mcp.resource("project://{project_id}/state/export/image")
def get_project_graph(project_id: str):
    """Generates a Graphviz PNG diagram of the project dependency graph."""
    # 1. Fetch nodes and project info
    proj_res = conn.execute("MATCH (p:Project {id: $id}) RETURN p.name", {"id": project_id})
    if not proj_res.has_next():
        return "Error: Project not found."
    project_name = proj_res.get_next()[0]
    
    # 2. Fetch all tasks and their metrics
    task_res = conn.execute("""
        MATCH (p:Project {id: $id})-[:CONTAINS]->(t:Task)
        RETURN t.name, t.duration, t.cost
    """, {"id": project_id})
    
    dot = graphviz.Digraph(comment=f"Project: {project_name}")
    dot.attr(rankdir='LR')
    dot.attr('node', shape='box', style='rounded,filled', fillcolor='lightblue', fontname='Helvetica')
    
    while task_res.has_next():
        name, dur, cost = task_res.get_next()
        label = f"{name}\n({dur}d | ${cost:,.0f})"
        dot.node(name, label)
        
    # 3. Fetch all dependencies
    dep_res = conn.execute("""
        MATCH (p:Project {id: $id})-[:CONTAINS]->(s:Task)-[r:DEPENDS_ON]->(t:Task)
        RETURN s.name, t.name, r.lag
    """, {"id": project_id})
    
    while dep_res.has_next():
        s, t, lag = dep_res.get_next()
        label = f"lag={lag}" if lag > 0 else ""
        dot.edge(s, t, label=label)
        
    # 4. Generate PNG bytes
    png_bytes = dot.pipe(format='png')
    base64_data = base64.b64encode(png_bytes).decode('utf-8')
    
    return {
        "type": "image",
        "data": base64_data,
        "mimeType": "image/png"
    }

@mcp.tool()
def create_project(project_id: str, start_date: str, name: str) -> str:
    """
    Creates a new project or updates an existing one.
    start_date must be in YYYY-MM-DD format.
    """
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", start_date):
        return "Error: start_date must be in YYYY-MM-DD format."
    
    query = "MERGE (p:Project {id: $id, start_date: $start_date, name: $name})"
    params = {"id": project_id, "start_date": start_date, "name": name}
    return safe_cypher_read(query, params)

@mcp.tool()
def add_task(project_id: str, name: str, duration: int, cost: float, description: str = "") -> str:
    """
    Adds a task to a project and initializes its dates.
    """
    # Cypher to fetch project start_date and create task linked to project
    query = """
    MATCH (p:Project {id: $project_id})
    MERGE (t:Task {name: $name, description: $description, duration: $duration, cost: $cost, 
                   est_date: p.start_date, eft_date: p.start_date, 
                   status: 'AI_DRAFT', percent_complete: 0})
    MERGE (p)-[:CONTAINS]->(t)
    RETURN t.name
    """
    params = {
        "project_id": project_id,
        "name": name,
        "duration": duration,
        "cost": cost,
        "description": description
    }
    res = safe_cypher_read(query, params)
    conflicts = _recalculate_timeline(project_id)
    if conflicts:
        res += "\n" + "\n".join(conflicts)
    return res

@mcp.tool()
def create_dependency(source_name: str, target_name: str, lag: int = 0) -> str:
    """
    Creates a dependency between two tasks (Source -> Target).
    Enforces Law I: No Circular Dependencies.
    """
    # Gate 1: Cycle Check
    check_query = "MATCH path=(t:Task {name: $target_name})-[*]->(s:Task {name: $source_name}) RETURN count(path) as count"
    check_params = {"source_name": source_name, "target_name": target_name}
    check_res = safe_cypher_read(check_query, check_params)
    
    # Kuzu returns strings like '[[1]]' or error messages.
    if "Kuzu Error" in check_res:
        return check_res
        
    try:
        # Check if count > 0. safe_cypher_read returns str(rows).
        if "[1]" in check_res or "[[1]]" in check_res:
            return "Law I Violation: Circular Dependency Detected."
    except:
        pass

    # Gate 2: Create Edge
    query = """
    MATCH (a:Task {name: $source_name}), (b:Task {name: $target_name})
    MERGE (a)-[r:DEPENDS_ON {lag: $lag}]->(b)
    RETURN r.lag
    """
    params = {"source_name": source_name, "target_name": target_name, "lag": lag}
    res = safe_cypher_read(query, params)
    
    # Trigger recalculation: find the project this task belongs to
    if proj_res.has_next():
        project_id = proj_res.get_next()[0]
        conflicts = _recalculate_timeline(project_id)
        if conflicts:
            res += "\n" + "\n".join(conflicts)
            
    return res

@mcp.tool()
def add_resource(name: str, resource_type: str, cost_rate: float, description: str = "") -> str:
    """
    Adds a resource (HUMAN or EQUIPMENT) to the engine.
    """
    if resource_type.upper() not in ["HUMAN", "EQUIPMENT"]:
        return "Error: resource_type must be 'HUMAN' or 'EQUIPMENT'."
    
    query = "MERGE (r:Resource {name: $name, type: $type, cost_rate: $cost_rate, description: $description})"
    params = {"name": name, "type": resource_type.upper(), "cost_rate": cost_rate, "description": description}
    return safe_cypher_read(query, params)

@mcp.tool()
def add_skill(name: str, description: str = "") -> str:
    """
    Adds a skill to the competency database.
    """
    query = "MERGE (s:Skill {name: $name, description: $description})"
    params = {"name": name, "description": description}
    return safe_cypher_read(query, params)

@mcp.tool()
def grant_skill(resource_name: str, skill_name: str, proficiency: str = "Intermediate") -> str:
    """
    Grants a skill to a resource.
    """
    query = """
    MATCH (r:Resource {name: $resource_name}), (s:Skill {name: $skill_name})
    MERGE (r)-[h:HAS_SKILL {proficiency: $proficiency}]->(s)
    RETURN h.proficiency
    """
    params = {"resource_name": resource_name, "skill_name": skill_name, "proficiency": proficiency}
    return safe_cypher_read(query, params)

@mcp.tool()
def require_skill(task_name: str, skill_name: str) -> str:
    """
    Requires a skill for a specific task.
    """
    query = """
    MATCH (t:Task {name: $task_name}), (s:Skill {name: $skill_name})
    MERGE (t)-[r:REQUIRES_SKILL]->(s)
    RETURN count(r)
    """
    params = {"task_name": task_name, "skill_name": skill_name}
    return safe_cypher_read(query, params)

@mcp.tool()
def assign_resource(resource_name: str, task_name: str, allocation: int) -> str:
    """
    Assigns a resource to a task with a specified allocation percentage.
    Checks for skill mismatches and over-allocation.
    """
    # 1. Gate 1: Strict existence check
    res_node = conn.execute("MATCH (r:Resource {name: $name}) RETURN count(*)", {"name": resource_name})
    res_exists = res_node.get_next()[0] # count(*) returns a row with one int
    
    task_node = conn.execute("MATCH (t:Task {name: $name}) RETURN count(*)", {"name": task_name})
    task_exists = task_node.get_next()[0]
    
    if res_exists == 0:
        raise ValueError(f"Resource '{resource_name}' does not exist.")
    if task_exists == 0:
        raise ValueError(f"Task '{task_name}' does not exist.")
        
    # 2. Execute Assignment
    assign_query = """
    MATCH (r:Resource {name: $r}), (t:Task {name: $t})
    MERGE (r)-[w:WORKS_ON]->(t)
    SET w.allocation = $allocation
    RETURN w.allocation
    """
    safe_cypher_read(assign_query, {"r": resource_name, "t": task_name, "allocation": allocation})
    
    warnings = []
    
    # 3. State Monitor A: Skill Check
    req_query = "MATCH (t:Task {name: $t})-[:REQUIRES_SKILL]->(s:Skill) RETURN s.name"
    has_query = "MATCH (r:Resource {name: $r})-[:HAS_SKILL]->(s:Skill) RETURN s.name"
    
    required_it = conn.execute(req_query, {"t": task_name})
    required_skills = set()
    while required_it.has_next():
        required_skills.add(required_it.get_next()[0])
        
    if required_skills:
        possessed_it = conn.execute(has_query, {"r": resource_name})
        possessed_skills = set()
        while possessed_it.has_next():
            possessed_skills.add(possessed_it.get_next()[0])
            
        missing = required_skills - possessed_skills
        if missing:
            warnings.append(f"[WARNING: Skill Mismatch] {resource_name} lacks required skills for {task_name}: {', '.join(missing)}.")
            
    # 4. State Monitor B: Over-allocation Check
    over_alloc_msg = _check_over_allocation(resource_name)
    if over_alloc_msg:
        warnings.append(over_alloc_msg)
        
    # 5. Return
    msg = f"Resource '{resource_name}' successfully assigned to '{task_name}' at {allocation}% allocation."
    if warnings:
        msg += "\n" + "\n".join(warnings)
    return msg

@mcp.tool()
def check_timeline(project_id: str) -> str:
    """Manually triggers a timeline recalculation and returns any conflicts."""
    conflicts = _recalculate_timeline(project_id)
    if conflicts:
        return "\n".join(conflicts)
    return f"Timeline for project '{project_id}' is valid and up-to-date."

@mcp.tool()
def get_critical_path(project_id: str) -> str:
    """
    Identifies the critical path of the project.
    The critical path is the sequence of tasks that determines the project duration.
    """
    # 1. Recalculate to ensure dates are fresh
    _recalculate_timeline(project_id)
    
    # 2. Fetch project finish date
    finish_res = conn.execute("""
        MATCH (p:Project {id: $id})-[:CONTAINS]->(t:Task)
        RETURN max(t.eft_date)
    """, {"id": project_id})
    if not finish_res.has_next(): return "Project empty."
    proj_finish = finish_res.get_next()[0]
    
    # 3. Find tasks that end on the project finish date
    # Then trace back predecessors where predecessor.eft + 1 + lag == task.est
    query = """
    MATCH (p:Project {id: $id})-[:CONTAINS]->(t:Task)
    WHERE t.eft_date = $finish
    RETURN t.name
    """
    seeds = conn.execute(query, {"id": project_id, "finish": proj_finish})
    cp_tasks = set()
    stack = []
    while seeds.has_next():
        name = seeds.get_next()[0]
        cp_tasks.add(name)
        stack.append(name)
        
    # Backward trace
    while stack:
        current = stack.pop()
        # Fetch current Task EST
        est_res = conn.execute("MATCH (t:Task {name: $name}) RETURN t.est_date", {"name": current})
        curr_est = est_res.get_next()[0]
        
        # Find predecessors that drive this EST
        pred_query = """
        MATCH (s:Task)-[r:DEPENDS_ON]->(t:Task {name: $name})
        RETURN s.name, s.eft_date, r.lag
        """
        preds = conn.execute(pred_query, {"name": current})
        while preds.has_next():
            s_name, s_eft, lag = preds.get_next()
            # If s_eft + 1 + lag == curr_est (in business days)
            calc_est = str(np.busday_offset(s_eft, 1 + lag, roll='following'))
            if calc_est == curr_est:
                if s_name not in cp_tasks:
                    cp_tasks.add(s_name)
                    stack.append(s_name)

    return f"Critical Path for {project_id}: " + " -> ".join(sorted(list(cp_tasks)))

@mcp.tool()
def ping() -> str:
    """Health check tool to verify the MCP server is running and responsive."""
    return "pong: ProjectLogicEngine is online."

@mcp.resource("system://info")
def get_system_info() -> str:
    """Returns basic server status."""
    return "Engine Status: Awaiting Phase 1 Database Initialization."

if __name__ == "__main__":
    # By default, mcp.run() uses stdio transport
    mcp.run()
