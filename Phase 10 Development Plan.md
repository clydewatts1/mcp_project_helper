# **Development Plan: Phase 10 (Streamlit Dev Console & Interactive Chat)**

**ATTENTION CODING AGENT (ANTIGRAVITY):** This blueprint upgrades the ollama\_tester.py script into a full-fledged Developer Console. You will implement multi-view navigation, a manual chat interface, real-time DAG visualizations, and a direct Database Inspector with canned analytical queries.

## **Objective**

Transform the Streamlit application into a multi-page dashboard. Users must be able to switch between running YAML batch tests, injecting manual chat prompts to the LLM, viewing the graphical project DAG, and executing raw Cypher queries (both canned and custom) to inspect the Kùzu database state.

## **Part 1: Adding the execute\_read\_cypher Tool (server.py)**

Before updating the UI, you must give the MCP server the ability to process raw read-only queries so the Streamlit app can inspect the database safely without causing file locks.

**Action:** Add this new tool to server.py:

@mcp.tool()  
def execute\_read\_cypher(query: str) \-\> str:  
    """  
    Executes a raw read-only Cypher query against the Kuzu database.  
    Strictly blocks CREATE, MERGE, SET, and DELETE commands.  
    """  
    if any(keyword in query.upper() for keyword in \["CREATE", "MERGE", "SET", "DELETE", "DROP"\]):  
        return "Error: This tool is strictly for read-only MATCH queries."  
      
    return safe\_cypher\_read(query)

## **Part 2: UI Restructuring & The Navigation Menu (ollama\_tester.py)**

Restructure the Streamlit app to use a sidebar menu for navigation.

### **Step 2.1: The Sidebar Radio**

* In the run\_app() function, replace the old scenario selector with a main navigation menu:  
  st.sidebar.title("🛠️ MCP Dev Console")  
  view \= st.sidebar.radio("Navigation", \["🧪 Automated Scenarios", "💬 Interactive Chat", "🗄️ Database Inspector"\])

### **Step 2.2: Routing**

* Wrap the existing YAML execution logic inside an if view \== "🧪 Automated Scenarios": block.  
* Create empty elif blocks for the other two views.

## **Part 3: The Interactive Chat Window**

Inside elif view \== "💬 Interactive Chat":, build a live chat interface so the user can inject graph commands directly.

### **Step 3.1: Render History**

* Iterate through st.session\_state.messages and display them using st.chat\_message(msg\["role"\]). Hide "tool" roles inside st.expander blocks to keep the chat clean.

### **Step 3.2: The Chat Input**

* Use if prompt := st.chat\_input("Inject your own prompt or project instructions..."):  
* When triggered:  
  1. Append the user prompt to st.session\_state.messages and display it.  
  2. Invoke the exact same LLM Execution Loop from Phase 9 (sending messages and formatted\_tools to ollama.chat).  
  3. Execute any tools returned, update the state, and recursively call Ollama until a final text response is generated.

## **Part 4: Real-Time DAG & PERT Visualizer**

You must add a feature to fetch and render the project graph so the user can literally *see* what the LLM is building.

### **Step 4.1: Sidebar Graph Viewer**

* Add a text input to the sidebar: target\_project\_id \= st.sidebar.text\_input("Project ID for DAG Viewer")  
* Add a button: if st.sidebar.button("Fetch Project Graph"):  
* **Execution:**  
  1. Use the MCP session to read the resource: result \= await session.read\_resource(f"project://{target\_project\_id}/state/export/image")  
  2. Extract the base64 string from the result.  
  3. Decode it using the base64 python library.  
  4. Render it in the sidebar using st.sidebar.image(decoded\_bytes, caption=f"DAG for {target\_project\_id}").

## **Part 5: The Database Inspector & Canned Queries**

Inside elif view \== "🗄️ Database Inspector":, build a robust query terminal with quick-access tables.

### **Step 5.1: Canned Query Selector**

* Define a dictionary of pre-built queries:  
  canned\_queries \= {  
      "Custom Query": "",  
      "List all Projects": "MATCH (p:Project) RETURN p.id AS ID, p.name AS Name, p.start\_date AS StartDate",  
      "List all Resources": "MATCH (r:Resource) RETURN r.name AS Name, r.type AS Type, r.cost\_rate AS CostRate, r.description AS Desc",  
      "List all Skills": "MATCH (s:Skill) RETURN s.name AS Name, s.description AS Desc"  
  }

* Render a selectbox: selected\_query\_name \= st.selectbox("Quick Queries", list(canned\_queries.keys()))

### **Step 5.2: The Cypher Sandbox**

* Provide an st.text\_area for the query. Its default value should be tied to the canned\_queries dictionary selection.  
* Add an st.button("Run Query").

### **Step 5.3: MCP Execution & Table Rendering**

* When the button is clicked, directly invoke the MCP tool:  
  result \= await session.call\_tool("execute\_read\_cypher", arguments={"query": user\_query})  
* **Data Formatting:** The server.py tool returns a stringified list of rows (e.g., "\[\['PROJ1', 'Beta', '2026-01-01'\]...\]").  
* Use Python's ast.literal\_eval (in a try/except block) to parse the result string back into a Python list.  
* Display the parsed list using st.dataframe(parsed\_list) so the user gets a beautiful, sortable table. If parsing fails, fall back to st.code(result).

## **Part 6: Execution & Verification**

1. Restart your MCP server (to load the new Cypher tool).  
2. Run streamlit run ollama\_tester.py.  
3. **Verify Canned Tables:** Navigate to the DB Inspector, select "List all Resources", click Run Query, and verify it outputs a clean table using st.dataframe.  
4. **Verify Chat:** Navigate to the Interactive Chat, type "Create a project called DevTest", and watch the LLM successfully trigger the tools.  
5. **Verify Graph:** Type "DevTest" into the DAG Viewer sidebar and fetch the graph image.