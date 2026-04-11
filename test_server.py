from server import mcp
import asyncio

async def test():
    print("Testing ping tool...")
    # FastMCP tools are async
    try:
        result = await mcp.call_tool("ping", {})
        print(f"Ping result: {result}")
    except Exception as e:
        print(f"Error calling tool: {e}")
    
    print("Testing system://info resource...")
    try:
        resource = await mcp.read_resource("system://info")
        print(f"Resource info: {resource}")
    except Exception as e:
        print(f"Error reading resource: {e}")

if __name__ == "__main__":
    asyncio.run(test())
