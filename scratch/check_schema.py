import kuzu
import os

db_path = 'project_data.kuzu'
if os.path.exists(db_path):
    db = kuzu.Database(db_path)
    conn = kuzu.Connection(db)
    try:
        # Check all Phase 3 properties
        fields = ["status", "baseline_est_date", "baseline_eft_date", "baseline_cost", "percent_complete"]
        for field in fields:
            res = conn.execute(f'MATCH (t:Task) RETURN t.{field} LIMIT 1')
            print(f"Prop '{field}': OK")
    except Exception as e:
        print(f"Error checking schema: {e}")
else:
    print(f"Database {db_path} not found.")
