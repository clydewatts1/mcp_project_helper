# **mcp-project-logic: Comprehensive Operator Manual**

This manual explains how to interact with the engine and provides a complete reference for every tool and resource exposed to the LLM via the Model Context Protocol (MCP).

## **🧠 Core Operating Concepts**

1. **The Working-Day Calendar:** The engine operates strictly on business days using numpy.busday_offset. If a 5-day task starts on a Thursday, its calculated end date is the following Wednesday.  
2. **Strict Graph Entities:** Everything is a node. Tasks, Resources, and Skills must be explicitly created via tools before they can be linked.  
3. **The Auto-Leveler:** If resources are double-booked (>100% allocation), the system flags a warning. You can invoke the auto_level_schedule tool to let the engine mathematically shift non-critical tasks into the future to resolve the conflict.  
4. **Sandboxing:** Never experiment on a live project baseline. Use clone_scenario to duplicate a project, run your What-If scenarios, and review the budget impact safely.

## **🛠️ MCP Tool Reference (Actions & Mutations)**

These tools allow the LLM to mutate the database, calculate math, and orchestrate the project.

### **1. Project & Task Setup**

* create_project(project_id, start_date, name): Initializes a new project container. start_date must be YYYY-MM-DD.  
* add_task(project_id, name, duration, cost, description, optimistic, pessimistic): Creates a task. Optionally accepts PERT estimates (optimistic/pessimistic).  
* create_dependency(source_name, target_name, lag): Links two tasks. Enforces **Law I (No Cycles)** before allowing the edge.  
* lock_task(task_name): Changes task status to HUMAN_LOCKED. The Auto-Leveler and CPM engine will flag conflicts instead of moving it.

### **2. Resource & Skill Management**

* add_resource(name, resource_type, cost_rate, description): Registers a resource. Type must be HUMAN or EQUIPMENT.  
* add_skill(name, description): Registers a competency to the system.  
* grant_skill(resource_name, skill_name, proficiency): Gives a resource a skill.  
* require_skill(task_name, skill_name): Makes a task demand a specific skill.  
* assign_resource(resource_name, task_name, allocation): Assigns a resource to a task (1-100%). Triggers State Monitors for Skill Mismatches and Over-allocations.

### **3. Execution & Reporting (EVM)**

* baseline_project(project_id): Snapshots the current dates and budget. Required before using EVM tracking.  
* set_task_progress(task_name, percent_complete): Updates progress (0-100).  
* update_task_actual_cost(task_name, actual_cost): Logs real money spent on a task.

### **4. Advanced Analysis & Algorithms**

* check_timeline(project_id): Manually forces a CPM forward-pass calculation and returns any critical date conflicts.  
* get_critical_path(project_id): Back-traces from the project finish date to find the sequence of tasks driving the deadline.  
* update_estimates(task_name, optimistic, pessimistic): Updates the optimistic and pessimistic durations of a task for PERT analysis.
* run_pert_analysis(project_id): Mathematically calculates expected_duration using 3-point estimates for all tasks.  
* auto_level_schedule(project_id): Runs the heuristic sweep-line solver to shift tasks with positive float, resolving resource over-allocations.

### **5. Enterprise Portfolio & Integrations**

* clone_scenario(source_project_id, new_scenario_id): Duplicates a project, its tasks, assignments, and estimates into a safe sandbox.  
* export_to_kanban(project_id): Generates a Jira/Trello compatible JSON output of all tasks and their assignees.  
* generate_briefing_webhook(project_id): Condenses EVM, Budget, and Critical Path data into a dense Markdown payload suitable for Slack/Teams.  
* generate_agent_sub_prompt(task_name): Reads task requirements and outputs a strict prompt designed to instruct a sub-agent to do the work.  
* ping(): Basic health check to verify MCP server connectivity.

### **6. Data Purging & Lifecycle (Phase 13)**

* delete_task(task_name): Safely deletes a task after severing all dependencies, resource assignments, and project containment links.
* delete_resource(resource_name): Safely deletes a resource after severing all assignments and skill links.
* delete_skill(skill_name): Safely deletes a skill after severing all possession and requirement links.
* delete_project(project_id): Deletes a project and all its contained tasks (cascading cleanup).

### **7. Entity Inspection Tools (Phase 11)**

* list_projects(): Lists all projects in the system as a Markdown table (| Project ID | Name | Start Date |).  
* list_tasks(project_id=None): Lists tasks globally or filtered by project as a Markdown table (| Task Name | Duration | Status | Start Date | End Date |).  
* list_resources(): Lists all registered HUMAN and EQUIPMENT resources with formatted cost rates.  
* list_skills(): Lists all skills in the competency database (| Skill Name | Description |).
* execute_read_cypher(query): Executes a raw read-only Cypher query against the Kùzu database. Strictly blocks mutations (CREATE/DELETE/SET).

### **7. Dependency Traceability (Phase 12)**

* get_task_children(task_name, depth=1, include_resources=False): Returns a list of downstream dependent tasks. Optionally includes assigned resources.
* get_task_parents(task_name, depth=1, include_resources=False): Returns a list of upstream tasks (prerequisites). Optionally includes assigned resources.


## **📊 MCP Resource Reference (Context & Read-Only Data)**

These URIs can be fetched by the LLM at any time to gain immediate context about the system state.

### **System Architecture**

* system://info: Returns basic server initialization status.  
* system://constitution: Returns the core rules and visual iconography (🔨, 🪏, 👤, 📅) the LLM should follow.  
* system://schema: JSON map of Kùzu nodes, edges, and strict property types.

### **Project Output & Visuals**

* project://{project_id}/tasks: Markdown table of all tasks, their calculated dates, and durations.  
* project://{project_id}/state/export/image: Returns a complete **Graphviz DAG** (Directed Acyclic Graph) of the project as a Base64 PNG image.  
* project://{project_id}/state/export/pert: Returns a high-fidelity **PERT Chart** (Precedence Diagram) showing ES/EF dates, float/slack, and the Critical Path.

### **Analytical Reports**

* project://{project_id}/reports/budget: Financial breakdown aggregating fixed costs and calculated resource costs (cost_rate * duration * allocation).  
* project://{project_id}/reports/allocation: Sweep-line analysis showing exact YYYY-MM-DD windows where resources exceed 100% capacity within the project.  
* portfolio://reports/allocation: Global sweep-line analysis detecting bottlenecks across *all* active projects in the database.  
* project://{project_id}/reports/evm: Earned Value Management report displaying Planned Value (PV), Earned Value (EV), Actual Cost (AC), SPI, and CPI.  
* project://{project_id}/reports/risk: PERT analysis report highlighting tasks with dangerously high statistical variance on the timeline.

### **Dynamic Custom Reports (Phase 16)**

The project engine permits autonomous LLM workers to author and register their own repeatable analytics onto the graph database.

* `custom://reports`: Lists all user/AI registered custom analytical reports and their operational health status.
* **Relevant Tools**: `register_custom_report`, `run_custom_report`, `debug_custom_report`.
* **Security Constraints**: Reports are validated for syntax upon registration (`LIMIT 1`). Execution of structural mutation commands (e.g. `CREATE`, `SET`) are universally blocked.