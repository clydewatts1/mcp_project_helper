# **Development Plan: Phase 23 (API Refinement & Missing Capabilities)**

**ATTENTION CODING AGENT (ANTIGRAVITY):** This blueprint addresses the final layer of UX friction discovered during the latest LLM integration test. Your objective is to ensure all capabilities are properly exposed as @mcp.tool() endpoints, fix EVM date relativity, refactor batch inputs to native arrays, and implement missing resource/progress tools.

## **Objective**

Implement export\_project\_image\_tool, unassign\_resource, and set\_progress\_batch. Refactor batch tools to use native list\[dict\] typing. Update the EVM math to support an as\_of\_date parameter. Wire skill proficiency into the assignment warnings.

## **Step 1: Tool Exposure & Visual Export (Issues 1, 2, 4\)**

LLMs struggle to discover @mcp.resource endpoints natively. You must expose the Graphviz generation as an explicit tool. (Ensure get\_task\_children and update\_task from previous phases are also properly registered with @mcp.tool()).

**Action:** Add this tool to server.py to wrap the existing image resource:

@mcp.tool()  
def export\_project\_image\_tool(project\_id: str) \-\> str:  
    """  
    Generates a Base64 PNG of the Graphviz network diagram.   
    Call this to visually export and view the project state.  
    """  
    try:  
        result \= get\_project\_graph(project\_id) \# Call your existing function  
        if isinstance(result, dict) and "data" in result:  
            return create\_response(  
                operation="export\_project\_image",   
                status="success",   
                data={"image\_base64": result\["data"\], "format": "png"}  
            )  
        return create\_response("export\_project\_image", "error", warnings=\[str(result)\])  
    except Exception as e:  
        return create\_response("export\_project\_image", "error", warnings=\[f"Failed to generate image: {str(e)}"\])

## **Step 2: EVM Relative Dating (Issue 3\)**

EVM's Planned Value (PV) compares scheduled work against "today". If a project starts in the future, PV is correctly $0.00. We must allow the AI to run EVM reports "as of" a future date.

**Action:** Update the EVM functions in server.py:

1. Update get\_evm\_report(project\_id: str, as\_of\_date: str \= None) to accept the new parameter.  
2. Replace today \= np.datetime64(datetime.date.today()) with:  
   if as\_of\_date:  
       today \= np.datetime64(as\_of\_date)  
   else:  
       today \= np.datetime64(datetime.date.today())

3. Update the get\_evm\_report\_tool wrapper to expose it:  
   @mcp.tool()  
   def get\_evm\_report\_tool(project\_id: str, as\_of\_date: str \= None) \-\> str:  
       """  
       Generates the EVM report.   
       Use as\_of\_date (YYYY-MM-DD) to calculate Planned Value relative to a future/past date.  
       """  
       \# ... fetch string from get\_evm\_report and wrap in create\_response ...

## **Step 3: Native Arrays & Batch Progress (Issues 5 & 6\)**

FastMCP automatically handles JSON Schema translation. Using tasks\_json: str is brittle. We should use list\[dict\].

**Action 1:** Refactor Batch Tools in server.py:

Change the signatures of your batch tools to accept native lists.

@mcp.tool()  
def add\_tasks\_batch(project\_id: str, tasks: list\[dict\]) \-\> str:  
    """  
    Creates multiple tasks at once.  
    tasks: \[{"name": "T1", "duration": 5, "cost": 100, "optimistic": 4, "pessimistic": 6}\]  
    """  
    \# Remove json.loads(). Iterate directly over \`tasks\`.  
    \# ... existing transaction logic ...

*(Repeat this refactoring for create\_dependencies\_batch(dependencies: list\[dict\])).*

**Action 2:** Add set\_progress\_batch:

@mcp.tool()  
def set\_progress\_batch(updates: list\[dict\]) \-\> str:  
    """  
    Updates progress for multiple tasks at once.  
    updates: \[{"task\_name": "T1", "percent\_complete": 50}, ...\]  
    """  
    conn.execute("BEGIN TRANSACTION")  
    try:  
        results \= \[\]  
        for u in updates:  
            \# Call your existing set\_task\_progress logic here internally  
            \# or execute the Cypher directly.  
            conn.execute(  
                "MATCH (t:Task {name: $name}) SET t.percent\_complete \= $pct",   
                {"name": u\['task\_name'\], "pct": u\['percent\_complete'\]}  
            )  
            results.append(u\['task\_name'\])  
        conn.execute("COMMIT")  
        return create\_response("set\_progress\_batch", "success", data={"updated\_tasks": results})  
    except Exception as e:  
        conn.execute("ROLLBACK")  
        return create\_response("set\_progress\_batch", "error", warnings=\[str(e)\])

## **Step 4: Missing Lifecycle Tool \- Unassign Resource (Issue 7\)**

The AI needs the ability to remove a resource without deleting the resource entirely.

**Action:** Add this tool to server.py:

@mcp.tool()  
def unassign\_resource(resource\_name: str, task\_name: str) \-\> str:  
    """Removes a resource assignment from a task."""  
    query \= """  
    MATCH (r:Resource {name: $r\_name})-\[w:WORKS\_ON\]-\>(t:Task {name: $t\_name})  
    DELETE w  
    RETURN count(w)  
    """  
    try:  
        res \= conn.execute(query, {"r\_name": resource\_name, "t\_name": task\_name})  
        if res.has\_next() and res.get\_next()\[0\] \> 0:  
            \# Trigger leveler/recalculation if necessary, or just return success  
            return create\_response("unassign\_resource", "success", data={"resource": resource\_name, "task": task\_name})  
        return create\_response("unassign\_resource", "warning", warnings=\["Assignment not found."\])  
    except Exception as e:  
        return create\_response("unassign\_resource", "error", warnings=\[str(e)\])

## **Step 5: Skill Proficiency Validation (Issue 8\)**

Make the proficiency field functionally useful during assignment checks.

**Action:** Update the Skill Check block in assign\_resource (server.py):

Update the query that fetches required skills to also fetch the required proficiency level (defaulting to "Intermediate" if not set), and check it against the resource's proficiency level.

*Simple implementation:* If the task requires a skill, and the resource has it, append the proficiency levels to the output.

    \# Inside assign\_resource State Monitor A:  
    \# ... existing check ...  
        missing \= required\_skills \- possessed\_skills  
        if missing:  
            warnings.append(f"Skill Mismatch: {resource\_name} lacks required skills for {task\_name}: {', '.join(missing)}.")  
        else:  
            \# Optional: Add an info flag about proficiency levels for context  
            pass 

*(Agent Note: For full strictness, you can add an enum \["Beginner", "Intermediate", "Expert"\] and throw a warning if the resource's integer value is lower than the task's required value).*

## **Step 6: Verify and Document**

1. Update MANUAL.md to document export\_project\_image\_tool, unassign\_resource, and set\_progress\_batch.  
2. Update the batch tool documentation to explicitly state they accept native arrays of objects, NOT JSON strings.