import server
import asyncio

def test_phase_2():
    print("--- Phase 2: Final Test-Driven Verification ---")
    server.conn.execute("MATCH (n) DETACH DELETE n")
    
    # 1. Setup entities
    print("1. Setup: Creating Project, Task, Resource, and Skill requirement...")
    server.create_project("FINAL", "2026-09-07", "Phase 2 Final") # Sept 7 is Monday
    server.add_task("FINAL", "CoreTask", 5, 1000.0) # $1000 fixed
    server.add_resource("Alice", "HUMAN", 500.0) # $500/day
    server.add_skill("Python", "Coding")
    server.require_skill("CoreTask", "Python")
    
    # 2. Assign without skill
    print("2. Assigning Alice to CoreTask (50%) without Python skill...")
    res = server.assign_resource("Alice", "CoreTask", 50)
    print(f"Result: {res}")
    assert "Skill Mismatch" in res, "Should have triggered Skill Mismatch"
    
    # 3. Create overlap and trigger Over-allocation
    print("\n3. Creating Overlapping Task and exceeding capacity (50% + 60% = 110%)...")
    server.add_task("FINAL", "ExtraTask", 3, 0.0)
    res = server.assign_resource("Alice", "ExtraTask", 60)
    print(f"Result: {res}")
    assert "Over-allocation" in res, "Should have triggered Over-allocation"
    
    # 4. Final Budget Assertion
    print("\n4. Verifying Budget Calculation...")
    budget = server.get_budget_report("FINAL")
    print("Budget Report:")
    print(budget)
    
    # Calculation for CoreTask:
    # Fixed: $1000
    # Resource: $500 * 5 days * 0.5 = $1250
    # Total: $2250
    assert "$2,250.00" in budget, "Budget calculation for CoreTask is incorrect"
    
    # Calculation for ExtraTask:
    # Fixed: $0
    # Resource: $500 * 3 days * 0.6 = $900
    # Total: $900
    assert "$900.00" in budget, "Budget calculation for ExtraTask is incorrect"
    
    # Grand Total: $2250 + $900 = $3150
    assert "$3,150.00" in budget, "Grand total budget is incorrect"

    print("\nPHASE 2 COMPLETE: Resource management, competency tracking, and financial intelligence verified.")

if __name__ == "__main__":
    test_phase_2()
