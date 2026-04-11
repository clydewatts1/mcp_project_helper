from server import get_schema, get_project_tasks, get_project_graph
import asyncio

async def test_resources():
    print("1. Testing system://schema...")
    schema = get_schema()
    print(f"Schema: {schema}")
    
    print("\n2. Testing project://T1/tasks...")
    tasks = get_project_tasks("T1")
    print("Tasks Table:")
    print(tasks)
    
    print("\n3. Testing project://T1/state/export/image...")
    graph = get_project_graph("T1")
    if isinstance(graph, dict) and graph.get("type") == "image":
        print("Graph generated successfully.")
        print(f"MimeType: {graph.get('mimeType')}")
        print(f"Data length: {len(graph.get('data'))}")
    else:
        print(f"Error generating graph: {graph}")

if __name__ == "__main__":
    asyncio.run(test_resources())
