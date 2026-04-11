from server import create_project, add_task, create_dependency
import asyncio

async def test_tools():
    print("1. Creating Project...")
    res = create_project("P1", "2026-05-01", "Construction Alpha")
    print(f"Result: {res}")
    
    print("\n2. Adding Task A...")
    res = add_task("P1", "Task A", 5, 1000.0, "Foundations")
    print(f"Result: {res}")
    
    print("\n3. Adding Task B...")
    res = add_task("P1", "Task B", 3, 500.0, "Framing")
    print(f"Result: {res}")
    
    print("\n4. Creating Dependency A -> B...")
    res = create_dependency("Task A", "Task B", 1)
    print(f"Result: {res}")
    
    print("\n5. Testing Law I: Circular Dependency B -> A...")
    res = create_dependency("Task B", "Task A", 0)
    print(f"Result: {res}")

if __name__ == "__main__":
    asyncio.run(test_tools())
