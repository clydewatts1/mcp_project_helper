# **Development Plan: Phase 16 (Self-Extending Agent & Dynamic Reports)**

**ATTENTION CODING AGENT (ANTIGRAVITY):** This is your Phase 16 architectural blueprint. Your objective is to allow the LLM to program its own reusable, read-only analytics queries and save them directly into the Kùzu graph database.

You must enforce strict security boundaries (No mutation commands allowed) and build a debugging mechanism so the LLM can fix syntax errors in its own saved queries.

## **Objective**

Implement a CustomReport node table. Provide tools for the LLM to register\_custom\_report, run\_custom\_report, and debug\_custom\_report. Establish a read-only security gate to ensure these custom tools cannot corrupt the database.

## **Step 1: Schema Expansion (server.py)**

Add a new node table to store the LLM's custom tools.

Update the node\_queries list in the initialize\_schema() function to include:

"CREATE NODE TABLE CustomReport (name STRING, description STRING, cypher\_query STRING, last\_error STRING, PRIMARY KEY (name))"

## **Step 2: Implement the Registration Tool**

This tool validates the query against a strict read-only keyword blacklist, tests the syntax, and saves it to the database.

**Action:** Add this to server.py:

@mcp.tool()  
def register\_custom\_report(name: str, description: str, cypher\_query: str) \-\> str:  
    """  
    Allows the AI to save a custom analytical query as a reusable report.  
    SECURITY: The query MUST be read-only (MATCH/RETURN/WITH). Mutating commands are blocked.  
    """  
    \# 1\. Security Gate: Block all mutation keywords  
    forbidden\_keywords \= \["CREATE", "MERGE", "SET", "DELETE", "DROP", "ALTER", "REMOVE"\]  
    query\_upper \= cypher\_query.upper()  
    if any(keyword in query\_upper for keyword in forbidden\_keywords):  
        return f"Security Violation: Query rejected. Custom reports cannot contain mutating keywords like CREATE or SET."  
          
    \# 2\. Syntax Validation: Try running it with a LIMIT 1 to catch typos instantly  
    test\_query \= f"{cypher\_query} LIMIT 1"  
    last\_error \= ""  
    try:  
        conn.execute(test\_query)  
    except Exception as e:  
        last\_error \= f"Syntax Error during registration: {str(e)}"  
          
    \# 3\. Save to Database  
    save\_query \= """  
    MERGE (r:CustomReport {name: $name})  
    SET r.description \= $desc,  
        r.cypher\_query \= $query,  
        r.last\_error \= $error  
    RETURN r.name  
    """  
    conn.execute(save\_query, {"name": name, "desc": description, "query": cypher\_query, "error": last\_error})  
      
    if last\_error:  
        return f"Report '{name}' saved, but it contains a syntax error. Use debug\_custom\_report to view the error log."  
    return f"Success\! Custom report '{name}' has been registered and is ready to run."

## **Step 3: Implement the Execution Tool**

This tool fetches the saved string and runs it. If it fails, it actively writes the error back into the database's last\_error property so the LLM can debug it later.

**Action:** Add this to server.py:

@mcp.tool()  
def run\_custom\_report(name: str) \-\> str:  
    """  
    Executes a previously saved custom report by name.  
    """  
    \# 1\. Fetch the query  
    res \= conn.execute("MATCH (r:CustomReport {name: $name}) RETURN r.cypher\_query", {"name": name})  
    if not res.has\_next():  
        return f"Error: Custom report '{name}' not found."  
          
    query \= res.get\_next()\[0\]  
      
    \# 2\. Execute and trap errors  
    try:  
        result\_set \= conn.execute(query)  
        rows \= \[\]  
        while result\_set.has\_next():  
            rows.append(result\_set.get\_next())  
              
        \# Clear any previous errors on success  
        conn.execute("MATCH (r:CustomReport {name: $name}) SET r.last\_error \= ''", {"name": name})  
          
        if not rows:  
            return "Report executed successfully, but returned 0 rows."  
        return str(rows)  
          
    except Exception as e:  
        error\_msg \= str(e)  
        \# Log the error to the database for later debugging  
        conn.execute("MATCH (r:CustomReport {name: $name}) SET r.last\_error \= $err", {"name": name, "err": error\_msg})  
        return f"Execution Failed. Error logged to database. Please run debug\_custom\_report('{name}') to investigate."

## **Step 4: Implement Debugging & Listing**

The LLM needs a way to view all the reports it has built and read the error logs to fix them.

**Action:** Add these to server.py:

@mcp.tool()  
def debug\_custom\_report(name: str) \-\> str:  
    """  
    Returns the exact Cypher query and the last recorded error log for a custom report.  
    Use this to troubleshoot why a run\_custom\_report call failed.  
    """  
    res \= conn.execute("MATCH (r:CustomReport {name: $name}) RETURN r.cypher\_query, r.last\_error", {"name": name})  
    if not res.has\_next():  
        return f"Error: Custom report '{name}' not found."  
          
    query, last\_error \= res.get\_next()  
      
    debug\_info \= f"--- DEBUG LOG FOR: {name} \---\\n"  
    debug\_info \+= f"Query:\\n{query}\\n\\n"  
    debug\_info \+= f"Last Recorded Error:\\n{last\_error if last\_error else 'No errors recorded. Query is healthy.'}\\n"  
    return debug\_info

@mcp.resource("custom://reports")  
def list\_custom\_reports() \-\> str:  
    """Returns a list of all registered custom AI reports."""  
    res \= conn.execute("MATCH (r:CustomReport) RETURN r.name, r.description, r.last\_error")  
      
    table \= "| Report Name | Description | Status |\\n| :--- | :--- | :--- |\\n"  
    count \= 0  
    while res.has\_next():  
        name, desc, err \= res.get\_next()  
        status \= "❌ Failing" if err else "✅ Healthy"  
        table \+= f"| {name} | {desc} | {status} |\\n"  
        count \+= 1  
          
    if count \== 0:  
        return "No custom reports have been registered yet."  
    return table

## **Step 5: Update Documentation & Agent State**

1. **MANUAL.md**: Update the tools section to include "Dynamic Custom Reports". Explain that the AI can now author and store its own analytics.  
2. **Execution Test**: Have the LLM register a report called HighRiskTasks with a deliberate syntax error (e.g., MATC (t:Task)...). Verify that it fails, logs the error, and that the LLM can use debug\_custom\_report to view the typo, then re-register it with the correct MATCH spelling.