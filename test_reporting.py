import server
import asyncio

async def test_reporting():
    print("--- Phase 2 Step 4: Reporting Verification ---")
    server.conn.execute("MATCH (n) DETACH DELETE n")
    
    # 1. Setup Data
    print("1. Setting up project with costs and overlaps...")
    server.create_project("R1", "2026-08-03", "Reporting Test") # Aug 3 is Monday
    server.add_task("R1", "Task A", 5, 1000.0, "The Task") # Aug 3 - Aug 7
    server.add_task("R1", "Task B", 5, 0.0, "Overlap Task") # Aug 3 - Aug 7
    server.add_resource("Clyde", "HUMAN", 500.0) # $500/day
    server.assign_resource("Clyde", "Task A", 50) # 50% of $500 * 5 days = $1250. Task A Total should be $2250.
    server.assign_resource("Clyde", "Task B", 60) # Over-allocation
    
    # 2. Test Budget Report
    print("\n2. Fetching Budget Report...")
    budget = server.get_budget_report("R1")
    print("Budget Report Output:")
    print(budget)
    
    # 3. Test Allocation Report
    print("\n3. Fetching Allocation Report...")
    allocation = server.get_allocation_report("R1")
    print("Allocation Report Output:")
    print(allocation)

if __name__ == "__main__":
    asyncio.run(test_reporting())
