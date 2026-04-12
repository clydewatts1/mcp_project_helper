# **Development Plan: Phase 6 (Automated Testing & Validation)**

**ATTENTION CODING AGENT (ANTIGRAVITY):** This is your Phase 6 architectural blueprint. Your objective is to deprecate the manual test\_\*.py scripts and establish a robust, automated test suite using pytest. You must ensure test isolation by utilizing temporary Kùzu databases.

## **Objective**

Implement a formalized pytest suite that validates the Temporal Engine, Resource Leveler, and Schema integrity without corrupting the production database.

## **Step 1: Environment & Directory Setup**

1. **Install Dependencies:** Run pip install pytest pytest-asyncio and update requirements.txt.  
2. **Directory Structure:** Create a tests/ directory at the root of the project. Include an empty \_\_init\_\_.py file inside it.

## **Step 2: Database Isolation Fixture (conftest.py)**

To prevent tests from destroying the live ./project\_data.kuzu database, you must mock the database connection for the tests.

**Action:** Create tests/conftest.py with the following implementation:

import os  
import tempfile  
import pytest  
import kuzu  
import server  \# Import the main server module

@pytest.fixture(scope="function")  
def isolated\_server():  
    """  
    Creates a temporary Kuzu database for each test, overriding the server's  
    global db and conn variables to ensure total test isolation.  
    """  
    \# Create a temporary directory for the Kuzu DB  
    temp\_dir \= tempfile.TemporaryDirectory()  
      
    \# Override the server's database connection  
    test\_db \= kuzu.Database(temp\_dir.name)  
    test\_conn \= kuzu.Connection(test\_db)  
      
    \# Backup original  
    orig\_db \= server.db  
    orig\_conn \= server.conn  
      
    \# Inject test DB  
    server.db \= test\_db  
    server.conn \= test\_conn  
      
    \# Initialize the schema on the fresh test DB  
    server.initialize\_schema()  
      
    yield server  \# Provide the server module to the test  
      
    \# Cleanup and restore  
    server.db \= orig\_db  
    server.conn \= orig\_conn  
    temp\_dir.cleanup()

## **Step 3: Test Suite A \- The Temporal Engine (tests/test\_temporal.py)**

Create a test file to strictly validate Phase 1 logic.

1. **Test Circular Dependencies:**  
   * Create tasks A, B. Link A-\>B.  
   * Attempt to link B-\>A using create\_dependency.  
   * *Assert:* The returned string contains "Law I Violation".  
2. **Test Weekend Skips:**  
   * Create a project starting on a Thursday. Add a 4-day task.  
   * *Assert:* The calculated eft\_date skips the weekend and lands on the following Wednesday.

## **Step 4: Test Suite B \- Resources & Leveling (tests/test\_resources.py)**

Create a test file to validate Phase 2 and Phase 4 logic.

1. **Test Skill Mismatches:**  
   * Require a skill on a task. Assign a resource without the skill.  
   * *Assert:* The assignment is successful but returns the "Skill Mismatch" warning.  
2. **Test The Auto-Leveler:**  
   * Create two parallel tasks (A and B) and assign the same resource at 100% to both.  
   * Run auto\_level\_schedule().  
   * *Assert:* Task B's leveling\_delay increases, and its est\_date is pushed sequentially after Task A.

## **Step 5: Test Suite C \- Data Integrity (tests/test\_integrity.py)**

Create a test file to validate Phase 3 and Phase 5 edge cases.

1. **Test Kanban Aggregation:**  
   * Assign two different resources to the same task.  
   * Run export\_to\_kanban().  
   * *Assert:* The resulting JSON contains exactly ONE card for the task, with the assignees field containing both names separated by a comma.  
2. **Test Scenario Cloning Schema Drift:**  
   * Create a task with total\_float=5, actual\_cost=100, and leveling\_delay=2.  
   * Run clone\_scenario().  
   * Query the cloned task.  
   * *Assert:* The cloned task retains the exact values for total\_float, actual\_cost, and leveling\_delay.

## **Step 6: Execution & Self-Correction**

1. Run pytest \-v tests/ from the terminal.  
2. If any tests fail, read the output carefully, self-correct the logic in server.py or the test files, and rerun until the suite achieves a 100% pass rate.