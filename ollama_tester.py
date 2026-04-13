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

SYSTEM_PROMPT = """You are a Rigid Project Logic Engine controller.
Rules:
1. Every Project must have a unique identifier (project_id). Derive a short uppercase ID from the name if not supplied (e.g. 'BETA_1').
2. Durations and lags are Working Days (weekends excluded automatically).
3. Visuals: 🔨 SKILL  🪏 TASK  👤 RESOURCE  📅 DATES
4. If a tool call returns an error, analyse and retry with corrected arguments.
5. Kuzu Cypher: NEVER use CALL procedures. Query nodes directly, e.g. MATCH (p:Project) RETURN p.id, p.name
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
async def _llm_loop_async(messages: list, formatted_tools: list, output_queue: list):
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

            while True:
                response = ollama.chat(
                    model="llama3.2", messages=messages, tools=tools
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

    return messages


def run_llm_loop(system_prompt: str):
    """Synchronous wrapper: runs the LLM loop in a thread and renders output."""
    output_queue = []
    messages = list(st.session_state.messages)

    with st.spinner("🤖 Ollama is working..."):
        try:
            updated_messages = run_sync(
                _llm_loop_async(messages, [], output_queue)
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
            st.dataframe(parsed, use_container_width=True)
        else:
            st.info("Query returned no rows.")
    except (ValueError, SyntaxError):
        st.code(str(text), language="text")


# ─── Main App ─────────────────────────────────────────────────────────────────
def main():
    st.title("🪏 mcp-project-logic: Dev Console")

    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if "run_triggered" not in st.session_state:
        st.session_state.run_triggered = False

    # ── Sidebar ─────────────────────────────────────────────
    st.sidebar.title("🛠️ MCP Dev Console")
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
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": chosen["prompt"]},
                    ]
                    st.session_state.run_triggered = True

        for msg in st.session_state.messages:
            if msg["role"] == "user":
                st.chat_message("user").write(msg["content"])
            elif msg["role"] == "assistant" and msg.get("content"):
                st.chat_message("assistant").write(msg["content"])

        if st.session_state.run_triggered:
            st.session_state.run_triggered = False
            run_llm_loop(SYSTEM_PROMPT)

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
            run_llm_loop(SYSTEM_PROMPT)

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
