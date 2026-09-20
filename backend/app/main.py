import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from app import analyst, demo  # noqa: E402
from app.db import get_conn  # noqa: E402
from app.routes import analyze, chat, events, install, suggestions  # noqa: E402

MINER_INTERVAL_S = 60  # check gating every minute; mining itself is cheap


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = get_conn()
    if demo.demo_mode():
        result = demo.bootstrap_demo(conn)
        print(f"[demo] seeded {result['seededEvents']} events, "
              f"{result['suggestionsCreated']} suggestions created")
    task = asyncio.create_task(_miner_loop())
    yield
    task.cancel()


app = FastAPI(title="MIA Detection Backend", version="1.1", lifespan=lifespan)

# Ryan's frontend + local tooling call this directly; wide-open CORS is fine
# for the hackathon demo.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(install.router, prefix="/v1")
app.include_router(events.router, prefix="/v1")
app.include_router(suggestions.router, prefix="/v1")
app.include_router(analyze.router, prefix="/v1")
app.include_router(chat.router, prefix="/v1")


async def _miner_loop() -> None:
    while True:
        await asyncio.sleep(MINER_INTERVAL_S)
        try:
            conn = get_conn()
            if analyst.should_analyze(conn):
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None, lambda: analyst.run_analysis(conn, use_llm=True)
                )
        except Exception:
            pass  # never let the loop die


@app.get("/health")
def health() -> dict:
    return {"ok": True, "demoMode": demo.demo_mode()}
