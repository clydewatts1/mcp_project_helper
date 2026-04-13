# **Development Plan: Phase 11 (Entity Listing & Inspection Tools)**

**ATTENTION CODING AGENT (ANTIGRAVITY):** This is your Phase 11 architectural blueprint. Your objective is to expand the server.py toolset by adding dedicated inspection endpoints for all core Kùzu entities.

While the LLM can already use execute\_read\_cypher, providing explicit list tools creates a much more deterministic and reliable interface for system state retrieval.

## **Objective**

Implement four new @mcp.tool() endpoints (list\_projects, list\_tasks, list\_resources, list\_skills) that query the database and return the data as cleanly formatted Markdown tables.

## **Step 1: Implement list\_projects**

Add a tool to list all active projects in the system.

* **Tool Name:** list\_projects()  
* **Cypher Query:** MATCH (p:Project) RETURN p.id, p.name, p.start\_date  
* **Implementation Logic:**  
  Execute the query. If there are no results, return "No projects found." Otherwise, format the returned rows into a Markdown table with headers: | Project ID | Name | Start Date |.

## **Step 2: Implement list\_tasks**

Add a tool to list all tasks across the entire database (or optionally filtered by project if the agent prefers, but global is acceptable for this inspection tool).

* **Tool Name:** list\_tasks(project\_id: str \= None)  
* **Cypher Query (Global):** MATCH (t:Task) RETURN t.name, t.duration, t.status, t.est\_date, t.eft\_date  
* **Cypher Query (Filtered):** MATCH (p:Project {id: $pid})-\[:CONTAINS\]-\>(t:Task) RETURN t.name, t.duration, t.status, t.est\_date, t.eft\_date  
* **Implementation Logic:**  
  Format the results into a Markdown table with headers: | Task Name | Duration | Status | Start Date | End Date |.

## **Step 3: Implement list\_resources**

Add a tool to list all registered human and equipment resources.

* **Tool Name:** list\_resources()  
* **Cypher Query:** MATCH (r:Resource) RETURN r.name, r.type, r.cost\_rate  
* **Implementation Logic:**  
  Format the results into a Markdown table with headers: | Resource Name | Type | Cost Rate |. Ensure the cost rate is formatted as currency (e.g., $500.00).

## **Step 4: Implement list\_skills**

Add a tool to list all registered skills in the competency database.

* **Tool Name:** list\_skills()  
* **Cypher Query:** MATCH (s:Skill) RETURN s.name, s.description  
* **Implementation Logic:**  
  Format the results into a Markdown table with headers: | Skill Name | Description |.

## **Step 5: Update Documentation (Crucial)**

Because you are adding new tools to the MCP server, you **MUST** update the system documentation to prevent schema drift.

1. **MANUAL.md**: Add the four new tools to the "MCP Tool Reference" section.  
2. **mcp\_components.md**: Add the functional descriptions of these four tools to the components list so the LLM knows they exist and can be called.

## **Step 6: Test-Driven Verification**

1. Restart the server.py instance.  
2. Run the MCP Inspector (npx @modelcontextprotocol/inspector python server.py).  
3. Select list\_projects and execute. Verify a clean Markdown table is returned.  
4. Select list\_resources and execute. Verify the table renders correctly.