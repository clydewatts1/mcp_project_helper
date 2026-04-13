"""
mcp-project-logic: Streamlit Dev Console (Phase 10)

Architecture Note:
  MCP's stdio client uses `anyio` TaskGroups internally. Running anyio inside
  Streamlit's own event loop (even with nest_asyncio) causes ExceptionGroup
  crashes. The fix: every MCP operation runs in a dedicated background thread
  with its own fresh asyncio event loop, completely isolated from Streamlit.
"""
import ast
import asyncio
import base64
import concurrent.futures
import json
import sys
import yaml
import streamlit as st
import ollama
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession

# Use the venv Python explicitly to ensure server.py loads the right packages
VENV_PYTHON = sys.executable
SERVER_PARAMS = StdioServerParameters(command=VENV_PYTHON, args=["server.py"])

SYSTEM_PROMPT = """You are an expert Project Management AI connected to a strict Kuzu Graph Database.
You MUST use the provided tools to interact with the database.
Do NOT guess or hallucinate tools. If a tool returns an error, READ the error and use the suggested next tool.
Execute tasks step-by-step. Never repeat the exact same failed tool call.

You are a Rigid Project Logic Engine controller.
Rules:
1. Every Project must have a unique identifier (project_id). Derive a short uppercase ID from the name if not supplied (e.g. 'BETA_1').
2. Durations and lags are Working Days (weekends excluded automatically).
3. Visuals: 🔨 SKILL  🪏 TASK  👤 RESOURCE  📅 DATES
4. If a tool call returns an error, analyse and retry with corrected arguments.
5. Kuzu Cypher: NEVER use CALL procedures. Query nodes directly, e.g. MATCH (p:Project) RETURN p.id, p.name
6. CRITICAL — Numeric arguments: ALWAYS strip currency symbols and units before passing to tools. '$100/day' must be passed as 100.0. '$1,500' must be 1500.0. Never pass strings where a number is required.
7. CRITICAL — Resource names with underscores: pass the name exactly as written (e.g. 'Sir_Chews_A_Lot'), do NOT replace underscores with spaces.
8. CRITICAL — create_dependency only links ONE source to ONE target per call. If 'Task A depends on B AND C', make TWO calls: create_dependency('A','B') then create_dependency('A','C'). NEVER pass a list to target_name.
9. CRITICAL — assign_resource only links ONE resource to ONE task per call. If 'Assign Bob to X, Y, and Z', make THREE calls. NEVER pass a list to task_name. Allocation must be a plain integer (e.g. 100).
"""

CANNED_QUERIES = {
    "Custom Query": "",
    "List all Projects": "MATCH (p:Project) RETURN p.id AS ID, p.name AS Name, p.start_date AS StartDate",
    "List all Tasks": (
        "MATCH (t:Task) "
        "RETURN t.name AS Name, t.duration AS Duration, "
        "t.est_date AS EarlyStart, t.eft_date AS EarlyFinish, t.total_float AS Float"
    ),
    "List all Resources": "MATCH (r:Resource) RETURN r.name AS Name, r.type AS Type, r.cost_rate AS CostRate",
    "List all Skills": "MATCH (s:Skill) RETURN s.name AS Name, s.description AS Description",
    "Resource Assignments": (
        "MATCH (r:Resource)-[w:WORKS_ON]->(t:Task) "
        "RETURN r.name AS Resource, t.name AS Task, w.allocation AS Allocation"
    ),
    "Skill Requirements": (
        "MATCH (t:Task)-[:REQUIRES_SKILL]->(s:Skill) "
        "RETURN t.name AS Task, s.name AS Skill"
    ),
}


# ─── Thread-safe async runner ────────────────────────────────────────────────
def run_sync(coro, timeout: int = 120):
    """
    Run an async coroutine in a brand-new event loop inside a daemon thread.
    This completely isolates anyio/MCP from Streamlit's event loop.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, coro)
        return future.result(timeout=timeout)


# ─── Core MCP helpers ─────────────────────────────────────────────────────────
async def _fetch_tools():
    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            resp = await session.list_tools()
            return [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.inputSchema,
                    },
                }
                for t in resp.tools
            ]


async def _call_tool(tool_name: str, tool_args: dict) -> str:
    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments=tool_args)
            if result.content and len(result.content) > 0 and hasattr(result.content[0], "text"):
                return result.content[0].text
            return str(result)


async def _read_dag(project_id: str) -> bytes:
    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.read_resource(
                f"project://{project_id}/state/export/image"
            )
            if hasattr(result, "contents") and result.contents:
                data = json.loads(result.contents[0].text)
                return base64.b64decode(data["data"])
    raise ValueError("No image data returned from server.")


# ─── LLM loop (runs inside a single MCP session) ─────────────────────────────
async def _llm_loop_async(messages: list, formatted_tools: list, output_queue: list, selected_model: str = "llama3.2"):
    """
    Shared Ollama chat + tool-execution loop.
    Appends (role, content, tool_name?) tuples to output_queue so the
    caller can render them in Streamlit after the thread returns.
    """
    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            # Re-fetch tool schemas (ensures fresh session)
            tools_resp = await session.list_tools()
            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.inputSchema,
                    },
                }
                for t in tools_resp.tools
            ]

            MAX_ITERATIONS = 10
            iteration_count = 0
            valid_tool_names = [t.name for t in tools_resp.tools]

            while True:
                if iteration_count >= MAX_ITERATIONS:
                    output_queue.append(("assistant", "🛑 Circuit Breaker Triggered: LLM exceeded maximum consecutive tool calls (Looping).", None))
                    messages.append({"role": "assistant", "content": "I encountered an infinite loop error and had to stop."})
                    break

                response = ollama.chat(
                    model=selected_model, messages=messages, tools=tools
                )
                resp_msg = response.get("message", {})
                messages.append(resp_msg)

                if resp_msg.get("content"):
                    output_queue.append(("assistant", resp_msg["content"], None))

                if resp_msg.get("tool_calls"):
                    for call in resp_msg["tool_calls"]:
                        fn = call.get("function", {})
                        t_name = fn.get("name")
                        t_args = fn.get("arguments", {})
                        
                        if t_name not in valid_tool_names:
                            fake_result = f"CRITICAL ERROR: Tool '{t_name}' does not exist. Available tools are: {', '.join(valid_tool_names)}."
                            output_queue.append(("tool_result", fake_result, t_name))
                            messages.append({"role": "tool", "name": t_name, "content": fake_result})
                            continue
                            
                        output_queue.append(("tool_call", json.dumps(t_args), t_name))
                        try:
                            result = await session.call_tool(t_name, arguments=t_args)
                            if result.content and len(result.content) > 0 and hasattr(result.content[0], "text"):
                                result_str = result.content[0].text
                            else:
                                result_str = str(result)
                        except Exception as e:
                            result_str = f"Tool Error: {e}"
                        output_queue.append(("tool_result", result_str, t_name))
                        messages.append(
                            {"role": "tool", "name": t_name, "content": result_str}
                        )
                else:
                    break  # Final natural-language answer reached
                
                iteration_count += 1

    return messages


def run_llm_loop(system_prompt: str, selected_model: str = "llama3.2"):
    """Synchronous wrapper: runs the LLM loop in a thread and renders output."""
    output_queue = []
    messages = list(st.session_state.messages)

    with st.spinner("🤖 Ollama is working..."):
        try:
            updated_messages = run_sync(
                _llm_loop_async(messages, [], output_queue, selected_model)
            )
            st.session_state.messages = updated_messages
        except Exception as e:
            st.error(f"MCP Error: {e}")
            return

    for role, content, tool_name in output_queue:
        if role == "assistant":
            st.chat_message("assistant").write(content)
        elif role == "tool_call":
            with st.expander(f"🛠️ Tool: **{tool_name}**", expanded=True):
                try:
                    st.json(json.loads(content))
                except Exception:
                    st.code(content)
        elif role == "tool_result":
            with st.expander(f"📤 Result: **{tool_name}**", expanded=False):
                st.write(content)


# ─── Result rendering ─────────────────────────────────────────────────────────
def render_query_result(raw):
    """Parse stringified list → dataframe, or fall back to code block."""
    st.subheader("📊 Query Results")
    text = raw
    if hasattr(raw, "content") and raw.content:
        text = raw.content[0].text if raw.content else str(raw)

    try:
        parsed = ast.literal_eval(str(text))
        if isinstance(parsed, list) and parsed:
            st.dataframe(parsed, width='stretch')
        else:
            st.info("Query returned no rows.")
    except (ValueError, SyntaxError):
        st.code(str(text), language="text")


def get_available_models():
    try:
        resp = ollama.list()
        models = resp.get('models', []) if isinstance(resp, dict) else getattr(resp, 'models', [])
        return [m.get('model') if isinstance(m, dict) else m.model for m in models]
    except Exception:
        return ["llama3.2"]

# ─── Main App ─────────────────────────────────────────────────────────────────
def main():
    st.set_page_config(page_title="MCP Dev Console", page_icon="🪏")
    st.title("🪏 mcp-project-logic: Dev Console")

    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # ── Sidebar ─────────────────────────────────────────────
    st.sidebar.title("🛠️ MCP Dev Console")
    
    available_models = get_available_models()
    selected_model = st.sidebar.selectbox("🤖 Ollama Model", available_models, index=available_models.index("llama3.2") if "llama3.2" in available_models else 0)
    
    view = st.sidebar.radio(
        "Navigation",
        ["🧪 Automated Scenarios", "💬 Interactive Chat", "🗄️ Database Inspector"],
    )

    st.sidebar.markdown("---")
    st.sidebar.subheader("🗺️ DAG / PERT Viewer")
    target_pid = st.sidebar.text_input("Project ID")
    if st.sidebar.button("Fetch Graph"):
        if target_pid:
            try:
                img_bytes = run_sync(_read_dag(target_pid))
                st.sidebar.image(img_bytes, caption=f"DAG: {target_pid}")
            except Exception as e:
                st.sidebar.error(f"Failed: {e}")

    # ── Automated Scenarios ──────────────────────────────────
    if view == "🧪 Automated Scenarios":
        try:
            with open("test_prompts.yaml", "r") as f:
                scenarios = yaml.safe_load(f).get("scenarios", [])
        except Exception as e:
            st.error(f"Failed to load test_prompts.yaml: {e}")
            scenarios = []

        names = [s["name"] for s in scenarios]
        if names:
            sel = st.selectbox("Select Scenario", names)
            if st.button("▶ Execute Scenario"):
                chosen = next((s for s in scenarios if s["name"] == sel), None)
                if chosen:
                    st.session_state.messages = [
                        {"role": "system", "content": SYSTEM_PROMPT}
                    ]
                    
                    scenario_steps = chosen.get('steps', [chosen.get('prompt')])
                    
                    for step_idx, step_text in enumerate(scenario_steps):
                        st.markdown(f"### Executing Step {step_idx + 1} of {len(scenario_steps)}")
                        
                        st.session_state.messages.append({"role": "user", "content": step_text})
                        st.chat_message("user").write(step_text)
                        
                        run_llm_loop(SYSTEM_PROMPT, selected_model)
                        
        st.markdown("---")
        st.subheader("Scenario History")
        for msg in st.session_state.messages:
            if msg["role"] == "user":
                st.chat_message("user").write(msg["content"])
            elif msg["role"] == "assistant" and msg.get("content"):
                st.chat_message("assistant").write(msg["content"])
            elif msg["role"] == "tool":
                with st.expander(f"🛠️ Tool: {msg.get('name', '?')}"):
                    st.write(msg["content"])

    # ── Interactive Chat ─────────────────────────────────────
    elif view == "💬 Interactive Chat":
        for msg in st.session_state.messages:
            if msg["role"] == "user":
                st.chat_message("user").write(msg["content"])
            elif msg["role"] == "assistant" and msg.get("content"):
                st.chat_message("assistant").write(msg["content"])
            elif msg["role"] == "tool":
                with st.expander(f"🛠️ Tool: {msg.get('name', '?')}"):
                    st.write(msg["content"])

        if prompt := st.chat_input("Enter a project command or question..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
            st.chat_message("user").write(prompt)
            run_llm_loop(SYSTEM_PROMPT, selected_model)

    # ── Database Inspector ───────────────────────────────────
    elif view == "🗄️ Database Inspector":
        st.subheader("Kùzu Database Inspector")

        sel_q = st.selectbox("Quick Queries", list(CANNED_QUERIES.keys()))
        user_query = st.text_area(
            "Cypher Query (MATCH only — read-only):",
            value=CANNED_QUERIES[sel_q],
            height=120,
        )

        if st.button("▶ Run Query"):
            if user_query.strip():
                try:
                    result = run_sync(
                        _call_tool("execute_read_cypher", {"query": user_query})
                    )
                    render_query_result(result)
                except Exception as e:
                    st.error(f"Error: {e}")
            else:
                st.warning("Please enter a Cypher query.")


main()
