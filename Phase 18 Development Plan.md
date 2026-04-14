# **Development Plan: Phase 18 (Advanced Agentic PM Tools & Visualizations)**

**ATTENTION CODING AGENT (ANTIGRAVITY):** This is your Phase 18 architectural blueprint. Your objective is to implement a suite of tools specifically optimized for high-speed, multimodal LLMs (like Gemini Flash).

These tools prioritize context window efficiency (returning only the "diff"), complex in-memory diagnostics (so the LLM doesn't hallucinate critical path tracing), and multimodal visual generation (Gantt charts).

## **Objective**

Implement get\_project\_delta, semantic\_task\_search, analyze\_root\_cause, simulate\_impact, export\_gantt\_chart, and generate\_human\_decision\_prompt.

## **Step 1: Context & Token Efficiency Tools**

LLMs should not read 1,000 tasks to find the 3 that are failing. Add these tools to server.py:

**1\. get\_project\_delta(project\_id: str)**

@mcp.tool()  
def get\_project\_delta(project\_id: str) \-\> str:  
    """Returns ONLY the tasks that have slipped their baseline schedule or budget."""  
    query \= """  
    MATCH (p:Project {id: $pid})-\[:CONTAINS\]-\>(t:Task)  
    WHERE (t.est\_date \> t.baseline\_est\_date) OR (t.actual\_cost \> t.baseline\_cost)  
    RETURN t.name, t.est\_date, t.baseline\_est\_date, t.actual\_cost, t.baseline\_cost  
    """  
    res \= conn.execute(query, {"pid": project\_id})  
    table \= "| Task | Current Start | Baseline Start | Actual Cost | Baseline Cost |\\n|---|---|---|---|---|\\n"  
    count \= 0  
    while res.has\_next():  
        row \= res.get\_next()  
        table \+= f"| {row\[0\]} | {row\[1\]} | {row\[2\]} | ${row\[3\] or 0} | ${row\[4\] or 0} |\\n"  
        count \+= 1  
    if count \== 0: return "No deviations from baseline detected."  
    return table

**2\. semantic\_task\_search(keyword: str)**

@mcp.tool()  
def semantic\_task\_search(keyword: str) \-\> str:  
    """Searches task names and descriptions across the database for a keyword."""  
    \# Using simple CONTAINS for broad matching  
    query \= """  
    MATCH (p:Project)-\[:CONTAINS\]-\>(t:Task)  
    WHERE t.name CONTAINS $kw OR t.description CONTAINS $kw  
    RETURN p.id, t.name, t.description, t.status  
    """  
    res \= conn.execute(query, {"kw": keyword})  
    table \= "| Project | Task | Description | Status |\\n|---|---|---|---|\\n"  
    count \= 0  
    while res.has\_next():  
        row \= res.get\_next()  
        table \+= f"| {row\[0\]} | {row\[1\]} | {row\[2\]} | {row\[3\]} |\\n"  
        count \+= 1  
    if count \== 0: return f"No tasks found matching keyword '{keyword}'."  
    return table

## **Step 2: Diagnostic & "Dry-Run" Tools**

Allow the LLM to ask "Why?" and "What If?" without mutating the main graph or tracing 50 nodes manually.

**1\. analyze\_root\_cause(project\_id: str)**

@mcp.tool()  
def analyze\_root\_cause(project\_id: str) \-\> str:  
    """Analyzes the critical path to find the specific tasks causing project delays."""  
    \# 1\. First get the critical path tasks  
    cp\_string \= get\_critical\_path(project\_id)  
    if "Project empty" in cp\_string: return "Project is empty."  
      
    cp\_tasks \= \[t.strip() for t in cp\_string.replace(f"Critical Path for {project\_id}: ", "").split("-\>")\]  
      
    \# 2\. Check their baselines  
    report \= f"\#\#\# Root Cause Analysis for {project\_id}\\n\\n"  
    found\_slip \= False  
      
    for task in cp\_tasks:  
        res \= conn.execute("MATCH (t:Task {name: $name}) RETURN t.duration, t.est\_date, t.baseline\_est\_date", {"name": task})  
        if res.has\_next():  
            dur, est, b\_est \= res.get\_next()  
            if est and b\_est and est \> b\_est:  
                report \+= f"- \*\*{task}\*\*: Slipped\! Baseline Start was {b\_est}, now currently {est}.\\n"  
                found\_slip \= True  
                  
    if not found\_slip:  
        return report \+ "Critical path is healthy and aligned with baseline."  
    return report

**2\. simulate\_impact(project\_id: str, task\_name: str, added\_duration: int)**

@mcp.tool()  
def simulate\_impact(project\_id: str, task\_name: str, added\_duration: int) \-\> str:  
    """Simulates adding duration to a task to see if the overall project end date changes."""  
    \# Get current project end date  
    res\_orig \= conn.execute("MATCH (p:Project {id: $pid})-\[:CONTAINS\]-\>(t:Task) RETURN max(t.eft\_date)", {"pid": project\_id})  
    orig\_end \= res\_orig.get\_next()\[0\] if res\_orig.has\_next() else None  
      
    \# Simulate by temporarily updating, recalculating, capturing, and rolling back  
    conn.execute("MATCH (t:Task {name: $name}) SET t.duration \= t.duration \+ $add", {"name": task\_name, "add": int(added\_duration)})  
    \_recalculate\_timeline(project\_id)  
      
    res\_new \= conn.execute("MATCH (p:Project {id: $pid})-\[:CONTAINS\]-\>(t:Task) RETURN max(t.eft\_date)", {"pid": project\_id})  
    new\_end \= res\_new.get\_next()\[0\] if res\_new.has\_next() else None  
      
    \# Rollback  
    conn.execute("MATCH (t:Task {name: $name}) SET t.duration \= t.duration \- $add", {"name": task\_name, "add": int(added\_duration)})  
    \_recalculate\_timeline(project\_id)  
      
    if orig\_end \== new\_end:  
        return f"Safe. Adding {added\_duration} days to {task\_name} consumes Float but does NOT delay the project (End date remains {orig\_end})."  
    else:  
        return f"CRITICAL IMPACT: Adding {added\_duration} days to {task\_name} pushes the project end date from {orig\_end} to {new\_end}."

## **Step 3: Multimodal Gantt Chart Resource**

LLMs like Gemini can process images to understand visual density. Add matplotlib to requirements.txt (pip install matplotlib).

import matplotlib.pyplot as plt  
import matplotlib.dates as mdates  
import io

@mcp.resource("project://{project\_id}/state/export/gantt")  
def export\_gantt\_chart(project\_id: str):  
    """Generates a visual Gantt chart PNG of the project timeline."""  
    query \= """  
    MATCH (p:Project {id: $pid})-\[:CONTAINS\]-\>(t:Task)  
    RETURN t.name, t.est\_date, t.eft\_date  
    ORDER BY t.est\_date DESC  
    """  
    res \= conn.execute(query, {"pid": project\_id})  
      
    tasks \= \[\]  
    starts \= \[\]  
    ends \= \[\]  
      
    while res.has\_next():  
        row \= res.get\_next()  
        if row\[1\] and row\[2\]:  
            tasks.append(row\[0\])  
            starts.append(np.datetime64(row\[1\]))  
            ends.append(np.datetime64(row\[2\]))  
              
    if not tasks: return {"type": "text", "text": "No valid tasks found."}  
      
    fig, ax \= plt.subplots(figsize=(10, len(tasks) \* 0.5 \+ 2))  
      
    \# Convert numpy dates to matplotlib dates  
    start\_dates \= \[mdates.date2num(d.astype(datetime.date)) for d in starts\]  
    end\_dates \= \[mdates.date2num(d.astype(datetime.date)) for d in ends\]  
    durations \= \[e \- s for s, e in zip(start\_dates, end\_dates)\]  
      
    ax.barh(tasks, durations, left=start\_dates, color='skyblue', edgecolor='black')  
    ax.xaxis\_date()  
    ax.xaxis.set\_major\_formatter(mdates.DateFormatter('%Y-%m-%d'))  
    plt.xticks(rotation=45)  
    plt.title(f"Gantt Chart: {project\_id}")  
    plt.tight\_layout()  
      
    buf \= io.BytesIO()  
    plt.savefig(buf, format='png')  
    buf.seek(0)  
    base64\_data \= base64.b64encode(buf.read()).decode('utf-8')  
    plt.close(fig)  
      
    return {"type": "image", "data": base64\_data, "mimeType": "image/png"}

## **Step 4: Human-AI Decision Prompting**

Give the AI a tool to format complex escalations for the human operator.

@mcp.tool()  
def generate\_human\_decision\_prompt(task\_name: str, conflict\_description: str) \-\> str:  
    """Formats an escalation prompt for the human operator when the AI cannot resolve a conflict safely."""  
    prompt \= f"🚨 \*\*HUMAN ESCALATION REQUIRED\*\* 🚨\\n\\n"  
    prompt \+= f"\*\*Issue on Task:\*\* \`{task\_name}\`\\n"  
    prompt \+= f"\*\*Conflict:\*\* {conflict\_description}\\n\\n"  
    prompt \+= "The Auto-Leveler cannot resolve this without impacting the baseline. Please choose an intervention:\\n\\n"  
    prompt \+= "- \[ \] \*\*Option A: Increase Budget\*\* (Authorize overtime or assign additional resources to crash the schedule).\\n"  
    prompt \+= "- \[ \] \*\*Option B: Accept Delay\*\* (Allow the Critical Path to push back the project end date).\\n"  
    prompt \+= "- \[ \] \*\*Option C: Cut Scope\*\* (Reduce the duration of this task or a downstream task to regain time).\\n\\n"  
    prompt \+= "\*Reply with your choice and I will execute the necessary graph changes.\*"  
    return prompt

## **Step 5: Finalization & Documentation**

Update the MANUAL.md to document the new export\_gantt\_chart resource and the new diagnostic tools. Restart the server and test using the MCP Inspector.