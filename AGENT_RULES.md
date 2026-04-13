# **AI Agent Directives for mcp-project-logic**

**ATTENTION LLMs AND CODING AGENTS:** If you are reading this file, you are tasked with modifying or extending the mcp-project-logic codebase. You MUST adhere to the following strict rules to prevent destroying the mathematical integrity of the engine.

## **1\. Architectural Mandates**

* **Python for Math, Kùzu for Storage:** Kùzu Cypher is used strictly for fetching and storing graph state. **DO NOT** write complex nested Cypher queries to calculate dates, overlaps, or algorithms. All temporal math (CPM, Float), heuristics, and sweep-line algorithms MUST be executed in Python memory using numpy or standard libraries.  
* **The Single Source of Truth:** server.py is the central logic gate. Do not bypass it.

## **2\. Schema Modification Protocol (CRITICAL)**

If you add a new property to a Node or Edge in the Kùzu database, you MUST update the following locations synchronously:

1. **initialize\_schema():** Add the property to the CREATE NODE TABLE or ALTER TABLE queries.  
2. **get\_schema():** Update the JSON documentation resource so querying LLMs know the property exists.  
3. **clone\_scenario():** Update the query\_tasks Cypher block so the new property is successfully copied during sandbox duplication. Failure to do this causes schema drift and data loss.

## **3\. The Documentation Mandate (NEW)**

* **Update MANUAL.md:** If you add a new @mcp.tool() or @mcp.resource(), you MUST update the MANUAL.md file to document the new functionality, its required parameters, and its intended behavior.  
* **Transparency:** Future LLM instances rely on MANUAL.md to understand what the server is capable of. Undocumented tools are useless tools.

## **4\. The Test Suite Commandment**

* We use pytest with a temporary database fixture (isolated\_server).  
* **Never test against ./project\_data.kuzu directly.**  
* If you write a new tool, you MUST write a corresponding test in the tests/ directory.  
* If your code breaks the `test_fuzzing.py`, `test_temporal.py`, `test_transport.py`, or `test_benchmarks.py` suites, your code is mathematically flawed. Revert and rethink.

## **5\. Error Handling**

* Do not let Kùzu exceptions crash the MCP server.  
* Always use try/except loops around conn.execute(). Return the raw Kùzu error string to the user/client so the interacting LLM can read the syntax error and self-correct its Cypher.

## **6\. Temporal Engine Rules**

* All durations and lags are in **Working Days**.  
* Always use numpy.busday\_offset(..., roll='following') for calendar math. Do not use standard datetime.timedelta unless dealing with strict calendar days.