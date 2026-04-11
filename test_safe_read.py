import server

def test_safe_read():
    print("Testing valid query...")
    res = server.safe_cypher_read("MATCH (p:Project) RETURN count(*)")
    print(f"Valid result: {res}")
    
    print("\nTesting invalid query (Syntax Error)...")
    res = server.safe_cypher_read("SELECT * FROM Projects") # Cypher uses MATCH, not SELECT
    print(f"Invalid result: {res}")
    
    print("\nTesting invalid query (Missing Table)...")
    res = server.safe_cypher_read("MATCH (x:DoesNotExist) RETURN x")
    print(f"Missing table result: {res}")

if __name__ == "__main__":
    test_safe_read()
