# **Development Plan: Phase 0 (Environment & Skeleton Setup)**

**ATTENTION CODING AGENT (ANTIGRAVITY):** This is your Phase 0 blueprint. Your objective is to establish the foundation of the Python project, install the necessary dependencies, and create a functional FastMCP server with a basic health-check tool. Do not implement any Kùzu database logic or Cypher queries in this phase.

## **Objective**

Set up the Python environment, configure the FastMCP server skeleton, and prove that both stdio and sse transport mechanisms are working by exposing a simple ping tool.

## **Step 1: Environment Setup**

1. **Create Project Structure:** Create a new directory for the project (e.g., mcp-project-logic) and navigate into it.  
2. **Virtual Environment:** Initialize and activate a Python virtual environment (venv).  
3. **Install Dependencies:** Install the exact packages required for the entire Phase 1 scope so they are ready:  
   pip install mcp kuzu numpy graphviz uvicorn

   *(Note: uvicorn is included to serve the sse transport layer).*  
4. **Requirements File:** Generate a requirements.txt or pyproject.toml to lock these dependencies.

## **Step 2: The FastMCP Skeleton**

Create the main server file (e.g., server.py).

1. **Import FastMCP:** from mcp.server.fastmcp import FastMCP  
2. **Initialize Server:** Instantiate the server with the name of our engine.  
   \# server.py  
   from mcp.server.fastmcp import FastMCP

   \# Initialize FastMCP  
   mcp \= FastMCP("ProjectLogicEngine")

## **Step 3: Implement Health Check (Dummy Tool)**

Before building the complex temporal engine, we must ensure the LLM can successfully call tools on this server.

1. **Create a Ping Tool:** Use the @mcp.tool() decorator to create a simple health check.  
   @mcp.tool()  
   def ping() \-\> str:  
       """Health check tool to verify the MCP server is running and responsive."""  
       return "pong: ProjectLogicEngine is online."

2. **Create a System Info Resource:** Use the @mcp.resource() decorator to create a basic read-only endpoint.  
   @mcp.resource("system://info")  
   def get\_system\_info() \-\> str:  
       """Returns basic server status."""  
       return "Engine Status: Awaiting Phase 1 Database Initialization."

## **Step 4: Transport Layer Configuration**

The server must support both stdio (for direct desktop/CLI integration) and sse (for remote agentic frameworks). FastMCP handles this gracefully.

At the bottom of your server.py, configure the execution block so it can be run as a standard script, but also leaves the ASGI app exposed for uvicorn.

if \_\_name\_\_ \== "\_\_main\_\_":  
    \# By default, mcp.run() uses stdio transport  
    mcp.run()

*Agent Note:* To run the SSE version, the framework will use uvicorn server:mcp.asgi\_app \--port 8000\. Ensure your code structure supports this.

## **Step 5: Test-Driven Verification**

Write a small test script (test\_phase\_0.py) or provide terminal commands to verify the setup:

1. **Syntax Check:** Run python server.py \--help (FastMCP provides a built-in CLI) to ensure there are no syntax errors.  
2. **Verify Dependencies:** Ensure import kuzu and import numpy do not throw ModuleNotFoundError when testing the environment.  
3. **Agent Checkpoint:** Stop here and report successful environment initialization. Do not proceed to Kùzu implementation until instructed to start Phase 1\.