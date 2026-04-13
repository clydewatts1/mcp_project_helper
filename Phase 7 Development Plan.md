# **Development Plan: Phase 7 (Advanced Test Coverage & CI Readiness)**

**ATTENTION CODING AGENT (ANTIGRAVITY):** This is your Phase 7 architectural blueprint. Your objective is to significantly expand the pytest suite established in Phase 6\. You will introduce coverage reporting and write aggressive test cases targeting the engine's financial math, portfolio logic, and edge-case error handling.

## **Objective**

Achieve \>90% code coverage on server.py by implementing comprehensive test suites for Earned Value Management (EVM), multi-project portfolio logic, and negative/failure paths.

## **Step 1: Coverage Environment Setup**

1. **Install Coverage Tool:** Run pip install pytest-cov and update requirements.txt.  
2. **Configure Execution:** You will now run your tests using pytest \--cov=server tests/ \--cov-report=term-missing. This will show you exactly which lines in server.py are untested.

## **Step 2: Test Suite D \- Financials & EVM (tests/test\_financials.py)**

Create a dedicated suite for the Phase 3 budget and EVM reporting. All tests must use the isolated\_server fixture.

1. **Test Budget Aggregation:**  
   * Create a task with a fixed cost of $1000.  
   * Assign a resource ($500/day) for 4 days at 50% allocation (Resource cost \= $1000).  
   * *Assert:* get\_budget\_report() accurately calculates the Total Task Cost as $2000.  
2. **Test EVM Math (SPI & CPI):**  
   * Create a project, add tasks, and call baseline\_project().  
   * Fast-forward the task progress using set\_task\_progress(task, 50\) and update\_task\_actual\_cost(task, 2000).  
   * Call get\_evm\_report().  
   * *Assert:* The report outputs the correct Earned Value (EV) and Actual Cost (AC), and successfully generates Schedule Performance Index (SPI) and Cost Performance Index (CPI) metrics without throwing a ZeroDivisionError.

## **Step 3: Test Suite E \- Portfolio & Integrations (tests/test\_portfolio.py)**

Validate the Phase 5 enterprise features.

1. **Test Inter-Project Dependencies:**  
   * Create Project 1 (Task A) and Project 2 (Task B). Link Task A \-\> Task B.  
   * Change Task A's duration.  
   * *Assert:* The \_recalculate\_timeline successfully cascades and updates the est\_date of Task B in the entirely separate project.  
2. **Test Global Over-Allocation:**  
   * Assign Resource X to Project 1 (100% allocation).  
   * Assign Resource X to Project 2 (50% allocation) on the same date.  
   * *Assert:* get\_portfolio\_allocation\_report() flags Resource X as 150% allocated, proving the sweep-line algorithm works globally.

## **Step 4: Test Suite F \- Edge Cases & Error Handling (tests/test\_edge\_cases.py)**

Write negative tests to ensure the application handles bad data gracefully instead of crashing.

1. **Test Invalid Entities:**  
   * Attempt to assign a non-existent resource to a task.  
   * *Assert:* The system traps the error and returns a clear ValueError or failure string, avoiding a database crash.  
2. **Test Invalid Date Formats:**  
   * Call create\_project() with a start date of "01-01-2026" (instead of YYYY-MM-DD).  
   * *Assert:* The regex validation blocks the creation and returns the format error.  
3. **Test Auto-Leveler Failure:**  
   * Create a resource overload using only tasks that are HUMAN\_LOCKED.  
   * Run auto\_level\_schedule().  
   * *Assert:* The leveler exits gracefully, returning a message that no shifts were possible, rather than attempting an infinite loop.

## **Step 5: Iteration & Coverage Goal**

1. Run pytest \--cov=server tests/.  
2. Review the missing lines reported in the terminal.  
3. Write additional tests in the appropriate files until the coverage for server.py exceeds 90%.