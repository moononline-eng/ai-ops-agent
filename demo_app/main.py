"""A tiny shop API with three deliberately planted problems.

Planted issues (the agent should find these from the logs alone):
  1. GET /orders/{id}  -> KeyError when an order has no "discount" field
  2. GET /stats        -> ZeroDivisionError when there are no orders today
  3. GET /search       -> slow: a per-item "query" inside a loop (N+1 pattern)
"""

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from demo_app.logging_config import setup_logging

setup_logging()
log = logging.getLogger("demo_app")
app = FastAPI(title="Demo Shop")

ORDERS = {
    1: {"id": 1, "total": 120.0, "discount": 0.1, "customer": "alice@example.com"},
    2: {"id": 2, "total": 80.0, "customer": "bob@example.com"},  # no discount -> bug 1
    3: {"id": 3, "total": 42.5, "discount": 0.0, "customer": "carol@example.com"},
}
PRODUCTS = [{"id": i, "name": f"product-{i}"} for i in range(50)]
TODAYS_ORDERS: list[dict] = []  # empty -> bug 2


def fetch_product_details(product_id: int) -> dict:
    """Simulates a database round trip."""
    time.sleep(0.01)
    return {"id": product_id, "stock": product_id % 7}


@app.middleware("http")
async def access_log(request: Request, call_next):
    request_id = str(uuid.uuid4())[:8]
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log.exception(
            "unhandled error",
            extra={"path": request.url.path, "method": request.method, "request_id": request_id},
        )
        return JSONResponse({"error": "internal error", "request_id": request_id}, status_code=500)
    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    level = logging.WARNING if duration_ms > 300 else logging.INFO
    log.log(
        level,
        "slow request" if level == logging.WARNING else "request",
        extra={
            "path": request.url.path,
            "method": request.method,
            "status": response.status_code,
            "duration_ms": duration_ms,
            "request_id": request_id,
        },
    )
    return response


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/orders/{order_id}")
def get_order(order_id: int):
    order = ORDERS.get(order_id)
    if order is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    log.info("order lookup", extra={"user_email": order["customer"]})
    final = order["total"] * (1 - order["discount"])
    return {"id": order_id, "final_total": round(final, 2)}


@app.get("/stats")
def stats():
    revenue = sum(o["total"] for o in TODAYS_ORDERS)
    average = revenue / len(TODAYS_ORDERS)
    return {"orders": len(TODAYS_ORDERS), "average_order_value": average}


@app.get("/search")
def search(q: str = ""):
    matches = [p for p in PRODUCTS if q in p["name"]]
    results = []
    for p in matches:
        details = fetch_product_details(p["id"])
        results.append({**p, **details})
    return {"count": len(results), "results": results}
