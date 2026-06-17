import fcntl
import signal
import sys
import os
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Callable, Any

import structlog

from .config import config

logger = structlog.get_logger()


class GracefulShutdown:
    """AOP context manager registered on every plugin command (ADR-007)."""

    def __init__(self):
        self._already_interrupted = False

    def __enter__(self):
        signal.signal(signal.SIGINT, self._handle)
        signal.signal(signal.SIGTERM, self._handle)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)

    def _handle(self, signum, frame):
        if self._already_interrupted:
            # Second strike: force exit immediately
            sys.exit(128 + signum)
        
        self._already_interrupted = True
        logger.warning("Interrupt received. Starting graceful shutdown. Press Ctrl+C again to force exit.")
        raise KeyboardInterrupt


@contextmanager
def tool_lock(resource_id: str, timeout_secs: int = 30):
    """
    Acquires an exclusive flock on a resource (ADR-007 Multi-Agent Locking).
    Blocks if another agent holds the lock.
    """
    lock_dir = Path("/var/lock/dev-space")
    try:
        lock_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        # Fallback to local .dev-space if we can't write to /var/lock
        lock_dir = Path.home() / ".dev-space" / "locks"
        lock_dir.mkdir(parents=True, exist_ok=True)

    lock_file = lock_dir / f"{resource_id}.lock"
    
    fd = open(lock_file, "w")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()


def setup_observability(quiet: bool = False, verbose: bool = False):
    """Configures structlog processors and output mode based on TTY detection."""
    
    # Fast TTY detection logic (ADR-007)
    is_interactive = sys.stdout.isatty()
    
    log_level = "DEBUG" if verbose else ("WARNING" if quiet else "INFO")
    
    # Lazy initialize the processors depending on the mode
    processors = [
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]
    
    if is_interactive and not quiet:
        # Human mode: Rich Console Renderer
        processors.append(structlog.dev.ConsoleRenderer())
    else:
        # Agent mode: JSONL
        processors.append(structlog.processors.JSONRenderer())
        
    structlog.configure(
        processors=processors,
        logger_factory=structlog.PrintLoggerFactory(),
    )


def plugin_command(resource_lock: str | None = None):
    """
    AOP Decorator for all Typer commands.
    Enforces observability setup, graceful shutdown, and POSIX exit codes.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Observability is set up here if we want global flags, 
            # but usually Typer handles global flags via callbacks.
            # We'll assume the Typer callback calls setup_observability.
            
            with GracefulShutdown():
                try:
                    if resource_lock:
                        with tool_lock(resource_lock):
                            result = func(*args, **kwargs)
                    else:
                        result = func(*args, **kwargs)
                        
                    return result
                except KeyboardInterrupt:
                    sys.exit(130)  # POSIX SIGINT
                except Exception as e:
                    logger.error("Command failed", error=str(e), exc_info=True)
                    sys.exit(1)    # POSIX General Error
                    
        return wrapper
    return decorator
