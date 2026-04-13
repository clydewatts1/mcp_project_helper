# **mcp-project-logic 🪏**

An enterprise-grade, mathematically strict Project Management engine built on the Model Context Protocol (MCP) and Kùzu Graph Database.

Unlike standard task trackers that merely record text, this engine actively enforces the laws of project scheduling. It features a custom Temporal Engine built on numpy.busday to calculate real-world dates, an Automated Resource Leveler to mathematically resolve bottlenecks, and full Earned Value Management (EVM) tracking.

## **🚀 Key Capabilities**

* **Strict Graph Database (Kùzu):** Ensures tasks, resources, skills, and dependencies are mapped correctly without LLM hallucinations.  
* **Temporal CPM Engine:** Automatically calculates Earliest Start/Finish times based on a strict working-day calendar (skipping weekends).  
* **Auto-Leveler & Sweep-line Algorithm:** Mathematically shifts tasks with positive float to resolve \>100% resource over-allocations.  
* **Risk & PERT Analysis:** Supports 3-point duration estimates to calculate realistic variance and statistical risk scores.  
* **"What-If" Sandboxing:** Safely clone entire projects to simulate changes without corrupting the baseline timeline.  
* **Portfolio Management:** Tracks global resource availability across multiple active projects.  
* **Enterprise Integrations:** Generates Kanban JSON exports and high-density Slack/Teams webhook briefings.

## **🛠️ Installation & Setup**

1. **Clone and Setup Virtual Environment:**  
   git clone \<your-repo-url\>  
   cd mcp-project-logic  
   python3 \-m venv venv  
   source venv/bin/activate  \# On Windows: venv\\Scripts\\activate

2. **Install Dependencies:**  
   pip install \-r requirements.txt

3. **Run Automated Test Suite (Optional but Recommended):**  
   pytest \-v tests/

## **🔌 Connecting to an MCP Client (e.g., Claude Desktop)**

To use this engine directly from your AI assistant, add it to your MCP configuration file (claude\_desktop\_config.json):

{  
  "mcpServers": {  
    "project-logic-engine": {  
      "command": "/absolute/path/to/your/venv/bin/python",  
      "args": \[  
        "/absolute/path/to/your/mcp-project-logic/server.py"  
      \]  
    }  
  }  
}

## **📖 Documentation Directory**

* [**MANUAL.md**](./MANUAL.md): The comprehensive operator guide, including a complete index of all MCP Tools and Resources.  
* [**AGENT_RULES.md**](./AGENT_RULES.md): Strict architectural mandates for AI agents or developers working on this codebase.