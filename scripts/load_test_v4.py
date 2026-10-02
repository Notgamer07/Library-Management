"""
Enterprise CQRS Pure Write Load Test (load_test_v4.py)

STRICT SEPARATION:
This script ONLY tests write ingestion APIs (Landing Site / Bronze Database).
Zero read requests are made.

High-Performance Engine:
Powered by aiohttp with C-optimized HTTP parsing for sustained 150+ to 1000+ req/sec.

Supported Endpoints:
  1. POST /api/v1/ingest/landing (Book catalog raw write ingestion)
  2. POST /api/v1/ingest/borrow  (Student borrow write ingestion)

Execution Modes:
  1. Target RPS Mode (--rps <float> --duration <float> [-concurrency <int>]):
     Paces requests smoothly at the requested RPS for the specified duration and
     measures whether the server achieves and sustains that target rate.
  2. Concurrency Saturation Mode (-concurrency <int> --duration <float>):
     Keeps N concurrent workers continuously firing requests for the duration to
     measure the server's maximum sustainable throughput capacity.
  3. Fixed Request Mode (--total-req <int> [-concurrency <int>]):
     Dispatches a fixed total number of write requests.
  4. Stepped Progression Benchmark (--stages 50,100,250,500 --stage-duration 10):
     Tests multiple throughput levels sequentially and produces a scalability matrix.
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


async def send_book_ingest_request(
    session: aiohttp.ClientSession,
    base_url: str,
    req_id: int
) -> tuple[bool, int, float, str]:
    """
    Send write request to POST /ingest/landing (Landing/Bronze Database).
    Returns: (is_success, status_code, latency_ms, ingest_type)
    """
    start = time.perf_counter()
    payload = {
        "source_channel": "LOAD_TEST_V4",
        "payload": {
            "title": f"LoadTest Book #{req_id}",
            "author": f"Author Benchmark {req_id % 50 + 1}",
            "category": random.choice(["Computer Science", "Physics", "Mathematics", "Engineering", "Literature"]),
            "publisher": random.choice(["Tech Press", "Academic Press", "O'Reilly", "Springer", "MIT Press"]),
            "price": round(random.uniform(15.0, 180.0), 2),
            "total_copies": random.randint(2, 20),
            "isbn": f"978-0-{random.randint(1000000, 9999999)}"
        }
    }
    try:
        async with session.post(
            f"{base_url}/ingest/landing",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=5.0)
        ) as resp:
            await resp.read()
            elapsed = (time.perf_counter() - start) * 1000
            return resp.status == 200, resp.status, elapsed, "BOOK_INGEST"
    except asyncio.TimeoutError:
        elapsed = (time.perf_counter() - start) * 1000
        return False, 0, elapsed, "TIMEOUT"
    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000
        return False, 0, elapsed, f"ERR:{type(e).__name__}"


async def send_borrow_ingest_request(
    session: aiohttp.ClientSession,
    base_url: str,
    req_id: int,
    student_id_prefix: str = "STU-X",
    borrower_name: str = "Student X"
) -> tuple[bool, int, float, str]:
    """
    Send student borrow write request to POST /ingest/borrow (Landing/Bronze Database).
    Returns: (is_success, status_code, latency_ms, ingest_type)
    """
    start = time.perf_counter()
    specific_student_id = f"{student_id_prefix}-{req_id % 500 + 1:04d}"
    payload = {
        "student_id": specific_student_id,
        "borrower_name": borrower_name,
        "book_title": f"LoadTest Book #{random.randint(1, 200)}",
        "loan_days": random.choice([7, 14, 21, 28])
    }
    try:
        async with session.post(
            f"{base_url}/ingest/borrow",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=5.0)
        ) as resp:
            await resp.read()
            elapsed = (time.perf_counter() - start) * 1000
            return resp.status == 200, resp.status, elapsed, "BORROW_INGEST"
    except asyncio.TimeoutError:
        elapsed = (time.perf_counter() - start) * 1000
        return False, 0, elapsed, "TIMEOUT"
    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000
        return False, 0, elapsed, f"ERR:{type(e).__name__}"


async def execute_write_request(
    session: aiohttp.ClientSession,
    base_url: str,
    req_id: int,
    mode: str,
    borrow_ratio: float,
    student_id_prefix: str,
    borrower_name: str
) -> dict:
    """Dispatches a single write request based on selected mode."""
    if mode == "books":
        success, code, latency, itype = await send_book_ingest_request(session, base_url, req_id)
    elif mode == "borrow":
        success, code, latency, itype = await send_borrow_ingest_request(
            session, base_url, req_id, student_id_prefix, borrower_name
        )
    else:  # mixed
        if random.random() < borrow_ratio:
            success, code, latency, itype = await send_borrow_ingest_request(
                session, base_url, req_id, student_id_prefix, borrower_name
            )
        else:
            success, code, latency, itype = await send_book_ingest_request(session, base_url, req_id)

    return {
        "req_id": req_id,
        "success": success,
        "status_code": code,
        "latency_ms": latency,
        "type": itype
    }


def compute_metrics(results: list, total_time: float, target_rps: float = None):
    """Computes throughput, latency percentiles, error distribution, and verdict."""
    total_completed = len(results)
    successful = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]

    book_writes = [r for r in results if r["type"] == "BOOK_INGEST"]
    borrow_writes = [r for r in results if r["type"] == "BORROW_INGEST"]

    latencies = sorted([r["latency_ms"] for r in results])

    def calc_percentiles(lats):
        if not lats:
            return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
        n = len(lats)
        p50 = lats[int(n * 0.50)]
        p90 = lats[min(int(n * 0.90), n - 1)]
        p95 = lats[min(int(n * 0.95), n - 1)]
        p99 = lats[min(int(n * 0.99), n - 1)]
        return min(lats), p50, p90, p95, p99, max(lats)

    min_lat, p50, p90, p95, p99, max_lat = calc_percentiles(latencies)
    actual_rps = total_completed / total_time if total_time > 0 else 0.0
    success_rate = (len(successful) / total_completed * 100) if total_completed > 0 else 0.0

    status_codes = Counter([r["status_code"] for r in results])
    error_types = Counter([r["type"] for r in failed])

    achieved_ratio = (actual_rps / target_rps * 100) if (target_rps and target_rps > 0) else None

    if target_rps and target_rps > 0:
        if achieved_ratio >= 95.0 and success_rate >= 99.0:
            verdict = "PASSED: Server successfully achieved and sustained target write throughput."
            verdict_code = "PASS"
        elif achieved_ratio >= 80.0 and success_rate >= 95.0:
            verdict = "ACCEPTABLE: Server achieved target write throughput within acceptable tolerance."
            verdict_code = "ACCEPTABLE"
        else:
            verdict = f"FAILED: Server achieved {actual_rps:.1f} RPS ({achieved_ratio:.1f}% of {target_rps:.1f} target)."
            verdict_code = "FAIL"
    else:
        if success_rate >= 99.0:
            verdict = f"CAPACITY MEASURED: Server sustained {actual_rps:.1f} write req/sec with {success_rate:.1f}% success rate."
            verdict_code = "PASS"
        else:
            verdict = f"DEGRADED: Server achieved {actual_rps:.1f} write req/sec but encountered {len(failed)} errors."
            verdict_code = "WARN"

    return {
        "total": total_completed,
        "successful": len(successful),
        "failed": len(failed),
        "success_rate": success_rate,
        "book_writes": len(book_writes),
        "borrow_writes": len(borrow_writes),
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
        "status_codes": status_codes,
        "error_types": error_types
    }


def print_benchmark_report(m: dict, base_url: str, concurrency: int, mode: str, duration: float):
    """Prints a structured summary report."""
    print()
    print("=" * 75)
    print("                     WRITE BENCHMARK RESULTS")
    print("=" * 75)
    print(f"Target URL              : {base_url}")
    print(f"Workload Mode           : {mode.upper()}")
    print(f"Total Elapsed Time      : {m['total_time']:.2f} seconds")
    print(f"Concurrency Setting     : {concurrency} workers / max in-flight")
    print(f"Total Writes Handled    : {m['total']}")
    print(f"Successful Writes       : {m['successful']} ({m['success_rate']:.2f}%)")
    print(f"Failed Writes           : {m['failed']}")

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
    print("                 WRITE INGESTION BREAKDOWN")
    print("-" * 75)
    print(f"  * Book Catalog Ingest : {m['book_writes']} requests -> POST /ingest/landing")
    print(f"  * Student Borrow Ingest: {m['borrow_writes']} requests -> POST /ingest/borrow")

    print("-" * 75)
    print("                   LATENCY PROFILE (ms)")
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


async def run_write_benchmark(
    base_url: str,
    concurrency: int = 50,
    duration: float = None,
    target_rps: float = None,
    total_requests: int = None,
    mode: str = "mixed",
    borrow_ratio: float = 0.5,
    student_id_prefix: str = "STU-X",
    borrower_name: str = "Student X",
    silent_header: bool = False
) -> dict:
    """
    Executes a high-throughput write-only benchmark targeting Bronze/Landing APIs using aiohttp.
    """
    is_rps_mode = (target_rps is not None and target_rps > 0)
    is_duration_mode = (duration is not None and duration > 0)

    if is_duration_mode and not is_rps_mode and total_requests is None:
        mode_label = f"CONCURRENCY SATURATION ({concurrency} simultaneous workers)"
    elif is_rps_mode:
        mode_label = f"TARGET RATE PACING ({target_rps:.1f} req/sec)"
    else:
        mode_label = f"FIXED REQUESTS ({total_requests} requests)"

    if not silent_header:
        print("=" * 75)
        print("         ENTERPRISE PURE WRITE LOAD BENCHMARK (load_test_v4)")
        print("=" * 75)
        print(f"Start Time             : {current_time()}")
        print(f"Target Base URL        : {base_url}")
        print(f"Engine                 : aiohttp (High-Performance Async Client)")
        print(f"Execution Mode         : {mode_label}")
        if is_rps_mode:
            print(f"Target Throughput      : {target_rps:.1f} req/sec")
        if is_duration_mode:
            print(f"Test Duration          : {duration:.1f} seconds")
        print(f"Concurrency Bound      : {concurrency} workers / max in-flight")
        print(f"Workload Mode          : {mode.upper()} (Borrow Ratio: {int(borrow_ratio * 100)}%)")
        print(f"Student Identity       : '{borrower_name}' ({student_id_prefix}-xxxx)")
        print("=" * 75)
        print()

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

                    res = await execute_write_request(
                        session=session,
                        base_url=base_url,
                        req_id=my_req_id,
                        mode=mode,
                        borrow_ratio=borrow_ratio,
                        student_id_prefix=student_id_prefix,
                        borrower_name=borrower_name
                    )
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
                    p50_recent = sorted([r["latency_ms"] for r in recent])[len(recent) // 2] if recent else 0.0
                    errs_recent = sum(1 for r in recent if not r["success"])

                    print(
                        f"  [{current_time()}] [{elapsed_total:4.1f}s / {duration:4.1f}s] "
                        f"Rate: {window_rps:6.1f} req/s | "
                        f"Total: {curr_count:6d} writes | "
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
                    res = await execute_write_request(
                        session=session,
                        base_url=base_url,
                        req_id=r_id,
                        mode=mode,
                        borrow_ratio=borrow_ratio,
                        student_id_prefix=student_id_prefix,
                        borrower_name=borrower_name
                    )
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
                    p50_recent = sorted([r["latency_ms"] for r in recent])[len(recent) // 2] if recent else 0.0
                    errs_recent = sum(1 for r in recent if not r["success"])
                    elapsed_total = now_after - benchmark_start

                    pct = (window_rps / target_rps * 100) if target_rps > 0 else 100.0
                    print(
                        f"  [{current_time()}] [{elapsed_total:4.1f}s / {duration:4.1f}s] "
                        f"Target: {target_rps:5.1f} | "
                        f"Achieved: {window_rps:5.1f} req/s ({pct:5.1f}%) | "
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
                        res = await execute_write_request(
                            session=session,
                            base_url=base_url,
                            req_id=rid,
                            mode=mode,
                            borrow_ratio=borrow_ratio,
                            student_id_prefix=student_id_prefix,
                            borrower_name=borrower_name
                        )
                        results.append(res)
                tasks.append(asyncio.create_task(run_one(r_id)))

            await asyncio.gather(*tasks)

        benchmark_end = time.perf_counter()

    total_time = max(0.001, benchmark_end - benchmark_start)
    metrics = compute_metrics(results, total_time, target_rps=target_rps)

    if not silent_header:
        print_benchmark_report(
            m=metrics,
            base_url=base_url,
            concurrency=concurrency,
            mode=mode,
            duration=duration or total_time
        )

    return metrics


async def run_stepped_progression(
    base_url: str,
    stages: list[int],
    stage_duration: float,
    mode: str,
    borrow_ratio: float,
    student_id_prefix: str,
    borrower_name: str
):
    """
    Executes a stepped load test progression: e.g. 50 -> 100 -> 250 -> 500 req/sec.
    """
    print("=" * 85)
    print("      STEPPED LOAD TEST PROGRESSION (Rate Scalability Benchmark)")
    print("=" * 85)
    print(f"Target URL            : {base_url}")
    print(f"Progression Stages    : {' -> '.join(str(s) + ' req/s' for s in stages)}")
    print(f"Duration per Stage    : {stage_duration:.1f} seconds")
    print(f"Workload Mode         : {mode.upper()}")
    print("=" * 85)
    print()

    stage_summaries = []

    for idx, target_rps in enumerate(stages, start=1):
        concurrency = max(20, min(500, int(target_rps * 0.4)))
        print(f"\n>>> [Stage {idx}/{len(stages)}] Ramping up to {target_rps} req/sec (concurrency={concurrency}, duration={stage_duration}s)...")

        metrics = await run_write_benchmark(
            base_url=base_url,
            concurrency=concurrency,
            duration=stage_duration,
            target_rps=target_rps,
            mode=mode,
            borrow_ratio=borrow_ratio,
            student_id_prefix=student_id_prefix,
            borrower_name=borrower_name,
            silent_header=True
        )

        stage_summaries.append({
            "target_rps": target_rps,
            "concurrency": concurrency,
            "actual_rps": metrics["actual_rps"],
            "achieved_pct": metrics["achieved_ratio"] or 0.0,
            "success_rate": metrics["success_rate"],
            "total": metrics["total"],
            "p50": metrics["p50"],
            "p95": metrics["p95"],
            "p99": metrics["p99"],
            "verdict": metrics["verdict_code"]
        })

        print(
            f"    [Stage {idx} Result] Target: {target_rps} req/s | "
            f"Achieved: {metrics['actual_rps']:.1f} req/s ({metrics['achieved_ratio']:.1f}%) | "
            f"Success: {metrics['success_rate']:.1f}% | "
            f"P50: {metrics['p50']:.1f}ms | P95: {metrics['p95']:.1f}ms | Verdict: {metrics['verdict_code']}"
        )

        if idx < len(stages):
            await asyncio.sleep(2.0)

    print("\n" + "=" * 95)
    print("                        PROGRESSION SCALABILITY MATRIX")
    print("=" * 95)
    header = f"{'Target RPS':^12} | {'Concurrency':^12} | {'Actual RPS':^12} | {'Achieved %':^12} | {'Success %':^10} | {'P50 (ms)':^10} | {'P95 (ms)':^10} | {'Verdict':^9}"
    print(header)
    print("-" * 95)
    for s in stage_summaries:
        row = f"{s['target_rps']:^12} | {s['concurrency']:^12} | {s['actual_rps']:^12.1f} | {s['achieved_pct']:^11.1f}% | {s['success_rate']:^9.1f}% | {s['p50']:^10.2f} | {s['p95']:^10.2f} | {s['verdict']:^9}"
        print(row)
    print("=" * 95)
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Pure Write Load Testing & Rate Progression Benchmark (load_test_v4)"
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
        help="Target requests per second (e.g. 50, 100, 150, 300). If omitted, runs in Concurrency Saturation mode."
    )

    parser.add_argument(
        "-total-req", "--total-req", "--total_req",
        type=int,
        default=None,
        help="Total write requests to execute (optional if --duration is specified)"
    )

    parser.add_argument(
        "--stages",
        type=str,
        default=None,
        help="Comma-separated rates to test sequentially, e.g. '50,100,250,500'"
    )

    parser.add_argument(
        "--stage-duration",
        type=float,
        default=10.0,
        help="Duration in seconds per progression stage (default: 10.0)"
    )

    parser.add_argument(
        "--url",
        type=str,
        default="http://localhost:8000/api/v1",
        help="Base API URL (default: http://localhost:8000/api/v1)"
    )

    parser.add_argument(
        "--mode",
        type=str,
        choices=["books", "borrow", "mixed"],
        default="mixed",
        help="Workload mode: 'books' (/ingest/landing), 'borrow' (/ingest/borrow), or 'mixed' (both)"
    )

    parser.add_argument(
        "--borrow-ratio",
        type=float,
        default=0.5,
        help="Fraction of borrow requests in mixed mode (default: 0.5 = 50%% borrow, 50%% book ingest)"
    )

    parser.add_argument(
        "--student-id",
        type=str,
        default="STU-X",
        help="Student ID prefix for borrow requests (default: 'STU-X')"
    )

    parser.add_argument(
        "--borrower-name",
        type=str,
        default="Student X",
        help="Borrower name for borrow requests (default: 'Student X')"
    )

    args = parser.parse_args()

    if args.stages:
        stage_list = [int(s.strip()) for s in args.stages.split(",") if s.strip()]
        asyncio.run(
            run_stepped_progression(
                base_url=args.url,
                stages=stage_list,
                stage_duration=args.stage_duration,
                mode=args.mode,
                borrow_ratio=args.borrow_ratio,
                student_id_prefix=args.student_id,
                borrower_name=args.borrower_name
            )
        )
    else:
        duration = args.duration
        total_req = args.total_req
        if duration is None and total_req is None:
            duration = 10.0

        asyncio.run(
            run_write_benchmark(
                base_url=args.url,
                concurrency=args.concurrency,
                duration=duration,
                target_rps=args.rps,
                total_requests=total_req,
                mode=args.mode,
                borrow_ratio=args.borrow_ratio,
                student_id_prefix=args.student_id,
                borrower_name=args.borrower_name
            )
        )
