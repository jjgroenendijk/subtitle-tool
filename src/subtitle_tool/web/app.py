"""The FastAPI application factory.

The app wires together the persisted config, the SQLite job history, the event
broker, and the background worker, then serves the UI and a small JSON API on top
of them:

- a dashboard with scan-now buttons and recent jobs,
- a job detail page,
- a configuration page that validates and atomically writes the config file,
- a Server-Sent Events stream of live job progress,
- a JSON API (``/api/...``) used by tests and any programmatic client,
- ``/health/live`` (liveness) and ``/health/ready`` (readiness) probes, with the
  legacy ``/health`` kept as a deprecated liveness alias.

There is no build step: templates are server-rendered Jinja2, and the client-side
code is a small ``app.js`` (live event-stream wiring plus named Alpine.js
components for page-local interactivity) over a vendored, pinned Alpine.js build.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ValidationError

from subtitle_tool import __version__
from subtitle_tool.config import BootstrapSettings, load_bootstrap
from subtitle_tool.config.languages import LANGUAGE_NAMES
from subtitle_tool.config.loader import ConfigError, load_config, save_config
from subtitle_tool.config.models import Config
from subtitle_tool.index import IndexStore
from subtitle_tool.jobs import EventBroker, JobStore, Worker
from subtitle_tool.logging import configure_logging
from subtitle_tool.scheduler import Scheduler
from subtitle_tool.watcher import Watcher
from subtitle_tool.web import forms, serialize
from subtitle_tool.web.health import readiness
from subtitle_tool.web.sse import event_stream

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

_HERE = Path(__file__).parent


class ConfigUpdate(BaseModel):
    """Request body for the JSON config endpoint: a full or partial config dict."""

    model_config = {"extra": "allow"}


def create_app(bootstrap: BootstrapSettings | None = None) -> FastAPI:
    """Build the FastAPI application and its background machinery.

    A caller (tests) may pass a ``bootstrap`` pointing at a temporary config
    directory; the container's entry point passes none and the environment is read.
    """
    bootstrap = bootstrap or load_bootstrap()
    configure_logging()
    config_path = bootstrap.config_file
    store = JobStore(bootstrap.config_dir / "jobs.db")
    index = IndexStore(bootstrap.config_dir / "index.db")
    broker = EventBroker()

    def current_config() -> Config:
        if config_path.exists():
            return load_config(config_path)
        return Config()

    def safe_current_config() -> Config:
        # The scheduler and watcher run unattended and must not crash startup on a
        # malformed config file; they fall back to defaults until it is fixed.
        return _safe_config(current_config)

    worker = Worker(store, broker, current_config, index)
    scheduler = Scheduler(worker, safe_current_config)
    watcher = Watcher(worker, safe_current_config)

    def wanted_languages() -> list[str]:
        # From the safe (default-on-error) config so a malformed file never breaks
        # dashboard or library rendering.
        return safe_current_config().language.filter.wanted_languages

    def start_scan(mode: str) -> int | None:
        # Anything that is not an explicit "real" mode runs as a dry run.
        return worker.start(dry_run=(mode != "real"))

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        broker.bind_loop(asyncio.get_running_loop())
        # A job left running belongs to a previous, stopped process: mark it
        # interrupted rather than resume it, then start the unattended machinery.
        store.mark_running_interrupted()
        scheduler.start()
        watcher.start()
        try:
            yield
        finally:
            watcher.stop()
            scheduler.stop()
            broker.close()
            store.close()
            index.close()

    app = FastAPI(title="Subtitle Tool", version=__version__, lifespan=lifespan)
    app.state.store = store
    app.state.index = index
    app.state.broker = broker
    app.state.worker = worker
    app.state.scheduler = scheduler
    app.state.watcher = watcher
    app.mount("/static", StaticFiles(directory=_HERE / "static"), name="static")
    templates = Jinja2Templates(directory=_HERE / "templates")
    templates.env.filters["mtime"] = _format_mtime

    @app.get("/health/live")
    def health_live() -> dict[str, str]:
        """Liveness probe: the process is running and serving requests.

        Deliberately checks nothing else, so an orchestrator never restarts a healthy
        process for a transient dependency hiccup that liveness should not own.
        """
        return {"status": "alive", "version": __version__}

    @app.get("/health/ready")
    def health_ready() -> JSONResponse:
        """Readiness probe: the local state needed to serve real work is usable.

        Verifies the config directory is accessible and both SQLite databases answer
        a trivial query. Returns 200 when ready, 503 with the failing checks otherwise,
        so a load balancer or orchestrator can hold traffic until state is healthy.
        """
        result = readiness(bootstrap.config_dir, store, index)
        body = {"status": "ready" if result.ok else "not_ready", "checks": result.checks}
        return JSONResponse(body, status_code=200 if result.ok else 503)

    @app.get("/health")
    def health() -> dict[str, str]:
        """Deprecated liveness probe, kept for backward compatibility.

        Superseded by ``/health/live`` (liveness) and ``/health/ready`` (readiness);
        retained so existing container health checks keep working. Prefer the split
        endpoints in new deployments.
        """
        return {"status": "ok", "version": __version__}

    # --- HTML pages -----------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request, busy: bool = False) -> HTMLResponse:  # noqa: FBT001, FBT002
        # ``busy=1`` is set by the redirect from a manual scan rejected because a job
        # was already running; surface it as an explicit notice instead of a silent
        # bounce. ``current_job_id`` lets that notice link to the running job.
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "jobs": store.list_jobs(10),
                "busy": worker.is_busy,
                "scan_rejected": busy,
                "current_job_id": worker.current_job_id,
                "media_configured": bool(safe_current_config().scan.media_paths),
            },
        )

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    def job_page(request: Request, job_id: int) -> HTMLResponse:
        job = store.get_job(job_id)
        if job is None:
            return templates.TemplateResponse(
                request, "not_found.html", {"what": f"job {job_id}"}, status_code=404
            )
        return templates.TemplateResponse(request, "job_detail.html", {"job": job})

    @app.get("/library", response_class=HTMLResponse)
    def library_page(
        request: Request,
        page: int = 1,
        per_page: int = 50,
        # FastAPI binds this from the query string by name, so it cannot be
        # keyword-only at the call boundary (FBT001/FBT002 do not apply to routes).
        missing: bool = False,  # noqa: FBT001, FBT002
        sort: str = "name",
        direction: Annotated[str, Query(alias="dir")] = "asc",
    ) -> HTMLResponse:
        wanted = wanted_languages()
        videos = index.library(wanted)
        missing_total = sum(1 for video in videos if video.missing_languages)
        summary = {
            "total": len(videos),
            "missing": missing_total,
            "covered": len(videos) - missing_total,
        }
        # The missing filter, sort, and pagination run over the already-in-memory
        # list so counts stay correct across pages without re-querying the index.
        if missing:
            videos = [video for video in videos if video.missing_languages]
        sort, direction = _sort_library(videos, sort, direction)
        page_videos, pagination = _paginate(videos, page, per_page, missing=missing)
        return templates.TemplateResponse(
            request,
            "library.html",
            {
                "videos": page_videos,
                "wanted": wanted,
                "summary": summary,
                "pagination": pagination,
                "sort": sort,
                "dir": direction,
                "language_names": LANGUAGE_NAMES,
            },
        )

    @app.post("/scan")
    def trigger_scan(mode: Annotated[str, Form()] = "dry-run") -> RedirectResponse:
        job_id = start_scan(mode)
        target = f"/jobs/{job_id}" if job_id is not None else "/?busy=1"
        return RedirectResponse(target, status_code=303)

    @app.post("/scan/stop")
    def stop_scan() -> RedirectResponse:
        """Stop the running job from the dashboard. A no-op when nothing runs."""
        worker.cancel()
        return RedirectResponse("/", status_code=303)

    @app.post("/jobs/{job_id}/stop")
    def stop_job(job_id: int) -> RedirectResponse:
        """Stop the running job from its detail page."""
        worker.cancel(job_id)
        return RedirectResponse(f"/jobs/{job_id}", status_code=303)

    @app.post("/jobs/clear")
    def clear_jobs() -> RedirectResponse:
        """Delete finished job history from the dashboard. Keeps any running job."""
        store.clear()
        return RedirectResponse("/", status_code=303)

    @app.get("/config", response_class=HTMLResponse)
    def config_page(request: Request, index_reset: bool = False) -> HTMLResponse:  # noqa: FBT001, FBT002
        try:
            values = forms.flatten(current_config())
            load_error = None
        except ConfigError as exc:
            values = forms.flatten(Config())
            load_error = str(exc)
        return _render_config(
            request, templates, values, errors=[], load_error=load_error, index_reset=index_reset
        )

    @app.post("/config/reset-index")
    def reset_index() -> RedirectResponse:
        """Clear the media index so the next scan reprocesses the entire library.

        A deliberate maintenance action, confirmed in the UI: it does not touch the
        config file, only discards the rebuildable index.
        """
        index.reset()
        return RedirectResponse("/config?index_reset=1", status_code=303)

    @app.post("/config", response_class=HTMLResponse)
    async def save_config_page(request: Request) -> HTMLResponse:
        form = await request.form()
        specs = forms.field_specs()
        nested = forms.parse(form, specs)
        try:
            config = Config.model_validate(nested)
        except ValidationError as exc:
            errors = _validation_messages(exc)
            values = forms.flatten_partial(nested)
            return _render_config(
                request, templates, values, errors=errors, load_error=None, status_code=422
            )
        save_config(config, config_path)
        return _render_config(
            request, templates, forms.flatten(config), errors=[], load_error=None, saved=True
        )

    # --- Server-Sent Events ---------------------------------------------------

    @app.get("/events")
    async def events() -> StreamingResponse:
        return StreamingResponse(event_stream(broker), media_type="text/event-stream")

    # --- JSON API -------------------------------------------------------------

    @app.get("/api/config")
    def api_get_config() -> JSONResponse:
        try:
            return JSONResponse(current_config().model_dump(mode="json"))
        except ConfigError as exc:
            return _json_error(str(exc), 500)

    @app.put("/api/config")
    def api_put_config(payload: ConfigUpdate) -> JSONResponse:
        try:
            config = Config.model_validate(payload.model_dump())
        except ValidationError as exc:
            return JSONResponse({"errors": _validation_messages(exc)}, status_code=422)
        save_config(config, config_path)
        return JSONResponse(config.model_dump(mode="json"))

    @app.get("/api/jobs")
    def api_list_jobs(limit: int = 50) -> JSONResponse:
        return JSONResponse([serialize.job_summary(job) for job in store.list_jobs(limit)])

    @app.post("/api/jobs")
    def api_create_job(payload: dict[str, Any] | None = None) -> JSONResponse:
        mode = (payload or {}).get("mode", "dry-run")
        job_id = start_scan(mode)
        if job_id is None:
            return _json_error("a job is already running", 409)
        return JSONResponse(serialize.job_summary(store.get_job(job_id)), status_code=201)

    @app.post("/api/jobs/{job_id}/cancel")
    def api_cancel_job(job_id: int) -> JSONResponse:
        # Cancellation is cooperative: the worker observes it at the next file
        # boundary, so the job is not yet final when this returns. 202 reports the
        # request was accepted; the final cancelled status arrives over SSE and in
        # the job record once the run unwinds.
        if not worker.cancel(job_id):
            return _json_error("job is not running", 409)
        return JSONResponse({"status": "cancelling", "job_id": job_id}, status_code=202)

    @app.get("/api/jobs/{job_id}")
    def api_get_job(job_id: int) -> JSONResponse:
        job = store.get_job(job_id)
        if job is None:
            return _json_error("job not found", 404)
        return JSONResponse(serialize.job_detail(job))

    @app.get("/api/library")
    def api_library() -> JSONResponse:
        wanted = wanted_languages()
        return JSONResponse([serialize.library_video(v) for v in index.library(wanted)])

    @app.get("/api/browse")
    def api_browse(path: str | None = None) -> JSONResponse:
        """List the subdirectories of a container path, for the media-path picker.

        Browsing is confined to ``bootstrap.browse_root`` so the picker only ever
        offers paths the scanner can actually use from inside the container.
        """
        return _browse(bootstrap.browse_root, path)

    return app


def _json_error(message: str, status_code: int) -> JSONResponse:
    """A uniform ``{"error": ...}`` response for the API and browse routes."""
    return JSONResponse({"error": message}, status_code=status_code)


def _browse(root: Path, path: str | None) -> JSONResponse:
    root = root.resolve()
    target = Path(path).resolve() if path else root
    if target != root and root not in target.parents:
        return _json_error(f"path is outside the browsable root {root}", 400)
    if not target.is_dir():
        return _json_error(f"not a directory: {target}", 404)
    try:
        children = sorted(
            (
                child
                for child in target.iterdir()
                if not child.name.startswith(".") and child.is_dir()
            ),
            key=lambda child: child.name.lower(),
        )
    except OSError as exc:
        return _json_error(f"cannot read directory {target}: {exc}", 400)
    return JSONResponse(
        {
            "path": str(target),
            "parent": None if target == root else str(target.parent),
            "root": str(root),
            "entries": [{"name": child.name, "path": str(child)} for child in children],
        }
    )


def _safe_config(loader: Callable[[], Config]) -> Config:
    try:
        return loader()
    except ConfigError:
        return Config()


def _format_mtime(mtime_ns: int) -> str:
    """Render an indexed file's nanosecond mtime as a local date and time."""
    return datetime.fromtimestamp(mtime_ns / 1_000_000_000).astimezone().strftime("%Y-%m-%d %H:%M")


_MAX_PER_PAGE = 200

# Sort keys the library table exposes, mapped to the value each pulls off a
# LibraryVideo. Anything else falls back to the default name sort.
_LIBRARY_SORTS = {
    "name": lambda v: v.video.path.rsplit("/", 1)[-1].lower(),
    "count": lambda v: len(v.subtitles),
    "missing": lambda v: len(v.missing_languages),
    "size": lambda v: v.video.size,
    "modified": lambda v: v.video.mtime,
}


def _sort_library(videos: list[Any], sort: str, direction: str) -> tuple[str, str]:
    """Sort ``videos`` in place by a validated column and direction.

    Returns the normalized ``(sort, direction)`` so the template highlights the
    column actually applied rather than a bad query value. Videos arrive ordered by
    path, so an unrecognized sort leaves that stable order intact.
    """
    sort = sort if sort in _LIBRARY_SORTS else "name"
    direction = direction if direction in ("asc", "desc") else "asc"
    videos.sort(key=_LIBRARY_SORTS[sort], reverse=(direction == "desc"))
    return sort, direction


def _paginate(
    items: list[Any], page: int, per_page: int, *, missing: bool
) -> tuple[list[Any], dict[str, Any]]:
    """Slice ``items`` for the requested page, returning the slice and link metadata."""
    per_page = max(1, min(per_page, _MAX_PER_PAGE))
    total = len(items)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    pagination = {
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "total": total,
        "missing": missing,
    }
    return items[start : start + per_page], pagination


def _render_config(
    request: Request,
    templates: Jinja2Templates,
    values: dict[str, Any],
    *,
    errors: list[str],
    load_error: str | None,
    saved: bool = False,
    index_reset: bool = False,
    status_code: int = 200,
) -> HTMLResponse:
    media_paths = values.get("scan.media_paths") or []
    path_warnings = [p for p in media_paths if not Path(p).is_dir()]
    return templates.TemplateResponse(
        request,
        "config.html",
        {
            "specs": forms.field_specs(),
            "values": values,
            "errors": errors,
            "load_error": load_error,
            "saved": saved,
            "index_reset": index_reset,
            "path_warnings": path_warnings,
        },
        status_code=status_code,
    )


def _validation_messages(error: ValidationError) -> list[str]:
    messages = []
    for err in error.errors():
        location = ".".join(str(part) for part in err["loc"]) or "(root)"
        messages.append(f"{location}: {err['msg']}")
    return messages
