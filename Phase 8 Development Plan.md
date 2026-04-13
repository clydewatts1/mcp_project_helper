# **Development Plan: Phase 8 (Enterprise Reliability & Chaos Testing)**

**ATTENTION CODING AGENT (ANTIGRAVITY):** This is your Phase 8 architectural blueprint. Your objective is to elevate the test suite beyond simple line coverage. You will introduce property-based testing, algorithmic benchmarking, and transport-layer integration tests to guarantee 100% reliability under extreme or malformed LLM interactions.

## **Objective**

Implement fuzz testing to break the Temporal Engine, benchmark the graph algorithms for scaling limits, and execute MCP transport-layer integration tests.

## **Step 1: Environment Setup**

1. **Install Advanced Testing Tools:** Run pip install hypothesis pytest-benchmark mutmut and update requirements.txt.  
   * hypothesis: For property-based fuzzing.  
   * pytest-benchmark: For measuring algorithm execution speed.  
   * mutmut: For mutation testing.

## **Step 2: Test Suite G \- Property-Based Fuzzing (tests/test\_fuzzing.py)**

LLMs can generate highly unpredictable inputs. We must ensure the math engines never crash.

1. **Fuzz the Temporal Engine:**  
   * Use @given and strategies from hypothesis.  
   * Auto-generate hundreds of tasks with extreme parameters: duration from 1 to 10,000, lag from \-500 to 500, and crazy start dates (e.g., leap years, year 1999, year 2099).  
   * *Assert:* The \_recalculate\_timeline() function never throws an unhandled exception (like an out-of-bounds numpy.busday error) and always returns valid YYYY-MM-DD strings.  
2. **Fuzz the Resource Leveler:**  
   * Generate highly fragmented allocations (e.g., 1% allocation, 33% allocation, 999% allocation).  
   * *Assert:* The sweep-line algorithm in \_check\_over\_allocation processes floating-point math safely and never infinite-loops.

## **Step 3: Test Suite H \- Performance Benchmarking (tests/test\_benchmarks.py)**

Graph algorithms (Topological Sort, Sweep-line) can suffer from ![][image1] slowdowns if implemented poorly.

1. **Benchmark Critical Path Calculation:**  
   * **Setup:** Write a setup fixture that injects 1,000 Tasks and 2,500 DEPENDS\_ON edges into the isolated Kùzu database.  
   * **Test:** Use the benchmark fixture from pytest-benchmark to run get\_critical\_path().  
   * *Assert:* The calculation must resolve in under 200ms on average. If it takes seconds, the algorithm requires refactoring.  
2. **Benchmark Auto-Leveler:**  
   * **Setup:** Inject 500 overlapping tasks assigned to the same 10 resources.  
   * **Test:** Benchmark auto\_level\_schedule().  
   * *Assert:* Ensure the heuristic loop resolves or safely exits before timeout thresholds.

## **Step 4: Test Suite I \- MCP Transport Integration (tests/test\_transport.py)**

Stop testing the Python functions directly. Test the actual MCP JSON-RPC interface to ensure the agent framework can connect.

1. **Mock Client Connection:**  
   * Instantiate the FastMCP server using its test client or an ASGI test wrapper (httpx.AsyncClient).  
2. **Execute Tool via RPC:**  
   * Send a formatted JSON-RPC request to invoke add\_task.  
   * *Assert:* The server successfully parses the RPC payload, executes the database mutation, and returns the expected JSON-RPC response format without 500 Internal Server Errors.

## **Step 5: Mutation Testing (Quality Assurance)**

Line coverage guarantees a line was executed, but not that the assertion was meaningful.

1. Run mutmut run. This will actively change operators in server.py (e.g., changing if current\_alloc \> 100: to if current\_alloc \>= 100:).  
2. *Assert:* Ensure your test suite *fails* when the code is mutated. If a mutation survives, your tests in Phase 6/7 are too weak and must be hardened.

[image1]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADgAAAAYCAYAAACvKj4oAAAEAUlEQVR4Xu1XTUhUURR+okHRH/1MQ/Pz3sw4YNKvDEVCtIiIXNiiXAjVMmzRqjJJWgghYYsIEwwVpIVFFLWIsEJIUFroLhADjSjEqChpGYH2ffPuk/NOMzqjjm784OO9d75z77vn3Hvufc+yVrHiKHYc5wzYATYmk8lN2mFZEQgENsRisbXavlCgrzrbto9YbqA3wMFwOLzN0xOJxOZUKrVGNMkd7Cgej5/AC2rQcTlMxdpHAoM5AN9uvlRrCwGThff2g118Rt8J3E+CVZ4PxncIzz35vLMIjY5isENo2AueJfH8BtexaDR6UDcgkIwI9LcYxG6thUKh7dAGwBnDKfSzR/qg3TWhkxORSGQvifE49IGtHJyE73HV9hx4f96ZpAMCaUEnn3Qg1By3DqbACqkBRWh3F2xSdh/Q5ym0/c0AMvmaJL2DtktrBIJoYKI5s9KOJKxDuxfgaWn3gQGgg3Y4/eK0a50wGfwJtuGxyLNzNmD7oGdFg0GxpuA7AY7iPUGp43k/7J24LZF2o3EpPkQwW7VGoN9aJifrUoXDRThM86o1D0jAFvgMgyNcdsLeANvL2BybSzAYXA+fLjNLbY47i7XSx3HL4bK0ETG3tm+xDwZYWlq6Q/uY+hw3G5IfaJR03OL9L6sSIsDP4E7aGBSDAxu1v4QZQKfxrwT/wPaKy8vzgdaiB8j6A25jZmy+E/p5XT6ESWBfxnGg4ybHLexmrUmYQX6VAfLKZ2jV2l8CPlVgPe8ZFINjkGAlbUwexvFYJtgk47kZm8cJrgLPRwL+D6D3WKJ85FY8bavdSYM6/cCBsrKyjcaWwvM3nXkNJlH2H3NrhgNO1zOu5dDbrQz1lytst1T6fZuQY2bAcTcPnnVZAb2Vg+JgPRsDBL/wKlx98OoPMxf2bJwp2EYdd8PhOsxYf/nABDjM1TBrFAHOLrtMQGFHoY+BP2xx1uUSoC3qT9pFaVzKVH/5wgT40bePmEN4ZJ4Aec5dN4O5IoVcAuT5x/baLjY3LvHXcmdeCEyA/iUKlMD4CPybLYPmDOIB36G/Fszs+D6fNHT9CbD20kcG+NRaRP0R6KMZ7GNJaKGCAWAQ3ToA2I+B38E7ckv34K0ABFGnNQJf/wHODpK0T2uEY46MbO3zAJPVA7ZqIQ2eLRDHY+43aPr7E+zF83sGacmt148iJkZ3zMPY9DUjeM9SH+zmM+tZttWTK2z3mBliOWhNgr8k3K5rwGo4h6zsgc0CHdeyc75Ea8sFx10J3JXjWls0+FuFjgcR5EmtLRO4PG+SvNfiksD8KTzJVKeFhtmN+/hZp7WlBLNYT/Jei4WC+Qvqdub6VVoqmH/Gq1iqh7VWKCC4CytYGqsoOP4B5ucoNMMWiDUAAAAASUVORK5CYII=>