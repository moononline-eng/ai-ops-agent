"""Generate traffic against the demo app so it produces realistic logs.

Usage: python -m demo_app.traffic --base-url http://localhost:8000 --rounds 20
"""

import argparse
import random
import time

import httpx

PATHS = ["/health", "/orders/1", "/orders/2", "/orders/3", "/orders/99", "/stats", "/search?q=product"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--delay", type=float, default=0.1)
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url, timeout=10) as client:
        for _ in range(args.rounds):
            path = random.choice(PATHS)
            try:
                r = client.get(path)
                print(f"{r.status_code} {path}")
            except httpx.HTTPError as e:
                print(f"ERR {path}: {e}")
            time.sleep(args.delay)


if __name__ == "__main__":
    main()
