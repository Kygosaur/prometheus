from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time

import httpx


async def one(client: httpx.AsyncClient, path: str) -> tuple[float, int]:
    started = time.perf_counter()
    response = await client.get(path)
    return time.perf_counter() - started, response.status_code


async def run(base_url: str, requests: int, concurrency: int) -> dict[str, object]:
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(base_url=base_url, timeout=30, limits=limits, verify=False) as client:
        semaphore = asyncio.Semaphore(concurrency)
        async def guarded():
            async with semaphore:
                return await one(client, "/health/live")
        values = await asyncio.gather(*(guarded() for _ in range(requests)))
    latencies = sorted(item[0] for item in values)
    percentile = lambda p: latencies[min(len(latencies) - 1, int((len(latencies) - 1) * p))]
    return {"requests": requests, "concurrency": concurrency, "mean_ms": round(statistics.mean(latencies) * 1000, 2), "p50_ms": round(percentile(.50) * 1000, 2), "p95_ms": round(percentile(.95) * 1000, 2), "p99_ms": round(percentile(.99) * 1000, 2), "errors": sum(code >= 400 for _, code in values)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=20)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.url, args.requests, args.concurrency)), indent=2))
