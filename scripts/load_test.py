import asyncio
import time
import httpx
import argparse
import random
import sys

BASE_URL = "http://localhost:8000/api/v1"

async def send_read_request(client: httpx.AsyncClient) -> tuple[bool, float]:
    """Simulate hot read request (GET /books)."""
    start = time.perf_counter()
    try:
        resp = await client.get(f"{BASE_URL}/books", timeout=5.0)
        elapsed = (time.perf_counter() - start) * 1000
        return (resp.status_code == 200, elapsed)
    except Exception:
        elapsed = (time.perf_counter() - start) * 1000
        return (False, elapsed)

async def send_ingest_request(client: httpx.AsyncClient, req_id: int) -> tuple[bool, float]:
    """Simulate high-throughput Landing ingestion request (POST /ingest/landing)."""
    start = time.perf_counter()
    payload = {
        "source_channel": "LOAD_TEST_BENCHMARK",
        "payload": {
            "title": f"Benchmark Book #{req_id}",
            "author": "Benchmark Author",
            "price": random.randint(10, 100),
            "total_copies": 5
        }
    }
    try:
        resp = await client.post(f"{BASE_URL}/ingest/landing", json=payload, timeout=5.0)
        elapsed = (time.perf_counter() - start) * 1000
        return (resp.status_code == 200, elapsed)
    except Exception:
        elapsed = (time.perf_counter() - start) * 1000
        return (False, elapsed)

async def worker(worker_id: int, requests_per_worker: int, results: list):
    """Worker task sending requests."""
    async with httpx.AsyncClient(limits=httpx.Limits(max_keepalive_connections=50, max_connections=100)) as client:
        for i in range(requests_per_worker):
            req_id = (worker_id * requests_per_worker) + i
            # 80% Reads (Hot cache test), 20% Landing Ingestion Writes
            if random.random() < 0.8:
                success, latency = await send_read_request(client)
            else:
                success, latency = await send_ingest_request(client, req_id)
            results.append((success, latency))

async def run_benchmark(concurrency: int, total_requests: int):
    print(f"======================================================================")
    print(f"Starting High-Concurrency Benchmark (~1000 req/sec Target)")
    print(f"Concurrency level: {concurrency} workers")
    print(f"Total requests: {total_requests}")
    print(f"======================================================================\n")

    requests_per_worker = total_requests // concurrency
    results = []
    
    start_time = time.perf_counter()
    tasks = [worker(w_id, requests_per_worker, results) for w_id in range(concurrency)]
    await asyncio.gather(*tasks)
    total_time = time.perf_counter() - start_time

    successful = [lat for succ, lat in results if succ]
    failed = [lat for succ, lat in results if not succ]
    
    rps = len(results) / total_time
    sorted_lat = sorted([lat for _, lat in results])

    p50 = sorted_lat[int(len(sorted_lat) * 0.50)] if sorted_lat else 0
    p95 = sorted_lat[int(len(sorted_lat) * 0.95)] if sorted_lat else 0
    p99 = sorted_lat[int(len(sorted_lat) * 0.99)] if sorted_lat else 0

    print("=================== BENCHMARK RESULTS ===================")
    print(f"Total Elapsed Time    : {total_time:.2f} seconds")
    print(f"Total Requests        : {len(results)}")
    print(f"Successful Requests   : {len(successful)} ({len(successful)/len(results)*100:.1f}%)")
    print(f"Failed Requests       : {len(failed)}")
    print(f"Throughput (RPS)      : {rps:.2f} req/sec")
    print(f"Latency P50 (Median)  : {p50:.2f} ms")
    print(f"Latency P95           : {p95:.2f} ms")
    print(f"Latency P99           : {p99:.2f} ms")
    print("=========================================================\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load Test Benchmark for Decoupled Backend")
    parser.add_argument("--concurrency", type=int, default=100, help="Number of concurrent connections")
    parser.add_argument("--total-requests", type=int, default=5000, help="Total requests to transmit")
    args = parser.parse_args()

    asyncio.run(run_benchmark(args.concurrency, args.total_requests))
