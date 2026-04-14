# **Development Plan: Phase 19 (Critical Bug Fixes & Atomicity)**

**ATTENTION CODING AGENT (ANTIGRAVITY):** This blueprint addresses high-priority bugs discovered during live LLM integration testing. Your objective is to fix the PERT ingestion bug in the batch tools, implement transactional atomicity for batch operations, and optimize the database to prevent query timeouts.

## **Step 1: Fix PERT Batch Ingestion (P0)**

The add\_tasks\_batch tool currently fails to extract and pass the optimistic and pessimistic estimates to the add\_task function, resulting in 0.00 variance in reports.

**Action:** Update add\_tasks\_batch in server.py to explicitly handle these fields.

@mcp.tool()  
def add\_tasks\_batch(project\_id: str, tasks\_json: str) \-\> str:  
    """  
    Creates multiple tasks at once to prevent timeouts.  
    tasks\_json MUST be a valid JSON string array of objects.  
    """  
    import json  
    try:  
        tasks \= json.loads(tasks\_json)  
    except json.JSONDecodeError:  
        return '{"status": "error", "message": "tasks\_json must be a valid JSON string."}'  
          
    results \= \[\]  
    \# Wrap in transaction (Step 2\)  
    conn.execute("BEGIN TRANSACTION")  
    try:  
        for t in tasks:  
            \# CRITICAL FIX: Extract optimistic and pessimistic  
            res \= add\_task(  
                project\_id,   
                t\['name'\],   
                t\['duration'\],   
                t\['cost'\],   
                t.get('description', ''),  
                t.get('optimistic', None),  
                t.get('pessimistic', None)  
            )  
            results.append(res)  
        conn.execute("COMMIT")  
        return json.dumps({"status": "success", "tasks\_created": len(tasks)})  
    except Exception as e:  
        conn.execute("ROLLBACK")  
        return json.dumps({"status": "error", "message": f"Batch failed and rolled back. Error: {str(e)}"})

## **Step 2: Implement Batch Atomicity (P0)**

If add\_tasks\_batch or create\_dependencies\_batch fails halfway through, the database is left in a corrupted state.

**Action:** Update create\_dependencies\_batch to use explicit Kùzu transactions just like Step 1\.

    conn.execute("BEGIN TRANSACTION")  
    try:  
        for d in deps:  
            create\_dependency(d\['source'\], d\['target'\], d.get('lag', 0))  
        conn.execute("COMMIT")  
        return json.dumps({"status": "success", "dependencies\_created": len(deps)})  
    except Exception as e:  
        conn.execute("ROLLBACK")  
        return json.dumps({"status": "error", "message": f"Batch rolled back. Error: {str(e)}"})

## **Step 3: Database Indexing & Performance (P0)**

The 4-minute timeout on get\_project\_summary is unacceptable. We must index the heavily queried properties.

**Action:** Update initialize\_schema() to create indexes on startup. Add this to the migration\_queries list:

"CREATE INDEX IF NOT EXISTS ON Task(project\_id)"  
"CREATE INDEX IF NOT EXISTS ON Task(status)"  
"CREATE INDEX IF NOT EXISTS ON Resource(type)"

## **Step 4: Circular Dependency Hardening (P1)**

Update create\_dependency to return a clear JSON error showing the exact cycle path if one is detected.

**Action:** Update the cycle check in create\_dependency:

    check\_query \= "MATCH path=(t:Task {name: $target\_name})-\[\*\]-\>(s:Task {name: $source\_name}) RETURN nodes(path)"  
    try:  
        check\_res \= conn.execute(check\_query, {"source\_name": source\_name, "target\_name": target\_name})  
        if check\_res.has\_next():  
            nodes \= check\_res.get\_next()\[0\]  
            \# Extract names from the Kuzu node objects  
            path\_names \= \[n\['name'\] for n in nodes\]   
            return json.dumps({  
                "status": "error",   
                "code": "CIRCULAR\_DEPENDENCY",  
                "message": f"Creating dependency {source\_name}-\>{target\_name} would form a cycle.",  
                "current\_path": path\_names  
            })  
    except Exception as e:  
         pass \# Let the safe\_cypher\_read handle general errors later  
