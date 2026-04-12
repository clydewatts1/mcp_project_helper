# **Development Plan: Phase 5 (Enterprise Portfolio & Integrations)**

**ATTENTION CODING AGENT (ANTIGRAVITY):** This is your Phase 5 architectural blueprint. Your objective is to expand the engine from single-project simulations to Multi-Project Portfolio Management (PPM) and introduce external system syncs. Adhere strictly to the Kùzu schema rules.

## **Objective**

Implement global resource pools across multiple projects, add inter-project dependencies, and build sync endpoints for external systems (e.g., Jira, GitHub, Slack).

## **Step 1: Schema Expansion (Portfolio Level)**

Extend the database to support global entities.

* **Global Resources:** Resources should no longer be conceptually limited to one project. The WORKS\_ON relationship naturally supports linking one Resource to Tasks across different Projects.  
* **Inter-Project Dependencies:** The DEPENDS\_ON edge table already links Task to Task. You will now allow linking a Task in Project A to a Task in Project B.

## **Step 2: Portfolio Resource Leveling**

Update the State Monitors and Auto-Solver to handle global scope.

1. **Update \_check\_over\_allocation:**  
   * Modify the logic to fetch ALL tasks assigned to the resource across ALL projects, not just the current project.  
2. **Update get\_allocation\_report:**  
   * Expose a new resource URI: portfolio://reports/allocation that scans the entire database for bottlenecks across all active projects.  
3. **Update auto\_level\_schedule:**  
   * The heuristic loop must now check global availability. If shifting a task in Project A resolves a conflict, it must ensure it doesn't accidentally cause a conflict in Project B.

## **Step 3: Inter-Project Timeline Engine**

1. **Update \_recalculate\_timeline:**  
   * Currently, the engine recalculates dates scoped to a single project\_id.  
   * Modify the logic: If a task in Project A drives a task in Project B, recalculating Project A must automatically trigger a recalculation for Project B (cascading updates).

## **Step 4: External State Sync (The Dispatcher)**

Implement tools that allow the AI to format database data for external systems.

1. **export\_to\_kanban(project\_id: str)**  
   * *Logic:* Fetch all Tasks. Map status, est\_date, and resource into a standardized JSON array suitable for a Jira or Trello API payload.  
2. **generate\_briefing\_webhook(project\_id: str)**  
   * *Logic:* Compile the get\_critical\_path, get\_budget\_report, and get\_evm\_report into a single, highly condensed Markdown string designed specifically to be sent via a Slack/Teams webhook.

## **Step 5: The Agentic Dispatch Tool**

Give the LLM the ability to write instructions for *other* agents.

1. **generate\_agent\_sub\_prompt(task\_name: str)**  
   * *Logic:* Reads the description, REQUIRES\_SKILL, and duration of a task.  
   * *Output:* Returns a strict system prompt that the main AI can hand to a sub-agent (e.g., "You are an Expert Python coder. You have 3 days to complete \[description\]. Execute...").

## **Step 6: Test-Driven Verification**

Create a local test script test\_phase\_5.py:

1. Create Project 1 and Project 2\.  
2. Assign "Alice" (capacity: 100%) to Task A in Project 1 (100% allocation).  
3. Assign "Alice" to Task B in Project 2 (50% allocation) on overlapping dates.  
4. *Assert:* The portfolio://reports/allocation correctly flags Alice as 150% allocated globally, even though her allocation within each individual project looks safe.  
5. Link Task A (Project 1\) \-\> Task Z (Project 2).  
6. Shift Task A's duration.  
7. *Assert:* Task Z in Project 2 automatically recalculates its est\_date.