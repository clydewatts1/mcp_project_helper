import kuzu
import numpy as np

# Initialize Database
db = kuzu.Database('./project_data.kuzu')
conn = kuzu.Connection(db)

def get_task_children(task_name: str, depth: int = 1, include_resources: bool = False) -> str:
    depth = max(1, min(depth, 10))
    if include_resources:
        query = f"""
        MATCH (t:Task {{name: $name}})-[e:DEPENDS_ON*1..{depth}]->(child:Task)
        OPTIONAL MATCH (child)<-[:WORKS_ON]-(r:Resource)
        RETURN child.name, min(length(e)) AS depth, child.duration, child.est_date, child.eft_date, child.status, collect(r.name) AS resources
        ORDER BY depth, child.est_date
        """
    else:
        query = f"""
        MATCH (t:Task {{name: $name}})-[e:DEPENDS_ON*1..{depth}]->(child:Task)
        RETURN child.name, min(length(e)) AS depth, child.duration, child.est_date, child.eft_date, child.status
        ORDER BY depth, child.est_date
        """
    res = conn.execute(query, {"name": task_name})
    if include_resources:
        table = "| Child Task | Depth | Duration | Start Date | End Date | Status | Assigned Resources |\n"
        table += "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
    else:
        table = "| Child Task | Depth | Duration | Start Date | End Date | Status |\n"
        table += "| :--- | :--- | :--- | :--- | :--- | :--- |\n"
    count = 0
    while res.has_next():
        row = res.get_next()
        if include_resources:
            resources = ", ".join([r for r in row[6] if r]) if row[6] else "None"
            table += f"| {row[0]} | {row[1]} | {row[2]}d | {row[3]} | {row[4]} | {row[5]} | {resources} |\n"
        else:
            table += f"| {row[0]} | {row[1]} | {row[2]}d | {row[3]} | {row[4]} | {row[5]} |\n"
        count += 1
    if count == 0:
        return f"No downstream children found for '{task_name}' within depth {depth}."
    return table

def get_task_parents(task_name: str, depth: int = 1, include_resources: bool = False) -> str:
    depth = max(1, min(depth, 10))
    if include_resources:
        query = f"""
        MATCH (parent:Task)-[e:DEPENDS_ON*1..{depth}]->(t:Task {{name: $name}})
        OPTIONAL MATCH (parent)<-[:WORKS_ON]-(r:Resource)
        RETURN parent.name, min(length(e)) AS depth, parent.duration, parent.est_date, parent.eft_date, parent.status, collect(r.name) AS resources
        ORDER BY depth, parent.eft_date
        """
    else:
        query = f"""
        MATCH (parent:Task)-[e:DEPENDS_ON*1..{depth}]->(t:Task {{name: $name}})
        RETURN parent.name, min(length(e)) AS depth, parent.duration, parent.est_date, parent.eft_date, parent.status
        ORDER BY depth, parent.eft_date
        """
    res = conn.execute(query, {"name": task_name})
    if include_resources:
        table = "| Parent Task | Depth | Duration | Start Date | End Date | Status | Assigned Resources |\n"
        table += "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
    else:
        table = "| Parent Task | Depth | Duration | Start Date | End Date | Status |\n"
        table += "| :--- | :--- | :--- | :--- | :--- | :--- |\n"
    count = 0
    while res.has_next():
        row = res.get_next()
        if include_resources:
            resources = ", ".join([r for r in row[6] if r]) if row[6] else "None"
            table += f"| {row[0]} | {row[1]} | {row[2]}d | {row[3]} | {row[4]} | {row[5]} | {resources} |\n"
        else:
            table += f"| {row[0]} | {row[1]} | {row[2]}d | {row[3]} | {row[4]} | {row[5]} |\n"
        count += 1
    if count == 0:
        return f"No upstream parents found for '{task_name}' within depth {depth}."
    return table

print("Testing get_task_children('Task 1: Prepare soil'):")
print(get_task_children('Task 1: Prepare soil', depth=1, include_resources=True))

print("\nTesting get_task_parents('Task 2: Plant seeds'):")
print(get_task_parents('Task 2: Plant seeds', depth=1, include_resources=True))
