# **Development Plan: Phase 15 (Ollama Client Hardening & Loop Protection)**

**ATTENTION CODING AGENT (ANTIGRAVITY):** This blueprint is for the ollama\_tester.py Streamlit client, NOT the MCP server.

Local models like Llama 3.2 often suffer from infinite tool-calling loops, context degradation, and "instruction amnesia" when given massive prompts. You must update the Streamlit tester to include an aggressive System Prompt, an infinite-loop circuit breaker, tool-hallucination interceptors, and a sequential Prompt Chunking engine.

## **Objective**

Harden ollama\_tester.py to prevent the LLM from entering infinite loops, hallucinating tools, and forgetting its primary constraints by spoon-feeding it instructions one step at a time.

## **Step 1: The Ironclad System Prompt**

Smaller models need constant reminding of how to use tools. If you only send the user's prompt, the model loses its "Agent" persona.

**Action:** In ollama\_tester.py, update the initialization of st.session\_state.messages to strictly include a System prompt.

\# Replace the empty list initialization with this:  
if "messages" not in st.session\_state:  
    st.session\_state.messages \= \[  
        {  
            "role": "system",   
            "content": (  
                "You are an expert Project Management AI connected to a strict Kuzu Graph Database. "  
                "You MUST use the provided tools to interact with the database. "  
                "Do NOT guess or hallucinate tools. If a tool returns an error, READ the error and use the suggested next tool. "  
                "Execute tasks step-by-step. Never repeat the exact same failed tool call."  
            )  
        }  
    \]

## **Step 2: The Infinite Loop Circuit Breaker**

If the LLM makes 10 tool calls in a single conversational turn without stopping to give a text response, it is trapped in a loop.

**Action:** Wrap the LLM Execution Loop (Part 4 of the Streamlit script) in a counter.

\# Inside the execution loop:  
MAX\_ITERATIONS \= 10  
iteration\_count \= 0

while True: \# The recursive tool loop  
    if iteration\_count \>= MAX\_ITERATIONS:  
        st.error("🛑 Circuit Breaker Triggered: LLM exceeded maximum consecutive tool calls (Looping).")  
        st.session\_state.messages.append({"role": "assistant", "content": "I encountered an infinite loop error and had to stop."})  
        break  
          
    response \= ollama.chat(model='llama3.2', messages=st.session\_state.messages, tools=formatted\_tools)  
      
    \# ... process tool calls ...  
      
    if not response\['message'\].get('tool\_calls'):  
        \# Normal text response, break the loop  
        st.chat\_message("assistant").write(response\['message'\]\['content'\])  
        break  
          
    iteration\_count \+= 1

## **Step 3: The Hallucination Interceptor (Client-Side)**

Sometimes Llama 3.2 will try to call a tool that wasn't in the formatted\_tools list. If you pass this to the MCP server, the MCP SDK will crash.

**Action:** Before executing session.call\_tool(...), verify the tool name exists.

\# Inside the tool processing block:  
valid\_tool\_names \= \[t.name for t in mcp\_tools\_response.tools\]

for tool\_call in response\['message'\]\['tool\_calls'\]:  
    requested\_tool \= tool\_call\['function'\]\['name'\]  
      
    if requested\_tool not in valid\_tool\_names:  
        \# Intercept the hallucination\!  
        fake\_result \= f"CRITICAL ERROR: Tool '{requested\_tool}' does not exist. Available tools are: {', '.join(valid\_tool\_names)}."  
        st.warning(f"Intercepted Hallucinated Tool: {requested\_tool}")  
          
        st.session\_state.messages.append({  
            "role": "tool",  
            "name": requested\_tool,  
            "content": fake\_result  
        })  
        continue \# Skip calling the MCP server, go to the next tool call  
          
    \# Else, execute normally via MCP...  
    result \= await session.call\_tool(requested\_tool, arguments=tool\_call\['function'\]\['arguments'\])

## **Step 4: Prompt Chunking & Sequential Execution**

To prevent Llama 3.2 from forgetting instructions in massive prompts (like 10-step God-Mode prompts), update the tester to support chunked YAML scenarios and sequential execution.

**Action A: Update YAML Support**

Update the script to read scenarios that have a steps array instead of just a single prompt string.

\# Example test\_prompts.yaml structure to support:  
scenarios:  
  \- name: "The Elephant Banquet (Chunked)"  
    steps:  
      \- "Step 1: Create a project with ID 'daizy\_llama' starting on 2026-05-01."  
      \- "Step 2: Add a skill named 'Logistical Butchery' and a resource named 'Dr\_Frankenstein'."  
      \- "Step 3: Assign Dr\_Frankenstein to a new task 'T1\_Blueprint' (duration 5, cost 300)."

**Action B: The Sequential Step Feeder**

When the user clicks "Execute Scenario", iterate over the steps. Wait for the LLM to finish the tool-loop for Step 1 *before* appending Step 2 to the chat history.

\# Execution routing logic:  
scenario\_steps \= selected\_scenario.get('steps', \[selected\_scenario.get('prompt')\])

for step\_idx, step\_text in enumerate(scenario\_steps):  
    st.markdown(f"\#\#\# Executing Step {step\_idx \+ 1} of {len(scenario\_steps)}")  
      
    \# 1\. Spoon-feed the current step  
    st.session\_state.messages.append({"role": "user", "content": step\_text})  
    st.chat\_message("user").write(step\_text)  
      
    \# 2\. Trigger the Circuit-Breaker Tool Loop (from Step 2\)  
    iteration\_count \= 0  
    while True:  
        \# ... execute ollama.chat and handle tools/circuit breakers ...  
        \# (Break out of this while-loop when a standard text response is received)  
          
    \# 3\. Wait briefly or just continue to the next step seamlessly

## **Step 5: Run & Verify**

1. Update test\_prompts.yaml to include a chunked scenario.  
2. Restart your Streamlit app: streamlit run ollama\_tester.py.  
3. Select the chunked scenario.  
4. *Verify:* You should see the UI inject Step 1, watch Llama execute the tools, output a success message, and then automatically inject Step 2, keeping the LLM perfectly focused and on track\!