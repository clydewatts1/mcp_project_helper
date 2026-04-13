import pytest
import httpx
import json
from server import mcp, initialize_schema

@pytest.mark.asyncio
async def test_mcp_integration_call_tool(isolated_server):
    # Pre-requisite: Create the project
    await mcp.call_tool("create_project", {
        "project_id": "P_RPC",
        "start_date": "2026-01-01",
        "name": "Transport Project"
    })

    # FastMCP call_tool returns a tuple (content_list, meta_dict)
    content, meta = await mcp.call_tool("add_task", {
        "project_id": "P_RPC",
        "name": "RPC_Task",
        "duration": 5,
        "cost": 500.0
    })
    print(f"DEBUG CONTENT TYPE: {type(content)}")
    print(f"DEBUG CONTENT: {content}")
    print(f"DEBUG META: {meta}")
    
    # Check the content list
    # add_task returns the Kuzu result as a string: "[['RPC_Task']]"
    assert any("RPC_Task" in str(item) for item in content)
    
    # Verify DB state
    check = isolated_server.conn.execute("MATCH (t:Task {name: 'RPC_Task'}) RETURN t.duration").get_next()[0]
    assert check == 5
