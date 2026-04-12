import os
import tempfile
import pytest
import kuzu
import server

@pytest.fixture(scope="function")
def isolated_server():
    """
    Creates a temporary Kuzu database for each test, overriding the server's
    global db and conn variables to ensure total test isolation.
    """
    # Create a temporary directory for the Kuzu DB
    temp_dir = tempfile.TemporaryDirectory()
    db_path = os.path.join(temp_dir.name, "test.kuzu")
    
    # Override the server's database connection
    test_db = kuzu.Database(db_path)
    test_conn = kuzu.Connection(test_db)
    
    # Backup original
    orig_db = server.db
    orig_conn = server.conn
    
    # Inject test DB
    server.db = test_db
    server.conn = test_conn
    
    # Initialize the schema on the fresh test DB
    server.initialize_schema()
    
    yield server # Provide the server module to the test
    
    # Cleanup and restore
    server.db = orig_db
    server.conn = orig_conn
    temp_dir.cleanup()
