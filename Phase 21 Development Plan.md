# **Development Plan: Phase 21 (Standardized JSON Return Envelopes)**

**ATTENTION CODING AGENT (ANTIGRAVITY):** This blueprint instructs you to refactor the return values of all major MCP tools in server.py.

Currently, tools return raw strings (e.g., "Resource assigned successfully."). You must introduce a universal create\_response Python helper function and update the mutation tools to return a standardized JSON envelope. This drastically improves the LLM's ability to parse outcomes, read warnings, and self-correct.

## **Objective**

Implement the create\_response wrapper and refactor tool returns across server.py to output structured JSON matching the defined schema.

## **Step 1: Implement the Response Wrapper**

Add this helper function to server.py (near the top, after imports).

import json  
from datetime import datetime, timezone

def create\_response(operation: str, status: str, data: dict \= None, warnings: list \= None) \-\> str:  
    """  
    Standardized JSON envelope for all MCP tool responses.  
    Status should be 'success', 'warning', or 'error'.  
    """  
    response \= {  
        "status": status,  
        "operation": operation,  
        "timestamp": datetime.now(timezone.utc).isoformat(),  
        "affected\_rows": data.get("count", 1\) if data else 0,  
        "warnings": warnings or \[\],  
        "data": data or {}  
    }  
    return json.dumps(response, indent=2)

## **Step 2: Refactoring Complex Tools (Warnings)**

The most critical tool to refactor is assign\_resource, as it emits warnings that the LLM needs to parse programmatically.

**Action:** Update the return block of assign\_resource in server.py:

    \# ... existing assignment execution ...  
      
    warnings \= \[\]  
      
    \# State Monitor A: Skill Check  
    \# ... existing skill check logic ...  
        missing \= required\_skills \- possessed\_skills  
        if missing:  
            warnings.append(f"Skill Mismatch: {resource\_name} lacks required skills for {task\_name}: {', '.join(missing)}.")  
              
    \# State Monitor B: Over-allocation Check  
    over\_alloc\_msg \= \_check\_over\_allocation(resource\_name)  
    if over\_alloc\_msg:  
        warnings.append(over\_alloc\_msg)  
          
    \# Return Standardized JSON  
    status \= "warning" if warnings else "success"  
    return create\_response(  
        operation="assign\_resource",  
        status=status,  
        data={  
            "resource": resource\_name,  
            "task": task\_name,  
            "allocation": allocation  
        },  
        warnings=warnings  
    )

## **Step 3: Refactoring Standard Creation Tools**

Update the basic creation tools to use the envelope.

**1\. add\_task Return Refactor:**

    \# ... existing add\_task logic ...  
    res \= safe\_cypher\_read(query, params)  
      
    \# Handle auto-scheduler conflicts if any  
    conflicts \= \_recalculate\_timeline(project\_id)  
    status \= "warning" if conflicts else "success"  
      
    return create\_response(  
        operation="add\_task",  
        status=status,  
        data={"task": name, "project": project\_id},  
        warnings=conflicts  
    )

**2\. create\_dependency Error & Return Refactor:**

    \# ... Gate 1 Cycle Check ...  
    if path\_count \> 0:  
        return create\_response(  
            operation="create\_dependency",  
            status="error",  
            warnings=\["Law I Violation: Circular Dependency Detected."\]  
        )  
          
    \# ... Gate 2 Create Edge ...  
      
    conflicts \= \_recalculate\_timeline(project\_id)  
    status \= "warning" if conflicts else "success"  
      
    return create\_response(  
        operation="create\_dependency",  
        status=status,  
        data={"source": source\_name, "target": target\_name, "lag": lag},  
        warnings=conflicts  
    )

## **Step 4: Refactoring Deletion Tools**

Update the lifecycle management tools from Phase 13\.

**Example for delete\_task:**

    \# ... existing delete logic ...  
    if not res.has\_next() or res.get\_next()\[0\] \== 0:  
        return create\_response("delete\_task", "error", warnings=\[f"Task '{task\_name}' not found."\])  
          
    \_safe\_delete\_edges("Task", "name", task\_name, \["DEPENDS\_ON", "WORKS\_ON", "REQUIRES\_SKILL", "CONTAINS"\])  
    conn.execute("MATCH (t:Task {name: $name}) DELETE t", {"name": task\_name})  
      
    return create\_response("delete\_task", "success", data={"task": task\_name, "count": 1})

## **Step 5: Global Validation**

1. Review all @mcp.tool() endpoints in server.py.  
2. Replace simple string returns (return "Success..." or return "Error...") with the create\_response wrapper.  
3. Test using the MCP Inspector to ensure the tools return beautifully formatted JSON payloads.