# **Development Plan: Phase 22 (Advanced Analytics & Forecasting)**

**ATTENTION CODING AGENT (ANTIGRAVITY):** This blueprint addresses the final pending feature requests (Issues \#5, \#6, and \#7) from the QA integration tests. Your objective is to expand the reporting suite to include Unassigned Task detection, Timeline Utilization heatmaps, and advanced EVM forecasting.

## **Objective**

Implement get\_unassigned\_tasks, get\_resource\_timeline, and upgrade get\_evm\_report with Estimate At Completion (EAC) metrics. Ensure all new tools utilize the create\_response JSON envelope from Phase 21\.

## **Step 1: Issue \#5 \- Unassigned Task Visibility**

Project Managers (and AI agents) need a fast way to find out what work has slipped through the cracks without iterating through hundreds of tasks.

**Action:** Add this tool to server.py:

@mcp.tool()  
def get\_unassigned\_tasks(project\_id: str) \-\> str:  
    """  
    Returns a list of all tasks in a project that currently have no resources assigned.  
    Useful for identifying gaps in project planning.  
    """  
    query \= """  
    MATCH (p:Project {id: $pid})-\[:CONTAINS\]-\>(t:Task)  
    WHERE NOT (t)\<-\[:WORKS\_ON\]-(:Resource)  
    RETURN t.name, t.duration, t.cost, t.status, t.est\_date  
    """  
    try:  
        res \= conn.execute(query, {"pid": project\_id})  
        orphaned\_tasks \= \[\]  
        while res.has\_next():  
            row \= res.get\_next()  
            orphaned\_tasks.append({  
                "task": row\[0\],  
                "duration": row\[1\],  
                "cost": row\[2\],  
                "status": row\[3\],  
                "start\_date": row\[4\]  
            })  
              
        return create\_response(  
            operation="get\_unassigned\_tasks",  
            status="success",  
            data={  
                "project\_id": project\_id,   
                "unassigned\_tasks": orphaned\_tasks,  
                "count": len(orphaned\_tasks)  
            }  
        )  
    except Exception as e:  
        return create\_response("get\_unassigned\_tasks", "error", warnings=\[f"Database error: {str(e)}"\])

## **Step 2: Issue \#6 \- Resource Utilization Timeline**

Provide a structured array showing a resource's workload load over time so the LLM can generate heatmaps or make smart assignment recommendations.

**Action:** Add this tool to server.py:

@mcp.tool()  
def get\_resource\_timeline(resource\_name: str) \-\> str:  
    """  
    Returns a timeline of tasks and allocations for a specific resource.  
    Provides the exact intervals of their workload.  
    """  
    query \= """  
    MATCH (r:Resource {name: $name})-\[w:WORKS\_ON\]-\>(t:Task)  
    OPTIONAL MATCH (p:Project)-\[:CONTAINS\]-\>(t)  
    RETURN t.name, p.id, t.est\_date, t.eft\_date, w.allocation, t.status  
    ORDER BY t.est\_date  
    """  
    try:  
        res \= conn.execute(query, {"name": resource\_name})  
        timeline \= \[\]  
        total\_assignments \= 0  
          
        while res.has\_next():  
            row \= res.get\_next()  
            timeline.append({  
                "task": row\[0\],  
                "project\_id": row\[1\],  
                "start\_date": row\[2\],  
                "end\_date": row\[3\],  
                "allocation": row\[4\],  
                "status": row\[5\]  
            })  
            total\_assignments \+= 1  
              
        if total\_assignments \== 0:  
             return create\_response("get\_resource\_timeline", "success", warnings=\[f"Resource '{resource\_name}' has no active task assignments."\])  
               
        return create\_response(  
            operation="get\_resource\_timeline",  
            status="success",  
            data={  
                "resource": resource\_name,  
                "assignments": timeline,  
                "count": total\_assignments  
            }  
        )  
    except Exception as e:  
        return create\_response("get\_resource\_timeline", "error", warnings=\[f"Database error: {str(e)}"\])

## **Step 3: Issue \#7 \- Budget Forecast (EAC & VAC)**

Upgrade the existing get\_evm\_report resource string to include predictive forecasting.

**Action:** In server.py, locate the get\_evm\_report function. Update the summary math section:

    \# ... existing PV, EV, AC calculation loops ...  
      
    \# Add Total Baseline Cost (BAC) calculation inside the loop:  
    \# bac \+= b\_cost  
      
    \# Calculate totals  
    spi \= total\_ev / total\_pv if total\_pv \> 0 else 1.0  
    cpi \= total\_ev / total\_ac if total\_ac \> 0 else 1.0  
      
    \# NEW FORECAST MATH:  
    \# BAC (Budget At Completion)  
    total\_bac \= sum(s\['b\_cost'\] for s in tasks\_stats if 'b\_cost' in s)   
      
    \# EAC (Estimate At Completion) \= BAC / CPI  
    eac \= total\_bac / cpi if cpi \> 0 else total\_bac \+ total\_ac  
      
    \# VAC (Variance At Completion) \= BAC \- EAC (Negative is bad)  
    vac \= total\_bac \- eac  
      
    report \= f"\# EVM Report: Project {project\_id} ({today})\\n\\n"  
    report \+= f"- \*\*Total Planned Value (PV)\*\*: ${total\_pv:,.2f} \*(Standard DoD/PMI calculation: Work scheduled by today)\*\\n"  
    report \+= f"- \*\*Total Earned Value (EV)\*\*: ${total\_ev:,.2f}\\n"  
    report \+= f"- \*\*Total Actual Cost (AC)\*\*: ${total\_ac:,.2f}\\n"  
    report \+= f"- \*\*Budget At Completion (BAC)\*\*: ${total\_bac:,.2f}\\n"  
      
    report \+= f"\\n\#\#\# 🔮 Forecasting Metrics\\n"  
    report \+= f"- \*\*Estimate At Completion (EAC)\*\*: ${eac:,.2f} \*(Expected final cost based on current CPI)\*\\n"  
    report \+= f"- \*\*Variance At Completion (VAC)\*\*: ${vac:,.2f} "  
    report \+= "(Expected Overage)" if vac \< 0 else "(Expected Savings)"  
      
    \# ... existing SPI/CPI string logic ...

*(Note: Ensure you extract b\_cost into the tasks\_stats dict during the while loop so you can sum it for total\_bac).*

## **Step 4: System Documentation & Validation**

1. **Update MANUAL.md:** Add get\_unassigned\_tasks and get\_resource\_timeline to the documentation. Update the get\_evm\_report description to mention EAC and VAC forecasting.  
2. **Intentional Skill Mismatch Test:** To resolve Issue \#3 from the QA report, generate a test query explicitly assigning a resource to a task where they lack the required skill. Monitor the JSON output to ensure "status": "warning" is fired with the correct mismatch text.