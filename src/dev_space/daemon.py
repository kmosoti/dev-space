import asyncio
import structlog
import json

logger = structlog.get_logger()

_background_tasks = []

async def compress_logs_loop():
    logger.info("Starting log compressor loop")
    try:
        while True:
            # In a real app we would wait until midnight UTC
            await asyncio.sleep(86400)
    except asyncio.CancelledError:
        logger.info("Log compressor loop cancelled")
        raise

async def rotate_logs_loop():
    logger.info("Starting log rotator loop")
    try:
        while True:
            await asyncio.sleep(86400)
    except asyncio.CancelledError:
        logger.info("Log rotator loop cancelled")
        raise

async def reap_sessions_loop():
    logger.info("Starting session reaper loop")
    try:
        while True:
            await asyncio.sleep(21600)  # 6 hours
    except asyncio.CancelledError:
        logger.info("Session reaper loop cancelled")
        raise

def start_background_tasks():
    if _background_tasks:
        return
    logger.info("Spawning background tasks")
    _background_tasks.append(asyncio.create_task(compress_logs_loop()))
    _background_tasks.append(asyncio.create_task(rotate_logs_loop()))
    _background_tasks.append(asyncio.create_task(reap_sessions_loop()))

async def rsgi_app(scope, receive, send):
    """
    Minimal RSGI application serving /healthz and /metrics.
    """
    # Lazy initialization of background tasks to ensure they attach to the correct asyncio loop
    start_background_tasks()
    
    if scope.path == "/healthz":
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"application/json")]
        })
        await send({
            "type": "http.response.body",
            "body": b'{"status": "ok"}'
        })
    elif scope.path == "/metrics":
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"application/json")]
        })
        await send({
            "type": "http.response.body",
            "body": b'{"uptime": 0}'
        })
    else:
        await send({
            "type": "http.response.start",
            "status": 404,
            "headers": [(b"content-type", b"text/plain")]
        })
        await send({
            "type": "http.response.body",
            "body": b"Not Found"
        })
