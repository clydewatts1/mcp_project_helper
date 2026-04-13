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
        "CREATE NODE TABLE Task (name STRING, description STRING, duration INT, optimistic_duration INT, pessimistic_duration INT, expected_duration DOUBLE, cost DOUBLE, actual_cost DOUBLE, est_date STRING, eft_date STRING, status STRING, baseline_est_date STRING, baseline_eft_date STRING, baseline_cost DOUBLE, percent_complete INT, total_float INT, leveling_delay INT, PRIMARY KEY (name))",
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
        "ALTER TABLE Task ADD percent_complete INT DEFAULT 0",
        "ALTER TABLE Task ADD optimistic_duration INT",
        "ALTER TABLE Task ADD pessimistic_duration INT",
        "ALTER TABLE Task ADD expected_duration DOUBLE",
        "ALTER TABLE Task ADD total_float INT DEFAULT 0",
        "ALTER TABLE Task ADD leveling_delay INT DEFAULT 0"
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
        
        if not rows:
            return "Success: Query completed (No Return Rows)."
        return str(rows)
    except Exception as e:
        return f"Kuzu Error: {str(e)}"

@mcp.tool()
def execute_read_cypher(query: str) -> str:
    """
    Executes a raw read-only Cypher query against the Kuzu database.
    Strictly blocks CREATE, MERGE, SET, and DELETE commands.
    Available Labels: Project, Task, Resource, Skill.
    Example: MATCH (p:Project) RETURN p.id, p.name
    """
    if any(keyword in query.upper() for keyword in ["CREATE", "MERGE", "SET", "DELETE", "DROP"]):
        return "Error: This tool is strictly for read-only MATCH queries."
    
    return safe_cypher_read(query)

def _recalculate_timeline(project_id: str, repro_set=None):
    """
    Temporal Engine: Topologically sorts tasks and calculates 
    early start/finish dates using numpy.busday_offset.
    Respects HUMAN_LOCKED status and reports critical conflicts.
    Ph5: Cascades to successor projects if inter-project dependencies change.
    """
    if repro_set is None:
        repro_set = set()
    if project_id in repro_set:
        return []
    repro_set.add(project_id)

    # 1. Fetch Project Start Date
    proj_res = conn.execute("MATCH (p:Project {id: $id}) RETURN p.start_date", {"id": project_id})
    if not proj_res.has_next():
        return []
    project_start_date = proj_res.get_next()[0]

    # 2. Fetch all tasks in project
    task_res = conn.execute("""
        MATCH (p:Project {id: $id})-[:CONTAINS]->(t:Task) 
        RETURN t.name, t.duration, t.status, t.est_date, t.eft_date, t.leveling_delay
    """, {"id": project_id})
    tasks = {}
    while task_res.has_next():
        row = task_res.get_next()
        tasks[row[0]] = {
            "duration": row[1], 
            "status": row[2], 
            "est": row[3], 
            "eft": row[4],
            "delay": row[5] if row[5] is not None else 0,
            "in_degree": 0, 
            "successors": [], 
            "predecessors": []
        }

    # 3. Fetch dependencies (including inter-project)
    # Forward dependencies: (this project) -> (any project)
    # Backward dependencies: (any project) -> (this project)
    dep_res = conn.execute("""
        MATCH (s:Task)-[r:DEPENDS_ON]->(t:Task)
        MATCH (p_s:Project)-[:CONTAINS]->(s)
        MATCH (p_t:Project)-[:CONTAINS]->(t)
        WHERE p_s.id = $id OR p_t.id = $id
        RETURN s.name, t.name, r.lag, p_s.id, p_t.id, s.eft_date
    """, {"id": project_id})
    
    while dep_res.has_next():
        s_name, t_name, lag, s_proj, t_proj, s_eft = dep_res.get_next()
        
        # Case A: Dependency within this project or starting here
        if s_proj == project_id and s_name in tasks:
            tasks[s_name]["successors"].append({"target": t_name, "lag": lag, "target_proj": t_proj})
            if t_proj == project_id and t_name in tasks:
                tasks[t_name]["predecessors"].append({"source": s_name, "lag": lag})
                tasks[t_name]["in_degree"] += 1
        
        # Case B: Dependency ending here but starting in another project
        elif t_proj == project_id and t_name in tasks:
            # External predecessor is a fixed date constraint for this calculation
            tasks[t_name]["predecessors"].append({"source": s_name, "lag": lag, "external_eft": s_eft})
            # We don't increment in_degree for external predecessors because 
            # we don't calculate them in this pass; they are just 'max' constraints.

    # 4. Topological Sort (Kahn's Algorithm - internal tasks only)
    queue = deque([name for name, data in tasks.items() if data["in_degree"] == 0])
    sorted_tasks = []
    while queue:
        u = queue.popleft()
        sorted_tasks.append(u)
        for edge in tasks[u]["successors"]:
            v = edge["target"]
            if edge["target_proj"] == project_id: # only traverse internal edges
                tasks[v]["in_degree"] -= 1
                if tasks[v]["in_degree"] == 0:
                    queue.append(v)

    # 5. Calendar Calculation
    task_dates = {}
    critical_conflicts = []
    
    for name in sorted_tasks:
        task = tasks[name]
        candidate_dates = [np.busday_offset(project_start_date, 0, roll='following')]
        
        for pred in task["predecessors"]:
            if "external_eft" in pred:
                # Use fixed date from external project
                if pred["external_eft"]:
                    ref_eft = pred["external_eft"]
                else:
                    ref_eft = project_start_date # Default fallback
            else:
                # Use calculated date from this pass
                ref_eft = task_dates[pred["source"]]["eft"]
            
            start_candidate = np.busday_offset(ref_eft, 1 + pred["lag"], roll='following')
            candidate_dates.append(start_candidate)
            
        proposed_est = max(candidate_dates)
        
        # Apply leveling_delay (Defect 1 fix)
        if task["delay"] > 0:
            proposed_est = np.busday_offset(proposed_est, task["delay"], roll='following')
        
        if task["status"] == "HUMAN_LOCKED" and task["est"]:
            actual_est = np.datetime64(task["est"])
            if proposed_est > actual_est:
                critical_conflicts.append(f"[CRITICAL CONFLICT] Task '{name}' is locked at {task['est']} but dependencies push it to {proposed_est}")
            task_dates[name] = {"est": task["est"], "eft": task["eft"], "locked": True}
        else:
            eft = np.busday_offset(proposed_est, task["duration"] - 1, roll='following')
            task_dates[name] = {"est": str(proposed_est), "eft": str(eft), "locked": False}

    # 6. Update Database
    for name, dates in task_dates.items():
        if not dates.get("locked"):
            conn.execute("""
                MATCH (t:Task {name: $name}) 
                SET t.est_date = $est, t.eft_date = $eft
            """, {"name": name, "est": dates["est"], "eft": dates["eft"]})
            
    # 7. Cascading Trigger: Identify successor projects and recalculate them
    # Project B's dates might need to change if Project A moved.
    successor_projects_res = conn.execute("""
        MATCH (p_s:Project {id: $id})-[:CONTAINS]->(s:Task)-[:DEPENDS_ON]->(t:Task)<-[:CONTAINS]-(p_t:Project)
        WHERE p_s.id <> p_t.id
        RETURN DISTINCT p_t.id
    """, {"id": project_id})
    while successor_projects_res.has_next():
        target_pid = successor_projects_res.get_next()[0]
        critical_conflicts += _recalculate_timeline(target_pid, repro_set)
            
    return critical_conflicts

def _calculate_float(project_id: str):
    """
    Backward Pass Engine: Calculates Late Start/Finish and Total Float.
    Assumes _recalculate_timeline has already run (Early Start/Finish are set).
    C2 Fix: Batches all predecessor queries, guards against None eft.
    H2 Fix: Uses roll='backward' for correct LF subtraction.
    """
    # 1. Fetch all tasks and their dependencies in batch (C2: no N+1)
    task_res = conn.execute("""
        MATCH (p:Project {id: $id})-[:CONTAINS]->(t:Task)
        RETURN t.name, t.duration, t.est_date, t.eft_date
    """, {"id": project_id})
    tasks = {}
    while task_res.has_next():
        row = task_res.get_next()
        # C2 Fix: Guard against None eft
        if row[3] is None:
            continue
        tasks[row[0]] = {
            "duration": row[1],
            "es": row[2],
            "ef": row[3],
            "successors": [],
            "predecessors": [],
            "out_degree": 0
        }

    # Batch fetch all dependencies (C2: single query instead of N+1)
    dep_res = conn.execute("""
        MATCH (p:Project {id: $id})-[:CONTAINS]->(s:Task)-[r:DEPENDS_ON]->(t:Task)
        RETURN s.name, t.name, r.lag
    """, {"id": project_id})
    while dep_res.has_next():
        s, t, lag = dep_res.get_next()
        if s in tasks and t in tasks:
            tasks[s]["successors"].append({"target": t, "lag": lag})
            tasks[s]["out_degree"] += 1
            tasks[t]["predecessors"].append(s)

    # 2. Project Finish Date
    all_ef = [np.datetime64(t["ef"]) for t in tasks.values()]
    if not all_ef: return
    project_finish = max(all_ef)

    # 3. Reverse Topological Sort (Kahn's — process sinks first)
    queue = deque([name for name, data in tasks.items() if data["out_degree"] == 0])
    sorted_rev = []
    while queue:
        u = queue.popleft()
        sorted_rev.append(u)
        for pred_name in tasks[u]["predecessors"]:
            if pred_name in tasks:
                tasks[pred_name]["out_degree"] -= 1
                if tasks[pred_name]["out_degree"] == 0:
                    queue.append(pred_name)

    # 4. Backward Pass Calculation
    task_lfls = {}
    for name in sorted_rev:
        task = tasks[name]
        if not task["successors"]:
            lf = project_finish
        else:
            candidates = []
            for succ in task["successors"]:
                v_ls = task_lfls[succ["target"]]["ls"]
                # LF(u) = LS(v) - 1 - lag (in business days)
                lf_candidate = np.busday_offset(v_ls, -(1 + succ["lag"]), roll='backward')
                candidates.append(lf_candidate)
            lf = min(candidates)
        
        # H2 Fix: Use roll='backward' for correct business-day subtraction
        ls = np.busday_offset(lf, -(task["duration"] - 1), roll='backward')
        task_lfls[name] = {"ls": ls, "lf": lf}

    # 5. Update Total Float in DB
    for name, dates in task_lfls.items():
        ef = np.datetime64(tasks[name]["ef"])
        lf = dates["lf"]
        # Total Float = LF - EF (in business days)
        float_days = int(np.busday_count(ef, lf))
        conn.execute("MATCH (t:Task {name: $name}) SET t.total_float = $f", {"name": name, "f": float_days})

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
        
        # Safely handle None values from DB
        ac = ac if ac is not None else 0.0
        pct = pct if pct is not None else 0
        b_cost = b_cost if b_cost is not None else 0.0
        
        # PV: Planned Value (How much work was scheduled to be done by today?)
        pv = 0.0
        # Safely parse baseline dates
        if b_est and b_eft and str(b_est) != "None" and str(b_eft) != "None":
            b_est_dt = np.datetime64(b_est)
            b_eft_dt = np.datetime64(b_eft)
            if today >= b_eft_dt:
                pv = b_cost
            elif today >= b_est_dt:
                total_days = (b_eft_dt - b_est_dt).astype(int) + 1
                elapsed_days = (today - b_est_dt).astype(int) + 1
                pv = b_cost * (elapsed_days / total_days)
        
        # EV: Earned Value (Value of work actually performed)
        # EV = % Complete * Baseline Cost
        ev = (pct / 100.0) * b_cost
        
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
        MATCH (p:Project {id: $pid})-[:CONTAINS]->(t:Task)<-[w:WORKS_ON]-(r:Resource {name: $name})
        RETURN t.name, t.est_date, t.eft_date, w.allocation
        """
        assign_nodes = conn.execute(query, {"name": r_name, "pid": project_id})
        events = []
        while assign_nodes.has_next():
            t_name, est, eft, alloc = assign_nodes.get_next()
            # Priority 0 for START, 1 for END to ensure START is processed first on identical dates
            events.append((est, 0, alloc, t_name, "START"))
            
            # Defect 2 Fix: Robust drop_date calculation
            drop_date = None
            if eft:
                try:
                    drop_date = str(np.busday_offset(eft, 1, roll='following'))
                except Exception:
                    pass
            
            if not drop_date:
                drop_date = est # Immediate release fallback
                
            events.append((drop_date, 1, -alloc, t_name, "END"))
        
        events.sort()
        
        current_alloc = 0
        active_tasks = set()
        conflict_windows = []
        
        for i in range(len(events)):
            date, priority, delta, task, event_type = events[i]
            current_alloc += delta
            if event_type == "START": active_tasks.add(task)
            else: active_tasks.discard(task)
            
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

@mcp.resource("portfolio://reports/allocation")
def get_portfolio_allocation_report() -> str:
    """Generates a global resource allocation conflict report across all projects."""
    # 1. Fetch all resources in the system
    res_query = "MATCH (r:Resource) RETURN r.name"
    res_nodes = conn.execute(res_query)
    resources = []
    while res_nodes.has_next():
        resources.append(res_nodes.get_next()[0])
    
    report = "# Global Portfolio Allocation Conflict Report\n\n"
    conflicts_found = False
    
    for r_name in resources:
        query = """
        MATCH (r:Resource {name: $name})-[w:WORKS_ON]->(t:Task)
        MATCH (p:Project)-[:CONTAINS]->(t)
        RETURN t.name, t.est_date, t.eft_date, w.allocation, p.id
        """
        assign_nodes = conn.execute(query, {"name": r_name})
        events = []
        while assign_nodes.has_next():
            t_name, est, eft, alloc, pid = assign_nodes.get_next()
            label = f"{t_name} ({pid})"
            # Priority 0 for START, 1 for END to ensure START is processed first on identical dates
            events.append((est, 0, alloc, label, "START"))
            
            # Defect 2 Fix: Robust drop_date calculation
            drop_date = None
            if eft:
                try:
                    drop_date = str(np.busday_offset(eft, 1, roll='following'))
                except Exception:
                    pass
            
            if not drop_date:
                drop_date = est # Immediate release fallback
                
            events.append((drop_date, 1, -alloc, label, "END"))
        
        if not events: continue
        events.sort()
        
        current_alloc = 0
        active_tasks = set()
        conflict_windows = []
        
        for i in range(len(events)):
            date, priority, delta, task_label, event_type = events[i]
            current_alloc += delta
            if event_type == "START": active_tasks.add(task_label)
            else: active_tasks.discard(task_label)
            
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
        return report + "No global resource allocation conflicts detected."
    return report

def _check_over_allocation(resource_name: str) -> str:
    """Checks if a resource is over-allocated (>100%) in any date window."""
    query = """
    MATCH (r:Resource {name: $name})-[w:WORKS_ON]->(t:Task)
    RETURN t.est_date, t.eft_date, w.allocation
    """
    try:
        res = conn.execute(query, {"name": resource_name})
        intervals = []
        while res.has_next():
            row = res.get_next()
            if row[0] and row[1]: # Only process if dates are set
                intervals.append(row)
            
        if not intervals:
            return ""
            
        # Sweep-line algorithm
        events = []
        for est, eft, alloc in intervals:
            # We assume duration is working days, so eft is the last working day.
            # The resource is released on the next business day.
            # Priority 0 for START, 1 for END to ensure START is processed first on identical dates
            events.append((est, 0, alloc))
            
            # Robust drop_date calculation
            drop_date = None
            try:
                # np.busday_offset(eft, 1) gets the next working day
                drop_date = str(np.busday_offset(eft, 1, roll='following'))
            except Exception:
                drop_date = est # Immediate release fallback if eft is invalid
            
            events.append((drop_date, 1, -alloc))
            
        # Sort events by date
        events.sort()
        
        current_alloc = 0
        max_alloc = 0
        
        for i in range(len(events)):
            _, priority, delta = events[i]
            current_alloc += delta
            if current_alloc > 100:
                max_alloc = max(max_alloc, current_alloc)
                
        if max_alloc > 100:
            return f"[WARNING: Over-allocation] {resource_name} exceeds 100% capacity (Max: {max_alloc}%)."
        return ""
    except Exception as e:
        return f"[ERROR: Query Failed] {str(e)}"


@mcp.resource("system://schema")
def get_schema() -> str:
    """Returns the strict database schema."""
    schema = {
        "nodes": {
            "Project": ["id", "start_date", "name"],
            "Task": ["name", "description", "duration", "optimistic_duration", "pessimistic_duration",
                     "expected_duration", "cost", "actual_cost", "est_date", "eft_date", "status",
                     "baseline_est_date", "baseline_eft_date", "baseline_cost",
                     "percent_complete", "total_float", "leveling_delay"],
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

@mcp.resource("project://{project_id}/state/export/pert")
def get_pert_chart(project_id: str):
    """Generates a high-fidelity PERT Chart (Precedence Diagram) with CPM metrics."""
    # 1. Fetch info
    proj_res = conn.execute("MATCH (p:Project {id: $id}) RETURN p.name", {"id": project_id})
    if not proj_res.has_next():
        return "Error: Project not found."
    project_name = proj_res.get_next()[0]
    
    # 2. Fetch Tasks with CPM data
    task_res = conn.execute("""
        MATCH (p:Project {id: $id})-[:CONTAINS]->(t:Task)
        RETURN t.name, t.duration, t.est_date, t.eft_date, t.total_float
    """, {"id": project_id})
    
    dot = graphviz.Digraph(comment=f"PERT: {project_name}")
    dot.attr(rankdir='LR', splines='ortho')
    
    while task_res.has_next():
        name, dur, es, ef, f = task_res.get_next()
        # ES/EF are strings YYYY-MM-DD, let's just use MM-DD for brevity in the chart
        es_short = es[-5:] if es else "N/A"
        ef_short = ef[-5:] if ef else "N/A"
        
        float_color = "red" if (f is not None and f <= 0) else "black"
        penwidth = "3" if float_color == "red" else "1"
        
        # HTML label for structured PERT node
        label = f'''<<TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0">
            <TR><TD COLSPAN="3"><B>{name}</B></TD></TR>
            <TR>
                <TD BGCOLOR="#EEEEEE">{es_short}</TD>
                <TD>{dur}d</TD>
                <TD BGCOLOR="#EEEEEE">{ef_short}</TD>
            </TR>
            <TR><TD COLSPAN="3" PORT="f">Float: {f if f is not None else '?'}</TD></TR>
        </TABLE>>'''
        
        dot.node(name, label=label, shape='none', color=float_color, penwidth=penwidth)
        
    # 3. Dependencies
    dep_res = conn.execute("""
        MATCH (p:Project {id: $id})-[:CONTAINS]->(s:Task)-[r:DEPENDS_ON]->(t:Task)
        RETURN s.name, t.name, s.total_float, t.total_float
    """, {"id": project_id})
    
    while dep_res.has_next():
        s, t, sf, tf = dep_res.get_next()
        # Highlight edge if both tasks are on critical path
        ecolor = "red" if (sf == 0 and tf == 0) else "black"
        ewith = "2" if ecolor == "red" else "1"
        dot.edge(s, t, color=ecolor, penwidth=ewith)
        
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
    
    query = """
    MERGE (p:Project {id: $id})
    SET p.start_date = $start_date, p.name = $name
    RETURN p.id
    """
    params = {"id": project_id, "start_date": start_date, "name": name}
    res = safe_cypher_read(query, params)
    return f"Project created/updated: {res}"

@mcp.tool()
def add_task(project_id: str, name: str, duration: int, cost: float, description: str = "", optimistic: int = None, pessimistic: int = None) -> str:
    """
    Adds a task to a project and initializes its dates and PERT estimates.
    """
    # Default PERT estimates to the provided duration if not specified
    opt = optimistic if optimistic is not None else duration
    pess = pessimistic if pessimistic is not None else duration
    
    # MERGE on name (PK) only, then SET all other properties to avoid duplicate nodes
    query = """
    MATCH (p:Project {id: $project_id})
    MERGE (t:Task {name: $name})
    SET t.description = $description,
        t.duration = $duration,
        t.optimistic_duration = $opt,
        t.pessimistic_duration = $pess,
        t.cost = $cost,
        t.actual_cost = coalesce(t.actual_cost, 0.0),
        t.est_date = coalesce(t.est_date, p.start_date),
        t.eft_date = coalesce(t.eft_date, p.start_date),
        t.status = coalesce(t.status, 'AI_DRAFT'),
        t.percent_complete = coalesce(t.percent_complete, 0),
        t.total_float = coalesce(t.total_float, 0),
        t.leveling_delay = coalesce(t.leveling_delay, 0)
    MERGE (p)-[:CONTAINS]->(t)
    RETURN t.name
    """
    params = {
        "project_id": project_id,
        "name": name,
        "duration": duration,
        "opt": opt,
        "pess": pess,
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
    # Gate 1: Cycle Check (Extract exact count natively, avoid brittle string matching)
    check_query = "MATCH path=(t:Task {name: $target_name})-[*]->(s:Task {name: $source_name}) RETURN count(path)"
    try:
        check_res = conn.execute(check_query, {"source_name": source_name, "target_name": target_name})
        if check_res.has_next():
            path_count = check_res.get_next()[0]
            if path_count > 0:
                return "Law I Violation: Circular Dependency Detected."
    except Exception as e:
         return f"Kuzu Error during Cycle Check: {str(e)}"

    # Gate 2: Create Edge
    query = """
    MATCH (a:Task {name: $source_name}), (b:Task {name: $target_name})
    MERGE (a)-[r:DEPENDS_ON {lag: $lag}]->(b)
    RETURN r.lag
    """
    res = safe_cypher_read(query, {"source_name": source_name, "target_name": target_name, "lag": lag})
      
    # Trigger recalculation: Correctly fetch the project_id using the source_name
    proj_query = "MATCH (p:Project)-[:CONTAINS]->(t:Task {name: $name}) RETURN p.id"
    proj_res = conn.execute(proj_query, {"name": source_name})
    if proj_res.has_next():
        project_id = proj_res.get_next()[0]
        conflicts = _recalculate_timeline(project_id)
        if conflicts:
            res += "\n" + "\n".join(conflicts)
              
    return res

@mcp.tool()
def update_estimates(task_name: str, optimistic: int, pessimistic: int) -> str:
    """Updates the 3-point estimates for a task's duration."""
    res = conn.execute("""
        MATCH (t:Task {name: $name})
        SET t.optimistic_duration = $opt, t.pessimistic_duration = $pess
        RETURN t.name
    """, {"name": task_name, "opt": optimistic, "pess": pessimistic})
    if res.has_next():
        return f"PERT estimates updated for task '{task_name}'."
    return f"Error: Task '{task_name}' not found."

@mcp.tool()
def run_pert_analysis(project_id: str) -> str:
    """
    Runs PERT analysis for all tasks in a project.
    Expected Duration = (Optimistic + 4*Most_Likely + Pessimistic) / 6
    """
    query = """
    MATCH (p:Project {id: $pid})-[:CONTAINS]->(t:Task)
    SET t.expected_duration = (CAST(t.optimistic_duration AS DOUBLE) + (4.0 * CAST(t.duration AS DOUBLE)) + CAST(t.pessimistic_duration AS DOUBLE)) / 6.0
    RETURN count(t)
    """
    res = conn.execute(query, {"pid": project_id})
    if res.has_next():
        count = res.get_next()[0]
        return f"PERT analysis complete for {count} tasks in project '{project_id}'."
    return f"No tasks found for project '{project_id}'."

@mcp.resource("project://{project_id}/reports/risk")
def get_risk_report(project_id: str) -> str:
    """Generates a PERT risk analysis report, highlighting high-variance tasks."""
    query = """
    MATCH (p:Project {id: $pid})-[:CONTAINS]->(t:Task)
    RETURN t.name, t.duration, t.optimistic_duration, t.pessimistic_duration, t.expected_duration
    """
    res = conn.execute(query, {"pid": project_id})
    
    tasks = []
    while res.has_next():
        row = res.get_next()
        name, m, o, p, e = row
        # Variance = ((P - O) / 6)^2
        variance = ((p - o) / 6.0)**2 if p is not None and o is not None else 0.0
        tasks.append({
            "name": name, "m": m, "o": o, "p": p, "e": e, "var": variance
        })
    
    if not tasks:
        return f"No task data found for project {project_id}."
        
    tasks.sort(key=lambda x: x["var"], reverse=True)
    
    report = f"# PERT Risk Analysis: Project {project_id} 🎲\n\n"
    report += "| Task | Most Likely | Optimistic | Pessimistic | Expected (PERT) | Variance |\n"
    report += "| :--- | :--- | :--- | :--- | :--- | :--- |\n"
    
    for t in tasks:
        e_str = f"{t['e']:.2f}" if t['e'] is not None else "N/A"
        report += f"| {t['name']} | {t['m']}d | {t['o']}d | {t['p']}d | {e_str}d | {t['var']:.2f} |\n"
        
    report += "\n### Risk Interpretation\n"
    report += "- **High Variance (> 1.0)**: High uncertainty. Task duration is unpredictable.\n"
    report += "- **Low Variance (< 0.2)**: High certainty. Task is well-understood.\n"
    
    return report

@mcp.tool()
def clone_scenario(source_project_id: str, new_scenario_id: str) -> str:
    """
    Clones a project, its tasks, dependencies, and resource assignments into a sandbox.
    Prefixes the task names with the new_scenario_id to maintain Primary Key uniqueness.
    """
    # 1. Create the new project clone
    query_proj = """
    MATCH (p:Project {id: $src})
    MERGE (new_p:Project {id: $dest, start_date: p.start_date, name: p.name + ' (Clone)'})
    RETURN new_p.id
    """
    res = conn.execute(query_proj, {"src": source_project_id, "dest": new_scenario_id})
    if not res.has_next():
        return f"Error: Source project '{source_project_id}' not found."

    # 2. Clone Tasks and CONTAINS edges
    query_tasks = """
    MATCH (p:Project {id: $src})-[:CONTAINS]->(t:Task)
    MATCH (new_p:Project {id: $dest})
    MERGE (new_t:Task {
        name: $dest + '_' + t.name, 
        description: t.description, 
        duration: t.duration, 
        optimistic_duration: t.optimistic_duration,
        pessimistic_duration: t.pessimistic_duration,
        expected_duration: t.expected_duration,
        cost: t.cost, 
        actual_cost: t.actual_cost,
        est_date: t.est_date, 
        eft_date: t.eft_date, 
        baseline_est_date: t.baseline_est_date,
        baseline_eft_date: t.baseline_eft_date,
        baseline_cost: t.baseline_cost,
        percent_complete: t.percent_complete,
        status: t.status,
        total_float: t.total_float,
        leveling_delay: t.leveling_delay
    })
    MERGE (new_p)-[:CONTAINS]->(new_t)
    """
    conn.execute(query_tasks, {"src": source_project_id, "dest": new_scenario_id})

    # 3. Clone DEPENDS_ON edges
    query_deps = """
    MATCH (p:Project {id: $src})-[:CONTAINS]->(s:Task)-[r:DEPENDS_ON]->(t:Task)
    MATCH (new_s:Task {name: $dest + '_' + s.name})
    MATCH (new_t:Task {name: $dest + '_' + t.name})
    MERGE (new_s)-[:DEPENDS_ON {lag: r.lag}]->(new_t)
    """
    conn.execute(query_deps, {"src": source_project_id, "dest": new_scenario_id})
      
    # 4. Clone WORKS_ON (Resource assignments)
    query_works = """
    MATCH (p:Project {id: $src})-[:CONTAINS]->(t:Task)<-[w:WORKS_ON]-(r:Resource)
    MATCH (new_t:Task {name: $dest + '_' + t.name})
    MERGE (r)-[:WORKS_ON {allocation: w.allocation}]->(new_t)
    """
    conn.execute(query_works, {"src": source_project_id, "dest": new_scenario_id})

    return f"Scenario cloned successfully. You can now safely test changes on project '{new_scenario_id}'."

@mcp.tool()
def export_to_kanban(project_id: str) -> str:
    """
    Exports project tasks in a JSON format compatible with Kanban systems (Jira/Trello).
    """
    query = """
    MATCH (p:Project {id: $pid})-[:CONTAINS]->(t:Task)
    OPTIONAL MATCH (t)<-[w:WORKS_ON]-(r:Resource)
    RETURN t.name, t.status, t.est_date, t.eft_date, collect(r.name), t.description
    """
    res = conn.execute(query, {"pid": project_id})
    
    cards = []
    while res.has_next():
        name, status, est, eft, r_names, desc = res.get_next()
        # Handle Kuzu's list aggregation 
        assignees = ", ".join([r for r in r_names if r]) if r_names else "Unassigned"
        
        cards.append({
            "title": name,
            "status": status,
            "start": est,
            "due": eft,
            "assignees": assignees,
            "description": desc
        })
    
    return json.dumps({"project_id": project_id, "cards": cards}, indent=2)

@mcp.tool()
def generate_briefing_webhook(project_id: str) -> str:
    """
    Generates a high-density Markdown briefing suitable for a Slack/Teams webhook.
    Combines Critical Path, Budget, and EVM data.
    """
    cp = get_critical_path(project_id)
    evm = get_evm_report(project_id)
    budget = get_budget_report(project_id)
    
    # Condensed version
    briefing = f"🚀 **Project Pulse: {project_id}**\n\n"
    
    # Extract SPI/CPI from EVM
    spi = re.search(r"SPI\)\*\*: ([\d\.]+)", evm)
    cpi = re.search(r"CPI\)\*\*: ([\d\.]+)", evm)
    
    briefing += "📊 **Metrics**\n"
    briefing += f"- SPI: {spi.group(1) if spi else '1.00'}\n"
    briefing += f"- CPI: {cpi.group(1) if cpi else '1.00'}\n\n"
    
    briefing += "🛤️ **Critical Path**\n"
    briefing += f"{cp}\n\n"
    
    briefing += "💰 **Budget Summary**\n"
    # Extract Total Budget from report
    total = re.search(r"\*\*TOTAL PROJECT BUDGET\*\* \| \| \| \*\*(\$[\d\.,]+)\*\*", budget)
    briefing += f"Total Forecast: {total.group(1) if total else 'Unknown'}\n"
    
    return briefing

@mcp.tool()
def generate_agent_sub_prompt(task_name: str) -> str:
    """
    Generates a specialized system prompt for a sub-agent to execute a specific task.
    Uses task metadata, dependencies, and required skills.
    """
    query = """
    MATCH (t:Task {name: $name})
    OPTIONAL MATCH (t)-[:REQUIRES_SKILL]->(s:Skill)
    RETURN t.description, t.duration, collect(s.name)
    """
    res = conn.execute(query, {"name": task_name})
    if not res.has_next():
        return f"Error: Task '{task_name}' not found."
    
    desc, dur, skills = res.get_next()
    skills_str = ", ".join(skills) if skills else "Generalist Skills"
    
    prompt = f"YOU ARE AN EXPERT AGENT specializing in: {skills_str}.\n"
    prompt += f"OBJECTIVE: Execute the task '{task_name}'.\n"
    prompt += f"SCOPE: {desc}\n"
    prompt += f"CONSTRAINTS: You have a hard deadline of {dur} working days.\n"
    prompt += "INSTRUCTION: Provide the implementation plan first, then execute only upon approval."
    
    return f"--- SUB-AGENT PROMPT ---\n{prompt}\n--- END PROMPT ---"

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
def auto_level_schedule(project_id: str) -> str:
    """
    Automatic Resource Leveler: Resolves resource over-allocations by shifting 
    tasks with positive float. Adheres to Law of Optimization.
    """
    shifts = []
    max_iterations = 20 # Prevent infinite loops
    
    for _ in range(max_iterations):
        # 1. Update dates and floats
        _recalculate_timeline(project_id)
        _calculate_float(project_id)
        
        # 2. Extract allocation conflicts
        # We reuse the logic from get_allocation_report but in a more machine-readable way
        res_query = """
        MATCH (p:Project {id: $pid})-[:CONTAINS]->(t:Task)<-[w:WORKS_ON]-(r:Resource)
        RETURN DISTINCT r.name
        """
        res_it = conn.execute(res_query, {"pid": project_id})
        resources = []
        while res_it.has_next():
            resources.append(res_it.get_next()[0])
        
        conflict_found = False
        for r_name in resources:
            query = """
            MATCH (r:Resource {name: $name})-[w:WORKS_ON]->(t:Task)
            MATCH (p:Project)-[:CONTAINS]->(t)
            RETURN t.name, t.est_date, t.eft_date, w.allocation, t.status, t.total_float, p.id
            """
            tasks_data = []
            assign_it = conn.execute(query, {"name": r_name})
            while assign_it.has_next():
                tasks_data.append(assign_it.get_next())
            
            # Sweep-line to find first conflict date
            events = []
            for t_name, est, eft, alloc, status, t_float, t_pid in tasks_data:
                # Priority 0 for START, 1 for END
                events.append((est, 0, alloc, t_name, "START", status, t_float, t_pid))
                # M1 Fix: Guard against None eft (same fix as other allocation functions)
                drop_date = None
                if eft:
                    try:
                        drop_date = str(np.busday_offset(eft, 1, roll='following'))
                    except Exception:
                        pass
                if not drop_date:
                    drop_date = est  # Immediate release fallback
                events.append((drop_date, 1, -alloc, t_name, "END", status, t_float, t_pid))
            
            events.sort()
            current_alloc = 0
            active_tasks = {} # name -> {status, float, pid}
            
            for i in range(len(events)):
                date, priority, delta, t_name, ev_type, status, t_float, t_pid = events[i]
                current_alloc += delta
                if ev_type == "START": active_tasks[t_name] = {"status": status, "float": t_float, "pid": t_pid}
                else: active_tasks.pop(t_name, None)
                
                if current_alloc > 100:
                    # Conflict at 'date'!
                    # Heuristic: Pick task with highest float that isn't locked or float=0
                    # IMPORTANT: We only shift tasks in the CURRENT project_id 
                    # to keep the solver focused, but we see conflicts from other projects.
                    candidates = [
                        (name, data["float"]) for name, data in active_tasks.items() 
                        if data["status"] != "HUMAN_LOCKED" and data["float"] > 0 and data["pid"] == project_id
                    ]
                    
                    if candidates:
                        # Sort by float descending
                        candidates.sort(key=lambda x: x[1], reverse=True)
                        target_task, current_float = candidates[0]
                        
                        # Apply 1-day delay (Defect 1 Fix)
                        # We increment the task's inherent leveling_delay instead of modifying edges.
                        # This works for all tasks, including root tasks.
                        conn.execute("""
                            MATCH (t:Task {name: $name})
                            SET t.leveling_delay = coalesce(t.leveling_delay, 0) + 1
                        """, {"name": target_task})
                        
                        shifts.append(f"Shifted '{target_task}' by 1 day to resolve {r_name} overload at {date}")
                        conflict_found = True
                        break # Recalculate everything
            
            if conflict_found: break
        
        if not conflict_found:
            break
            
    if not shifts:
        return "No automated shifts were necessary or possible (all conflicts might be on Critical Path or Locked)."
    
    return "Schedule Leveled Successfully:\n" + "\n".join(shifts)

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
    seeds_list = []  # H3: track seed tasks to anchor the forward order
    while seeds.has_next():
        name = seeds.get_next()[0]
        cp_tasks.add(name)
        stack.append(name)
        seeds_list.append(name)
        
    # Backward trace — collect CP tasks maintaining insertion order
    cp_ordered = []  # Will be built in reverse (project-end first)
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
                    cp_ordered.append(s_name)

    # H3 Fix: Output in topological (forward) order — reverse the backward trace
    # Seeds are endpoints, cp_ordered are their predecessors discovered backward
    # Reverse cp_ordered and append seeds at the end for correct forward order
    forward_path = list(reversed(cp_ordered)) + list(seeds_list)
    return f"Critical Path for {project_id}: " + " -> ".join(forward_path)

@mcp.tool()
def ping() -> str:
    """Health check tool to verify the MCP server is running and responsive."""
    return "pong: ProjectLogicEngine is online."

# ─── Phase 11: Entity Inspection Tools ────────────────────────────────────────

@mcp.tool()
def list_projects() -> str:
    """
    Lists all projects in the system as a Markdown table.
    Returns: | Project ID | Name | Start Date |
    """
    query = "MATCH (p:Project) RETURN p.id, p.name, p.start_date ORDER BY p.start_date"
    rows = []
    try:
        res = conn.execute(query)
        while res.has_next():
            rows.append(res.get_next())
    except Exception as e:
        return f"Kuzu Error: {e}"

    if not rows:
        return "No projects found."

    table = "| Project ID | Name | Start Date |\n|---|---|---|\n"
    for pid, name, start in rows:
        table += f"| {pid or '—'} | {name or '—'} | {start or '—'} |\n"
    return table


@mcp.tool()
def list_tasks(project_id: str = None) -> str:
    """
    Lists tasks as a Markdown table. If project_id is supplied, filters to that project only.
    Returns: | Task Name | Duration | Status | Start Date | End Date |
    """
    if project_id:
        query = """
        MATCH (p:Project {id: $pid})-[:CONTAINS]->(t:Task)
        RETURN t.name, t.duration, t.status, t.est_date, t.eft_date
        ORDER BY t.est_date
        """
        params = {"pid": project_id}
    else:
        query = """
        MATCH (t:Task)
        RETURN t.name, t.duration, t.status, t.est_date, t.eft_date
        ORDER BY t.est_date
        """
        params = {}

    rows = []
    try:
        res = conn.execute(query, params) if params else conn.execute(query)
        while res.has_next():
            rows.append(res.get_next())
    except Exception as e:
        return f"Kuzu Error: {e}"

    if not rows:
        return "No tasks found."

    table = "| Task Name | Duration (d) | Status | Start Date | End Date |\n|---|---|---|---|---|\n"
    for name, dur, status, es, ef in rows:
        table += f"| {name or '—'} | {dur or 0} | {status or '—'} | {es or '—'} | {ef or '—'} |\n"
    return table


@mcp.tool()
def list_resources() -> str:
    """
    Lists all registered resources (HUMAN and EQUIPMENT) as a Markdown table.
    Returns: | Resource Name | Type | Cost Rate |
    """
    query = "MATCH (r:Resource) RETURN r.name, r.type, r.cost_rate ORDER BY r.type, r.name"
    rows = []
    try:
        res = conn.execute(query)
        while res.has_next():
            rows.append(res.get_next())
    except Exception as e:
        return f"Kuzu Error: {e}"

    if not rows:
        return "No resources found."

    table = "| Resource Name | Type | Cost Rate |\n|---|---|---|\n"
    for name, rtype, rate in rows:
        rate_str = f"${rate:,.2f}/day" if rate is not None else "—"
        table += f"| {name or '—'} | {rtype or '—'} | {rate_str} |\n"
    return table


@mcp.tool()
def list_skills() -> str:
    """
    Lists all registered skills in the competency database as a Markdown table.
    Returns: | Skill Name | Description |
    """
    query = "MATCH (s:Skill) RETURN s.name, s.description ORDER BY s.name"
    rows = []
    try:
        res = conn.execute(query)
        while res.has_next():
            rows.append(res.get_next())
    except Exception as e:
        return f"Kuzu Error: {e}"

    if not rows:
        return "No skills found."

    table = "| Skill Name | Description |\n|---|---|\n"
    for name, desc in rows:
        table += f"| {name or '—'} | {desc or '—'} |\n"
    return table


@mcp.resource("system://info")
def get_system_info() -> str:
    """Returns basic server status."""
    return "Engine Status: Online | Phase 11 (Audit & Inspection) | Logic Engine Active"

@mcp.resource("system://constitution")
def get_constitution() -> str:
    """Returns the Symbolic Standard and Laws of Logic for the Project Engine."""
    constitution = """
# mcp-project-logic Constitution (Phase 11)

## 1. The Symbolic Standard
- SKILL Nodes: 🔨
- TASK Nodes: 🪏
- RESOURCE Nodes: 👤
- CALENDAR/DATES: 📅
- RISK/PERT Nodes: 🎲
- FLOAT/SLACK: 〰️

## 2. Fundamental Logic & States
- Law I: The Law of Non-Circularity (No cycles)
- Law II: The Law of Temporal Sequence (Working day calendar)
- Law III: The Law of Financial Tracking (Cost summation)
- Law IV: The Law of Optimization (AI may shift AI_DRAFT tasks within their Total Float to resolve conflicts)
- Law V: The Law of Transparency (All system entities must be inspectable via dedicated listing tools)

## 3. State Monitors
- Resource Integrity: Verify resource existence and skill possession.
- Allocation Check: Monitor for >100% resource load across date windows.
    """
    return constitution

if __name__ == "__main__":
    # By default, mcp.run() uses stdio transport
    mcp.run()
