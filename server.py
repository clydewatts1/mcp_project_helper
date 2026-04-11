import kuzu
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
