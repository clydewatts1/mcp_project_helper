import asyncio
import server

async def debug_transport():
    server.initialize_schema()
    server.create_project("P", "2026-01-01", "P")
    res = await server.mcp.call_tool("add_task", {
        "project_id": "P",
        "name": "T",
        "duration": 1,
        "cost": 100.0
    })
    print(f"RESULT TYPE: {type(res)}")
    print(f"RESULT CONTENT: {res}")
    for item in res:
        print(f"ITEM TYPE: {type(item)}")
        print(f"ITEM STR: {str(item)}")

if __name__ == "__main__":
    asyncio.run(debug_transport())
