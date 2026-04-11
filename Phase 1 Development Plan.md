# **Development Plan: Phase 1 (Core Engine MVP)**

**ATTENTION CODING AGENT (ANTIGRAVITY):** This is your strict architectural blueprint. You are to build an MCP server in Python using FastMCP and the kuzu graph database. Do not hallucinate features outside of this Phase 1 scope. Follow the exact data types, schemas, and logic gates defined below.

## **Objective**

Establish the bare-bones MCP Python server, initialize the strictly-typed Kùzu database, enforce Law I (No Cycles), and implement the Temporal Engine (Calendar Math) for Tasks and Dependencies.

## **Step 1: Environment & Transport Setup**

1. **Initialize Project:** Create a standard Python project.  
2. **Dependencies:** pip install kuzu mcp numpy graphviz  
3. **Server Instance:** Use mcp.server.fastmcp.FastMCP.  
   * Initialize: mcp \= FastMCP("ProjectLogicEngine")  
   * Ensure it supports standard stdio running (mcp.run()) but is also structured so it can be mounted as an ASGI app for sse transport if required later.  
4. **Database Init:** Initialize a local Kùzu database instance at ./project\_data.kuzu on startup.  
   * *Code Pattern:* db \= kuzu.Database('./project\_data.kuzu'); conn \= kuzu.Connection(db)

## **Step 2: Strict Schema Initialization**

Kùzu is strictly typed. On startup, your code MUST execute a try/except block to create these exact tables if they do not exist. **Use these exact Cypher queries:**

// Node Tables  
CREATE NODE TABLE Project (id STRING, start\_date STRING, name STRING, PRIMARY KEY (id));  
CREATE NODE TABLE Task (name STRING, description STRING, duration INT, cost DOUBLE, est\_date STRING, eft\_date STRING, PRIMARY KEY (name));

// Edge Tables  
CREATE REL TABLE CONTAINS (FROM Project TO Task);  
CREATE REL TABLE DEPENDS\_ON (FROM Task TO Task, lag INT);

## **Step 3: Implement The Self-Healing Query Wrapper**

Before building tools, create a helper function for all custom database reads.

* **Function:** def safe\_cypher\_read(query: str, params: dict \= None) \-\> str:  
* **Logic:** Wrap conn.execute() in try/except Exception as e:.  
* **Agentic Guardrail:** If an error occurs, return f"Kuzu Error: {str(e)}". Do NOT crash the server. This allows the LLM to read the error and rewrite its query.

## **Step 4: Implement Core Tools (The Logic Gates)**

Implement the following using the @mcp.tool() decorator:

1. **create\_project(project\_id: str, start\_date: str, name: str)**  
   * *Validation:* Ensure start\_date matches YYYY-MM-DD.  
   * *Cypher:* MERGE (p:Project {id: $project\_id, start\_date: $start\_date, name: $name})  
2. **add\_task(project\_id: str, name: str, duration: int, cost: float, description: str \= "")**  
   * *Logic:* Default est\_date and eft\_date to the project's start\_date temporarily.  
   * *Cypher:* MATCH (p:Project {id: $project\_id}) MERGE (t:Task {name: $name, description: $description, duration: $duration, cost: $cost, est\_date: p.start\_date, eft\_date: p.start\_date}) MERGE (p)-\[:CONTAINS\]-\>(t)  
   * *Post-Action:* Call \_recalculate\_timeline(project\_id)  
3. **create\_dependency(source\_name: str, target\_name: str, lag: int \= 0\)**  
   * *Gate 1 (Law I \- Cycle Check):* Run MATCH path=(t:Task {name: $target\_name})-\[\*\]-\>(s:Task {name: $source\_name}) RETURN count(path). If \> 0, raise ValueError("Law I Violation: Circular Dependency Detected.").  
   * *Gate 2:* If safe, execute MATCH (a:Task {name: $source\_name}), (b:Task {name: $target\_name}) MERGE (a)-\[:DEPENDS\_ON {lag: $lag}\]-\>(b).  
   * *Post-Action:* Call \_recalculate\_timeline(project\_id)

## **Step 5: The Temporal Engine (Calendar Math)**

Do NOT attempt complex graph math in Cypher. Write a Python function \_recalculate\_timeline(project\_id):

1. **Fetch Data:** Query all tasks and dependencies for the project into a Python dictionary/list.  
2. **Topological Sort:** Sort the tasks in Python so you process parents before children.  
3. **Calendar Math:** Use numpy.busday\_offset.  
   * est\_date \= max of (eft\_date of all incoming dependencies \+ lag working days).  
   * eft\_date \= np.busday\_offset(est\_date, duration).astype(str)  
4. **Update DB:** Loop through the updated tasks and conn.execute("MATCH (t:Task {name: $name}) SET t.est\_date \= $est, t.eft\_date \= $eft", parameters=...)

## **Step 6: Expose Phase 1 Resources**

Implement the following using @mcp.resource():

1. **system://schema**  
   * Returns a JSON string of the exact schema defined in Step 2\.  
2. **project://{project\_id}/tasks**  
   * Cypher: MATCH (p:Project {id: $project\_id})-\[:CONTAINS\]-\>(t:Task) RETURN t.name, t.duration, t.est\_date, t.eft\_date  
   * Formats result as a Markdown table.  
3. **project://{project\_id}/state/export/image** (Graphviz)  
   * Query all tasks and DEPENDS\_ON edges for the project.  
   * Generate a .dot string.  
   * Compile to PNG using the graphviz python package.  
   * **Crucial:** Return strictly in MCP format: {"type": "image", "data": "\<base64\_encoded\_png\_string\>", "mimeType": "image/png"}

## **Step 7: Test-Driven Verification**

Before attaching the server to the LLM agent, write a local test\_engine.py script that:

1. Initializes db and conn.  
2. Creates Project "P1" starting "2026-05-01" (a Friday).  
3. Adds Task A (duration: 1\) and Task B (duration: 2).  
4. Links A \-\> B.  
5. Asserts that B's est\_date skips the weekend correctly using the numpy engine.