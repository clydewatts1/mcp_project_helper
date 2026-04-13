# **Development Plan: Phase 9 (E2E Ollama Integration & Streamlit GUI)**

**ATTENTION CODING AGENT (ANTIGRAVITY):** This is a highly granular, step-by-step blueprint for building a standalone Streamlit application that acts as an MCP client. Because Streamlit state management can conflict with asynchronous MCP connections, you MUST follow these specific implementation steps exactly to prevent connection drops and infinite loops.

## **Objective**

Create an asynchronous Streamlit web application (ollama\_tester.py) that reads test prompts from a YAML file, connects to the local server.py via MCP, passes the tools to a local Ollama model, and visualizes the agent's tool-calling process.

## **Part 1: Project Setup & Data Preparation**

### **Step 1.1: Dependencies**

Ensure your environment contains these specific packages:

pip install streamlit ollama mcp pyyaml

### **Step 1.2: Scenario File Creation**

Create test\_prompts.yaml in the root directory. This will drive the testing UI.

scenarios:  
  \- name: "Basic Project Setup"  
    prompt: "Create a new project called 'OllamaTest' starting on 2026-10-01. Add a task 'CoreLogic' (duration: 5, cost: 1000)."  
  \- name: "Self-Correction Test"  
    prompt: "Try assigning a resource named 'Ghost' to 'CoreLogic'. If it fails, create the resource (HUMAN, 100/day), then assign it."

## **Part 2: The Streamlit Architecture (Finer-Grained Implementation)**

Create ollama\_tester.py. You must structure this file using asyncio because the MCP client SDK is fully asynchronous.

### **Step 2.1: The Async Streamlit Wrapper**

Set up the core script structure to handle asynchronous execution safely within Streamlit.

* Import asyncio, streamlit as st, yaml, ollama.  
* Import the MCP client: from mcp.client.stdio import stdio\_client, StdioServerParameters and from mcp.client.session import ClientSession.  
* Create a main async function: async def run\_app():  
* At the very bottom of the file, invoke it: asyncio.run(run\_app())

### **Step 2.2: Session State Initialization**

Inside run\_app(), initialize Streamlit's st.session\_state to hold chat history so the UI doesn't reset when buttons are clicked.

* If "messages" is not in st.session\_state, set it to an empty list \[\].  
* If "mcp\_tools" is not in state, set it to \[\].

### **Step 2.3: The Sidebar (Scenario Loader)**

Build the left-hand configuration panel.

* Read the test\_prompts.yaml file.  
* Use st.sidebar.selectbox to let the user choose a scenario by name.  
* Add an st.sidebar.button("Execute Scenario").  
* When the button is clicked, clear st.session\_state.messages, append the selected scenario's prompt as a "user" message, and set a flag (e.g., st.session\_state.run\_triggered \= True) to begin processing.

## **Part 3: The MCP Connection & Tool Translation**

### **Step 3.1: Establishing the Connection**

Only execute the MCP connection if run\_triggered is true. Use an asynchronous context manager to spin up the server subprocess.

* Define server params: server\_params \= StdioServerParameters(command="python", args=\["server.py"\])  
* Open the client: async with stdio\_client(server\_params) as (read, write):  
* Open the session: async with ClientSession(read, write) as session:  
* Await initialization: await session.initialize()

### **Step 3.2: Tool Fetching and Translation**

Once connected, fetch the available tools from server.py and convert them to the format Ollama expects.

* Fetch: mcp\_tools\_response \= await session.list\_tools()  
* Iterate through mcp\_tools\_response.tools.  
* Convert each tool into a dictionary matching Ollama's schema requirement:  
  formatted\_tools \= \[\]  
  for t in mcp\_tools\_response.tools:  
      formatted\_tools.append({  
          "type": "function",  
          "function": {  
              "name": t.name,  
              "description": t.description,  
              "parameters": t.inputSchema  
          }  
      })

## **Part 4: The LLM Execution Loop (The "Window")**

Still inside the ClientSession context block, implement the LLM chat loop.

### **Step 4.1: The Primary LLM Call**

* Send the current st.session\_state.messages and formatted\_tools to Ollama.  
  response \= ollama.chat(model='llama3.2', messages=st.session\_state.messages, tools=formatted\_tools)

* Append the response\['message'\] to st.session\_state.messages.

### **Step 4.2: Tool Execution Parsing**

Check if Ollama decided to use a tool.

* If response\['message'\].get('tool\_calls') exists, iterate over the calls.  
* **UI Visualization:** Use with st.expander(f"🛠️ Executing Tool: {tool\_call\['function'\]\['name'\]}", expanded=True): to create a visual block for the user to watch.  
* Display the JSON arguments inside the expander using st.json(tool\_call\['function'\]\['arguments'\]).

### **Step 4.3: Executing the MCP Tool**

Inside the tool loop, execute the requested action against the Kùzu database.

* Execute: result \= await session.call\_tool(tool\_call\['function'\]\['name'\], arguments=tool\_call\['function'\]\['arguments'\])  
* **UI Visualization:** Print the raw result inside the expander using st.write(result).  
* **State Update:** Append the result back to the chat history so Ollama can read it.  
  st.session\_state.messages.append({  
      "role": "tool",  
      "name": tool\_call\['function'\]\['name'\],  
      "content": str(result)  
  })

### **Step 4.4: The Recursive Loop**

* If tool calls were made, the LLM needs to interpret the results.  
* Loop back to **Step 4.1** (make another ollama.chat call) automatically, passing the updated message history (which now includes the tool roles).  
* The loop breaks when Ollama returns a standard natural language message without tool\_calls.  
* Render the final message to the screen using st.chat\_message("assistant").

## **Part 5: Execution**

1. Pull the model locally: ollama pull llama3.2  
2. Run the application: streamlit run ollama\_tester.py  
3. Verify that the UI correctly isolates the tool calls inside Streamlit Expanders, allowing you to see the exact Kùzu database interactions alongside the LLM's thought process.