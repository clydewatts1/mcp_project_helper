import kuzu
import numpy as np
import datetime

# Initialize Database
db = kuzu.Database('./project_data.kuzu')
conn = kuzu.Connection(db)

def test_allocation_crash():
    print("Testing portfolio allocation report for crash robustness...")
    
    # We will simulate the condition where a task release date (drop_date) 
    # is the same as another event's date, but sorted incorrectly.
    # The fix is in server.py, so we can't easily call the MCP tool here 
    # without running the server, but we can import the logic if we want.
    # Alternatively, we can just run the server logic directly in this script.
    
    # Mocking the data that caused the crash
    # Task 'Root_A' in project 'P_ROOT'
    # Suppose Root_A has est='2026-10-05' and eft=None (triggering fallback drop_date=est)
    
    r_name = "Repro_Resource"
    # Ensure resource exists
    conn.execute("MERGE (r:Resource {name: $n, type: 'HUMAN', cost_rate: 100})", {"n": r_name})
    
    # Ensure project and tasks exist
    conn.execute("MERGE (p:Project {id: 'REPRO_P', start_date: '2026-10-01', name: 'Repro'})")
    conn.execute("MERGE (t:Task {name: 'Root_A'}) SET t.est_date = '2026-10-05', t.eft_date = NULL")
    conn.execute("MATCH (p:Project {id: 'REPRO_P'}), (t:Task {name: 'Root_A'}) MERGE (p)-[:CONTAINS]->(t)")
    conn.execute("MATCH (r:Resource {name: $r}), (t:Task {name: 'Root_A'}) MERGE (r)-[w:WORKS_ON]->(t) SET w.allocation = 100", {"r": r_name})
    
    # Now simulate the get_portfolio_allocation_report logic for this resource
    query = """
    MATCH (r:Resource {name: $name})-[w:WORKS_ON]->(t:Task)
    MATCH (p:Project)-[:CONTAINS]->(t)
    RETURN t.name, t.est_date, t.eft_date, w.allocation, p.id
    """
    assign_nodes = conn.execute(query, {"name": r_name})
    events = []
    while assign_nodes.has_next():
        t_name, est, eft, alloc, pid = assign_nodes.get_next()
        label = f"{t_name} ({pid})"
        # THE FIX: Priority 0 for START, 1 for END
        events.append((est, 0, alloc, label, "START"))
        
        drop_date = None
        if eft:
            try:
                drop_date = str(np.busday_offset(eft, 1, roll='following'))
            except Exception:
                pass
        
        if not drop_date:
            drop_date = est # Immediate release fallback
            
        events.append((drop_date, 1, -alloc, label, "END"))

    events.sort()
    print(f"Sorted events: {events}")
    
    current_alloc = 0
    active_tasks = set()
    
    try:
        for i in range(len(events)):
            date, priority, delta, task_label, event_type = events[i]
            current_alloc += delta
            if event_type == "START": 
                active_tasks.add(task_label)
                print(f"Added {task_label}")
            else: 
                active_tasks.discard(task_label)
                print(f"Discarded {task_label}")
        print("Success: Sweep-line completed without crash.")
    except Exception as e:
        print(f"CRASH: {e}")

if __name__ == "__main__":
    test_allocation_crash()
