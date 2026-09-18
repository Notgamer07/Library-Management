
import asyncio
import time
import httpx
import argparse
import random
from datetime import datetime


BASE_URL = "http://localhost:8000/api/v1"


def current_time():
    """Return current time in HH:MM:SS.ms format."""
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


async def send_read_request(
    client: httpx.AsyncClient,
    req_id: int
) -> tuple[bool, float]:

    start = time.perf_counter()

    try:
        resp = await client.get(
            f"{BASE_URL}/books",
            timeout=5.0
        )

        elapsed = (time.perf_counter() - start) * 1000

        return resp.status_code == 200, elapsed

    except Exception:
        elapsed = (time.perf_counter() - start) * 1000
        return False, elapsed


async def send_ingest_request(
    client: httpx.AsyncClient,
    req_id: int
) -> tuple[bool, float]:

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
            f"{BASE_URL}/ingest/landing",
            json=payload,
            timeout=5.0
        )

        elapsed = (time.perf_counter() - start) * 1000

        return resp.status_code == 200, elapsed

    except Exception:
        elapsed = (time.perf_counter() - start) * 1000
        return False, elapsed


async def send_request(
    client: httpx.AsyncClient,
    req_id: int,
    results: list
):

    # 80% GET /books
    # 20% POST /ingest/landing

    if random.random() < 0.8:
        success, latency = await send_read_request(
            client,
            req_id
        )
    else:
        success, latency = await send_ingest_request(
            client,
            req_id
        )

    results.append(
        (success, latency)
    )


async def run_benchmark(
    target_rps: int,
    duration: int
):

    start_clock = current_time()

    total_requests = target_rps * duration

    print("=" * 70)
    print("             RATE-CONTROLLED LOAD TEST")
    print("=" * 70)
    print(f"Start Time             : {start_clock}")
    print(f"Target Throughput      : {target_rps} requests/sec")
    print(f"Duration               : {duration} seconds")
    print(f"Target Total Requests  : {total_requests}")
    print("=" * 70)
    print()

    results = []

    # Allow a large number of simultaneous connections.
    limits = httpx.Limits(
        max_connections=2000,
        max_keepalive_connections=1000
    )

    async with httpx.AsyncClient(
        limits=limits
    ) as client:

        tasks = []

        benchmark_start = time.perf_counter()

        # ---------------------------------------------------------
        # Generate exactly target_rps request launch opportunities
        # per second.
        # ---------------------------------------------------------

        request_interval = 1.0 / target_rps

        for req_id in range(total_requests):

            # Calculate when this request should start.
            scheduled_time = (
                benchmark_start +
                (req_id * request_interval)
            )

            # Wait until scheduled launch time.
            now = time.perf_counter()

            if scheduled_time > now:
                await asyncio.sleep(
                    scheduled_time - now
                )

            # Launch request WITHOUT waiting for its completion.
            task = asyncio.create_task(
                send_request(
                    client,
                    req_id,
                    results
                )
            )

            tasks.append(task)

        # Wait for all requests to finish.
        await asyncio.gather(*tasks)

        benchmark_end = time.perf_counter()

    total_time = benchmark_end - benchmark_start

    end_clock = current_time()

    # ---------------------------------------------------------
    # Calculate statistics
    # ---------------------------------------------------------

    total_completed = len(results)

    successful = [
        latency
        for success, latency in results
        if success
    ]

    failed = [
        latency
        for success, latency in results
        if not success
    ]

    all_latencies = [
        latency
        for _, latency in results
    ]

    sorted_latencies = sorted(all_latencies)

    if sorted_latencies:

        p50 = sorted_latencies[
            int(len(sorted_latencies) * 0.50)
        ]

        p95 = sorted_latencies[
            min(
                int(len(sorted_latencies) * 0.95),
                len(sorted_latencies) - 1
            )
        ]

        p99 = sorted_latencies[
            min(
                int(len(sorted_latencies) * 0.99),
                len(sorted_latencies) - 1
            )
        ]

    else:

        p50 = 0
        p95 = 0
        p99 = 0

    actual_rps = (
        total_completed / total_time
        if total_time > 0
        else 0
    )

    success_rate = (
        len(successful) / total_completed * 100
        if total_completed > 0
        else 0
    )

    # ---------------------------------------------------------
    # Results
    # ---------------------------------------------------------

    print()
    print("=" * 70)
    print("                    BENCHMARK RESULTS")
    print("=" * 70)

    print(f"Start Time             : {start_clock}")
    print(f"End Time               : {end_clock}")

    print(f"Total Elapsed Time     : {total_time:.2f} seconds")

    print(f"Target Throughput      : {target_rps} req/sec")

    print(f"Total Requests         : {total_completed}")

    print(
        f"Successful Requests    : "
        f"{len(successful)} "
        f"({success_rate:.2f}%)"
    )

    print(
        f"Failed Requests        : "
        f"{len(failed)}"
    )

    print(
        f"Actual Throughput      : "
        f"{actual_rps:.2f} req/sec"
    )

    print()

    print(
        f"Latency P50 (Median)   : "
        f"{p50:.2f} ms"
    )

    print(
        f"Latency P95            : "
        f"{p95:.2f} ms"
    )

    print(
        f"Latency P99            : "
        f"{p99:.2f} ms"
    )

    print("=" * 70)
    print()


if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description="Rate-controlled HTTP load test"
    )

    parser.add_argument(
        "--rps",
        type=int,
        default=1000,
        help="Target requests per second"
    )

    parser.add_argument(
        "--duration",
        type=int,
        default=10,
        help="Benchmark duration in seconds"
    )

    args = parser.parse_args()

    asyncio.run(
        run_benchmark(
            target_rps=args.rps,
            duration=args.duration
        )
    )

