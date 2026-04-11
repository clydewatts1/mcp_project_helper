# **MCP Server Components: mcp-project-logic**

This document defines the comprehensive Tools, Resources, and Prompts that the MCP server will expose to the LLM. It acts as the technical specification for implementing the mcp.server.fastmcp instance.

*Note: The server must be configured to support both stdio and sse (HTTP-streamable) transport layers. All data types map strictly to Kùzu database types.*

## **1\. Tools (Actions & Logic Gates)**

Tools are asynchronous functions the LLM can invoke. Each tool acts as a logic gate, pulling data from Kùzu into Python, validating laws (like the Calendar Engine or Circular Dependency checks), and writing back to the graph.

### **Project & Calendar Setup Tools**

* **create\_project**  
  * *Description:* Initializes a new project container. Sets the baseline anchor for calendar calculations.  
  * *Inputs:* \* project\_id (STRING, unique)  
    * name (STRING)  
    * start\_date (STRING, format: "YYYY-MM-DD")  
    * description (STRING, optional)  
* **add\_holiday**  
  * *Description:* Adds an exclusion date to the global calendar. Automatically triggers \_recalculate\_timeline() to shift task est\_date and eft\_date values past the holiday.  
  * *Inputs:*  
    * project\_id (STRING)  
    * date (STRING, format: "YYYY-MM-DD")  
    * description (STRING, e.g., "Thanksgiving")  
* **set\_workweek**  
  * *Description:* Defines which days of the week are considered working days.  
  * *Inputs:*  
    * project\_id (STRING)  
    * working\_days (ARRAY of INTs, 0=Monday, 6=Sunday. Default: \[0, 1, 2, 3, 4\])

### **Data Mutation Tools (Entities)**

* **add\_task**  
  * *Description:* Creates/updates a task node using its name as the primary key. Triggers the Calendar Engine to calculate est\_date and eft\_date.  
  * *Inputs:*  
    * project\_id (STRING)  
    * name (STRING) \- Unique Task ID / Primary Key  
    * description (STRING, optional)  
    * duration (INT) \- Working days (excluding weekends/holidays)  
    * cost (DOUBLE) \- Fixed cost budget  
* **add\_resource**  
  * *Description:* Registers a human or equipment resource.  
  * *Inputs:*  
    * project\_id (STRING)  
    * name (STRING) \- Unique Resource ID / Primary Key  
    * description (STRING, optional)  
    * type (STRING, enum: "HUMAN", "EQUIPMENT")  
    * cost\_rate (DOUBLE) \- Cost per working day  
* **add\_skill\_requirement**  
  * *Description:* Creates a SKILL node (if missing) and defines a REQUIRES\_SKILL edge from a Task to the Skill.  
  * *Inputs:* project\_id (STRING), task\_name (STRING), skill\_name (STRING).

### **Graph Relationship Tools (Edges)**

* **create\_dependency**  
  * *Description:* Links two tasks (source\_name \-\> target\_name). **Enforces Law I:** Uses Cypher to ensure no cycle exists before creation.  
  * *Inputs:* \* project\_id (STRING)  
    * source\_name (STRING)  
    * target\_name (STRING)  
    * lag (INT, default 0\) \- Wait time in working days.  
* **assign\_resource**  
  * *Description:* Assigns a resource to a task via WORKS\_ON. **State Monitor:** Calculates if the resource exceeds 100% capacity on any calendar date. Emits a Warning to the LLM if true, but allows the transaction.  
  * *Inputs:* \* project\_id (STRING)  
    * resource\_name (STRING)  
    * task\_name (STRING)  
    * allocation\_percentage (INT, 1-100)

### **Analysis & Advanced Agent Tools**

* **save\_baseline**  
  * *Description:* Snapshots the timeline/budget by copying est\_date, eft\_date, and cost to baseline\_\* properties, unlocking EVM reporting.  
  * *Inputs:* project\_id (STRING).  
* **auto\_level\_schedule**  
  * *Description:* Python-based auto-solver that shifts non-critical tasks within their Float window to mathematically resolve over-allocations on specific calendar dates.  
  * *Inputs:* project\_id (STRING).  
* **execute\_read\_cypher**  
  * *Description:* Allows the LLM to run custom MATCH queries.  
  * *Self-Healing Loop:* If Kùzu throws a RuntimeError (e.g., schema mismatch), the tool catches the exception and returns the exact error string so the LLM can rewrite the query. Hard-coded to reject CREATE, MERGE, or DELETE.  
  * *Inputs:* query (STRING).

## **2\. Resources (Context & State)**

Resources provide the LLM with live read-only context. The backend intercepts these URIs and dynamically generates the markdown, JSON, or images.

### **System & Architecture Context**

* **system://constitution**  
  * *Content:* The raw markdown of the "Project Logic Constitution" so the LLM remembers the strict laws and visual iconography (🔨, 🪏, 👤, 📅).  
* **system://schema**  
  * *Content:* A JSON map of the active Kùzu database tables, edge relationships, and strict property types. The LLM MUST read this before utilizing execute\_read\_cypher.

### **Project Data Resources**

* **projects://list**  
  * *Content:* Markdown table of all active projects (id, start\_date, total tasks).  
* **project://{project\_id}/tasks**  
  * *Content:* Complete table of tasks, showing duration, est\_date, eft\_date, and dependencies.  
* **project://{project\_id}/calendar**  
  * *Content:* JSON list of configured working\_days and holidays.

### **Visual & Export Resources**

* **project://{project\_id}/state/export/image**  
  * *Content:* A compiled Graphviz diagram. Must be returned strictly using the MCP Image Payload format: {"type": "image", "data": "\<base64\>", "mimeType": "image/png"}. Visualizes the DAG (Tasks, Dependencies, Resources).  
* **project://{project\_id}/state/export/calendar**  
  * *Content:* An auto-generated .ics (iCalendar) text string mapping est\_date and eft\_date to real-world calendar events. Can be provided to the user to import into Google Calendar/Outlook.

### **Automated Intelligence Reports**

* **project://{project\_id}/reports/budget**  
  * *Content:* Financial breakdown aggregating fixed costs \+ variable costs (cost\_rate \* duration \* allocation).  
* **project://{project\_id}/reports/allocation**  
  * *Content:* Flags resources exceeding 100% capacity over specific YYYY-MM-DD date ranges.  
* **project://{project\_id}/reports/earned\_value**  
  * *Content:* EVM report comparing current dates to baseline dates (SPI, CPI).

## **3\. Prompts (Guided Workflows)**

Predefined templates to kick off specific interactions.

* **init\_project**  
  * *Behavior:* Reads user requirements, invokes create\_project (anchoring the start\_date), extracts entities, and executes add\_task / create\_dependency tool calls. Fetches the state/export/image resource to display the resulting DAG.  
* **generate\_status\_report**  
  * *Behavior:* Reads the Budget, Allocation, and Risk reports. Synthesizes an executive briefing using strict visual iconography (e.g., "📅 Project End: 2026-05-01. 👤 Bob is over-allocated.").  
* **build\_custom\_report**  
  * *Behavior:* Triggers the Data Analyst persona. The LLM reads system://schema, drafts a custom Cypher query to answer a complex human question, runs execute\_read\_cypher, catches any syntax errors to self-correct, and outputs a formatted Markdown data table.