"""API entrypoint."""

from fastapi import FastAPI

from .config import DEBUG
from .routers import orders

app = FastAPI(title="ACME orders", debug=DEBUG)
app.include_router(orders.router)


@app.get("/health")
def health():
    return {"status": "ok"}


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
