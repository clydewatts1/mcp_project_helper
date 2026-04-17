import os
import re
import json
import base64
import datetime
import graphviz
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import io
import kuzu
import sys
from collections import deque
from mcp.server.fastmcp import FastMCP

# Resolve absolute path for database
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Set to "" for in-memory mode, or an absolute path for persistent storage
DEFAULT_DB_PATH = os.getenv("KUZU_DB_PATH", "")

# Initialize FastMCP
mcp = FastMCP("ProjectLogicEngine")

@mcp.tool()
def export_project_image_tool(project_id: str) -> str:
    """
    Generates a Base64 PNG of the Graphviz network diagram. 
    Call this to visually export and view the project state.
    """
    try:
        result = get_project_graph(project_id) # Call your existing function
        if isinstance(result, dict) and "data" in result:
            return create_response(
                operation="export_project_image", 
                status="success", 
                data={"image_base64": result["data"], "format": "png"}
            )
        return create_response("export_project_image", "error", warnings=[str(result)])
    except Exception as e:
        return create_response("export_project_image", "error", warnings=[f"Failed to generate image: {str(e)}"])

def create_response(operation: str, status: str, data: dict = None, warnings: list = None) -> str:
    """
    Standardized JSON envelope for all MCP tool responses.
    Status should be 'success', 'warning', or 'error'.
    """
    response = {
        "status": status,
        "operation": operation,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "affected_rows": data.get("count", 1) if data else 0,
        "warnings": warnings or [],
        "data": data or {}
    }
    return json.dumps(response, indent=2)

# Database State (Lazy Init)
db = None
conn = None

def get_db_connection():
    """Lazily initializes and returns the database connection."""
    global db, conn
    if db is None:
        db_path = DEFAULT_DB_PATH
        import time as _time
        max_retries = 5
        retry_delay = 1.0
        
        for attempt in range(max_retries):
            try:
                db = kuzu.Database(db_path)
                conn = kuzu.Connection(db)
                break
            except Exception as e:
                if "Could not set lock on file" in str(e) and attempt < max_retries - 1:
                    print(f"DATABASE LOCKED (Attempt {attempt+1}/{max_retries}). Retrying in {retry_delay}s...", file=sys.stderr)
                    _time.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                # Print to stderr to avoid breaking MCP JSON-RPC protocol
                print(f"FAILED TO INIT KUZU AT {db_path}: {e}", file=sys.stderr)
                raise
    return db, conn

def initialize_schema():
    """Initializes the database schema with Project, Task, and Relationship tables."""
    _, conn = get_db_connection()
    # Node Tables
    node_queries = [
        "CREATE NODE TABLE Project (id STRING, start_date STRING, name STRING, PRIMARY KEY (id))",
        "CREATE NODE TABLE Task (name STRING, description STRING, duration INT, optimistic_duration INT, pessimistic_duration INT, expected_duration DOUBLE, cost DOUBLE, actual_cost DOUBLE, est_date STRING, eft_date STRING, status STRING, baseline_est_date STRING, baseline_eft_date STRING, baseline_cost DOUBLE, percent_complete INT, total_float INT, leveling_delay INT, PRIMARY KEY (name))",
        "CREATE NODE TABLE Resource (name STRING, description STRING, type STRING, cost_rate DOUBLE, PRIMARY KEY (name))",
        "CREATE NODE TABLE Skill (name STRING, description STRING, PRIMARY KEY (name))",
        "CREATE NODE TABLE CustomReport (name STRING, description STRING, cypher_query STRING, last_error STRING, PRIMARY KEY (name))",
        "CREATE NODE TABLE Holiday (date STRING, description STRING, PRIMARY KEY (date))"
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
        "ALTER TABLE Task ADD leveling_delay INT DEFAULT 0",
        "ALTER TABLE Task ADD project_id STRING",
        "ALTER TABLE Task ADD pert_std_dev DOUBLE",
        "ALTER TABLE Task ADD pert_variance DOUBLE",
        "CREATE INDEX IF NOT EXISTS ON Task(project_id)",
        "CREATE INDEX IF NOT EXISTS ON Task(status)",
        "CREATE INDEX IF NOT EXISTS ON Resource(type)"
    ]
    
    for q in migration_queries:
        try:
            conn.execute(q)
        except:
            pass

    try:
        conn.execute("MATCH (p:Project)-[:CONTAINS]->(t:Task) WHERE t.project_id IS NULL SET t.project_id = p.id")
    except Exception:
        pass

# Note: initialize_schema() is now called in the __main__ block to prevent accidental DB locking on import.

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
        error_msg = str(e)
        if len(error_msg) > 200:
            error_msg = error_msg[:200] + "... [TRUNCATED]"
        return f"Database Error: {error_msg}. Please check your tool arguments and try again."

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
    
    # 1.1 Fetch Global Holidays
    hol_res = conn.execute("MATCH (h:Holiday) RETURN h.date")
    holidays = []
    while hol_res.has_next():
        holidays.append(np.datetime64(hol_res.get_next()[0]))
    holidays = np.array(holidays, dtype='datetime64[D]')

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
        candidate_dates = [np.busday_offset(project_start_date, 0, roll='following', holidays=holidays)]
        
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
            
            start_candidate = np.busday_offset(ref_eft, 1 + pred["lag"], roll='following', holidays=holidays)
            candidate_dates.append(start_candidate)
            
        proposed_est = max(candidate_dates)
        
        # Apply leveling_delay (Defect 1 fix)
        if task["delay"] > 0:
            proposed_est = np.busday_offset(proposed_est, task["delay"], roll='following', holidays=holidays)
        
        if task["status"] == "HUMAN_LOCKED" and task["est"]:
            actual_est = np.datetime64(task["est"])
            if proposed_est > actual_est:
                critical_conflicts.append(f"[CRITICAL CONFLICT] Task '{name}' is locked at {task['est']} but dependencies push it to {proposed_est}")
            task_dates[name] = {"est": task["est"], "eft": task["eft"], "locked": True}
        else:
            eft = np.busday_offset(proposed_est, task["duration"] - 1, roll='following', holidays=holidays)
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
    successor_pids = []
    successor_projects_res = conn.execute("""
        MATCH (p_s:Project {id: $id})-[:CONTAINS]->(s:Task)-[:DEPENDS_ON]->(t:Task)<-[:CONTAINS]-(p_t:Project)
        WHERE p_s.id <> p_t.id
        RETURN DISTINCT p_t.id
    """, {"id": project_id})
    
    while successor_projects_res.has_next():
        successor_pids.append(successor_projects_res.get_next()[0])
    
    for target_pid in successor_pids:
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
        return create_response("lock_task", "success", data={"task": task_name, "status": "HUMAN_LOCKED"})
    return create_response("lock_task", "error", warnings=[f"Task '{task_name}' not found."])

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
        if count == 0:
            return create_response("baseline_project", "warning", warnings=[f"No tasks found for project '{project_id}'."])
        return create_response("baseline_project", "success", data={"project_id": project_id, "count": count})
    return create_response("baseline_project", "error", warnings=[f"Project '{project_id}' not found."])

@mcp.tool()
def set_task_progress(task_name: str, percent_complete: int, skip_recalc: bool = False) -> str:
    """Updates completion percentage (0-100) and automatically transitions the status."""
    if not (0 <= percent_complete <= 100): 
        return create_response("set_task_progress", "error", warnings=["percent_complete must be 0-100."])
    
    status = "IN_PROGRESS"
    if percent_complete == 100: status = "DONE"
    elif percent_complete == 0: status = "AI_DRAFT"
    
    res = conn.execute("""
        MATCH (t:Task {name: $name})
        SET t.percent_complete = $pct, t.status = $status
        RETURN t.name
    """, {"name": task_name, "pct": percent_complete, "status": status})
    
    if res.has_next(): 
        return create_response("set_task_progress", "success", data={"task": task_name, "percent": percent_complete, "status": status})
    return create_response("set_task_progress", "error", warnings=[f"Task '{task_name}' not found."])

@mcp.tool()
def update_task(task_name: str, duration: int = None, cost: float = None, description: str = None) -> str:
    """Updates an existing task's attributes. Only pass the values you want to change."""
    updates = []
    params = {"name": task_name}
    if duration is not None:
        updates.append("t.duration = $duration")
        params["duration"] = int(duration)
    if cost is not None:
        updates.append("t.cost = $cost")
        params["cost"] = float(cost)
    if description is not None:
        updates.append("t.description = $desc")
        params["desc"] = description
        
    if not updates:
        return create_response("update_task", "warning", warnings=["No updates provided."])
        
    query = f"MATCH (t:Task {{name: $name}}) SET {', '.join(updates)} RETURN t.name"
    res = conn.execute(query, params)
    
    if not res.has_next():
        return create_response("update_task", "error", warnings=[f"Task '{task_name}' not found."])
    
    warnings = []
    # Recalculate timeline if duration changed
    if duration is not None:
        proj_res = conn.execute("MATCH (t:Task {name: $name}) RETURN t.project_id", {"name": task_name})
        if proj_res.has_next():
            pid = proj_res.get_next()[0]
            conflicts = _recalculate_timeline(pid)
            if conflicts:
                warnings.extend(conflicts)
            
    status = "warning" if warnings else "success"
    return create_response("update_task", status, data={"task": task_name}, warnings=warnings)


# ─── Advanced Agentic PM Tools (Phase 18) ───────────────────────────────────

@mcp.tool()
def get_project_delta(project_id: str) -> str:
    """Returns ONLY the tasks that have slipped their baseline schedule or budget."""
    query = """
    MATCH (p:Project {id: $pid})-[:CONTAINS]->(t:Task)
    WHERE (t.est_date > t.baseline_est_date) OR (t.actual_cost > t.baseline_cost)
    RETURN t.name, t.est_date, t.baseline_est_date, t.actual_cost, t.baseline_cost
    """
    res = conn.execute(query, {"pid": project_id})
    table = "| Task | Current Start | Baseline Start | Actual Cost | Baseline Cost |\n|---|---|---|---|---|\n"
    count = 0
    while res.has_next():
        row = res.get_next()
        table += f"| {row[0]} | {row[1]} | {row[2]} | ${row[3] or 0} | ${row[4] or 0} |\n"
        count += 1
    if count == 0: return "No deviations from baseline detected."
    return table

@mcp.tool()
def semantic_task_search(keyword: str) -> str:
    """Searches task names and descriptions across the database for a keyword."""
    # Using simple CONTAINS for broad matching
    query = """
    MATCH (p:Project)-[:CONTAINS]->(t:Task)
    WHERE t.name CONTAINS $kw OR t.description CONTAINS $kw
    RETURN p.id, t.name, t.description, t.status
    """
    res = conn.execute(query, {"kw": keyword})
    table = "| Project | Task | Description | Status |\n|---|---|---|---|\n"
    count = 0
    while res.has_next():
        row = res.get_next()
        table += f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} |\n"
        count += 1
    if count == 0: return f"No tasks found matching keyword '{keyword}'."
    return table



@mcp.tool()
def update_task_actual_cost(task_name: str, actual_cost: float) -> str:
    """Updates the actual cost spent on a task so far."""
    res = conn.execute("""
        MATCH (t:Task {name: $name})
        SET t.actual_cost = $cost
        RETURN t.name
    """, {"name": task_name, "cost": actual_cost})
    if res.has_next():
        return create_response("update_task_actual_cost", "success", data={"task": task_name, "actual_cost": actual_cost})
    return create_response("update_task_actual_cost", "error", warnings=[f"Task '{task_name}' not found."])

def get_evm_report_internal(project_id: str, as_of_date: str = None) -> str:
    """
    Generates an Earned Value Management (EVM) report.
    Calculates PV, EV, AC, SPI, and CPI.
    Use as_of_date (YYYY-MM-DD) to calculate Planned Value relative to a future/past date.
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
    
    if as_of_date:
        today = np.datetime64(as_of_date)
    else:
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
            "pct": pct,
            "b_cost": b_cost
        })

    if not tasks_stats:
        return f"No activities found in project {project_id}."

    spi = total_ev / total_pv if total_pv > 0 else 1.0
    cpi = total_ev / total_ac if total_ac > 0 else 1.0
    
    # NEW FORECAST MATH (Phase 22)
    total_bac = sum(s['b_cost'] for s in tasks_stats)
    eac = total_bac / cpi if cpi > 0 else total_bac + total_ac
    vac = total_bac - eac
    
    report = f"# EVM Report: Project {project_id} ({today})\n\n"
    report += f"- **Total Planned Value (PV)**: ${total_pv:,.2f}\n"
    report += f"- **Total Earned Value (EV)**: ${total_ev:,.2f}\n"
    report += f"- **Total Actual Cost (AC)**: ${total_ac:,.2f}\n"
    report += f"- **Budget At Completion (BAC)**: ${total_bac:,.2f}\n\n"
    
    report += "### 🔮 Forecasting Metrics\n"
    report += f"- **Estimate At Completion (EAC)**: ${eac:,.2f} *(Expected final cost based on current CPI)*\n"
    report += f"- **Variance At Completion (VAC)**: ${vac:,.2f} "
    report += "(Expected Overage)" if vac < 0 else "(Expected Savings)"
    report += "\n\n"
    
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
        
        i = 0
        while i < len(events):
            current_date = events[i][0]
            # Process all events for the current date
            while i < len(events) and events[i][0] == current_date:
                date, priority, delta, task_label, event_type = events[i]
                current_alloc += delta
                if event_type == "START": active_tasks.add(task_label)
                else: active_tasks.discard(task_label)
                i += 1
            
            if current_alloc > 100:
                # Find the next date in events or use "End of Project"
                next_date = events[i][0] if i < len(events) else "Project End"
                if next_date != current_date:
                    conflict_windows.append({
                        "window": f"{current_date} to {next_date}",
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
        # print(f"DEBUG Resource {resource_name} events: {events}")
        
        # Process events by date
        current_alloc = 0
        max_alloc = 0
        
        i = 0
        while i < len(events):
            current_date = events[i][0]
            # Process all events for the current date before checking max_alloc
            while i < len(events) and events[i][0] == current_date:
                current_alloc += events[i][2]
                i += 1
            # Check after processing all events for this date
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
    
    node_ids = {}
    
    while task_res.has_next():
        name, dur, cost = task_res.get_next()
        node_id = f"node_{len(node_ids)}"
        node_ids[name] = node_id
        label = f"{name}\n({dur}d | ${cost:,.0f})"
        dot.node(node_id, label)
        
    # 3. Fetch all dependencies
    dep_res = conn.execute("""
        MATCH (p:Project {id: $id})-[:CONTAINS]->(s:Task)-[r:DEPENDS_ON]->(t:Task)
        RETURN s.name, t.name, r.lag
    """, {"id": project_id})
    
    while dep_res.has_next():
        s, t, lag = dep_res.get_next()
        if s in node_ids and t in node_ids:
            label = f"lag={lag}" if lag > 0 else ""
            dot.edge(node_ids[s], node_ids[t], label=label)
        
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
    
    node_ids = {}
    import html
    
    while task_res.has_next():
        name, dur, es, ef, f = task_res.get_next()
        node_id = f"node_{len(node_ids)}"
        node_ids[name] = node_id
        # ES/EF are strings YYYY-MM-DD, let's just use MM-DD for brevity in the chart
        es_short = es[-5:] if es else "N/A"
        ef_short = ef[-5:] if ef else "N/A"
        
        float_color = "red" if (f is not None and f <= 0) else "black"
        penwidth = "3" if float_color == "red" else "1"
        
        # HTML label for structured PERT node
        safe_name = html.escape(name)
        label = f'''<<TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0">
            <TR><TD COLSPAN="3"><B>{safe_name}</B></TD></TR>
            <TR>
                <TD BGCOLOR="#EEEEEE">{es_short}</TD>
                <TD>{dur}d</TD>
                <TD BGCOLOR="#EEEEEE">{ef_short}</TD>
            </TR>
            <TR><TD COLSPAN="3" PORT="f">Float: {f if f is not None else '?'}</TD></TR>
        </TABLE>>'''
        
        dot.node(node_id, label=label, shape='none', color=float_color, penwidth=penwidth)
        
    # 3. Dependencies
    dep_res = conn.execute("""
        MATCH (p:Project {id: $id})-[:CONTAINS]->(s:Task)-[r:DEPENDS_ON]->(t:Task)
        RETURN s.name, t.name, s.total_float, t.total_float
    """, {"id": project_id})
    
    while dep_res.has_next():
        s, t, sf, tf = dep_res.get_next()
        if s in node_ids and t in node_ids:
            # Highlight edge if both tasks are on critical path
            ecolor = "red" if (sf == 0 and tf == 0) else "black"
            ewith = "2" if ecolor == "red" else "1"
            dot.edge(node_ids[s], node_ids[t], color=ecolor, penwidth=ewith)
        
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
        return create_response("create_project", "error", warnings=[f"Invalid date format: {start_date}."])
    
    query = """
    MERGE (p:Project {id: $id})
    SET p.start_date = $start_date, p.name = $name
    RETURN p.id
    """
    params = {"id": project_id, "start_date": start_date, "name": name}
    conn.execute(query, params)
    return create_response("create_project", "success", data={"project_id": project_id, "name": name, "start_date": start_date})

@mcp.tool()
def add_task(project_id: str, name: str, duration, cost, description: str = "", optimistic: int = None, pessimistic: int = None, skip_recalc: bool = False) -> str:
    """
    Adds a task to a project and initializes its dates and PERT estimates.
    """
    try:
        duration = int(duration)
        cost = float(cost)
    except ValueError:
        return create_response("add_task", "error", warnings=["duration must be integer, cost must be number."])

    # Default PERT estimates to the provided duration if not specified
    opt = optimistic if optimistic is not None else duration
    pess = pessimistic if pessimistic is not None else duration
    
    # MERGE on name (PK) only, then SET all other properties to avoid duplicate nodes
    query = """
    MATCH (p:Project {id: $project_id})
    MERGE (t:Task {name: $name})
    SET t.project_id = $project_id,
        t.description = $description,
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
    res = conn.execute(query, params)
    if not res.has_next():
         return create_response("add_task", "error", warnings=[f"Project '{project_id}' not found. Create project first."])
         
    if not skip_recalc:
        conflicts = _recalculate_timeline(project_id)
        status = "warning" if conflicts else "success"
    else:
        conflicts = []
        status = "success"
    
    return create_response(
        operation="add_task",
        status=status,
        data={"task": name, "project": project_id},
        warnings=conflicts
    )

@mcp.tool()
def create_dependency(source_name: str, target_name: str = None, target_names: list = None, lag: int = 0, skip_recalc: bool = False) -> str:
    """
    Creates a dependency between two tasks. 
    CRITICAL: You MUST ensure BOTH tasks exist before calling this.
    source_name: The task that must finish first.
    target_name: The task that waits for the source to finish.
    lag: Wait time in working days. Use 0 by default.
    """
    # Fan-out: handle list form defensively
    if target_name is None and target_names:
        results = []
        all_warnings = []
        for t in target_names:
            res_str = create_dependency(source_name=source_name, target_name=t, lag=lag, skip_recalc=skip_recalc)
            res_json = json.loads(res_str)
            if res_json.get("status") == "error":
                return res_str # Bubble up hard errors during fan-out
            results.append(res_json.get("data", {}))
            all_warnings.extend(res_json.get("warnings", []))
        
        status = "warning" if all_warnings else "success"
        return create_response("create_dependency", status, data={"source": source_name, "dependencies": results}, warnings=all_warnings)
        
    if target_name is None:
        return create_response("create_dependency", "error", warnings=["target_name is required."])

    # Validate node existence
    s_id = conn.execute("MATCH (t:Task {name: $name}) RETURN count(*)", {"name": source_name}).get_next()[0]
    if s_id == 0:
        return create_response("create_dependency", "error", warnings=[f"Source task '{source_name}' not found."])
        
    t_id = conn.execute("MATCH (t:Task {name: $name}) RETURN count(*)", {"name": target_name}).get_next()[0]
    if t_id == 0:
        return create_response("create_dependency", "error", warnings=[f"Target task '{target_name}' not found."])

    # Gate 1: Cycle Check
    check_query = "MATCH path=(t:Task {name: $target_name})-[*]->(s:Task {name: $source_name}) RETURN nodes(path)"
    try:
        check_res = conn.execute(check_query, {"source_name": source_name, "target_name": target_name})
        if check_res.has_next():
            nodes = check_res.get_next()[0]
            try:
                path_names = [n['name'] for n in nodes]
            except (TypeError, KeyError):
                path_names = [getattr(n, 'name', str(n)) for n in nodes]
                
            return create_response(
                operation="create_dependency",
                status="error",
                data={"cycle_path": path_names},
                warnings=["Law I Violation: Circular Dependency Detected."]
            )
    except Exception as e:
         return create_response("create_dependency", "error", warnings=[f"Kuzu Error in cycle check: {str(e)}"])

    # Gate 2: Create Edge (Idempotent MERGE + SET pattern)
    query = """
    MATCH (a:Task {name: $source_name}), (b:Task {name: $target_name})
    MERGE (a)-[r:DEPENDS_ON]->(b)
    SET r.lag = $lag
    RETURN count(r)
    """
    conn.execute(query, {"source_name": source_name, "target_name": target_name, "lag": lag})
      
    # Trigger recalculation
    proj_query = "MATCH (p:Project)-[:CONTAINS]->(t:Task {name: $name}) RETURN p.id"
    proj_res = conn.execute(proj_query, {"name": source_name})
    conflicts = []
    if not skip_recalc and proj_res.has_next():
        project_id = proj_res.get_next()[0]
        conflicts = _recalculate_timeline(project_id)
              
    status = "warning" if conflicts else "success"
    return create_response(
        operation="create_dependency",
        status=status,
        data={"source": source_name, "target": target_name, "lag": lag},
        warnings=conflicts
    )

@mcp.tool()
def update_estimates(task_name: str, optimistic: int, pessimistic: int) -> str:
    """Updates the 3-point estimates for a task's duration."""
    res = conn.execute("""
        MATCH (t:Task {name: $name})
        SET t.optimistic_duration = $opt, t.pessimistic_duration = $pess
        RETURN t.name
    """, {"name": task_name, "opt": optimistic, "pess": pessimistic})
    if res.has_next():
        return create_response("update_estimates", "success", data={"task": task_name, "optimistic": optimistic, "pessimistic": pessimistic})
    return create_response("update_estimates", "error", warnings=[f"Task '{task_name}' not found."])

@mcp.tool()
def run_pert_analysis(project_id: str) -> str:
    """
    Runs PERT analysis for all tasks in a project.
    Expected Duration = (Optimistic + 4*Most_Likely + Pessimistic) / 6
    """
    query = """
    MATCH (p:Project {id: $pid})-[:CONTAINS]->(t:Task)
    WITH t, 
         (CAST(t.optimistic_duration AS DOUBLE) + (4.0 * CAST(t.duration AS DOUBLE)) + CAST(t.pessimistic_duration AS DOUBLE)) / 6.0 AS expected,
         (CAST(t.pessimistic_duration AS DOUBLE) - CAST(t.optimistic_duration AS DOUBLE)) / 6.0 AS std_dev
    SET t.expected_duration = expected,
        t.pert_std_dev = std_dev,
        t.pert_variance = std_dev * std_dev
    RETURN count(t)
    """
    res = conn.execute(query, {"pid": project_id})
    if res.has_next():
        count = res.get_next()[0]
        if count == 0:
            return create_response("run_pert_analysis", "warning", warnings=[f"No tasks found for project '{project_id}'."])
            
        conflicts = _recalculate_timeline(project_id)
        status = "warning" if conflicts else "success"
        return create_response("run_pert_analysis", status, data={"project_id": project_id, "tasks_analyzed": count}, warnings=conflicts)
    return create_response("run_pert_analysis", "error", warnings=[f"Project '{project_id}' not found."])

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
    MERGE (new_s)-[new_r:DEPENDS_ON]->(new_t)
    SET new_r.lag = r.lag
    """
    conn.execute(query_deps, {"src": source_project_id, "dest": new_scenario_id})
      
    # 4. Clone WORKS_ON (Resource assignments)
    query_works = """
    MATCH (p:Project {id: $src})-[:CONTAINS]->(t:Task)<-[w:WORKS_ON]-(r:Resource)
    MATCH (new_t:Task {name: $dest + '_' + t.name})
    MERGE (r)-[new_w:WORKS_ON]->(new_t)
    SET new_w.allocation = w.allocation
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
    evm = get_evm_report_internal(project_id)
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
def add_resource(name: str, resource_type: str, cost_rate, description: str = "") -> str:
    """
    Adds a resource (HUMAN or EQUIPMENT) to the engine.
    cost_rate must be a positive number (e.g. 100.0). If a string like '$100/day' is
    passed, the engine will attempt to extract the numeric portion automatically.
    """
    if resource_type.upper() not in ["HUMAN", "EQUIPMENT"]:
        return create_response("add_resource", "error", warnings=[f"Invalid resource_type: {resource_type}. Must be HUMAN or EQUIPMENT."])
    
    # Defensive coercion: strip currency symbols, commas, units (e.g. '$100/day' -> 100.0)
    if isinstance(cost_rate, str):
        import re as _re
        cleaned = _re.sub(r"[^\d.]", "", cost_rate.split("/")[0])
        try:
            cost_rate = float(cleaned)
        except ValueError:
            return create_response("add_resource", "error", warnings=[f"cost_rate '{cost_rate}' could not be parsed as a number."])
    
    query = "MERGE (r:Resource {name: $name, type: $type, cost_rate: $cost_rate, description: $description})"
    params = {"name": name, "type": resource_type.upper(), "cost_rate": float(cost_rate), "description": description}
    conn.execute(query, params)
    return create_response("add_resource", "success", data={"resource": name, "type": resource_type.upper()})

@mcp.tool()
def add_skill(name: str, description: str = "") -> str:
    """
    Adds a skill to the competency database.
    """
    query = "MERGE (s:Skill {name: $name, description: $description})"
    params = {"name": name, "description": description}
    conn.execute(query, params)
    return create_response("add_skill", "success", data={"skill": name})

@mcp.tool()
def grant_skill(resource_name: str, skill_name: str, proficiency: str = "Intermediate") -> str:
    """
    Grants a skill to a resource.
    """
    s_exists = conn.execute("MATCH (s:Skill {name: $name}) RETURN count(*)", {"name": skill_name}).get_next()[0]
    if s_exists == 0:
        return create_response("grant_skill", "error", warnings=[f"Skill '{skill_name}' not found."])
        
    r_exists = conn.execute("MATCH (r:Resource {name: $name}) RETURN count(*)", {"name": resource_name}).get_next()[0]
    if r_exists == 0:
        return create_response("grant_skill", "error", warnings=[f"Resource '{resource_name}' not found."])

    query = """
    MATCH (r:Resource {name: $resource_name}), (s:Skill {name: $skill_name})
    MERGE (r)-[h:HAS_SKILL]->(s)
    SET h.proficiency = $proficiency
    RETURN h.proficiency
    """
    params = {"resource_name": resource_name, "skill_name": skill_name, "proficiency": proficiency}
    conn.execute(query, params)
    return create_response("grant_skill", "success", data={"resource": resource_name, "skill": skill_name, "proficiency": proficiency})

@mcp.tool()
def require_skill(task_name: str, skill_name: str) -> str:
    """
    Requires a skill for a specific task.
    """
    s_exists = conn.execute("MATCH (s:Skill {name: $name}) RETURN count(*)", {"name": skill_name}).get_next()[0]
    if s_exists == 0:
        return create_response("require_skill", "error", warnings=[f"Skill '{skill_name}' not found."])
        
    t_exists = conn.execute("MATCH (t:Task {name: $name}) RETURN count(*)", {"name": task_name}).get_next()[0]
    if t_exists == 0:
        return create_response("require_skill", "error", warnings=[f"Task '{task_name}' not found."])

    query = """
    MATCH (t:Task {name: $task_name}), (s:Skill {name: $skill_name})
    MERGE (t)-[r:REQUIRES_SKILL]->(s)
    RETURN count(r)
    """
    params = {"task_name": task_name, "skill_name": skill_name}
    conn.execute(query, params)
    return create_response("require_skill", "success", data={"task": task_name, "skill": skill_name})

@mcp.tool()
def assign_resource(resource_name: str, task_name: str = None, task_names: list = None, allocation: int = 100) -> str:
    """
    Assigns a resource to a task with a specified allocation percentage.
    Checks for skill mismatches and over-allocation.
    If multiple tasks are passed via task_names (list), each is processed in sequence.
    """
    # Defensive coercion for allocation (handle cases where LLM passes "100")
    try:
        if isinstance(allocation, str):
            allocation = allocation.replace("%", "")
        allocation = int(allocation)
    except ValueError:
        return "Error: allocation must be a whole number between 1 and 100."

    # Fan-out: handle list form defensively
    if task_name is None and task_names:
        results = []
        all_warnings = []
        for t in task_names:
            # Recursive call returns a JSON string, we parse it to aggregate
            res_str = assign_resource(resource_name=resource_name, task_name=t, allocation=allocation)
            res_json = json.loads(res_str)
            results.append(res_json.get("data", {}))
            all_warnings.extend(res_json.get("warnings", []))
        
        status = "warning" if all_warnings else "success"
        return create_response("assign_resource", status, data={"resource": resource_name, "assignments": results}, warnings=all_warnings)
        
    if task_name is None:
        return create_response("assign_resource", "error", warnings=["task_name is required."])

    # 1. Gate 1: Strict existence check
    res_node = conn.execute("MATCH (r:Resource {name: $name}) RETURN count(*)", {"name": resource_name})
    res_exists = res_node.get_next()[0] 
    
    task_node = conn.execute("MATCH (t:Task {name: $name}) RETURN count(*)", {"name": task_name})
    task_exists = task_node.get_next()[0]
    
    if res_exists == 0:
        return create_response("assign_resource", "error", warnings=[f"Resource '{resource_name}' not found."])
    if task_exists == 0:
        return create_response("assign_resource", "error", warnings=[f"Task '{task_name}' not found."])

    # 2. Execute Assignment
    assign_query = """
    MATCH (r:Resource {name: $r}), (t:Task {name: $t})
    MERGE (r)-[w:WORKS_ON]->(t)
    SET w.allocation = $allocation
    RETURN w.allocation
    """
    conn.execute(assign_query, {"r": resource_name, "t": task_name, "allocation": allocation})
    
    warnings = []
    
    # 3. State Monitor A: Skill Check
    req_query = "MATCH (t:Task {name: $t})-[:REQUIRES_SKILL]->(s:Skill) RETURN s.name"
    has_query = "MATCH (r:Resource {name: $r})-[h:HAS_SKILL]->(s:Skill) RETURN s.name, h.proficiency"
    
    required_it = conn.execute(req_query, {"t": task_name})
    required_skills = set()
    while required_it.has_next():
        required_skills.add(required_it.get_next()[0])
        
    if required_skills:
        possessed_it = conn.execute(has_query, {"r": resource_name})
        possessed_skills = {} # name -> proficiency
        while possessed_it.has_next():
            row = possessed_it.get_next()
            possessed_skills[row[0]] = row[1]
            
        missing = required_skills - set(possessed_skills.keys())
        if missing:
            warnings.append(f"Skill Mismatch: {resource_name} lacks required skills for {task_name}: {', '.join(missing)}.")
        else:
            # Check proficiency levels (Defaulting requirement to Intermediate)
            rank = {"Beginner": 1, "Intermediate": 2, "Expert": 3}
            for skill in required_skills:
                p_level = possessed_skills.get(skill, "Beginner")
                if rank.get(p_level, 0) < rank["Intermediate"]:
                    warnings.append(f"Proficiency Warning: {resource_name} is only '{p_level}' in {skill} (Task recommends at least Intermediate).")
                else:
                    # Optional: Info about proficiency
                    pass
            
    # 4. State Monitor B: Over-allocation Check
    over_alloc_msg = _check_over_allocation(resource_name)
    if over_alloc_msg:
        warnings.append(over_alloc_msg)
        
    # 5. Return JSON
    status = "warning" if warnings else "success"
    return create_response(
        operation="assign_resource",
        status=status,
        data={"resource": resource_name, "task": task_name, "allocation": allocation},
        warnings=warnings
    )

@mcp.tool()
def unassign_resource(resource_name: str, task_name: str) -> str:
    """Removes a resource assignment from a task."""
    query = """
    MATCH (r:Resource {name: $r_name})-[w:WORKS_ON]->(t:Task {name: $t_name})
    DELETE w
    RETURN count(w)
    """
    try:
        res = conn.execute(query, {"r_name": resource_name, "t_name": task_name})
        if res.has_next() and res.get_next()[0] > 0:
            return create_response("unassign_resource", "success", data={"resource": resource_name, "task": task_name})
        return create_response("unassign_resource", "warning", warnings=["Assignment not found."])
    except Exception as e:
        return create_response("unassign_resource", "error", warnings=[str(e)])

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
    Fixes resource over-allocations automatically.
    Call this IMMEDIATELY if an assign_resource tool returns an "[WARNING: Over-allocation]" message.
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
            
            i = 0
            while i < len(events):
                current_date = events[i][0]
                while i < len(events) and events[i][0] == current_date:
                    date, priority, delta, t_name, ev_type, status, t_float, t_pid = events[i]
                    current_alloc += delta
                    if ev_type == "START": active_tasks[t_name] = {"status": status, "float": t_float, "pid": t_pid}
                    else: active_tasks.pop(t_name, None)
                    i += 1
                
                if current_alloc > 100:
                    # Conflict at 'current_date'!
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
        return create_response("auto_level_schedule", "success", data={"project_id": project_id}, warnings=["No automated shifts were necessary or possible."])
    
    return create_response(
        operation="auto_level_schedule",
        status="success",
        data={
            "project_id": project_id,
            "shifts_count": len(shifts),
            "summary": shifts
        }
    )

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


# ─── Phase 12: Dependency Impact & Traceability ───────────────────────────────

@mcp.tool()
def get_task_children(task_name: str, depth: int = 1, include_resources: bool = False) -> str:
    """
    Returns a list of downstream dependent tasks (children) up to a specified depth.
    Depth 1 = direct children. Depth 2 = children and grandchildren.
    """
    depth = max(1, min(depth, 10)) # Bound between 1 and 10
    
    if include_resources:
        query = f"""
        MATCH (t:Task {{name: $name}})-[e:DEPENDS_ON*1..{depth}]->(child:Task)
        OPTIONAL MATCH (child)<-[:WORKS_ON]-(r:Resource)
        RETURN child.name, min(length(e)) AS depth, child.duration, child.est_date, child.eft_date, child.status, collect(r.name) AS resources
        ORDER BY depth, child.est_date
        """
    else:
        query = f"""
        MATCH (t:Task {{name: $name}})-[e:DEPENDS_ON*1..{depth}]->(child:Task)
        RETURN child.name, min(length(e)) AS depth, child.duration, child.est_date, child.eft_date, child.status
        ORDER BY depth, child.est_date
        """
        
    res = conn.execute(query, {"name": task_name})
    
    if include_resources:
        table = "| Child Task | Depth | Duration | Start Date | End Date | Status | Assigned Resources |\n"
        table += "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
    else:
        table = "| Child Task | Depth | Duration | Start Date | End Date | Status |\n"
        table += "| :--- | :--- | :--- | :--- | :--- | :--- |\n"
        
    count = 0
    while res.has_next():
        row = res.get_next()
        if include_resources:
            resources = ", ".join([r for r in row[6] if r]) if row[6] else "None"
            table += f"| {row[0]} | {row[1]} | {row[2]}d | {row[3]} | {row[4]} | {row[5]} | {resources} |\n"
        else:
            table += f"| {row[0]} | {row[1]} | {row[2]}d | {row[3]} | {row[4]} | {row[5]} |\n"
        count += 1
        
    if count == 0:
        return f"No downstream children found for '{task_name}' within depth {depth}."
    return table


@mcp.tool()
def get_task_parents(task_name: str, depth: int = 1, include_resources: bool = False) -> str:
    """
    Returns a list of upstream tasks (parents/prerequisites) up to a specified depth.
    Depth 1 = direct parents. Depth 2 = parents and grandparents.
    """
    depth = max(1, min(depth, 10)) # Bound between 1 and 10
    
    if include_resources:
        query = f"""
        MATCH (parent:Task)-[e:DEPENDS_ON*1..{depth}]->(t:Task {{name: $name}})
        OPTIONAL MATCH (parent)<-[:WORKS_ON]-(r:Resource)
        RETURN parent.name, min(length(e)) AS depth, parent.duration, parent.est_date, parent.eft_date, parent.status, collect(r.name) AS resources
        ORDER BY depth, parent.eft_date
        """
    else:
        query = f"""
        MATCH (parent:Task)-[e:DEPENDS_ON*1..{depth}]->(t:Task {{name: $name}})
        RETURN parent.name, min(length(e)) AS depth, parent.duration, parent.est_date, parent.eft_date, parent.status
        ORDER BY depth, parent.eft_date
        """
        
    res = conn.execute(query, {"name": task_name})
    
    if include_resources:
        table = "| Parent Task | Depth | Duration | Start Date | End Date | Status | Assigned Resources |\n"
        table += "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
    else:
        table = "| Parent Task | Depth | Duration | Start Date | End Date | Status |\n"
        table += "| :--- | :--- | :--- | :--- | :--- | :--- |\n"
        
    count = 0
    while res.has_next():
        row = res.get_next()
        if include_resources:
            resources = ", ".join([r for r in row[6] if r]) if row[6] else "None"
            table += f"| {row[0]} | {row[1]} | {row[2]}d | {row[3]} | {row[4]} | {row[5]} | {resources} |\n"
        else:
            table += f"| {row[0]} | {row[1]} | {row[2]}d | {row[3]} | {row[4]} | {row[5]} |\n"
        count += 1
        
    if count == 0:
        return f"No upstream parents found for '{task_name}' within depth {depth}."
    return table



# ─── Phase 13: Data Purging & Lifecycle ───────────────────────────────────────

def _safe_delete_edges(node_label: str, key_property: str, value: str, edge_labels: list):
    """Severs edges in both directions for a node before deletion."""
    for rel in edge_labels:
        # Outgoing
        try:
            conn.execute(f"MATCH (n:{node_label} {{{key_property}: $val}})-[r:{rel}]->() DELETE r", {"val": value})
        except:
            pass
        # Incoming
        try:
            conn.execute(f"MATCH (n:{node_label} {{{key_property}: $val}})<-[r:{rel}]-() DELETE r", {"val": value})
        except:
            pass

@mcp.tool()
def delete_task(task_name: str) -> str:
    """Safely deletes a task after severing all dependencies and assignments."""
    _safe_delete_edges("Task", "name", task_name, ["DEPENDS_ON", "WORKS_ON", "REQUIRES_SKILL", "CONTAINS"])
    res = conn.execute("MATCH (t:Task {name: $name}) DELETE t RETURN count(*)", {"name": task_name})
    if res.has_next() and res.get_next()[0] > 0:
        return create_response("delete_task", "success", data={"task": task_name, "count": 1})
    return create_response("delete_task", "error", warnings=[f"Task '{task_name}' not found."])

@mcp.tool()
def delete_resource(resource_name: str) -> str:
    """Safely deletes a resource after severing all assignments and skills."""
    _safe_delete_edges("Resource", "name", resource_name, ["WORKS_ON", "HAS_SKILL"])
    res = conn.execute("MATCH (r:Resource {name: $name}) DELETE r RETURN count(*)", {"name": resource_name})
    if res.has_next() and res.get_next()[0] > 0:
        return create_response("delete_resource", "success", data={"resource": resource_name, "count": 1})
    return create_response("delete_resource", "error", warnings=[f"Resource '{resource_name}' not found."])

@mcp.tool()
def delete_skill(skill_name: str) -> str:
    """Safely deletes a skill after severing all possession and requirement links."""
    _safe_delete_edges("Skill", "name", skill_name, ["HAS_SKILL", "REQUIRES_SKILL"])
    res = conn.execute("MATCH (s:Skill {name: $name}) DELETE s RETURN count(*)", {"name": skill_name})
    if res.has_next() and res.get_next()[0] > 0:
        return create_response("delete_skill", "success", data={"skill": skill_name, "count": 1})
    return create_response("delete_skill", "error", warnings=[f"Skill '{skill_name}' not found."])

@mcp.tool()
def delete_project(project_id: str) -> str:
    """Deletes a project and all its contained tasks (cascading)."""
    # 1. Bulk sever ALL incident edges (directed both ways) for tasks in this project 
    # This prevents orphaned edges from re-attaching to future tasks with same names.
    # Bug 1 Fix: Explicitly delete DEPENDS_ON edges before other incident edges to be super safe.
    conn.execute("MATCH (a:Task {project_id: $id})-[r:DEPENDS_ON]->() DELETE r", {"id": project_id})
    conn.execute("MATCH (a:Task {project_id: $id})<-[r:DEPENDS_ON]-() DELETE r", {"id": project_id})
    # General detachment
    conn.execute("MATCH (t:Task {project_id: $id})-[r]->() DELETE r", {"id": project_id})
    conn.execute("MATCH (t:Task {project_id: $id})<-[r]-() DELETE r", {"id": project_id})
    
    # 2. Bulk delete the tasks themselves
    res_tasks = conn.execute("MATCH (t:Task {project_id: $id}) DELETE t RETURN count(*)", {"id": project_id})
    tasks_deleted = res_tasks.get_next()[0] if res_tasks.has_next() else 0

    # 3. Sever project's own edges and delete
    _safe_delete_edges("Project", "id", project_id, ["CONTAINS"])
    res = conn.execute("MATCH (p:Project {id: $id}) DELETE p RETURN count(*)", {"id": project_id})
    if res.has_next() and res.get_next()[0] > 0:
        return create_response("delete_project", "success", data={"project_id": project_id, "tasks_cascaded": tasks_deleted})
    return create_response("delete_project", "error", warnings=[f"Project '{project_id}' not found."])


@mcp.tool()
def add_holiday(date: str, description: str = "") -> str:
    """Adds a global holiday (YYYY-MM-DD) that the scheduler respects."""
    try:
        np.datetime64(date)
    except Exception:
        return create_response("add_holiday", "error", warnings=["Invalid date format. Use YYYY-MM-DD."])
    
    db, conn = get_db_connection()
    conn.execute("MERGE (h:Holiday {date: $date})", {"date": date})
    conn.execute("MATCH (h:Holiday {date: $date}) SET h.description = $holiday_desc", {"date": date, "holiday_desc": description})
    return create_response("add_holiday", "success", data={"date": date, "description": description})

@mcp.tool()
def remove_holiday(date: str) -> str:
    """Removes a global holiday."""
    db, conn = get_db_connection()
    res = conn.execute("MATCH (h:Holiday {date: $date}) DELETE h RETURN count(*)", {"date": date})
    if res.has_next() and res.get_next()[0] > 0:
        return create_response("remove_holiday", "success", data={"date": date})
    return create_response("remove_holiday", "error", warnings=[f"Holiday '{date}' not found."])

@mcp.tool()
def get_holidays() -> str:
    """Returns all registered global holidays."""
    db, conn = get_db_connection()
    res = conn.execute("MATCH (h:Holiday) RETURN h.date, h.description ORDER BY h.date")
    hols = []
    while res.has_next():
        date, desc = res.get_next()
        hols.append({"date": date, "description": desc})
    return create_response("get_holidays", "success", data={"holidays": hols})

@mcp.tool()
def export_to_gantt(project_id: str) -> str:
    """Exports a Mermaid Gantt chart of the project, grouped by task status."""
    db, conn = get_db_connection()
    proj_res = conn.execute("MATCH (p:Project {id: $id}) RETURN p.name", {"id": project_id})
    if not proj_res.has_next():
        return create_response("export_to_gantt", "error", warnings=[f"Project '{project_id}' not found."])
    project_name = proj_res.get_next()[0]

    # Fetch tasks grouped by status
    # We'll use status as sections
    task_res = conn.execute("""
        MATCH (p:Project {id: $id})-[:CONTAINS]->(t:Task)
        RETURN t.name, t.est_date, t.eft_date, t.status
        ORDER BY t.status, t.est_date
    """, {"id": project_id})
    
    gantt = "gantt\n"
    gantt += f"    title {project_name}\n"
    gantt += "    dateFormat YYYY-MM-DD\n"
    gantt += "    axisFormat %m-%d\n\n"
    
    current_status = None
    while task_res.has_next():
        name, est, eft, status = task_res.get_next()
        if status != current_status:
            current_status = status
            gantt += f"    section {status}\n"
        
        # Format task line for Mermaid
        # [Name] :[ID], [Start], [End]
        # Mermaid needs dates in dateFormat.
        clean_name = name.replace(":", " ") # Escape colons
        gantt += f"    {clean_name} :{est}, {eft}\n"
        
    return create_response("export_to_gantt", "success", data={"mermaid": gantt})

@mcp.tool()
def batch_assign_resources(assignments: list[dict]) -> str:
    """
    Assigns multiple resources to tasks in one transaction.
    assignments: [{"resource_name": "Alice", "task_name": "T1", "allocation": 100}, ...]
    """
    db, conn = get_db_connection()
    conn.execute("BEGIN TRANSACTION")
    try:
        results = []
        for x in assignments:
            res_str = assign_resource(x['resource_name'], x['task_name'], x.get('allocation', 100))
            res_json = json.loads(res_str)
            if res_json.get("status") == "error":
                raise Exception(f"Assignment failed for {x}: {res_json.get('warnings')}")
            results.append(x)
        conn.execute("COMMIT")
        return create_response("batch_assign_resources", "success", data={"assignments": results})
    except Exception as e:
        conn.execute("ROLLBACK")
        return create_response("batch_assign_resources", "error", warnings=[str(e)])

@mcp.tool()
def batch_grant_skills(grants: list[dict]) -> str:
    """
    Grants multiple skills to resources in one transaction.
    grants: [{"resource_name": "Alice", "skill_name": "Python", "proficiency": "Expert"}, ...]
    """
    db, conn = get_db_connection()
    conn.execute("BEGIN TRANSACTION")
    try:
        results = []
        for g in grants:
            res_str = grant_skill(g['resource_name'], g['skill_name'], g.get('proficiency', 'Intermediate'))
            res_json = json.loads(res_str)
            if res_json.get("status") == "error":
                raise Exception(f"Skill grant failed for {g}: {res_json.get('warnings')}")
            results.append(g)
        conn.execute("COMMIT")
        return create_response("batch_grant_skills", "success", data={"grants": results})
    except Exception as e:
        conn.execute("ROLLBACK")
        return create_response("batch_grant_skills", "error", warnings=[str(e)])


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

# ─── Custom Dynamic Reports (Phase 16) ───────────────────────────────────────

@mcp.tool()
def register_custom_report(name: str, description: str, cypher_query: str) -> str:
    """
    Allows the AI to save a custom analytical query as a reusable report.
    SECURITY: The query MUST be read-only (MATCH/RETURN/WITH). Mutating commands are blocked.
    """
    # 1. Security Gate: Block all mutation keywords
    forbidden_keywords = ["CREATE", "MERGE", "SET", "DELETE", "DROP", "ALTER", "REMOVE"]
    query_upper = cypher_query.upper()
    if any(keyword in query_upper for keyword in forbidden_keywords):
        return create_response("register_custom_report", "error", warnings=[f"Security Violation: Custom reports cannot contain mutating keywords ({', '.join(forbidden_keywords)})."])
        
    # 2. Syntax Validation: Try running it with a LIMIT 1 to catch typos instantly
    test_query = f"{cypher_query} LIMIT 1"
    last_error = ""
    try:
        conn.execute(test_query)
    except Exception as e:
        last_error = f"Syntax Error during registration: {str(e)}"
        
    # 3. Save to Database
    save_query = """
    MERGE (r:CustomReport {name: $name})
    SET r.description = $desc,
        r.cypher_query = $query,
        r.last_error = $error
    RETURN r.name
    """
    conn.execute(save_query, {"name": name, "desc": description, "query": cypher_query, "error": last_error})
    status = "warning" if last_error else "success"
    return create_response("register_custom_report", status, data={"report_name": name}, warnings=[last_error] if last_error else [])

@mcp.tool()
def run_custom_report(name: str) -> str:
    """
    Executes a previously saved custom report by name.
    """
    # 1. Fetch the query
    res = conn.execute("MATCH (r:CustomReport {name: $name}) RETURN r.cypher_query", {"name": name})
    if not res.has_next():
        return f"Error: Custom report '{name}' not found."
        
    query = res.get_next()[0]
    
    # 2. Execute and trap errors
    try:
        result_set = conn.execute(query)
        rows = []
        while result_set.has_next():
            rows.append(result_set.get_next())
            
        # Clear any previous errors on success
        conn.execute("MATCH (r:CustomReport {name: $name}) SET r.last_error = ''", {"name": name})
        
        if not rows:
            return "Report executed successfully, but returned 0 rows."
        return str(rows)
        
    except Exception as e:
        error_msg = str(e)
        # Log the error to the database for later debugging
        conn.execute("MATCH (r:CustomReport {name: $name}) SET r.last_error = $err", {"name": name, "err": error_msg})
        return f"Execution Failed. Error logged to database. Please run debug_custom_report('{name}') to investigate."

@mcp.tool()
def debug_custom_report(name: str) -> str:
    """
    Returns the exact Cypher query and the last recorded error log for a custom report.
    Use this to troubleshoot why a run_custom_report call failed.
    """
    res = conn.execute("MATCH (r:CustomReport {name: $name}) RETURN r.cypher_query, r.last_error", {"name": name})
    if not res.has_next():
        return f"Error: Custom report '{name}' not found."
        
    query, last_error = res.get_next()
    
    debug_info = f"--- DEBUG LOG FOR: {name} ---\n"
    debug_info += f"Query:\n{query}\n\n"
    debug_info += f"Last Recorded Error:\n{last_error if last_error else 'No errors recorded. Query is healthy.'}\n"
    return debug_info

@mcp.resource("custom://reports")
def list_custom_reports() -> str:
    """Returns a list of all registered custom AI reports."""
    res = conn.execute("MATCH (r:CustomReport) RETURN r.name, r.description, r.last_error")
    
    table = "| Report Name | Description | Status |\n| :--- | :--- | :--- |\n"
    count = 0
    while res.has_next():
        name, desc, err = res.get_next()
        status = "❌ Failing" if err else "✅ Healthy"
        table += f"| {name} | {desc} | {status} |\n"
        count += 1
        
    if count == 0:
        return "No custom reports have been registered yet."
    return table

# ─── Agentic Ergonomics (Phase 17) ──────────────────────────────────────────

@mcp.tool()
def get_evm_report_tool(project_id: str, as_of_date: str = None) -> str:
    """
    Generates the Earned Value Management (EVM) report. 
    Use as_of_date (YYYY-MM-DD) to calculate Planned Value relative to a future/past date.
    Returns PV, EV, AC, SPI, and CPI.
    """
    return get_evm_report_internal(project_id, as_of_date)

@mcp.resource("project://{project_id}/reports/evm")
def get_evm_report_resource(project_id: str) -> str:
    """
    Generates the static EVM report for the current date.
    """
    return get_evm_report_internal(project_id)

@mcp.tool()
def get_risk_report_tool(project_id: str) -> str:
    """Generates the PERT Risk report, ranking tasks by variance."""
    return get_risk_report(project_id)

@mcp.tool()
def get_database_schema_tool() -> str:
    """Returns the database schema (Node labels, properties, and edges). Call this if you are unsure of property names!"""
    return get_schema()

@mcp.tool()
def get_project_summary(project_id: str) -> str:
    """Generates a high-density project summary containing Metrics, Critical Path, and Budget."""
    return generate_briefing_webhook(project_id)

@mcp.tool()
def add_tasks_batch(project_id: str, tasks: list[dict]) -> str:
    """
    Creates multiple tasks at once.
    tasks: [{"name": "T1", "duration": 5, "cost": 100, "optimistic": 4, "pessimistic": 6}, ...]
    """
    results = []
    # Explicit Transactional Block
    conn.execute("BEGIN TRANSACTION")
    try:
        for t in tasks:
            # add_task now returns a JSON string
            res_str = add_task(
                project_id=project_id, 
                name=t['name'], 
                duration=t['duration'], 
                cost=t['cost'], 
                description=t.get('description', ''),
                optimistic=t.get('optimistic', None),
                pessimistic=t.get('pessimistic', None),
                skip_recalc=True
            )
            res_json = json.loads(res_str)
            if res_json.get("status") == "error":
                raise Exception(f"Task '{t.get('name')}' failed: {res_json.get('warnings')}")
            results.append(res_json.get("data", {}))
            
        # Single recalculation at the end
        warnings = _recalculate_timeline(project_id)
        conn.execute("COMMIT")
        return create_response("add_tasks_batch", "success", data={"project_id": project_id, "tasks_created": results}, warnings=warnings)
    except Exception as e:
        conn.execute("ROLLBACK")
        return create_response("add_tasks_batch", "error", warnings=[f"Batch failed and rolled back. Error: {str(e)}"])

@mcp.tool()
def create_dependencies_batch(dependencies: list[dict]) -> str:
    """
    Creates multiple dependencies at once.
    dependencies: [{"source": "A", "target": "B", "lag": 0}, ...]
    """
    results = []
    # Explicit Transactional Block
    conn.execute("BEGIN TRANSACTION")
    try:
        for d in dependencies:
            res_str = create_dependency(
                source_name=d['source'], 
                target_name=d.get('target'), 
                lag=d.get('lag', 0),
                skip_recalc=True
            )
            res_json = json.loads(res_str)
            if res_json.get("status") == "error":
                raise Exception(f"Dependency {d.get('source')}->{d.get('target')} failed: {res_json.get('warnings')}")
            results.append(res_json.get("data", {}))
            
        # Single recalculation at the end (for all affected projects)
        all_warnings = []
        affected_projects = set()
        for d in dependencies:
             # Find project for each source task
             p_res = conn.execute("MATCH (p:Project)-[:CONTAINS]->(t:Task {name: $name}) RETURN p.id", {"name": d['source']})
             if p_res.has_next(): 
                 affected_projects.add(p_res.get_next()[0])
        
        for pid in affected_projects:
            all_warnings.extend(_recalculate_timeline(pid))
            
        conn.execute("COMMIT")
        return create_response("create_dependencies_batch", "success", data={"dependencies_created": results}, warnings=all_warnings)
    except Exception as e:
        conn.execute("ROLLBACK")
        return create_response("create_dependencies_batch", "error", warnings=[f"Batch rolled back. Error: {str(e)}"])

@mcp.tool()
def set_progress_batch(updates: list[dict]) -> str:
    """
    Updates progress for multiple tasks at once.
    updates: [{"task_name": "T1", "percent_complete": 50}, ...]
    """
    conn.execute("BEGIN TRANSACTION")
    try:
        results = []
        for u in updates:
            # Call set_task_progress logic or execute Cypher directly
            res_str = set_task_progress(u['task_name'], u['percent_complete'], skip_recalc=True)
            res_json = json.loads(res_str)
            if res_json.get("status") == "error":
                raise Exception(f"Task '{u['task_name']}' update failed: {res_json.get('warnings')}")
            results.append(u['task_name'])
        # Progress updates might affect timeline if they trigger triggers? Not yet, but good to be safe.
        # Actually, let's just commit. Progress updates in Ph23 don't shift dates.
        conn.execute("COMMIT")
        return create_response("set_progress_batch", "success", data={"updated_tasks": results})
    except Exception as e:
        conn.execute("ROLLBACK")
        return create_response("set_progress_batch", "error", warnings=[str(e)])

@mcp.tool()
def analyze_root_cause(project_id: str) -> str:
    """Analyzes the critical path to find the specific tasks causing project delays."""
    # 1. First get the critical path tasks
    cp_string = get_critical_path(project_id)
    if "Project empty" in cp_string: return "Project is empty."
      
    cp_tasks = [t.strip() for t in cp_string.replace(f"Critical Path for {project_id}: ", "").split("->")]
      
    # 2. Check their baselines
    report = f"### Root Cause Analysis for {project_id}\n\n"
    found_slip = False
      
    for task in cp_tasks:
        res = conn.execute("MATCH (t:Task {name: $name}) RETURN t.duration, t.est_date, t.baseline_est_date", {"name": task})
        if res.has_next():
            dur, est, b_est = res.get_next()
            if est and b_est and est > b_est:
                report += f"- **{task}**: Slipped! Baseline Start was {b_est}, now currently {est}.\n"
                found_slip = True
                  
    if not found_slip:
        return report + "Critical path is healthy and aligned with baseline."
    return report

@mcp.tool()
def get_unassigned_tasks(project_id: str) -> str:
    """
    Returns a list of all tasks in a project that currently have no resources assigned.
    Useful for identifying gaps in project planning.
    """
    query = """
    MATCH (p:Project {id: $pid})-[:CONTAINS]->(t:Task)
    WHERE NOT (t)<-[:WORKS_ON]-(:Resource)
    RETURN t.name, t.duration, t.cost, t.status, t.est_date
    """
    try:
        res = conn.execute(query, {"pid": project_id})
        orphaned_tasks = []
        while res.has_next():
            row = res.get_next()
            orphaned_tasks.append({
                "task": row[0],
                "duration": row[1],
                "cost": row[2],
                "status": row[3],
                "start_date": row[4]
            })
            
        return create_response(
            operation="get_unassigned_tasks",
            status="success",
            data={
                "project_id": project_id, 
                "unassigned_tasks": orphaned_tasks,
                "count": len(orphaned_tasks)
            }
        )
    except Exception as e:
        return create_response("get_unassigned_tasks", "error", warnings=[f"Database error: {str(e)}"])

@mcp.tool()
def get_resource_timeline(resource_name: str) -> str:
    """
    Returns a timeline of tasks and allocations for a specific resource.
    Provides the exact intervals of their workload across all projects.
    """
    query = """
    MATCH (r:Resource {name: $name})-[w:WORKS_ON]->(t:Task)
    OPTIONAL MATCH (p:Project)-[:CONTAINS]->(t)
    RETURN t.name, p.id, t.est_date, t.eft_date, w.allocation, t.status
    ORDER BY t.est_date
    """
    try:
        res = conn.execute(query, {"name": resource_name})
        timeline = []
        total_assignments = 0
        
        while res.has_next():
            row = res.get_next()
            timeline.append({
                "task": row[0],
                "project_id": row[1],
                "start_date": row[2],
                "end_date": row[3],
                "allocation": row[4],
                "status": row[5]
            })
            total_assignments += 1
            
        if total_assignments == 0:
             return create_response("get_resource_timeline", "success", warnings=[f"Resource '{resource_name}' has no active task assignments."])
               
        return create_response(
            operation="get_resource_timeline",
            status="success",
            data={
                "resource": resource_name,
                "assignments": timeline,
                "count": total_assignments
            }
        )
    except Exception as e:
        return create_response("get_resource_timeline", "error", warnings=[f"Database error: {str(e)}"])

@mcp.tool()
def simulate_impact(project_id: str, task_name: str, added_duration: int) -> str:
    """Simulates adding duration to a task to see if the overall project end date changes."""
    # Get current project end date
    res_orig = conn.execute("MATCH (p:Project {id: $pid})-[:CONTAINS]->(t:Task) RETURN max(t.eft_date)", {"pid": project_id})
    orig_end = res_orig.get_next()[0] if res_orig.has_next() else None
      
    # Simulate by temporarily updating, recalculating, capturing, and rolling back
    conn.execute("MATCH (t:Task {name: $name}) SET t.duration = t.duration + $add", {"name": task_name, "add": int(added_duration)})
    _recalculate_timeline(project_id)
      
    res_new = conn.execute("MATCH (p:Project {id: $pid})-[:CONTAINS]->(t:Task) RETURN max(t.eft_date)", {"pid": project_id})
    new_end = res_new.get_next()[0] if res_new.has_next() else None
      
    # Rollback
    conn.execute("MATCH (t:Task {name: $name}) SET t.duration = t.duration - $add", {"name": task_name, "add": int(added_duration)})
    _recalculate_timeline(project_id)
      
    if orig_end == new_end:
        return f"Safe. Adding {added_duration} days to {task_name} consumes Float but does NOT delay the project (End date remains {orig_end})."
    else:
        return f"CRITICAL IMPACT: Adding {added_duration} days to {task_name} pushes the project end date from {orig_end} to {new_end}."

@mcp.resource("project://{project_id}/state/export/gantt")
def export_gantt_chart(project_id: str):
    """Generates a visual Gantt chart PNG of the project timeline."""
    query = """
    MATCH (p:Project {id: $pid})-[:CONTAINS]->(t:Task)
    RETURN t.name, t.est_date, t.eft_date
    ORDER BY t.est_date DESC
    """
    res = conn.execute(query, {"pid": project_id})
      
    tasks = []
    starts = []
    ends = []
      
    while res.has_next():
        row = res.get_next()
        if row[1] and row[2]:
            tasks.append(row[0])
            starts.append(np.datetime64(row[1]))
            ends.append(np.datetime64(row[2]))
              
    if not tasks: return {"type": "text", "text": "No valid tasks found."}
      
    fig, ax = plt.subplots(figsize=(10, len(tasks) * 0.5 + 2))
      
    # Convert numpy dates to matplotlib dates
    start_dates = [mdates.date2num(d.astype(datetime.date)) for d in starts]
    end_dates = [mdates.date2num(d.astype(datetime.date)) for d in ends]
    durations = [e - s for s, e in zip(start_dates, end_dates)]
      
    ax.barh(tasks, durations, left=start_dates, color='skyblue', edgecolor='black')
    ax.xaxis_date()
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    plt.xticks(rotation=45)
    plt.title(f"Gantt Chart: {project_id}")
    plt.tight_layout()
      
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    base64_data = base64.b64encode(buf.read()).decode('utf-8')
    plt.close(fig)
      
    return {"type": "image", "data": base64_data, "mimeType": "image/png"}

@mcp.tool()
def generate_human_decision_prompt(task_name: str, conflict_description: str) -> str:
    """Formats an escalation prompt for the human operator when the AI cannot resolve a conflict safely."""
    prompt = f"🚨 **HUMAN ESCALATION REQUIRED** 🚨\n\n"
    prompt += f"**Issue on Task:** `{task_name}`\n"
    prompt += f"**Conflict:** {conflict_description}\n\n"
    prompt += "The Auto-Leveler cannot resolve this without impacting the baseline. Please choose an intervention:\n\n"
    prompt += "- [ ] **Option A: Increase Budget** (Authorize overtime or assign additional resources to crash the schedule).\n"
    prompt += "- [ ] **Option B: Accept Delay** (Allow the Critical Path to push back the project end date).\n"
    prompt += "- [ ] **Option C: Cut Scope** (Reduce the duration of this task or a downstream task to regain time).\n\n"
    prompt += "*Reply with your choice and I will execute the necessary graph changes.*"
    return prompt




if __name__ == "__main__":
    # Ensure DB is initialized before server starts
    initialize_schema()
    # By default, mcp.run() uses stdio transport
    mcp.run()
