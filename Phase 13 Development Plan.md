# **Development Plan: Phase 13 (Data Purging & Lifecycle Management)**

**ATTENTION CODING AGENT (ANTIGRAVITY):** This is your Phase 13 architectural blueprint. Your objective is to introduce safe deletion tools to the MCP server.

Because Kùzu enforces strict edge constraints, a node cannot be deleted if any relationship (edge) still points to it. You must implement a "cascading delete" helper function to sever all edges before dropping the nodes.

## **Objective**

Implement four lifecycle management tools: delete\_task, delete\_resource, delete\_skill, and delete\_project. The project deletion tool must recursively delete all tasks contained within the project.

## **Step 1: Implement Edge-Severing Helper**

In server.py, add a helper function named \_safe\_delete\_edges.

* **Logic:** It should accept a Node Label, a Key Property, a Value, and a list of Edge Labels.  
* It must iterate through the edge labels and execute targeted DELETE queries in both directions (-\> and \<-) wrapped in try/except blocks to ignore missing edges silently.

## **Step 2: Implement Deletion Tools**

Using the helper function from Step 1, create the following @mcp.tool() endpoints:

1. **delete\_task(task\_name: str)**  
   * *Edges to sever:* DEPENDS\_ON, WORKS\_ON, REQUIRES\_SKILL, CONTAINS  
   * *Action:* Delete the task node.  
2. **delete\_resource(resource\_name: str)**  
   * *Edges to sever:* WORKS\_ON, HAS\_SKILL  
   * *Action:* Delete the resource node.  
3. **delete\_skill(skill\_name: str)**  
   * *Edges to sever:* HAS\_SKILL, REQUIRES\_SKILL  
   * *Action:* Delete the skill node.  
4. **delete\_project(project\_id: str)**  
   * *Logic:* First, query all tasks connected to the project via CONTAINS.  
   * Loop through the tasks and execute the delete\_task logic on each.  
   * *Edges to sever (Project):* CONTAINS  
   * *Action:* Delete the project node. Return a string summarizing how many tasks were cascade-deleted alongside the project.

## **Step 3: Update Documentation**

Because you are adding four new mutation tools to the MCP server, you MUST update the system documentation to prevent schema drift.

1. **MANUAL.md**: Update the tool reference section to describe the new deletion capabilities.  
2. **mcp\_components.md**: Update the tool specifications so the LLM knows it has the ability to tear down resources and projects.