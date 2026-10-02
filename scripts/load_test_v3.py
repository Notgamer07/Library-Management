import asyncio
import time
import httpx
import argparse
import random
from datetime import datetime


def current_time():
    """Return current time in HH:MM:SS.ms format."""
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


async def send_read_request(
    client: httpx.AsyncClient,
    base_url: str,
    req_id: int,
    max_pages: int = 10
) -> tuple[bool, float, bool, int]:
    """
    Send read request with page number to /books.
    Returns: (is_success, latency_ms, is_cache_hit, page_no)
    """
    start = time.perf_counter()
    # Cycle through pages 1 to max_pages to trigger 3-page predictive caching
    page_no = (req_id % max_pages) + 1

    try:
        resp = await client.get(
            f"{base_url}/books",
            params={"page": page_no, "page_size": 10},
            timeout=5.0
        )
        elapsed = (time.perf_counter() - start) * 1000

        is_success = (resp.status_code == 200)
        is_cache_hit = False
        if is_success:
            try:
                body = resp.json()
                is_cache_hit = (body.get("source") == "cache")
            except Exception:
                pass

        return is_success, elapsed, is_cache_hit, page_no

    except Exception:
        elapsed = (time.perf_counter() - start) * 1000
        return False, elapsed, False, page_no


async def send_ingest_request(
    client: httpx.AsyncClient,
    base_url: str,
    req_id: int
) -> tuple[bool, float]:
    """
    Send write request to /ingest/landing.
    Returns: (is_success, latency_ms)
    """
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
        resp = await client.post(
            f"{base_url}/ingest/landing",
            json=payload,
            timeout=5.0
        )
        elapsed = (time.perf_counter() - start) * 1000
        return resp.status_code == 200, elapsed

    except Exception:
        elapsed = (time.perf_counter() - start) * 1000
        return False, elapsed


async def bounded_request(
    sem: asyncio.Semaphore,
    client: httpx.AsyncClient,
    base_url: str,
    req_id: int,
    results: list,
    max_pages: int
):
    """
    Executes a single request while strictly holding an in-flight concurrency slot.
    """
    async with sem:
        # 80% GET /books (Read with pagination & Redis cache)
        # 20% POST /ingest/landing (Write to Landing layer)
        if random.random() < 0.8:
            success, latency, is_cache_hit, page_no = await send_read_request(
                client, base_url, req_id, max_pages
            )
            results.append({
                "type": "READ",
                "success": success,
                "latency": latency,
                "cache_hit": is_cache_hit,
                "page": page_no
            })
        else:
            success, latency = await send_ingest_request(
                client, base_url, req_id
            )
            results.append({
                "type": "WRITE",
                "success": success,
                "latency": latency,
                "cache_hit": False,
                "page": None
            })


async def run_benchmark(
    base_url: str,
    total_requests: int,
    concurrency: int,
    duration: int,
    max_pages: int
):
    start_clock = current_time()
    target_rps = total_requests / duration if duration > 0 else total_requests

    print("=" * 70)
    print("      RATE-CONTROLLED & CONCURRENCY-BOUNDED LOAD TEST")
    print("=" * 70)
    print(f"Start Time             : {start_clock}")
    print(f"Target Base URL        : {base_url}")
    print(f"Total Requests         : {total_requests} (in {duration} seconds)")
    print(f"Concurrency Limit      : {concurrency} requests at the same time")
    print(f"Target Throughput      : {target_rps:.2f} req/sec")
    print(f"Read Pagination Range  : Pages 1 to {max_pages}")
    print("=" * 70)
    print()

    results = []

    limits = httpx.Limits(
        max_connections=max(2000, concurrency * 2),
        max_keepalive_connections=max(1000, concurrency)
    )

    # Semaphore strictly guarantees no more than `concurrency` requests execute at the same time
    sem = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(limits=limits) as client:
        tasks = []
        benchmark_start = time.perf_counter()

        # Distribute total_requests evenly across duration seconds
        request_interval = float(duration) / float(total_requests) if total_requests > 0 else 0.0

        for req_id in range(total_requests):
            scheduled_time = benchmark_start + (req_id * request_interval)
            now = time.perf_counter()

            if scheduled_time > now:
                await asyncio.sleep(scheduled_time - now)

            # Launch task bounded by semaphore
            task = asyncio.create_task(
                bounded_request(
                    sem, client, base_url, req_id, results, max_pages
                )
            )
            tasks.append(task)

        # Await completion of all scheduled requests
        await asyncio.gather(*tasks)
        benchmark_end = time.perf_counter()

    total_time = benchmark_end - benchmark_start
    end_clock = current_time()

    # ---------------------------------------------------------
    # Calculate statistics
    # ---------------------------------------------------------
    total_completed = len(results)

    successful = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]

    read_results = [r for r in results if r["type"] == "READ"]
    write_results = [r for r in results if r["type"] == "WRITE"]

    cache_hits = [r for r in read_results if r["cache_hit"]]
    cache_misses = [r for r in read_results if not r["cache_hit"]]

    all_latencies = sorted([r["latency"] for r in results])
    cache_hit_latencies = sorted([r["latency"] for r in cache_hits])
    cache_miss_latencies = sorted([r["latency"] for r in cache_misses])

    def calc_percentiles(latencies):
        if not latencies:
            return 0.0, 0.0, 0.0
        n = len(latencies)
        p50 = latencies[int(n * 0.50)]
        p95 = latencies[min(int(n * 0.95), n - 1)]
        p99 = latencies[min(int(n * 0.99), n - 1)]
        return p50, p95, p99

    p50, p95, p99 = calc_percentiles(all_latencies)
    hit_p50, hit_p95, _ = calc_percentiles(cache_hit_latencies)
    miss_p50, miss_p95, _ = calc_percentiles(cache_miss_latencies)

    actual_rps = total_completed / total_time if total_time > 0 else 0.0
    success_rate = (len(successful) / total_completed * 100) if total_completed > 0 else 0.0
    cache_hit_rate = (len(cache_hits) / len(read_results) * 100) if read_results else 0.0

    # ---------------------------------------------------------
    # Results Presentation
    # ---------------------------------------------------------
    print()
    print("=" * 70)
    print("                    BENCHMARK RESULTS")
    print("=" * 70)
    print(f"Start Time             : {start_clock}")
    print(f"End Time               : {end_clock}")
    print(f"Total Elapsed Time     : {total_time:.2f} seconds")
    print(f"Target Total Requests  : {total_requests} in {duration}s")
    print(f"Concurrency Setting    : {concurrency} simultaneous requests")
    print(f"Total Requests Handled : {total_completed}")
    print(f"Successful Requests    : {len(successful)} ({success_rate:.2f}%)")
    print(f"Failed Requests        : {len(failed)}")
    print(f"Actual Throughput      : {actual_rps:.2f} req/sec")
    print()
    print("-" * 70)
    print("                  READ / CACHE PERFORMANCE")
    print("-" * 70)
    print(f"Total Read Requests    : {len(read_results)}")
    print(f"  * Redis Cache Hits   : {len(cache_hits)} ({cache_hit_rate:.2f}%)")
    print(f"  * Database Misses    : {len(cache_misses)} ({100.0 - cache_hit_rate:.2f}%)")
    if cache_hits:
        print(f"Cache Hit Latency P50  : {hit_p50:.2f} ms")
        print(f"Cache Hit Latency P95  : {hit_p95:.2f} ms")
    if cache_misses:
        print(f"DB Miss Latency P50    : {miss_p50:.2f} ms")
        print(f"DB Miss Latency P95    : {miss_p95:.2f} ms")
    print()
    print("-" * 70)
    print("                  WRITE INGEST PERFORMANCE")
    print("-" * 70)
    print(f"Total Write Requests   : {len(write_results)}")
    write_success = sum(1 for w in write_results if w["success"])
    write_rate = (write_success / len(write_results) * 100) if write_results else 0.0
    print(f"Write Ingest Success   : {write_success} ({write_rate:.2f}%)")
    print()
    print("-" * 70)
    print("                    OVERALL LATENCIES")
    print("-" * 70)
    print(f"Latency P50 (Median)   : {p50:.2f} ms")
    print(f"Latency P95            : {p95:.2f} ms")
    print(f"Latency P99            : {p99:.2f} ms")
    print("=" * 70)
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Concurrency-bounded, rate-controlled HTTP load test with cache hit tracking"
    )

    # Support -concurrency and --concurrency
    parser.add_argument(
        "-concurrency", "--concurrency",
        type=int,
        default=50,
        help="Amount of requests to give at the same time (concurrency limit)"
    )

    # Support --total-req, -total-req, and --total_req
    parser.add_argument(
        "-total-req", "--total-req", "--total_req",
        type=int,
        default=1000,
        help="Total requests to give in 60 seconds (default: 1000)"
    )

    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="Benchmark duration in seconds (default: 60)"
    )

    parser.add_argument(
        "--url",
        type=str,
        default="http://localhost:8000/api/v1",
        help="Base API URL (default: http://localhost:8000/api/v1)"
    )

    parser.add_argument(
        "--max-pages",
        type=int,
        default=10,
        help="Max page number to cycle through during read requests (default: 10)"
    )

    args = parser.parse_args()

    asyncio.run(
        run_benchmark(
            base_url=args.url,
            total_requests=args.total_req,
            concurrency=args.concurrency,
            duration=args.duration,
            max_pages=args.max_pages
        )
    )

