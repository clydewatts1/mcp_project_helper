import json
import datetime
import numpy as np

def test_budget_aggregation(isolated_server):
    s = isolated_server
    s.create_project("P_BUDGET", "2026-01-01", "Budget Test")
    # Fixed cost 1000
    s.add_task("P_BUDGET", "T1", 4, 1000.0)
    
    # Resource: 500/day
    s.add_resource("FinancePro", "HUMAN", 500.0)
    # 4 days @ 50% = 2 days of work = 1000.0
    s.assign_resource("FinancePro", "T1", 50)
    
    report = s.get_budget_report("P_BUDGET")
    # Total should be 1000 (fixed) + 1000 (resource) = 2000
    assert "$2,000.00" in report

def test_evm_math(isolated_server):
    s = isolated_server
    # Use today's date for EVM calculations as the report uses datetime.date.today()
    today_str = str(datetime.date.today())
    s.create_project("P_EVM", today_str, "EVM Test")
    
    # Task 1: 5 days, cost 5000.
    s.add_task("P_EVM", "T1", 5, 5000.0)
    
    # Baseline it
    s.baseline_project("P_EVM")
    
    # Set progress to 50% (EV should be 2500)
    s.set_task_progress("T1", 50)
    
    # Set actual cost to 2000 (AC)
    s.update_task_actual_cost("T1", 2000.0)
    
    report = s.get_evm_report_internal("P_EVM")
    
    # EV = 0.5 * 5000 = 2500
    # AC = 2000
    # SPI = EV / PV. Today is start date, so PV depends on how much time has passed.
    # Since we set today as start date, PV might be 1 day's worth? 
    # Actually, get_evm_report 392: if today >= b_eft_dt: pv = b_cost
    # If today == b_est_dt, elapsed_days = 1. total_days = 5. PV = 5000 * 1/5 = 1000.
    
    assert "Total Earned Value (EV)**: $2,500.00" in report
    assert "Total Actual Cost (AC)**: $2,000.00" in report
    
    # CPI = EV / AC = 2500 / 2000 = 1.25
    assert "Cost Performance Index (CPI)**: 1.25" in report
    assert "(Under budget)" in report
