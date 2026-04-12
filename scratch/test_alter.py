import kuzu
import os

db_path = 'project_data.kuzu'
if os.path.exists(db_path):
    db = kuzu.Database(db_path)
    conn = kuzu.Connection(db)
    print("Testing ALTER TABLE Task ADD status STRING DEFAULT 'AI_DRAFT'...")
    try:
        conn.execute("ALTER TABLE Task ADD status STRING DEFAULT 'AI_DRAFT'")
        print("Success!")
    except Exception as e:
        print(f"Error: {e}")
else:
    print("Database not found.")
