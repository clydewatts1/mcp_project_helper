# mcp-project-logic: Component Reference

This document provides a functional description of every `@mcp.tool()` and `@mcp.resource()` registered by `server.py`. It is the primary reference for LLM agents to determine what capabilities are available.

---

## Tools (Mutations & Actions)

### Project & Task Management
| Tool | Signature | Purpose |
|---|---|---|
| `create_project` | `(project_id, start_date, name)` | Initializes a new project node. |
| `add_task` | `(project_id, name, duration, cost, description, optimistic, pessimistic)` | Adds a task to a project. Triggers timeline recalculation. |
| `create_dependency` | `(source_name, target_name, lag=0)` | Links two tasks. Enforces Law I (no cycles). |
| `lock_task` | `(task_name)` | Sets task status to HUMAN_LOCKED to prevent auto-leveler movement. |
| `update_estimates` | `(task_name, optimistic, pessimistic)` | Updates PERT 3-point duration estimates. |

### Resource & Skill Management
| Tool | Signature | Purpose |
|---|---|---|
| `add_resource` | `(name, resource_type, cost_rate, description)` | Registers a new HUMAN or EQUIPMENT resource. |
| `add_skill` | `(name, description)` | Registers a new competency node. |
| `grant_skill` | `(resource_name, skill_name, proficiency)` | Links a resource to a skill. |
| `require_skill` | `(task_name, skill_name)` | Makes a task demand a specific skill, enabling validation. |
| `assign_resource` | `(resource_name, task_name, allocation)` | Assigns a resource at 1-100% allocation. Triggers over-allocation check. |

### Execution & Progress Tracking
| Tool | Signature | Purpose |
|---|---|---|
| `baseline_project` | `(project_id)` | Snapshots current dates and costs as the baseline. |
| `set_task_progress` | `(task_name, percent_complete)` | Updates % complete for EVM calculations. |
| `update_task_actual_cost` | `(task_name, actual_cost)` | Logs real-world spend against a task. |

### Analysis & Scheduling
| Tool | Signature | Purpose |
|---|---|---|
| `check_timeline` | `(project_id)` | Forces CPM forward-pass and returns date conflicts. |
| `get_critical_path` | `(project_id)` | Identifies the task sequence driving the final deadline. |
| `run_pert_analysis` | `(project_id)` | Calculates expected durations via 3-point estimation. |
| `auto_level_schedule` | `(project_id)` | Runs sweep-line solver to resolve resource over-allocations. |

### Enterprise & Portfolio
| Tool | Signature | Purpose |
|---|---|---|
| `clone_scenario` | `(source_project_id, new_scenario_id)` | Clones a project into an isolated sandbox for what-if analysis. |
| `export_to_kanban` | `(project_id)` | Generates Jira/Trello-compatible JSON task cards. |
| `generate_briefing_webhook` | `(project_id)` | Creates a Markdown briefing payload for Slack/Teams. |
| `generate_agent_sub_prompt` | `(task_name)` | Outputs a structured sub-agent prompt for a specific task. |
| `ping` | `()` | Health check — returns "pong" if server is responsive. |

### Entity Inspection (Phase 11)
| Tool | Signature | Purpose |
|---|---|---|
| `list_projects` | `()` | Returns all projects as a Markdown table. |
| `list_tasks` | `(project_id=None)` | Returns all tasks (or project-filtered) as a Markdown table. |
| `list_resources` | `()` | Returns all resources with type and formatted cost rate. |
| `list_skills` | `()` | Returns all skills as a Markdown table. |
| `execute_read_cypher` | `(query)` | Executes raw read-only MATCH queries. Blocks mutations. |

### Dependency Traceability (Phase 12)
| Tool | Signature | Purpose |
|---|---|---|
| `get_task_children` | `(task_name, depth=1, include_resources=False)` | Traverses downstream `DEPENDS_ON` relationships. |
| `get_task_parents` | `(task_name, depth=1, include_resources=False)` | Traverses upstream `DEPENDS_ON` relationships. |

---

## Resources (Read-Only Context URIs)

| URI | Purpose |
|---|---|
| `system://info` | Server initialization status. |
| `system://constitution` | Full engine rules and visual iconography for LLM agents. |
| `system://schema` | JSON schema of all Kùzu node types and property definitions. |
| `project://{project_id}/tasks` | Markdown table of all tasks with dates for a given project. |
| `project://{project_id}/state/export/image` | Base64-encoded PNG DAG of the project dependency graph. |
| `project://{project_id}/state/export/pert` | Base64-encoded PNG PERT Chart with CPM metrics and critical path. |
| `project://{project_id}/reports/budget` | Budget breakdown: fixed costs + resource costs. |
| `project://{project_id}/reports/allocation` | Resource over-allocation windows (sweep-line analysis). |
| `project://{project_id}/reports/evm` | EVM report: PV, EV, AC, SPI, CPI. |
| `project://{project_id}/reports/risk` | PERT risk report highlighting high-variance tasks. |
| `portfolio://reports/allocation` | Global resource allocation report across all active projects. |
