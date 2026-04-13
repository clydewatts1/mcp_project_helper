# **Development Plan: Phase 14 (LLM Resilience & Agent Ergonomics)**

**ATTENTION CODING AGENT (ANTIGRAVITY):** This is your Phase 14 blueprint. Your objective is to optimize the MCP tools for smaller, local LLMs (like Llama 3.2).

Smaller models struggle with zero-shot tool chaining and abstract errors. You must update server.py to use "Defensive Tool Design." This means returning explicit, actionable instructions when an error occurs, rather than generic exceptions, and expanding tool docstrings to act as mini-system-prompts.

## **Objective**

Harden the MCP server by implementing the "Next Step Error Pattern", defensive type casting, and highly explicit docstrings.

## **Step 1: The "Next Step" Error Pattern**

When an LLM fails an execution, do not just say "Error: Not found." You must tell it *exactly* which tool to call to fix the problem.

**Action:** Update the error returns in the following tools in server.py:

1. **assign\_resource:**  
   * *Old Error:* raise ValueError(f"Resource '{resource\_name}' does not exist.")  
   * *New Error:* return f"Error: Resource '{resource\_name}' does not exist in the database. You MUST call the 'add\_resource' tool to create it before attempting this assignment again."  
   * *New Error (Task):* return f"Error: Task '{task\_name}' does not exist. Call 'add\_task' first."  
2. **create\_dependency:**  
   * *New Error (Source missing):* return f"Error: Source task '{source\_name}' not found. Call 'add\_task' to create it."  
   * *New Error (Cycle):* return f"Law I Violation: Circular Dependency. Linking these creates a cycle. Do NOT attempt to create this specific dependency again. Re-evaluate your plan."  
3. **grant\_skill & require\_skill:**  
   * *New Error:* return f"Error: Skill '{skill\_name}' does not exist. Call 'add\_skill' to register this capability first."

## **Step 2: Docstring Hardening (Prompt Engineering)**

FastMCP uses your Python docstrings directly as the tool description fed to the LLM. For smaller models, these need to be imperative commands, not just descriptions.

**Action:** Update the docstrings in server.py to be extremely explicit.

* **Example for create\_dependency:**  
  @mcp.tool()  
  def create\_dependency(source\_name: str, target\_name: str, lag: int \= 0\) \-\> str:  
      """  
      Creates a dependency between two tasks.   
      CRITICAL: You MUST ensure BOTH tasks exist before calling this.  
      source\_name: The task that must finish first.  
      target\_name: The task that waits for the source to finish.  
      lag: Wait time in working days. Use 0 by default.  
      """

* **Example for auto\_level\_schedule:**  
  @mcp.tool()  
  def auto\_level\_schedule(project\_id: str) \-\> str:  
      """  
      Fixes resource over-allocations automatically.  
      Call this IMMEDIATELY if an assign\_resource tool returns an "\[WARNING: Over-allocation\]" message.  
      """

## **Step 3: Defensive Parameter Handling**

Local models frequently hallucinate data types (e.g., passing "5" instead of 5, or omitting optional fields).

**Action:** Add defensive casting to numeric tools in server.py:

1. In add\_task: Force cast duration \= int(duration) and cost \= float(cost).  
2. In assign\_resource: Force cast allocation \= int(allocation). Wrap this in a try/except ValueError block that returns: "Error: allocation must be a whole number between 1 and 100."

## **Step 4: Context Truncation**

If Kùzu throws a massive syntax error stack trace, small models lose their context window and hallucinate.

**Action:** Update safe\_cypher\_read to truncate Kùzu errors.

def safe\_cypher\_read(query: str, params: dict \= None) \-\> str:  
    try:  
        \# ... existing logic ...  
    except Exception as e:  
        error\_msg \= str(e)  
        \# Truncate massively long database errors so the LLM doesn't get confused  
        if len(error\_msg) \> 200:  
            error\_msg \= error\_msg\[:200\] \+ "... \[TRUNCATED\]"  
        return f"Database Error: {error\_msg}. Please check your tool arguments and try again."

## **Step 5: Test Execution**

1. Restart the server.  
2. Connect Ollama 3.2.  
3. Ask it to "Assign Bob to Task A". (Neither exist yet).  
4. *Verify:* Ollama should read the new error, say "I need to create Bob and Task A first", invoke add\_task and add\_resource, and then successfully try the assignment again without human intervention\!