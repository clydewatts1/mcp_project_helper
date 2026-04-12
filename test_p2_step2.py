import server
import asyncio

async def test_p2_step2():
    print("--- Phase 2 Step 2: Tool Verification ---")
    
    # 0. Setup: Create Project and Task
    print("0. Setup: Creating Project and Task...")
    server.conn.execute("MATCH (n) DETACH DELETE n")
    server.create_project("P1", "2026-06-01", "Verif Project")
    server.add_task("P1", "Task A", 5, 1000.0, "The Task")

    # 1. Add Resource
    print("1. Adding Resource 'Bob' (HUMAN)...")
    res = server.add_resource("Bob", "HUMAN", 50.0, "Lead Developer")
    print(f"Result: {res}")
    
    # 2. Add Skill
    print("\n2. Adding Skill 'Python'...")
    res = server.add_skill("Python", "Programming Language")
    print(f"Result: {res}")
    
    # 3. Grant Skill
    print("\n3. Granting 'Expert' Python skill to 'Bob'...")
    res = server.grant_skill("Bob", "Python", "Expert")
    print(f"Result: {res}")
    
    # 4. Require Skill (Assuming Task A exists from previous tests)
    print("\n4. Requiring Python skill for 'Task A'...")
    res = server.require_skill("Task A", "Python")
    print(f"Result: {res}")
    
    # 5. Summary Check
    print("\n--- Summary Check ---")
    r_count = server.conn.execute("MATCH (r:Resource) RETURN count(*)").get_next()[0]
    s_count = server.conn.execute("MATCH (s:Skill) RETURN count(*)").get_next()[0]
    hs_count = server.conn.execute("MATCH ()-[r:HAS_SKILL]->() RETURN count(*)").get_next()[0]
    rs_count = server.conn.execute("MATCH ()-[r:REQUIRES_SKILL]->() RETURN count(*)").get_next()[0]
    
    print(f"Resources: {r_count}")
    print(f"Skills: {s_count}")
    print(f"HAS_SKILL edges: {hs_count}")
    print(f"REQUIRES_SKILL edges: {rs_count}")

if __name__ == "__main__":
    asyncio.run(test_p2_step2())
