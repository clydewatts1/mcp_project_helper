# **Development Plan: Phase 3 (Advanced Intelligence & Collaboration)**

**ATTENTION CODING AGENT (ANTIGRAVITY):** This is your Phase 3 architectural blueprint. Your objective is to introduce advanced human-in-the-loop features, baseline tracking (EVM), and sandboxed scenario simulation. Ensure you adhere strictly to Kùzu's typing and schema modification rules.

## **Objective**

Implement the "Draft & Lock" protocol for human-AI collaboration, add project baselining for Earned Value Management (EVM) reporting, and build a sandbox cloning tool for safe "what-if" simulations.

## **Step 1: Schema Expansion (Baselines & Status)**

Extend the database initialization logic. Note: In Kùzu, you may need to write a migration script or recreate the tables if adding properties to existing node tables is not supported in the current version. Ensure the Task node can support these properties:

* status (STRING) \- Default: "AI\_DRAFT". Can be "HUMAN\_LOCKED".  
* baseline\_est\_date (STRING)  
* baseline\_eft\_date (STRING)  
* baseline\_cost (DOUBLE)  
* percent\_complete (INT) \- 0 to 100

## **Step 2: The "Draft & Lock" Protocol**

1. **Update add\_task:** Ensure new tasks default to status: "AI\_DRAFT".  
2. **Implement lock\_task(task\_name: str):**  
   * Changes the task status to "HUMAN\_LOCKED".  
3. **Update \_recalculate\_timeline() (Critical Path Engine):**  
   * If the engine tries to change the est\_date or eft\_date of a "HUMAN\_LOCKED" task due to a dependency shift, it MUST NOT change the date.  
   * Instead, it should throw a ValueError or append a critical warning: "\[CRITICAL CONFLICT\] Task {task\_name} is locked by human but dependencies push its start date to {new\_date}."

## **Step 3: Baseline & Earned Value Management (EVM)**

1. **Implement save\_baseline(project\_id: str) Tool:**  
   * Cypher: MATCH (p:Project {id: $project\_id})-\[:CONTAINS\]-\>(t:Task) SET t.baseline\_est\_date \= t.est\_date, t.baseline\_eft\_date \= t.eft\_date, t.baseline\_cost \= t.cost  
2. **Implement update\_progress(task\_name: str, percent\_complete: int) Tool:**  
   * Cypher: MATCH (t:Task {name: $task\_name}) SET t.percent\_complete \= $percent\_complete  
3. **Implement project://{project\_id}/reports/earned\_value Resource:**  
   * Fetch all tasks. Calculate Planned Value (PV), Earned Value (EV), and Actual Cost (AC) based on baseline\_cost vs cost and percent\_complete.  
   * Return a Markdown report showing Schedule Performance Index (SPI) and Cost Performance Index (CPI).

## **Step 4: The "What-If" Sandbox**

Implement a tool to clone the entire project structure so the AI can simulate changes without corrupting the main timeline.

**clone\_scenario(source\_project\_id: str, new\_scenario\_id: str)**

1. Read all Tasks, Resources, Skills, and Edges associated with source\_project\_id into Python memory.  
2. Insert them back into Kùzu under new\_scenario\_id (Note: name primary keys might need a prefix like \[SCENARIO\_1\]\_TaskName to avoid PK collisions).  
3. The LLM can now run assign\_resource or add\_task on the new\_scenario\_id safely, view the Budget Report, and compare it to the main project.

## **Step 5: Test-Driven Verification**

Create a local test script test\_phase\_3.py:

1. Create a Project and Task A. Lock Task A to start on a specific date.  
2. Add a dependency that forces Task A to move. Assert that the engine throws the \[CRITICAL CONFLICT\] warning instead of moving the locked task silently.  
3. Save the baseline. Change the duration of Task A.  
4. Run the EVM report and assert that Schedule Variance is detected between est\_date and baseline\_est\_date.  
5. Clone the project and verify the new sandbox exists independently.