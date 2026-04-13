# **MCP Integration Test: The Elephant Banquet**

**How to use:** Copy and paste the entire block below into your LLM client (Claude, Gemini, or Ollama). Before sending, replace \<agent\_name\> with the name of the LLM you are testing (e.g., daizy\_claude or daizy\_gemini).

**System Prompt / User Input:**

You are currently undergoing a rigorous integration test to verify your ability to orchestrate the ProjectLogicEngine via your MCP toolset. You will execute a project plan based on the old adage: "How do you eat an elephant? One bite at a time."

You must execute the following steps precisely using your MCP tools. **Do not hallucinate Cypher queries.** Use the provided tools (like create\_project, add\_task, add\_resource, assign\_resource, auto\_level\_schedule, etc.). Execute these steps sequentially. You may batch tool calls if your framework allows it.

### **Step 1: Initialization**

1. Create a project with the ID daizy\_\<agent\_name\> named "The Great Elephant Banquet".  
2. Set the start\_date to "2026-05-01".

### **Step 2: Skills & Resources**

Add the following skills and resources to the database, then grant the skills:

* **Skills:** "Logistical Butchery", "Cutlery Mastery", "Digestive Fortitude".  
* **Resources:**  
  1. Sir\_Chews\_A\_Lot (HUMAN, $100/day). Grant him "Cutlery Mastery" and "Digestive Fortitude".  
  2. The\_Iron\_Stomach (EQUIPMENT, $500/day). Grant it "Digestive Fortitude".  
  3. Dr\_Frankenstein (HUMAN, $250/day). Grant him "Logistical Butchery".

### **Step 3: The 10-Course Tasks (with PERT Estimates)**

Add these 10 tasks to the project. *Pay attention to the optimistic/pessimistic estimates where provided.*

1. T1\_Giant\_Bib: Duration 2, Cost $50.  
2. T2\_Blueprint\_Cuts: Duration 3, Cost $300. Require skill: "Logistical Butchery".  
3. T3\_Sharpen\_Knives: Duration 1, Cost $20. Require skill: "Cutlery Mastery".  
4. T4\_Trunk\_Tapas: Duration 4, Cost $400.  
5. T5\_Ear\_Carpaccio: Duration 3, Cost $150.  
6. T6\_Leg\_Roast\_Marathon: Duration 10, Cost $1000. (Optimistic: 8, Pessimistic: 20\)  
7. T7\_Stockpile\_Antacids: Duration 2, Cost $500.  
8. T8\_The\_Belly\_Burger: Duration 6, Cost $800. Require skill: "Digestive Fortitude".  
9. T9\_Ivory\_Toothpicks: Duration 5, Cost $0.  
10. T10\_Food\_Coma: Duration 7, Cost $2000. (Optimistic: 3, Pessimistic: 30\)

### **Step 4: Indigestion (Dependencies)**

Create the following dependency chains to form the critical path:

* T3\_Sharpen\_Knives depends on T1\_Giant\_Bib.  
* T4\_Trunk\_Tapas depends on T2\_Blueprint\_Cuts AND T3\_Sharpen\_Knives.  
* T5\_Ear\_Carpaccio depends on T2\_Blueprint\_Cuts.  
* T6\_Leg\_Roast\_Marathon depends on T4\_Trunk\_Tapas AND T5\_Ear\_Carpaccio.  
* T8\_The\_Belly\_Burger depends on T6\_Leg\_Roast\_Marathon AND T7\_Stockpile\_Antacids.  
* T9\_Ivory\_Toothpicks depends on T2\_Blueprint\_Cuts.  
* T10\_Food\_Coma depends on T8\_The\_Belly\_Burger AND T9\_Ivory\_Toothpicks.

### **Step 5: The Over-Allocation Trap**

Make the following assignments:

* Assign Dr\_Frankenstein to T2\_Blueprint\_Cuts at 100%.  
* Assign The\_Iron\_Stomach to T8\_The\_Belly\_Burger at 100%.  
* Assign Sir\_Chews\_A\_Lot to T4\_Trunk\_Tapas, T5\_Ear\_Carpaccio, AND T6\_Leg\_Roast\_Marathon—all at 100% capacity. *(Note: Watch the MCP server warnings, as T4 and T5 happen simultaneously\!)*

### **Step 6: Resolution & Baselining**

1. Run auto\_level\_schedule to mathematically fix Sir\_Chews\_A\_Lot's severe indigestion (over-allocation) by pushing non-critical tasks.  
2. Run run\_pert\_analysis.  
3. Once the schedule is leveled and PERT is calculated, lock it in by calling baseline\_project.

### **Step 7: Execution & Reporting**

1. We made progress\! Update T1\_Giant\_Bib to 100% complete and $60 actual cost. Update T2\_Blueprint\_Cuts to 50% complete and $150 actual cost.  
2. Fetch the EVM Report (reports/evm), the Risk Report (reports/risk), and the Critical Path.  
3. Fetch the Graphviz PNG image (state/export/image).

**Final Output:**

Summarize the EVM status, tell me which task is statistically the riskiest based on the PERT report, list the Critical Path, and display the Graphviz image inline. Let me know if I am going to survive eating this elephant.