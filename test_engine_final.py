import server
import numpy as np

def test_final():
    print("--- Phase 1: Final Test Verification ---")
    
    # 1. Reset Database for a clean test run
    server.conn.execute("MATCH (n) DETACH DELETE n")

    # 2. Create Project (Starting on Friday 2026-05-01)
    print("1. Creating Project P1 starting 2026-05-01 (Friday)...")
    server.create_project("P1", "2026-05-01", "Final Verification Project")
    
    # 3. Add Tasks
    print("2. Adding Task A (1 day duration)...")
    server.add_task("P1", "A", 1, 100.0, "Initial Task")
    
    print("3. Adding Task B (2 days duration)...")
    server.add_task("P1", "B", 2, 200.0, "Dependent Task")
    
    # 4. Link Tasks and trigger recalculation
    print("4. Linking A -> B (Lag 0)...")
    server.create_dependency("A", "B", 0)
    
    # 5. Final Assertions
    print("5. Running Assertions...")
    
    # Fetch Results
    res_a = server.conn.execute("MATCH (t:Task {name: 'A'}) RETURN t.est_date, t.eft_date").get_next()
    res_b = server.conn.execute("MATCH (t:Task {name: 'B'}) RETURN t.est_date, t.eft_date").get_next()
    
    # Task A should stay on Friday
    assert res_a[0] == '2026-05-01', f"A start mismatch: {res_a[0]}"
    assert res_a[1] == '2026-05-01', f"A finish mismatch: {res_a[1]}"
    print(f"  - Task A: {res_a[0]} to {res_a[1]} (OK)")
    
    # Task B must jump to Monday 2026-05-04
    # Because A finishes Friday, B (lag 0) starts next working day = Monday.
    # Duration 2 means it finishes on Tuesday 2026-05-05.
    assert res_b[0] == '2026-05-04', f"B start mismatch (expected Monday): {res_b[0]}"
    assert res_b[1] == '2026-05-05', f"B finish mismatch (expected Tuesday): {res_b[1]}"
    print(f"  - Task B: {res_b[0]} to {res_b[1]} (OK)")
    
    print("\nPHASE 1 COMPLETE: Temporal Engine logic verified and stable.")

if __name__ == "__main__":
    try:
        test_final()
    except Exception as e:
        print(f"\nVERIFICATION FAILED: {e}")
        exit(1)
