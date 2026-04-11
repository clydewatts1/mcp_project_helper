from server import create_project, add_task, create_dependency, conn
import asyncio

def check_dates():
    res = conn.execute("MATCH (t:Task) RETURN t.name, t.est_date, t.eft_date ORDER BY t.name")
    while res.has_next():
        print(f"Task: {res.get_next()}")

async def test_engine():
    print("--- Temporal Engine Test ---")
    # Clean previous test data safely
    conn.execute("MATCH (n) DETACH DELETE n")

    print("1. Creating Project starting Friday 2026-05-01...")
    create_project("T1", "2026-05-01", "Engine Test")
    
    print("2. Adding Task A (1 day)...")
    add_task("T1", "A", 1, 0)
    
    print("3. Adding Task B (2 days) depending on A (lag 0)...")
    add_task("T1", "B", 2, 0)
    create_dependency("A", "B", 0)
    
    print("4. Adding Task C (1 day) depending on both A (lag 0) and B (lag 1)...")
    add_task("T1", "C", 1, 0)
    create_dependency("A", "C", 0) # A-next: Monday
    create_dependency("B", "C", 1) # B-next: Thursday (Tuesday + 1 working day + 1 day lag = Thursday)
    
    print("\n--- Results ---")
    check_dates()

if __name__ == "__main__":
    asyncio.run(test_engine())
