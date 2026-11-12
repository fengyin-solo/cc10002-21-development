"""数据指标分析平台 后端服务入口。

启动：uvicorn app.main:app --host 127.0.0.1 --port 8000
健康检查：GET /api/health
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.collab.errors import CollabError
from app.collab.router import router as collab_router
from app.collab.seed import seed_collab
from app.collab.store import collab_store
from app.config import settings
from app.routers import ROUTERS
from app.store import store

app = FastAPI(title="数据指标分析平台", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in ROUTERS:
    app.include_router(module.router)
app.include_router(collab_router)


@app.on_event("startup")
def _seed_collab() -> None:
    """初始化协作域本地身份、工作空间与示例看板（幂等）。"""
    if not collab_store.workspaces:
        seed_collab(collab_store)


@app.exception_handler(CollabError)
async def collab_error_handler(request: Request, exc: CollabError) -> JSONResponse:
    """协作域错误统一出口：details 只携带调用方本空间数据，绝不回显他空间实体。"""
    body: dict[str, object] = {"ok": False, "detail": exc.message}
    if exc.details is not None:
        body["details"] = exc.details
    return JSONResponse(status_code=exc.status_code, content=body)


@app.get("/api/health")
def health() -> dict[str, object]:
    """健康检查：确认服务已经监听、示例数据已经就绪。"""
    return {"ok": True, "app": settings.app_name, "modules": len(store.module_names())}


@app.get("/api/overview")
def overview() -> dict[str, object]:
    """运营概览：把各业务模块的待处理量汇总成看板卡片。"""
    return store.overview()
