"""FastAPI entrypoint for the local ContextPatch dashboard."""

from __future__ import annotations

import secrets
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import Settings
from app.db import Database
from app.minds import MindsBuilderTransport, MindsError, MindsSchemaError
from app.services import ContextPatchService

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


def redirect(
    path: str = "/", *, notice: str | None = None, error: str | None = None
) -> RedirectResponse:
    query: dict[str, str] = {}
    if notice:
        query["notice"] = notice
    if error:
        query["error"] = error
    target = f"{path}?{urlencode(query)}" if query else path
    return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)


async def checked_form(request: Request) -> Any:
    form = await request.form()
    supplied = str(form.get("csrf_token", ""))
    expected = str(request.cookies.get("contextpatch_csrf", ""))
    if not expected or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="表单安全校验失败，请刷新页面")
    return form


def service(request: Request) -> ContextPatchService:
    return request.app.state.service


def settings(request: Request) -> Settings:
    return request.app.state.settings


def transport(request: Request) -> MindsBuilderTransport:
    config = settings(request)
    if not config.minds_api_key or not config.mind_id:
        raise ValueError("尚未在 .env 配置 Minds；本地流程仍可完整演示")
    return MindsBuilderTransport(
        config.minds_api_key, config.mind_id, config.minds_base_url
    )


def create_app(config: Settings | None = None) -> FastAPI:
    active = config or Settings.from_env()
    database_path = active.database_path
    if not database_path.is_absolute():
        database_path = BASE_DIR / database_path
    app_service = ContextPatchService(Database(database_path))

    app = FastAPI(title="ContextPatch", version="0.1.0", docs_url=None, redoc_url=None)
    app.state.service = app_service
    app.state.settings = active
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")

    @app.middleware("http")
    async def local_security(request: Request, call_next: Any) -> Any:
        token = request.cookies.get("contextpatch_csrf") or secrets.token_urlsafe(32)
        request.state.csrf_token = token
        response = await call_next(request)
        if "contextpatch_csrf" not in request.cookies:
            response.set_cookie(
                "contextpatch_csrf",
                token,
                httponly=True,
                samesite="strict",
                secure=False,
                max_age=86_400,
            )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; img-src 'self' data:"
        )
        return response

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "paused" if app_service.is_paused() else "ok",
            "database": "local_sqlite",
            "auto_publish": False,
            "minds_configured": bool(active.minds_api_key and active.mind_id),
            "credit_floor": active.credit_floor,
        }

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={
                "request": request,
                "csrf_token": request.state.csrf_token,
                "notice": request.query_params.get("notice"),
                "error": request.query_params.get("error"),
                "state": app_service.dashboard(),
                "default_due": (date.today() + timedelta(days=2)).isoformat(),
                "minds_configured": bool(active.minds_api_key and active.mind_id),
            },
        )

    @app.post("/demo/load")
    async def load_demo(request: Request) -> RedirectResponse:
        try:
            await checked_form(request)
            inserted, duplicates = app_service.load_demo(BASE_DIR / "data" / "synthetic_demo.json")
            return redirect(notice=f"合成演示已载入：新增 {inserted} 个版本，重复 {duplicates} 个")
        except ValueError as exc:
            return redirect(error=str(exc))

    @app.post("/changes")
    async def create_change(request: Request) -> RedirectResponse:
        try:
            form = await checked_form(request)
            change_id = app_service.create_change(
                source_id=int(str(form.get("source_id", "0"))),
                fact_key=str(form.get("fact_key", "")),
                old_fact=str(form.get("old_fact", "")),
                new_fact=str(form.get("new_fact", "")),
                disclosure_principle=str(form.get("disclosure_principle", "")),
                due_at=str(form.get("due_at", "")),
            )
            return redirect(notice=f"事实变更 #{change_id} 已录入，待人工批准")
        except (TypeError, ValueError) as exc:
            return redirect(error=str(exc))

    @app.post("/changes/{change_id}/approve")
    async def approve_change(change_id: int, request: Request) -> RedirectResponse:
        try:
            await checked_form(request)
            exchange_id = app_service.approve_change(change_id)
            return redirect(notice=f"变更已批准；Minds 记忆写入请求 #{exchange_id} 已准备，未发送")
        except ValueError as exc:
            return redirect(error=str(exc))

    @app.post("/changes/{change_id}/reject")
    async def reject_change(change_id: int, request: Request) -> RedirectResponse:
        try:
            await checked_form(request)
            app_service.reject_change(change_id)
            return redirect(notice="变更已拒绝，相关更正项已取消")
        except ValueError as exc:
            return redirect(error=str(exc))

    @app.post("/queue/{queue_id}/approve")
    async def approve_correction(queue_id: int, request: Request) -> RedirectResponse:
        try:
            await checked_form(request)
            app_service.decide_correction(queue_id, True)
            return redirect(notice="更正草稿已人工批准；仍未发布，请在平台人工执行")
        except ValueError as exc:
            return redirect(error=str(exc))

    @app.post("/queue/{queue_id}/reject")
    async def reject_correction(queue_id: int, request: Request) -> RedirectResponse:
        try:
            await checked_form(request)
            app_service.decide_correction(queue_id, False)
            return redirect(notice="更正草稿已拒绝，未发布")
        except ValueError as exc:
            return redirect(error=str(exc))

    @app.post("/queue/{queue_id}/follow-up")
    async def mark_follow_up(queue_id: int, request: Request) -> RedirectResponse:
        try:
            await checked_form(request)
            app_service.mark_follow_up(queue_id)
            return redirect(notice="WHY NOW 跟进已记录；没有发送外部消息")
        except ValueError as exc:
            return redirect(error=str(exc))

    @app.post("/pause")
    async def toggle_pause(request: Request) -> RedirectResponse:
        form = await checked_form(request)
        paused = str(form.get("paused", "1")) == "1"
        app_service.set_paused(paused)
        return redirect(notice="系统已暂停" if paused else "系统已恢复")

    @app.post("/minds/{exchange_id}/send")
    async def send_minds(exchange_id: int, request: Request) -> RedirectResponse:
        try:
            await checked_form(request)
            receipt = await app_service.send_exchange(
                exchange_id, transport(request), credit_floor=active.credit_floor
            )
            return redirect(
                notice=(
                    f"Minds 请求已发送（会话 {receipt.alias}）；"
                    "更正内容仍未对外发布"
                )
            )
        except (ValueError, MindsError) as exc:
            return redirect(error=str(exc))

    @app.post("/minds/{exchange_id}/sync")
    async def sync_minds(exchange_id: int, request: Request) -> RedirectResponse:
        try:
            await checked_form(request)
            found = await app_service.sync_exchange(exchange_id, transport(request))
            return redirect(notice="Minds 回复已核验" if found else "历史中暂无可核验回复，未重发")
        except (ValueError, MindsError, MindsSchemaError) as exc:
            return redirect(error=str(exc))

    return app


app = create_app()
