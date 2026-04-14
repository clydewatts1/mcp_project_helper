# **Development Plan: Phase 17 (Agentic Ergonomics & Feedback Remediation)**

**ATTENTION CODING AGENT (ANTIGRAVITY):** This is your Phase 17 architectural blueprint. Based on live integration testing with an LLM, we have identified major friction points in the server's UX. Your objective is to shift the server from merely "functional" to "agent-optimized."

You must implement schema updates, convert key resources into explicit tools, add batch operations, and introduce task modification capabilities.

## **Step 1: Schema Updates & Backfilling**

The AI needs an easier way to query tasks by project without writing complex graph traversals, and it needs explicit PERT fields.

1. **Update initialize\_schema() in server.py:**  
   Add these to the migration\_queries list:  
   "ALTER TABLE Task ADD project\_id STRING"  
   "ALTER TABLE Task ADD pert\_std\_dev DOUBLE"  
   "ALTER TABLE Task ADD pert\_variance DOUBLE"

2. **Backfill Existing Data:** Add this execution right after the migration loop to fix existing tasks:  
   try:  
       conn.execute("MATCH (p:Project)-\[:CONTAINS\]-\>(t:Task) WHERE t.project\_id IS NULL SET t.project\_id \= p.id")  
   except Exception:  
       pass

3. **Update add\_task:** Update the Cypher query in add\_task to explicitly set the property: t.project\_id \= $project\_id.

## **Step 2: Fix PERT Math**

Update the run\_pert\_analysis tool in server.py to calculate and store the standard deviation and variance so the LLM doesn't have to calculate them manually.

**Update the Cypher query in run\_pert\_analysis:**

MATCH (p:Project {id: $pid})-\[:CONTAINS\]-\>(t:Task)  
WITH t,   
     (CAST(t.optimistic\_duration AS DOUBLE) \+ (4.0 \* CAST(t.duration AS DOUBLE)) \+ CAST(t.pessimistic\_duration AS DOUBLE)) / 6.0 AS expected,  
     (CAST(t.pessimistic\_duration AS DOUBLE) \- CAST(t.optimistic\_duration AS DOUBLE)) / 6.0 AS std\_dev  
SET t.expected\_duration \= expected,  
    t.pert\_std\_dev \= std\_dev,  
    t.pert\_variance \= std\_dev \* std\_dev  
RETURN count(t)

## **Step 3: Tool-ify Core Resources & Rename Webhook**

LLMs heavily bias towards calling explicit tools over reading resources. Wrap the existing resource functions into new tools.

**Action:** Add these new tools to server.py:

@mcp.tool()  
def get\_evm\_report\_tool(project\_id: str) \-\> str:  
    """Generates the Earned Value Management (EVM) report. Returns PV, EV, AC, SPI, and CPI."""  
    return get\_evm\_report(project\_id) \# Calls your existing resource function

@mcp.tool()  
def get\_risk\_report\_tool(project\_id: str) \-\> str:  
    """Generates the PERT Risk report, ranking tasks by variance."""  
    return get\_risk\_report(project\_id)

@mcp.tool()  
def get\_database\_schema() \-\> str:  
    """Returns the database schema (Node labels, properties, and edges). Call this if you are unsure of property names\!"""  
    return get\_schema() \# Calls your existing resource function

@mcp.tool()  
def get\_project\_summary(project\_id: str) \-\> str:  
    """Generates a high-density project summary containing Metrics, Critical Path, and Budget."""  
    return generate\_briefing\_webhook(project\_id) \# Renamed for clarity\!

*(Note: You may now deprecate or remove generate\_briefing\_webhook entirely).*

## **Step 4: Missing CRUD \- Update Task & Status**

The LLM needs a way to correct its mistakes without dropping the whole database.

**Action 1:** Add update\_task

@mcp.tool()  
def update\_task(task\_name: str, duration: int \= None, cost: float \= None, description: str \= None) \-\> str:  
    """Updates an existing task's attributes. Only pass the values you want to change."""  
    updates \= \[\]  
    params \= {"name": task\_name}  
    if duration is not None:  
        updates.append("t.duration \= $duration")  
        params\["duration"\] \= int(duration)  
    if cost is not None:  
        updates.append("t.cost \= $cost")  
        params\["cost"\] \= float(cost)  
    if description is not None:  
        updates.append("t.description \= $desc")  
        params\["desc"\] \= description  
          
    if not updates:  
        return "No updates provided."  
          
    query \= f"MATCH (t:Task {{name: $name}}) SET {', '.join(updates)} RETURN t.name"  
    res \= conn.execute(query, params)  
      
    if not res.has\_next():  
        return f"Error: Task '{task\_name}' not found."  
      
    \# Recalculate timeline if duration changed  
    if duration is not None:  
        proj\_res \= conn.execute("MATCH (t:Task {name: $name}) RETURN t.project\_id", {"name": task\_name})  
        if proj\_res.has\_next():  
            \_recalculate\_timeline(proj\_res.get\_next()\[0\])  
              
    return f"Task '{task\_name}' updated successfully."

**Action 2:** Update set\_task\_progress in server.py to auto-transition the status:

@mcp.tool()  
def set\_task\_progress(task\_name: str, percent\_complete: int) \-\> str:  
    """Updates completion percentage (0-100) and automatically transitions the status."""  
    if not (0 \<= percent\_complete \<= 100): return "Error: Must be 0-100."  
      
    status \= "IN\_PROGRESS"  
    if percent\_complete \== 100: status \= "DONE"  
    elif percent\_complete \== 0: status \= "AI\_DRAFT"  
      
    res \= conn.execute("""  
        MATCH (t:Task {name: $name})  
        SET t.percent\_complete \= $pct, t.status \= $status  
        RETURN t.name  
    """, {"name": task\_name, "pct": percent\_complete, "status": status})  
      
    if res.has\_next(): return f"Task '{task\_name}' updated to {percent\_complete}% ({status})."  
    return f"Error: Task '{task\_name}' not found."

## **Step 5: Batch Operations (Anti-Timeout)**

LLMs time out if they make 10 separate sequential calls to create\_dependency.

**Action:** Add these batch tools:

@mcp.tool()  
def add\_tasks\_batch(project\_id: str, tasks\_json: str) \-\> str:  
    """  
    Creates multiple tasks at once to prevent timeouts.  
    tasks\_json MUST be a valid JSON string array of objects: \[{"name": "T1", "duration": 5, "cost": 100}, ...\]  
    """  
    import json  
    try:  
        tasks \= json.loads(tasks\_json)  
    except json.JSONDecodeError:  
        return "Error: tasks\_json must be a valid JSON string."  
          
    results \= \[\]  
    for t in tasks:  
        results.append(add\_task(project\_id, t\['name'\], t\['duration'\], t\['cost'\], t.get('description', '')))  
    return "\\n".join(results)

@mcp.tool()  
def create\_dependencies\_batch(dependencies\_json: str) \-\> str:  
    """  
    Creates multiple dependencies at once.  
    dependencies\_json MUST be a valid JSON string array: \[{"source": "A", "target": "B", "lag": 0}, ...\]  
    """  
    import json  
    try:  
        deps \= json.loads(dependencies\_json)  
    except json.JSONDecodeError:  
        return "Error: dependencies\_json must be a valid JSON string."  
          
    results \= \[\]  
    for d in deps:  
        results.append(create\_dependency(d\['source'\], d\['target'\], d.get('lag', 0)))  
    return "\\n".join(results)

## **Step 6: Verify & Document**

1. Update MANUAL.md to reflect get\_project\_summary, update\_task, and the new batch JSON tools.  
2. Restart the server and verify that get\_database\_schema directly returns the JSON schema via an MCP Tool call.