# **Development Plan: Phase 3a (Code Hardening & Missing Features)**

**ATTENTION CODING AGENT (ANTIGRAVITY):** Before proceeding to Phase 4, you must patch critical runtime bugs in server.py and implement a missing feature from Phase 3\. Execute the following steps exactly.

## **Step 1: Fix create\_dependency (NameError and Cycle Check)**

The create\_dependency tool currently contains an undefined variable (proj\_res) causing a NameError, and a brittle string-matching logic for cycle detection ("\[1\]" in check\_res).

**Action:** Replace the entire create\_dependency function in server.py with this fortified version:

@mcp.tool()  
def create\_dependency(source\_name: str, target\_name: str, lag: int \= 0\) \-\> str:  
    """  
    Creates a dependency between two tasks (Source \-\> Target).  
    Enforces Law I: No Circular Dependencies.  
    """  
    \# Gate 1: Cycle Check (Extract exact count natively, avoid brittle string matching)  
    check\_query \= "MATCH path=(t:Task {name: $target\_name})-\[\*\]-\>(s:Task {name: $source\_name}) RETURN count(path)"  
    try:  
        check\_res \= conn.execute(check\_query, {"source\_name": source\_name, "target\_name": target\_name})  
        if check\_res.has\_next():  
            path\_count \= check\_res.get\_next()\[0\]  
            if path\_count \> 0:  
                return "Law I Violation: Circular Dependency Detected."  
    except Exception as e:  
         return f"Kuzu Error during Cycle Check: {str(e)}"

    \# Gate 2: Create Edge  
    query \= """  
    MATCH (a:Task {name: $source\_name}), (b:Task {name: $target\_name})  
    MERGE (a)-\[r:DEPENDS\_ON {lag: $lag}\]-\>(b)  
    RETURN r.lag  
    """  
    res \= safe\_cypher\_read(query, {"source\_name": source\_name, "target\_name": target\_name, "lag": lag})  
      
    \# Trigger recalculation: Correctly fetch the project\_id using the source\_name  
    proj\_query \= "MATCH (p:Project)-\[:CONTAINS\]-\>(t:Task {name: $name}) RETURN p.id"  
    proj\_res \= conn.execute(proj\_query, {"name": source\_name})  
    if proj\_res.has\_next():  
        project\_id \= proj\_res.get\_next()\[0\]  
        conflicts \= \_recalculate\_timeline(project\_id)  
        if conflicts:  
            res \+= "\\n" \+ "\\n".join(conflicts)  
              
    return res

## **Step 2: Implement the Missing clone\_scenario Tool**

You missed Step 4 of the Phase 3 plan. The system requires a "What-If" sandbox so the LLM can test scenarios safely.

**Action:** Add the following new tool to server.py. It reads the baseline project and duplicates its Tasks, Resources, and Relationships under a new Project ID.

@mcp.tool()  
def clone\_scenario(source\_project\_id: str, new\_scenario\_id: str) \-\> str:  
    """  
    Clones a project, its tasks, dependencies, and resource assignments into a sandbox.  
    Prefixes the task names with the new\_scenario\_id to maintain Primary Key uniqueness.  
    """  
    \# 1\. Create the new project clone  
    query\_proj \= """  
    MATCH (p:Project {id: $src})  
    MERGE (new\_p:Project {id: $dest, start\_date: p.start\_date, name: p.name \+ ' (Clone)'})  
    RETURN new\_p.id  
    """  
    res \= conn.execute(query\_proj, {"src": source\_project\_id, "dest": new\_scenario\_id})  
    if not res.has\_next():  
        return f"Error: Source project '{source\_project\_id}' not found."

    \# 2\. Clone Tasks and CONTAINS edges  
    query\_tasks \= """  
    MATCH (p:Project {id: $src})-\[:CONTAINS\]-\>(t:Task)  
    MATCH (new\_p:Project {id: $dest})  
    MERGE (new\_t:Task {  
        name: $dest \+ '\_' \+ t.name,   
        description: t.description,   
        duration: t.duration,   
        cost: t.cost,   
        est\_date: t.est\_date,   
        eft\_date: t.eft\_date,   
        status: t.status  
    })  
    MERGE (new\_p)-\[:CONTAINS\]-\>(new\_t)  
    """  
    conn.execute(query\_tasks, {"src": source\_project\_id, "dest": new\_scenario\_id})

    \# 3\. Clone DEPENDS\_ON edges  
    query\_deps \= """  
    MATCH (p:Project {id: $src})-\[:CONTAINS\]-\>(s:Task)-\[r:DEPENDS\_ON\]-\>(t:Task)  
    MATCH (new\_s:Task {name: $dest \+ '\_' \+ s.name})  
    MATCH (new\_t:Task {name: $dest \+ '\_' \+ t.name})  
    MERGE (new\_s)-\[:DEPENDS\_ON {lag: r.lag}\]-\>(new\_t)  
    """  
    conn.execute(query\_deps, {"src": source\_project\_id, "dest": new\_scenario\_id})  
      
    \# 4\. Clone WORKS\_ON (Resource assignments)  
    query\_works \= """  
    MATCH (p:Project {id: $src})-\[:CONTAINS\]-\>(t:Task)\<-\[w:WORKS\_ON\]-(r:Resource)  
    MATCH (new\_t:Task {name: $dest \+ '\_' \+ t.name})  
    MERGE (r)-\[:WORKS\_ON {allocation: w.allocation}\]-\>(new\_t)  
    """  
    conn.execute(query\_works, {"src": source\_project\_id, "dest": new\_scenario\_id})

    return f"Scenario cloned successfully. You can now safely test changes on project '{new\_scenario\_id}'."

## **Step 3: Fortify EVM Date Handling**

In get\_evm\_report(), if a task is created *after* a baseline is saved, b\_est will be None. Passing the string "None" to np.datetime64() crashes the server.

**Action:** In server.py, locate the get\_evm\_report function and update the PV conditional block to ensure b\_est and b\_eft are not "None" strings before parsing them:

        \# PV: Planned Value (How much work was scheduled to be done by today?)  
        pv \= 0.0  
        \# Safely parse baseline dates  
        if b\_est and b\_eft and b\_cost and str(b\_est) \!= "None" and str(b\_eft) \!= "None":  
            b\_est\_dt \= np.datetime64(b\_est)  
            b\_eft\_dt \= np.datetime64(b\_eft)  
            if today \>= b\_eft\_dt:  
                pv \= b\_cost  
            elif today \>= b\_est\_dt:  
                total\_days \= (b\_eft\_dt \- b\_est\_dt).astype(int) \+ 1  
                elapsed\_days \= (today \- b\_est\_dt).astype(int) \+ 1  
                pv \= b\_cost \* (elapsed\_days / total\_days)

## **Verification**

Once completed, run test\_safe\_read.py and execute manual tests to ensure the NameError is eliminated and scenario cloning works correctly.