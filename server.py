import re
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
        "CREATE NODE TABLE Task (name STRING, description STRING, duration INT, cost DOUBLE, est_date STRING, eft_date STRING, PRIMARY KEY (name))"
    ]
    
    # Edge Tables
    rel_queries = [
        "CREATE REL TABLE CONTAINS (FROM Project TO Task)",
        "CREATE REL TABLE DEPENDS_ON (FROM Task TO Task, lag INT)"
    ]
    
    for query in node_queries + rel_queries:
        try:
            conn.execute(query)
            # print(f"DEBUG: Schema Created: {query.split('(')[0]}")
        except Exception as e:
            # Handle Case: Table already exists
            if "already exists" in str(e).lower():
                pass
            else:
                print(f"Kuzu Schema Error: {e}")

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
    """
    # 1. Fetch Project Start Date
    proj_res = conn.execute("MATCH (p:Project {id: $id}) RETURN p.start_date", {"id": project_id})
    if not proj_res.has_next():
        return
    project_start_date = proj_res.get_next()[0]

    # 2. Fetch all tasks in project
    task_res = conn.execute("MATCH (p:Project {id: $id})-[:CONTAINS]->(t:Task) RETURN t.name, t.duration", {"id": project_id})
    tasks = {}
    while task_res.has_next():
        row = task_res.get_next()
        tasks[row[0]] = {"duration": row[1], "in_degree": 0, "successors": [], "predecessors": []}

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

    # 5. Calendar Calculation (Inclusive Math)
    task_dates = {}
    for name in sorted_tasks:
        task = tasks[name]
        if not task["predecessors"]:
            # Initial task starts on project start date (or next busday if weekend)
            est = np.busday_offset(project_start_date, 0, roll='following')
        else:
            # Dependent task
            candidate_dates = []
            for pred in task["predecessors"]:
                source_eft = task_dates[pred["source"]]["eft"]
                # Start is 1 day after end + lag
                start_candidate = np.busday_offset(source_eft, 1 + pred["lag"], roll='following')
                candidate_dates.append(start_candidate)
            est = max(candidate_dates)
        
        # Calculate EFT (inclusive)
        # If duration is 1, eft = est. If duration is 2, eft = est + 1 working day.
        eft = np.busday_offset(est, task["duration"] - 1, roll='following')
        
        task_dates[name] = {"est": str(est), "eft": str(eft)}

    # 6. Update Database
    for name, dates in task_dates.items():
        conn.execute("""
            MATCH (t:Task {name: $name}) 
            SET t.est_date = $est, t.eft_date = $eft
        """, {"name": name, "est": dates["est"], "eft": dates["eft"]})

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
    MERGE (t:Task {name: $name, description: $description, duration: $duration, cost: $cost, est_date: p.start_date, eft_date: p.start_date})
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
    _recalculate_timeline(project_id)
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
    
    # We need project_id for recalculation. For now, we'd need to find it from the task.
    # This will be refined in Step 5.
    return res

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
