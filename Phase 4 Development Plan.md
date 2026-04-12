# **Development Plan: Phase 4 (Optimization & Risk Engine)**

**ATTENTION CODING AGENT (ANTIGRAVITY):** This is your Phase 4 architectural blueprint. Your objective is to introduce advanced scheduling algorithms, specifically an Automated Resource Leveler (Auto-Solver) and PERT (3-point) risk estimation. Adhere strictly to the Kùzu schema rules and execute complex math exclusively in Python memory.

## **Objective**

Implement the auto\_level\_schedule tool to mathematically resolve resource conflicts using Task Float, and introduce PERT estimations so the AI can run probabilistic risk analysis on the project timeline.

## **Step 1: Schema Expansion (Risk & PERT)**

Extend the database initialization logic to support 3-point estimation (Optimistic, Pessimistic, and Most Likely).

Ensure the Task node supports the following new properties:

* optimistic\_duration (INT) \- Best case scenario.  
* pessimistic\_duration (INT) \- Worst case scenario.  
* expected\_duration (DOUBLE) \- Calculated PERT value.  
* total\_float (INT) \- The number of days a task can be delayed without delaying the project.

## **Step 2: PERT Risk Analysis Implementation**

Shift from single-point duration guessing to intelligent risk calculation.

1. **Update add\_task / Create update\_estimates:**  
   * Allow the LLM to input optimistic and pessimistic durations alongside the standard duration (which acts as the "Most Likely").  
2. **Implement run\_pert\_analysis(project\_id: str) Tool:**  
   * **Math:** For every task, calculate the Expected Duration: (Optimistic \+ (4 \* Most\_Likely) \+ Pessimistic) / 6\.  
   * **Math:** Calculate Task Variance: ((Pessimistic \- Optimistic) / 6)^2.  
   * **Action:** SET t.expected\_duration \= \<calculated\_value\>.  
3. **Implement project://{project\_id}/reports/risk Resource:**  
   * Summarize the PERT results. Identify the highest variance tasks (the riskiest tasks) on the Critical Path.

## **Step 3: The Resource Leveling Engine (Auto-Solver)**

This is a complex algorithmic tool. It actively modifies the graph to resolve State I Monitor warnings (Over-allocation).

**auto\_level\_schedule(project\_id: str)**

1. **Calculate Float:** Run a Forward Pass to get Earliest Start/Finish. Run a Backward Pass (from the project end date) to get Latest Start/Finish. Total Float \= Latest Start \- Earliest Start. Update t.total\_float in Kùzu.  
2. **Identify Conflicts:** Fetch the project://{project\_id}/reports/allocation data to find dates where a resource is \> 100% allocated.  
3. **The Heuristic Loop (In Python):**  
   * For the conflicting date, get all active tasks assigned to the over-allocated resource.  
   * **Constraint:** Filter out any tasks with status \== "HUMAN\_LOCKED" or total\_float \== 0 (Critical Path). These cannot be moved.  
   * **Action:** Take the task with the highest total\_float and delay its est\_date by \+1 working day (updating its eft\_date). Decrease its total\_float by 1\.  
   * **Recalculate:** Re-check the resource load for that date. Repeat until allocation is \<= 100% OR all unlocked non-critical tasks reach total\_float \== 0\.  
4. **Graph Update:** Use Cypher to bulk update the shifted est\_date and eft\_date values in Kùzu. Add a lag to the DEPENDS\_ON edges if necessary to lock the delay.  
5. **Return Status:** Return a summary string of which tasks were shifted to resolve the conflict, or a warning if the conflict is unresolvable without delaying the Critical Path.

## **Step 4: System Design & Constitution Updates**

If executing Phase 4, the agent must update the system://constitution to include:

* **The Law of Optimization:** "The AI may automatically shift AI\_DRAFT tasks to resolve resource bottlenecks, provided the shift does not exceed the task's total\_float (delaying the overall project)."  
* **New Visual Iconography:** \* **RISK/PERT Nodes:** Use the DICE icon (🎲)  
  * **FLOAT/SLACK:** Use the SPRING icon (〰️)

## **Step 5: Test-Driven Verification**

Create a local test script test\_phase\_4.py:

1. Create Project. Create Task A (duration 5), Task B (duration 3), Task C (duration 4).  
2. Dependency: A \-\> C. (Task B has no dependencies and runs parallel to A).  
3. Assign Resource 'Bob' to Task A (100%) and Task B (100%).  
4. *Assert:* Over-allocation warning triggers on days 1-3.  
5. Run auto\_level\_schedule().  
6. *Assert:* Task B's est\_date is pushed automatically to start *after* Task A, resolving the conflict without human input, because Task B had positive float.  
7. Lock Task B. Reset. Run Leveler.  
8. *Assert:* Leveler fails and returns an error because locked tasks cannot be shifted.