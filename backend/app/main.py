from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .processor import process_workspace_reports


app = FastAPI(title="ENEM Monitoring API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/process")
async def process_files() -> dict:
    try:
        result = process_workspace_reports()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erro ao processar relatórios: {exc}") from exc

    return {
        "metrics": result.metrics,
        "charts": result.charts,
        "substitution_log": result.substitution_log,
        "totals_by_role": result.totals_by_role,
        "municipalities_without_coordinator": result.municipalities_without_coordinator,
    }
