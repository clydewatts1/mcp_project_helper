# **System Design: mcp-project-logic**

This document defines the technical architecture for the mcp-project-logic server, integrating the **MCP (Model Context Protocol)** with **Kùzu Graph Database** to enforce the "Project Logic Constitution."

## **1\. Architectural Overview**

The system operates as a stateful logic gate between the LLM and a local Kùzu database file.

* **Host (e.g., Claude Desktop, AntiGravity):** Sends requests to the MCP server.  
* **MCP Server (Python):** Orchestrates logic validation, calculates the Critical Path using a Python-based calendar engine, and manages the Kùzu connection. Built using FastMCP.  
* **Transport Layers:** Supports stdio for local integrations and sse (Server-Sent Events) over HTTP for web-based or remote agent frameworks.  
* **Kùzu DB:** An embedded, strictly typed graph database that stores the project state (.kuzu file).

## **2\. Kùzu Schema Design**

Kùzu requires strict typing. The schema maps exactly to the Symbolic Standard, using natural language name fields as Primary Keys to reduce LLM hallucination.

### **Node Tables**

| Table | Property | Type | Description |
| :---- | :---- | :---- | :---- |
| **Project** | id | STRING (PK) | Unique project identifier |
|  | start\_date | STRING | Anchor date (YYYY-MM-DD) |
| **Task** | name | STRING (PK) | Short title / Primary Key |
|  | description | STRING | Detailed scope text |
|  | duration | INT | Working days (excluding weekends) |
|  | cost | DOUBLE | Base fixed cost |
|  | est\_date | STRING | Earliest Start Time (YYYY-MM-DD) |
|  | eft\_date | STRING | Earliest Finish Time (YYYY-MM-DD) |
| **Resource** | name | STRING (PK) | Display name / Primary Key |
|  | description | STRING | Details/Contact |
|  | type | STRING | "HUMAN" or "EQUIPMENT" |
|  | cost\_rate | DOUBLE | Cost per working day |
| **Skill** | name | STRING (PK) | Skill capability (e.g., "Python") |
|  | description | STRING | Skill definition |

### **Relationship Tables**

| Table | From | To | Properties | Description |
| :---- | :---- | :---- | :---- | :---- |
| **CONTAINS** | Project | Task | None | Associates task to project. |
| **DEPENDS\_ON** | Task | Task | lag (INT) | Directed dependencies. |
| **WORKS\_ON** | Resource | Task | allocation (INT) | Capacity tracking. |
| **HAS\_SKILL** | Resource | Skill | proficiency (STR) | Resource capabilities. |
| **REQUIRES\_SKILL** | Task | Skill | None | Required task capability. |

## **3\. Logic Gate Implementation (The "Engine")**

The MCP server wraps database mutations in logical checks categorized into **Strict Laws** (Execution Blockers) and **State Monitors** (Warning Triggers).

### **Strict Law I: Circular Dependency Guard**

Before executing CREATE (a)-\[:DEPENDS\_ON\]-\>(b), the server verifies no path exists from b back to a. If cycle\_exists \> 0, the MCP server blocks the action and returns a Structural Conflict Error.

### **Strict Law II: Temporal & Calendar Engine (CPM)**

The server includes a Python-based **Critical Path Method (CPM)** engine that respects a Global Calendar (skipping weekends/holidays).

* **Process:** Data is pulled from Kùzu into Python. Python calculates the forward pass (e.g., using numpy.busday\_offset to translate duration: 5 into real YYYY-MM-DD dates).  
* **Result:** Python writes the new est\_date and eft\_date values back to Kùzu in a single transaction.

### **State Monitor: Resource Leveling Guard**

Before assigning a resource, the server validates capacity.

* **Logic:** Checks tasks overlapping with the new task's calendar window (est\_date to eft\_date).  
* **Result:** If total\_load \+ new\_allocation \> 100, the server allows the assignment but appends an **Over-allocation Warning** to the LLM response.

## **4\. Visualizations & Output**

* **Graphviz DAG:** The server compiles the current database state into a visual Directed Acyclic Graph (DAG) using graphviz.  
* **Payload Structure:** Visuals are returned to the LLM client strictly matching the MCP SDK image payload: {"type": "image", "data": "\<base64\>", "mimeType": "image/png"}.

## **5\. Developer Directives (For Coding Agents)**

When implementing or querying this server, autonomous agents must adhere to the following:

1. **FastMCP:** Build the server utilizing the mcp.server.fastmcp module for streamlined decorator-based tool creation.  
2. **Schema Definition First:** Kùzu is strictly typed. Nodes and Edge tables MUST be explicitly created with Cypher (CREATE NODE TABLE...) before data insertion.  
3. **Self-Healing Query Loop:** All raw Cypher executions (query\_graph) must be wrapped in try/except blocks. If Kùzu throws an exception, the exact error string must be returned to the LLM so it can debug and rewrite the query.  
4. **Python Math:** Complex topological sorts and business-day math must be executed in Python memory, not via complex nested Cypher queries.