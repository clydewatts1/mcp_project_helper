# **Development Plan: Phase 2 (Resources, Skills & Financials)**

**ATTENTION CODING AGENT (ANTIGRAVITY):** This is your Phase 2 architectural blueprint. You are to expand the existing FastMCP server and Kùzu database to support Resources, Skills, Assignments, and Financial calculations. Adhere strictly to the logic gates and warning mechanisms defined below.

## **Objective**

Expand the graph schema to include Resource and Skill nodes. Implement the assign\_resource tool, enforcing "State Monitors" (Warning Triggers for over-allocation and skill mismatches). Implement basic Financial Reporting.

## **Step 1: Schema Expansion**

Extend the database initialization logic (from Phase 1\) to execute these additional Cypher queries on startup if the tables do not exist. **Maintain strict typing.**

// Node Tables  
CREATE NODE TABLE Resource (name STRING, description STRING, type STRING, cost\_rate DOUBLE, PRIMARY KEY (name));  
CREATE NODE TABLE Skill (name STRING, description STRING, PRIMARY KEY (name));

// Edge Tables  
CREATE REL TABLE WORKS\_ON (FROM Resource TO Task, allocation INT);  
CREATE REL TABLE HAS\_SKILL (FROM Resource TO Skill, proficiency STRING);  
CREATE REL TABLE REQUIRES\_SKILL (FROM Task TO Skill);

## **Step 2: Implement Entity & Edge Tools**

Add the following tools using @mcp.tool(). Ensure try/except self-healing loops are used for database executions.

1. **add\_resource(name: str, type: str, cost\_rate: float, description: str \= "")**  
   * *Validation:* type must be "HUMAN" or "EQUIPMENT".  
   * *Cypher:* MERGE (r:Resource {name: $name, type: $type, cost\_rate: $cost\_rate, description: $description})  
2. **add\_skill(name: str, description: str \= "")**  
   * *Cypher:* MERGE (s:Skill {name: $name, description: $description})  
3. **grant\_skill(resource\_name: str, skill\_name: str, proficiency: str \= "Intermediate")**  
   * *Cypher:* MATCH (r:Resource {name: $resource\_name}), (s:Skill {name: $skill\_name}) MERGE (r)-\[:HAS\_SKILL {proficiency: $proficiency}\]-\>(s)  
4. **require\_skill(task\_name: str, skill\_name: str)**  
   * *Cypher:* MATCH (t:Task {name: $task\_name}), (s:Skill {name: $skill\_name}) MERGE (t)-\[:REQUIRES\_SKILL\]-\>(s)

## **Step 3: The Assignment Engine & State Monitors**

This is the most complex tool. It must assign a resource but actively check for warnings. Do **NOT** block execution for warnings.

**assign\_resource(resource\_name: str, task\_name: str, allocation: int)**

1. **Gate 1 (Strict):** Verify Resource and Task exist. If not, raise ValueError.  
2. **Execute Assignment:** MERGE (r)-\[:WORKS\_ON {allocation: $allocation}\]-\>(t)  
3. **State Monitor A (Skill Check):** \* Query: Does task\_name have REQUIRES\_SKILL edges? If yes, does resource\_name have matching HAS\_SKILL edges?  
   * If missing: Append to warning string: "\[WARNING: Skill Mismatch\] {resource\_name} lacks required skills for {task\_name}."  
4. **State Monitor B (Over-allocation Check):**  
   * Do this math in Python to avoid Cypher date-overlap complexities.  
   * Query all tasks assigned to resource\_name, returning est\_date, eft\_date, and allocation.  
   * Check if the sum of allocation exceeds 100 for any overlapping date window (comparing YYYY-MM-DD strings).  
   * If \> 100: Append to warning string: "\[WARNING: Over-allocation\] {resource\_name} exceeds 100% capacity during overlapping tasks."  
5. **Return:** Return a success message appended with any triggered warnings.

## **Step 4: Implement Financial & Reporting Resources**

Use @mcp.resource() to expose dynamic reports to the LLM.

1. **project://{project\_id}/reports/budget**  
   * *Logic:* Fetch all Tasks and their assigned Resources via WORKS\_ON.  
   * *Calculation:* For each Task: Task Cost \+ SUM(Resource.cost\_rate \* Task.duration \* (WORKS\_ON.allocation / 100.0))  
   * *Output:* Return a Markdown formatted string detailing the Fixed Costs, Resource Costs, and Total Project Cost.  
2. **project://{project\_id}/reports/allocation**  
   * *Logic:* Identify any resources that currently have \> 100% overlapping allocations across the project.  
   * *Output:* Return a Markdown list of over-allocated resources, the specific tasks causing the overlap, and the problematic date windows.

## **Step 5: Test-Driven Verification**

Create a local test script test\_phase\_2.py:

1. Create a Task (duration: 5, cost: 1000).  
2. Create a Resource (cost\_rate: 500/day).  
3. Require skill "Python" on the Task.  
4. Assign Resource to Task at 50% allocation without granting the skill.  
   * *Assert:* The assignment succeeds, but returns the "Skill Mismatch" warning.  
5. Create a second overlapping Task and assign the same Resource at 60% allocation.  
   * *Assert:* The assignment succeeds, but returns the "Over-allocation" warning.  
6. Check Budget Report.  
   * *Assert:* Cost equals $1000 \+ (5 days \* $500 \* 0.5) \+ (overlap task costs).