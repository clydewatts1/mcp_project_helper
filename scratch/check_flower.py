import kuzu
db = kuzu.Database('./project_data.kuzu')
conn = kuzu.Connection(db)
print('Tasks:')
res = conn.execute("MATCH (p:Project {id: 'FLOWER_1'})-[:CONTAINS]->(t:Task) RETURN t.name")
while res.has_next(): print(res.get_next()[0])
print('Edges:')
res = conn.execute("MATCH (p:Project {id: 'FLOWER_1'})-[:CONTAINS]->(s:Task)-[r:DEPENDS_ON]->(t:Task) RETURN s.name, t.name")
while res.has_next(): print(res.get_next())
