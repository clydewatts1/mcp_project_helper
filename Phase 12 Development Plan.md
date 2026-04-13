# **Development Plan: Phase 12 (Dependency Impact & Traceability)**

**ATTENTION CODING AGENT (ANTIGRAVITY):** This is your Phase 12 architectural blueprint. Your objective is to implement the get\_task\_children and get\_task\_parents tools.

You must expand these tools to include an optional boolean flag that fetches assigned resources, and ensure they return a comprehensive Markdown table containing the task's duration, early start/finish dates, status, and the aggregated list of resources.

## **Objective**

Enhance the variable-depth tree traversal tools to provide maximum context to the LLM regarding downstream impacts and upstream prerequisites.

## **Step 1: Implement get\_task\_children (Downstream Impact)**

Implement the following Python code directly into server.py. Notice the use of f-strings to safely inject the depth parameter, and Kùzu's collect() to aggregate resources.

@mcp.tool()  
def get\_task\_children(task\_name: str, depth: int \= 1, include\_resources: bool \= False) \-\> str:  
    """  
    Returns a list of downstream dependent tasks (children) up to a specified depth.  
    Depth 1 \= direct children. Depth 2 \= children and grandchildren.  
    """  
    depth \= max(1, min(depth, 10)) \# Bound between 1 and 10  
      
    if include\_resources:  
        query \= f"""  
        MATCH (t:Task {{name: $name}})-\[e:DEPENDS\_ON\*1..{depth}\]-\>(child:Task)  
        OPTIONAL MATCH (child)\<-\[:WORKS\_ON\]-(r:Resource)  
        RETURN child.name, min(length(e)) AS depth, child.duration, child.est\_date, child.eft\_date, child.status, collect(r.name) AS resources  
        ORDER BY depth, child.est\_date  
        """  
    else:  
        query \= f"""  
        MATCH (t:Task {{name: $name}})-\[e:DEPENDS\_ON\*1..{depth}\]-\>(child:Task)  
        RETURN child.name, min(length(e)) AS depth, child.duration, child.est\_date, child.eft\_date, child.status  
        ORDER BY depth, child.est\_date  
        """  
          
    res \= conn.execute(query, {"name": task\_name})  
      
    if include\_resources:  
        table \= "| Child Task | Depth | Duration | Start Date | End Date | Status | Assigned Resources |\\n"  
        table \+= "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\\n"  
    else:  
        table \= "| Child Task | Depth | Duration | Start Date | End Date | Status |\\n"  
        table \+= "| :--- | :--- | :--- | :--- | :--- | :--- |\\n"  
          
    count \= 0  
    while res.has\_next():  
        row \= res.get\_next()  
        if include\_resources:  
            resources \= ", ".join(\[r for r in row\[6\] if r\]) if row\[6\] else "None"  
            table \+= f"| {row\[0\]} | {row\[1\]} | {row\[2\]}d | {row\[3\]} | {row\[4\]} | {row\[5\]} | {resources} |\\n"  
        else:  
            table \+= f"| {row\[0\]} | {row\[1\]} | {row\[2\]}d | {row\[3\]} | {row\[4\]} | {row\[5\]} |\\n"  
        count \+= 1  
          
    if count \== 0:  
        return f"No downstream children found for '{task\_name}' within depth {depth}."  
    return table

## **Step 2: Implement get\_task\_parents (Upstream Drivers)**

Implement the exact reverse traversal logic for upstream dependencies.

@mcp.tool()  
def get\_task\_parents(task\_name: str, depth: int \= 1, include\_resources: bool \= False) \-\> str:  
    """  
    Returns a list of upstream tasks (parents/prerequisites) up to a specified depth.  
    Depth 1 \= direct parents. Depth 2 \= parents and grandparents.  
    """  
    depth \= max(1, min(depth, 10)) \# Bound between 1 and 10  
      
    if include\_resources:  
        query \= f"""  
        MATCH (parent:Task)-\[e:DEPENDS\_ON\*1..{depth}\]-\>(t:Task {{name: $name}})  
        OPTIONAL MATCH (parent)\<-\[:WORKS\_ON\]-(r:Resource)  
        RETURN parent.name, min(length(e)) AS depth, parent.duration, parent.est\_date, parent.eft\_date, parent.status, collect(r.name) AS resources  
        ORDER BY depth, parent.eft\_date  
        """  
    else:  
        query \= f"""  
        MATCH (parent:Task)-\[e:DEPENDS\_ON\*1..{depth}\]-\>(t:Task {{name: $name}})  
        RETURN parent.name, min(length(e)) AS depth, parent.duration, parent.est\_date, parent.eft\_date, parent.status  
        ORDER BY depth, parent.eft\_date  
        """  
          
    res \= conn.execute(query, {"name": task\_name})  
      
    if include\_resources:  
        table \= "| Parent Task | Depth | Duration | Start Date | End Date | Status | Assigned Resources |\\n"  
        table \+= "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\\n"  
    else:  
        table \= "| Parent Task | Depth | Duration | Start Date | End Date | Status |\\n"  
        table \+= "| :--- | :--- | :--- | :--- | :--- | :--- |\\n"  
          
    count \= 0  
    while res.has\_next():  
        row \= res.get\_next()  
        if include\_resources:  
            resources \= ", ".join(\[r for r in row\[6\] if r\]) if row\[6\] else "None"  
            table \+= f"| {row\[0\]} | {row\[1\]} | {row\[2\]}d | {row\[3\]} | {row\[4\]} | {row\[5\]} | {resources} |\\n"  
        else:  
            table \+= f"| {row\[0\]} | {row\[1\]} | {row\[2\]}d | {row\[3\]} | {row\[4\]} | {row\[5\]} |\\n"  
        count \+= 1  
          
    if count \== 0:  
        return f"No upstream parents found for '{task\_name}' within depth {depth}."  
    return table

## **Step 3: Update Documentation**

Because you are adding two new MCP tools, you MUST update the system documentation to prevent schema drift.

1. **MANUAL.md**: Update the tool reference section to describe get\_task\_children and get\_task\_parents and mention the new include\_resources optional parameter.  
2. **mcp\_components.md**: Update the tool specifications so the LLM knows it can pass include\_resources: true.

## **Step 4: Test-Driven Verification**

1. Restart the server.py instance.  
2. Using the MCP Inspector, execute get\_task\_children with include\_resources set to True.  
3. Verify that the Markdown table successfully renders the Start Date, End Date, Duration, and a comma-separated list of Resources without failing on index out-of-bounds errors.