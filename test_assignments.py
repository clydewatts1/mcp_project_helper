import server
import asyncio

async def test_assignments():
    print("--- Phase 2 Step 3: Assignment Verification ---")
    server.conn.execute("MATCH (n) DETACH DELETE n")
    
    # Setup
    server.create_project("P1", "2026-07-06", "Assignment Test") # July 6 is a Monday
    server.add_task("P1", "Task A", 5, 0) # July 6 - July 10
    server.add_task("P1", "Task B", 5, 0) # July 6 - July 10 (Overlap)
    server.add_resource("Bob", "HUMAN", 100.0)
    server.add_skill("Python", "Programming")
    server.require_skill("Task A", "Python")
    
    # 1. Test Skill Mismatch
    print("\n1. Testing Skill Mismatch (Bob lacks Python)...")
    res = server.assign_resource("Bob", "Task A", 50)
    print(res)
    
    # 2. Test Over-allocation
    print("\n2. Testing Over-allocation (50% + 60% = 110%)...")
    res = server.assign_resource("Bob", "Task B", 60)
    print(res)
    
    # 3. Test Skill Granting and Re-assignment
    print("\n3. Granting Skill and reassessing...")
    server.grant_skill("Bob", "Python", "Expert")
    res = server.assign_resource("Bob", "Task A", 50)
    print(res)

if __name__ == "__main__":
    asyncio.run(test_assignments())
