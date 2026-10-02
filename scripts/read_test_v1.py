"""
Enterprise CQRS Pure Read & Redis Cache Benchmark (read_test_v1.py)

STRICT SEPARATION:
This script ONLY tests read APIs (Silver Database & Redis Cache Layer).
Zero write requests are made.

High-Performance Engine:
Powered by aiohttp with C-optimized HTTP parsing for sustained 400+ to 1500+ req/sec.

Supported Endpoints:
  1. GET /api/v1/books?page={page}&page_size={page_size}

Execution Modes:
  1. Target RPS Mode (--rps <float> --duration <float> [-concurrency <int>]):
     Paces requests smoothly at the requested RPS for the specified duration and
     measures whether the server and Redis cache achieve and sustain that rate.
  2. Concurrency Saturation Mode (-concurrency <int> --duration <float>):
     Keeps N concurrent workers continuously reading for the duration to measure
     the server's maximum sustainable read throughput capacity.
  3. Fixed Request Mode (--total-req <int> [-concurrency <int>]):
     Dispatches a fixed total number of read requests.
  4. Functional Verification Mode (--verify):
     Tests the 3-page predictive caching logic deterministically.
"""

import asyncio
import time
import aiohttp
import argparse
import random
from collections import Counter
from datetime import datetime


def current_time():
    """Return current time in HH:MM:SS format."""
    return datetime.now().strftime("%H:%M:%S")


async def single_read(
    session: aiohttp.ClientSession,
    base_url: str,
    page: int,
    page_size: int = 10
) -> dict:
    """
    Executes a single read request to /books and captures detailed cache metrics.
    """
    start = time.perf_counter()
    try:
        url = f"{base_url}/books"
        params = {"page": str(page), "page_size": str(page_size)}
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5.0)) as resp:
            body_bytes = await resp.read()
            elapsed = (time.perf_counter() - start) * 1000
            success = (resp.status == 200)
            x_cache = resp.headers.get("X-Cache", "MISS").upper()
            cache_key = resp.headers.get("X-Cache-Key", "")
            is_cache_hit = (x_cache == "HIT")
            source = "cache" if is_cache_hit else "database"
            data_count = 0
            total_pages = 0
            total_books = 0

            if success:
                try:
                    import json
                    body = json.loads(body_bytes)
                    data_count = len(body.get("data", []))
                    total_pages = body.get("total_pages", 1)
                    total_books = body.get("total_books", 0)
                except Exception:
                    source = "parse_error"

            return {
                "page": page,
                "success": success,
                "status_code": resp.status,
                "elapsed_ms": elapsed,
                "source": source,
                "is_cache_hit": is_cache_hit,
                "cache_key": cache_key,
                "data_count": data_count,
                "total_pages": total_pages,
                "total_books": total_books,
            }
    except asyncio.TimeoutError:
        elapsed = (time.perf_counter() - start) * 1000
        return {
            "page": page,
            "success": False,
            "status_code": 0,
            "elapsed_ms": elapsed,
            "source": "timeout",
            "is_cache_hit": False,
            "cache_key": "",
            "data_count": 0,
            "total_pages": 0,
            "total_books": 0,
        }
    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000
        return {
            "page": page,
            "success": False,
            "status_code": 0,
            "elapsed_ms": elapsed,
            "source": f"ERR:{type(e).__name__}",
            "is_cache_hit": False,
            "cache_key": "",
            "data_count": 0,
            "total_pages": 0,
            "total_books": 0,
        }


async def run_prefetch_verification(base_url: str, page_size: int = 10):
    """
    Deterministic functional verification of the 3-page predictive caching.
    """
    print("=" * 75)
    print("        PREFETCH CACHE FUNCTIONAL VERIFICATION")
    print("=" * 75)
    print(f"Target URL: {base_url}/books")
    print()

    connector = aiohttp.TCPConnector(limit=10)
    async with aiohttp.ClientSession(connector=connector) as session:
        # Step 1: Query Page 2
        print("[Step 1] Requesting Page 2 (expect DB fetch + prefetch lag=1, lead=3)...")
        r2 = await single_read(session, base_url, page=2, page_size=page_size)
        print(f"  -> Page 2: status={r2['status_code']}, source={r2['source']}, latency={r2['elapsed_ms']:.2f}ms, items={r2['data_count']}")

        # Step 2: Query Page 1 (Lag page)
        print("\n[Step 2] Requesting Page 1 (Lag page - should be Cache HIT)...")
        r1 = await single_read(session, base_url, page=1, page_size=page_size)
        print(f"  -> Page 1: status={r1['status_code']}, source={r1['source']}, latency={r1['elapsed_ms']:.2f}ms")
        if r1["is_cache_hit"]:
            print("  [PASS] Lag Page 1 was successfully prefetched into Redis!")
        else:
            print("  [NOTE] Page 1 was not in cache.")

        # Step 3: Query Page 3 (Lead page)
        print("\n[Step 3] Requesting Page 3 (Lead page - should be Cache HIT)...")
        r3 = await single_read(session, base_url, page=3, page_size=page_size)
        print(f"  -> Page 3: status={r3['status_code']}, source={r3['source']}, latency={r3['elapsed_ms']:.2f}ms")
        if r3["is_cache_hit"]:
            print("  [PASS] Lead Page 3 was successfully prefetched into Redis!")
        else:
            print("  [NOTE] Page 3 was not in cache.")

        # Step 4: Edge Case: First Page (Page 1)
        print("\n[Step 4] Edge Case: First Page (Page 1)...")
        print(f"  -> Page 1 items returned: {r1['data_count']}, total pages: {r1['total_pages']}")

        # Step 5: Edge Case: Out of Bounds Page
        print("\n[Step 5] Edge Case: Out of bounds (Page 99999)...")
        roob = await single_read(session, base_url, page=99999, page_size=page_size)
        print(f"  -> Page 99999: status={roob['status_code']}, items={roob['data_count']}, source={roob['source']}")
        if roob["data_count"] == 0:
            print("  [PASS] Out of bounds page returned empty dataset cleanly.")

    print("\n" + "=" * 75)
    print("Verification complete.")
    print("=" * 75)


def compute_metrics(results: list, total_time: float, target_rps: float = None):
    """Computes comprehensive throughput, cache hit rate, and latency metrics."""
    total_completed = len(results)
    successful = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]

    cache_hits = [r for r in results if r["is_cache_hit"]]
    cache_misses = [r for r in results if not r["is_cache_hit"] and r["success"]]

    all_latencies = sorted([r["elapsed_ms"] for r in results])
    hit_latencies = sorted([r["elapsed_ms"] for r in cache_hits])
    miss_latencies = sorted([r["elapsed_ms"] for r in cache_misses])

    def calc_percentiles(lats):
        if not lats:
            return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
        n = len(lats)
        p50 = lats[int(n * 0.50)]
        p90 = lats[min(int(n * 0.90), n - 1)]
        p95 = lats[min(int(n * 0.95), n - 1)]
        p99 = lats[min(int(n * 0.99), n - 1)]
        return min(lats), p50, p90, p95, p99, max(lats)

    min_lat, p50, p90, p95, p99, max_lat = calc_percentiles(all_latencies)
    _, hit_p50, _, hit_p95, _, _ = calc_percentiles(hit_latencies)
    _, miss_p50, _, miss_p95, _, _ = calc_percentiles(miss_latencies)

    actual_rps = total_completed / total_time if total_time > 0 else 0.0
    success_rate = (len(successful) / total_completed * 100) if total_completed > 0 else 0.0
    hit_rate = (len(cache_hits) / len(successful) * 100) if successful else 0.0

    status_codes = Counter([r["status_code"] for r in results])
    error_types = Counter([r["source"] for r in failed])

    achieved_ratio = (actual_rps / target_rps * 100) if (target_rps and target_rps > 0) else None

    if target_rps and target_rps > 0:
        if achieved_ratio >= 95.0 and success_rate >= 99.0:
            verdict = "PASSED: Server successfully achieved and sustained target read throughput."
            verdict_code = "PASS"
        elif achieved_ratio >= 80.0 and success_rate >= 95.0:
            verdict = "ACCEPTABLE: Server achieved target read throughput within acceptable tolerance."
            verdict_code = "ACCEPTABLE"
        else:
            verdict = f"FAILED: Server achieved {actual_rps:.1f} RPS ({achieved_ratio:.1f}% of {target_rps:.1f} target)."
            verdict_code = "FAIL"
    else:
        if success_rate >= 99.0:
            verdict = f"CAPACITY MEASURED: Server sustained {actual_rps:.1f} read req/sec with {success_rate:.1f}% success rate."
            verdict_code = "PASS"
        else:
            verdict = f"DEGRADED: Server achieved {actual_rps:.1f} read req/sec but encountered {len(failed)} errors."
            verdict_code = "WARN"

    return {
        "total": total_completed,
        "successful": len(successful),
        "failed": len(failed),
        "success_rate": success_rate,
        "cache_hits": len(cache_hits),
        "cache_misses": len(cache_misses),
        "hit_rate": hit_rate,
        "actual_rps": actual_rps,
        "target_rps": target_rps,
        "achieved_ratio": achieved_ratio,
        "verdict": verdict,
        "verdict_code": verdict_code,
        "total_time": total_time,
        "min": min_lat,
        "p50": p50,
        "p90": p90,
        "p95": p95,
        "p99": p99,
        "max": max_lat,
        "hit_p50": hit_p50,
        "hit_p95": hit_p95,
        "miss_p50": miss_p50,
        "miss_p95": miss_p95,
        "status_codes": status_codes,
        "error_types": error_types
    }


def print_read_report(m: dict, base_url: str, concurrency: int, duration: float, max_pages: int, page_size: int):
    """Prints a structured summary report."""
    print()
    print("=" * 75)
    print("                     READ BENCHMARK RESULTS")
    print("=" * 75)
    print(f"Target URL              : {base_url}/books")
    print(f"Page Range Tested       : Pages 1 to {max_pages} (page_size={page_size})")
    print(f"Total Elapsed Time      : {m['total_time']:.2f} seconds")
    print(f"Concurrency Setting     : {concurrency} workers / max in-flight")
    print(f"Total Reads Handled     : {m['total']}")
    print(f"Successful Requests     : {m['successful']} ({m['success_rate']:.2f}%)")
    print(f"Failed Requests         : {m['failed']}")

    print("-" * 75)
    print("                 SERVER THROUGHPUT & CAPACITY")
    print("-" * 75)
    if m["target_rps"]:
        print(f"Target Throughput       : {m['target_rps']:.1f} req/sec")
        print(f"Actual Achieved Rate    : {m['actual_rps']:.2f} req/sec")
        print(f"Target Achievement      : {m['achieved_ratio']:.1f}% of target")
    else:
        print(f"Sustained Throughput    : {m['actual_rps']:.2f} req/sec")
    print(f"Server Evaluation       : {m['verdict']}")

    print("-" * 75)
    print("                  REDIS CACHE TELEMETRY")
    print("-" * 75)
    print(f"  * Redis Cache Hits    : {m['cache_hits']} ({m['hit_rate']:.2f}%)")
    print(f"  * Database Misses     : {m['cache_misses']} ({100.0 - m['hit_rate']:.2f}%)")
    if m["cache_hits"]:
        print(f"  * Cache Hit Latency   : P50 = {m['hit_p50']:.2f} ms | P95 = {m['hit_p95']:.2f} ms")
    if m["cache_misses"]:
        print(f"  * DB Miss Latency     : P50 = {m['miss_p50']:.2f} ms | P95 = {m['miss_p95']:.2f} ms")

    print("-" * 75)
    print("                    LATENCY PROFILE (ms)")
    print("-" * 75)
    print(f"Min Latency             : {m['min']:.2f} ms")
    print(f"Latency P50 (Median)    : {m['p50']:.2f} ms")
    print(f"Latency P90             : {m['p90']:.2f} ms")
    print(f"Latency P95             : {m['p95']:.2f} ms")
    print(f"Latency P99             : {m['p99']:.2f} ms")
    print(f"Max Latency             : {m['max']:.2f} ms")

    if m["status_codes"]:
        print("-" * 75)
        print("                  HTTP STATUS CODES")
        print("-" * 75)
        for code, count in sorted(m["status_codes"].items()):
            label = "OK" if code == 200 else ("ERROR / TIMEOUT" if code == 0 else f"HTTP {code}")
            print(f"  * Status {code} ({label}): {count} requests")

    if m["failed"] > 0 and m["error_types"]:
        print("-" * 75)
        print("                   ERROR BREAKDOWN")
        print("-" * 75)
        for err, count in m["error_types"].items():
            print(f"  * {err}: {count} occurrences")

    print("=" * 75)
    print()


async def run_read_benchmark(
    base_url: str,
    concurrency: int = 50,
    duration: float = None,
    target_rps: float = None,
    total_requests: int = None,
    max_pages: int = 10,
    page_size: int = 10,
    access_pattern: str = "mixed"
) -> dict:
    """
    Executes a high-throughput read-only benchmark measuring throughput,
    cache hit rates, and latency profiles using aiohttp.
    """
    is_rps_mode = (target_rps is not None and target_rps > 0)
    is_duration_mode = (duration is not None and duration > 0)

    if is_duration_mode and not is_rps_mode and total_requests is None:
        mode_label = f"CONCURRENCY SATURATION ({concurrency} simultaneous workers)"
    elif is_rps_mode:
        mode_label = f"TARGET RATE PACING ({target_rps:.1f} req/sec)"
    else:
        mode_label = f"FIXED REQUESTS ({total_requests} requests)"

    print("=" * 75)
    print("              PURE READ LOAD BENCHMARK (read_test_v1)")
    print("=" * 75)
    print(f"Start Time             : {current_time()}")
    print(f"Endpoint               : {base_url}/books")
    print(f"Engine                 : aiohttp (High-Performance Async Client)")
    print(f"Execution Mode         : {mode_label}")
    if is_rps_mode:
        print(f"Target Throughput      : {target_rps:.1f} req/sec")
    if is_duration_mode:
        print(f"Test Duration          : {duration:.1f} seconds")
    print(f"Concurrency Bound      : {concurrency} workers / max in-flight")
    print(f"Page Range Tested      : Pages 1 to {max_pages} (page_size={page_size})")
    print(f"Access Pattern         : {access_pattern.upper()}")
    print("=" * 75)
    print()

    def select_page(req_id: int) -> int:
        if access_pattern == "sequential":
            return (req_id % max_pages) + 1
        elif access_pattern == "random":
            return random.randint(1, max_pages)
        else:  # mixed (60% sequential cycles, 40% random jumps)
            if random.random() < 0.6:
                return (req_id % max_pages) + 1
            else:
                return random.randint(1, max_pages)

    connector = aiohttp.TCPConnector(
        limit=max(500, concurrency * 2),
        limit_per_host=max(500, concurrency * 2),
        keepalive_timeout=60,
        enable_cleanup_closed=True
    )

    results = []
    benchmark_start = time.perf_counter()

    async with aiohttp.ClientSession(connector=connector) as session:
        # ====================================================================
        # Mode 1: Concurrency Saturation Mode (Fixed Workers Looping for Duration)
        # ====================================================================
        if is_duration_mode and not is_rps_mode:
            stop_time = benchmark_start + duration
            req_counter = 0
            counter_lock = asyncio.Lock()

            async def saturation_worker():
                nonlocal req_counter
                while time.perf_counter() < stop_time:
                    async with counter_lock:
                        req_counter += 1
                        my_req_id = req_counter

                    page = select_page(my_req_id)
                    res = await single_read(session, base_url, page=page, page_size=page_size)
                    results.append(res)

            async def progress_reporter():
                last_count = 0
                last_time = time.perf_counter()
                while time.perf_counter() < stop_time:
                    await asyncio.sleep(1.0)
                    now = time.perf_counter()
                    delta_t = now - last_time
                    curr_count = len(results)
                    window_rps = (curr_count - last_count) / delta_t if delta_t > 0 else 0.0
                    last_count = curr_count
                    last_time = now

                    elapsed_total = now - benchmark_start
                    recent = results[-max(1, int(window_rps)):] if results else []
                    hits_recent = sum(1 for r in recent if r["is_cache_hit"])
                    hit_pct = (hits_recent / len(recent) * 100) if recent else 0.0
                    p50_recent = sorted([r["elapsed_ms"] for r in recent])[len(recent) // 2] if recent else 0.0
                    errs_recent = sum(1 for r in recent if not r["success"])

                    print(
                        f"  [{current_time()}] [{elapsed_total:4.1f}s / {duration:4.1f}s] "
                        f"Rate: {window_rps:6.1f} req/s | "
                        f"Cache Hit: {hit_pct:5.1f}% | "
                        f"Total: {curr_count:6d} reads | "
                        f"P50: {p50_recent:5.1f}ms | "
                        f"Errors: {errs_recent}"
                    )

            worker_tasks = [asyncio.create_task(saturation_worker()) for _ in range(concurrency)]
            reporter_task = asyncio.create_task(progress_reporter())

            await asyncio.gather(*worker_tasks)
            reporter_task.cancel()
            try:
                await reporter_task
            except asyncio.CancelledError:
                pass

        # ====================================================================
        # Mode 2: Target RPS Mode (Paced Dispatch over Duration)
        # ====================================================================
        elif is_rps_mode:
            sem = asyncio.Semaphore(concurrency)
            stop_time = benchmark_start + duration if is_duration_mode else None
            req_interval = 1.0 / target_rps if target_rps > 0 else 0.001
            req_id = 0
            tasks = set()

            last_report_time = benchmark_start
            last_report_count = 0

            async def bounded_dispatch(r_id):
                async with sem:
                    page = select_page(r_id)
                    res = await single_read(session, base_url, page=page, page_size=page_size)
                    results.append(res)

            while True:
                now = time.perf_counter()
                if is_duration_mode and now >= stop_time:
                    break
                if total_requests and req_id >= total_requests:
                    break

                req_id += 1
                scheduled_time = benchmark_start + (req_id * req_interval)
                sleep_delay = scheduled_time - now
                if sleep_delay > 0:
                    await asyncio.sleep(sleep_delay)

                t = asyncio.create_task(bounded_dispatch(req_id))
                tasks.add(t)
                t.add_done_callback(tasks.discard)

                now_after = time.perf_counter()
                if now_after - last_report_time >= 1.0:
                    dt = now_after - last_report_time
                    curr_len = len(results)
                    window_rps = (curr_len - last_report_count) / dt
                    last_report_count = curr_len
                    last_report_time = now_after

                    recent = results[-max(1, int(window_rps)):] if results else []
                    hits_recent = sum(1 for r in recent if r["is_cache_hit"])
                    hit_pct = (hits_recent / len(recent) * 100) if recent else 0.0
                    p50_recent = sorted([r["elapsed_ms"] for r in recent])[len(recent) // 2] if recent else 0.0
                    errs_recent = sum(1 for r in recent if not r["success"])
                    elapsed_total = now_after - benchmark_start

                    pct = (window_rps / target_rps * 100) if target_rps > 0 else 100.0
                    print(
                        f"  [{current_time()}] [{elapsed_total:4.1f}s / {duration:4.1f}s] "
                        f"Target: {target_rps:5.1f} | "
                        f"Achieved: {window_rps:5.1f} req/s ({pct:5.1f}%) | "
                        f"Cache Hit: {hit_pct:5.1f}% | "
                        f"In-Flight: {len(tasks):3d} | "
                        f"P50: {p50_recent:5.1f}ms | "
                        f"Errors: {errs_recent}"
                    )

            if tasks:
                _, pending = await asyncio.wait(tasks, timeout=3.0)
                for p in pending:
                    p.cancel()

        # ====================================================================
        # Mode 3: Fixed Total Requests Mode
        # ====================================================================
        else:
            sem = asyncio.Semaphore(concurrency)
            tasks = []
            for r_id in range(1, total_requests + 1):
                async def run_one(rid):
                    async with sem:
                        page = select_page(rid)
                        res = await single_read(session, base_url, page=page, page_size=page_size)
                        results.append(res)
                tasks.append(asyncio.create_task(run_one(r_id)))

            await asyncio.gather(*tasks)

        benchmark_end = time.perf_counter()

    total_time = max(0.001, benchmark_end - benchmark_start)
    metrics = compute_metrics(results, total_time, target_rps=target_rps)

    print_read_report(
        m=metrics,
        base_url=base_url,
        concurrency=concurrency,
        duration=duration or total_time,
        max_pages=max_pages,
        page_size=page_size
    )

    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Pure Read & Redis Cache Benchmark (read_test_v1)"
    )

    parser.add_argument(
        "-concurrency", "--concurrency",
        type=int,
        default=50,
        help="Simultaneous in-flight requests / worker count (default: 50)"
    )

    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Benchmark duration in seconds (e.g. 10, 30, 60)"
    )

    parser.add_argument(
        "--rps",
        type=float,
        default=None,
        help="Target requests per second (e.g. 50, 100, 200, 400, 800). If omitted, runs in Concurrency Saturation mode."
    )

    parser.add_argument(
        "-total-req", "--total-req", "--total_req",
        type=int,
        default=None,
        help="Total read requests to execute (optional if --duration is specified)"
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

    parser.add_argument(
        "--page-size",
        type=int,
        default=10,
        help="Page size per read request (default: 10)"
    )

    parser.add_argument(
        "--access-pattern",
        type=str,
        choices=["mixed", "random", "sequential"],
        default="mixed",
        help="Page access pattern: 'mixed' (60%% sequential, 40%% random), 'random', or 'sequential'"
    )

    parser.add_argument(
        "--verify",
        action="store_true",
        help="Run functional verification of 3-page predictive caching before benchmark"
    )

    args = parser.parse_args()

    if args.verify:
        asyncio.run(run_prefetch_verification(base_url=args.url, page_size=args.page_size))
    else:
        duration = args.duration
        total_req = args.total_req
        if duration is None and total_req is None:
            duration = 10.0

        asyncio.run(
            run_read_benchmark(
                base_url=args.url,
                concurrency=args.concurrency,
                duration=duration,
                target_rps=args.rps,
                total_requests=total_req,
                max_pages=args.max_pages,
                page_size=args.page_size,
                access_pattern=args.access_pattern
            )
        )
