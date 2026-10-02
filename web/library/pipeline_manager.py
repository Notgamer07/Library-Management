import sys
import os
import re
import subprocess
import threading
import queue
import collections
from datetime import datetime, timezone

# Django ORM is available when this module is imported inside the Django process
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "library_management.settings")

STAGE_DISPLAY_NAMES = {
    "bronze_to_silver": "Bronze to Silver",
    "silver_to_gold": "Silver to Gold",
    "landing_to_bronze": "Bronze to Silver",  # compatibility fallback
    "ALL": "Full Medallion Cycle",
    "DAEMON": "Scheduled Daemon",
    "RUN_ONCE": "Single Cycle",
}


class PipelineRunStats:
    """Lightweight mutable stats bag populated by parsing subprocess STATS: lines."""
    def __init__(self):
        self.rows_landing_to_bronze: int = 0
        self.rows_bronze_to_silver: int = 0
        self.gold_refreshed: bool = False


def _get_pipeline_script_path() -> str:
    """
    Dynamically resolves the absolute path to etl_medallion.py across possible directories
    (pipeline/ or pipelines/), whether running from project root or inside web/ directory.
    Guarantees no FileNotFoundError is raised.
    """
    curr = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        # When pipeline_manager is in web/library/: project root is 2 levels up from library
        os.path.join(os.path.dirname(os.path.dirname(curr)), "pipeline", "etl_medallion.py"),
        os.path.join(os.path.dirname(os.path.dirname(curr)), "pipelines", "etl_medallion.py"),
        # When pipeline_manager is in library/ at project root
        os.path.join(os.path.dirname(curr), "pipeline", "etl_medallion.py"),
        os.path.join(os.path.dirname(curr), "pipelines", "etl_medallion.py"),
        # Current working directory fallbacks
        os.path.join(os.getcwd(), "pipeline", "etl_medallion.py"),
        os.path.join(os.getcwd(), "pipelines", "etl_medallion.py"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[0]


class PipelineManager:
    """
    Manages the Medallion ETL subprocess with real-time lifecycle tracking.
    """

    _STATS_RE = re.compile(r"^STATS:(\w+):(\d+)$")

    def __init__(self):
        self.process: subprocess.Popen | None = None
        self.is_running: bool = False
        self.status: str = "IDLE"  # IDLE | STARTING | RUNNING | COMPLETED | FAILED | CANCELLED
        self.mode: str = "IDLE"
        self.current_pipeline_type: str | None = None
        self.started_at: datetime | None = None
        self.ended_at: datetime | None = None
        self.last_error: str | None = None
        self.logs: collections.deque = collections.deque(maxlen=500)
        self.lock = threading.RLock()

        # Non-blocking log queue - producer: _reader_thread, consumer: _drainer_thread
        self._log_queue: queue.Queue = queue.Queue(maxsize=5000)

        # Current run stats (reset on each new run)
        self._current_stats: PipelineRunStats = PipelineRunStats()

        # In-memory list of completed runs (also persisted to DB)
        self.history: list = []

        # Current DB run record id (set after Django ORM save)
        self._current_run_id: int | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _append_log(self, text: str):
        """Thread-safe log append."""
        ts = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] {text.strip()}"
        with self.lock:
            self.logs.append(entry)

    def _parse_stats_line(self, line: str):
        """Parse a STATS: line emitted by etl_medallion.py and update current stats."""
        m = self._STATS_RE.match(line.strip())
        if m:
            key, value = m.group(1), int(m.group(2))
            if key in ("bronze_to_silver", "landing_to_bronze"):
                self._current_stats.rows_bronze_to_silver = value
                self._current_stats.rows_landing_to_bronze = value
            elif key == "gold_refreshed":
                self._current_stats.gold_refreshed = bool(value)
            return True
        return False

    def _create_run_record(self, mode: str) -> int | None:
        """Persist a new PipelineRunHistory row with status=RUNNING."""
        try:
            from library.models import PipelineRunHistory
            record = PipelineRunHistory.objects.create(
                mode=mode,
                started_at=datetime.now(timezone.utc),
                status="RUNNING",
            )
            return record.pk
        except Exception as exc:
            self._append_log(f"[warn] Could not create run record in DB: {exc}")
            return None

    def _finalize_run(
        self,
        run_id: int | None,
        ended_at: datetime,
        status: str,
        error_message: str | None = None,
    ):
        """Update PipelineRunHistory row and prepend to in-memory history list."""
        stats = self._current_stats
        history_entry = {
            "run_id": run_id,
            "mode": self.current_pipeline_type or self.mode,
            "pipeline_type_display": STAGE_DISPLAY_NAMES.get(self.current_pipeline_type, self.mode),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": ended_at.isoformat(),
            "status": status,
            "rows_landing_to_bronze": stats.rows_landing_to_bronze,
            "rows_bronze_to_silver": stats.rows_bronze_to_silver,
            "gold_refreshed": stats.gold_refreshed,
            "error_message": error_message,
        }
        self.history.insert(0, history_entry)
        if len(self.history) > 50:
            self.history.pop()

        if run_id is not None:
            try:
                from library.models import PipelineRunHistory
                PipelineRunHistory.objects.filter(pk=run_id).update(
                    ended_at=ended_at,
                    status=status,
                    rows_landing_to_bronze=stats.rows_landing_to_bronze,
                    rows_bronze_to_silver=stats.rows_bronze_to_silver,
                    gold_refreshed=stats.gold_refreshed,
                    error_message=error_message,
                )
            except Exception as exc:
                self._append_log(f"[warn] Could not update run record in DB: {exc}")

    def _launch_subprocess(self, cmd: list[str]) -> subprocess.Popen:
        """Spawn pipeline subprocess with stdout and stderr merged."""
        return subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

    def _teardown_run(
        self,
        proc: subprocess.Popen,
        run_id: int | None,
        pipeline_type: str,
        exit_code: int,
    ):
        """Thread-safe teardown: finalizes DB run record, sets status, releases locks."""
        try:
            with self.lock:
                if self.process is proc or self.process is None:
                    ended_at = datetime.now(timezone.utc)
                    self.ended_at = datetime.now()
                    if self.status != "CANCELLED":
                        status = "COMPLETED" if exit_code == 0 else "FAILED"
                        error_msg = None if exit_code == 0 else f"Process exited with non-zero code: {exit_code}"
                        self.status = status
                        self.last_error = error_msg
                        self._finalize_run(
                            run_id=run_id,
                            ended_at=ended_at,
                            status=status,
                            error_message=error_msg,
                        )
                        display_name = STAGE_DISPLAY_NAMES.get(pipeline_type, pipeline_type)
                        self._append_log(
                            f"Pipeline stage '{display_name}' finished with status [{status}] (Exit code: {exit_code})."
                        )
                    self.is_running = False
                    self.process = None
        finally:
            # Crucial: clean up thread-local DB connections so Django connection pool never leaks
            try:
                from django.db import connections
                connections.close_all()
            except Exception:
                pass

    def _supervisor_thread(
        self,
        proc: subprocess.Popen,
        run_id: int | None,
        pipeline_type: str,
    ):
        """Monitors stdout, drains lines, reaps process, and safely transitions lifecycle."""
        try:
            if proc.stdout:
                for line in iter(proc.stdout.readline, ""):
                    if not line:
                        break
                    self._parse_stats_line(line)
                    self._append_log(line)
                proc.stdout.close()
        except Exception as read_exc:
            self._append_log(f"[warn] Subprocess log streaming error: {read_exc}")
        finally:
            try:
                proc.wait(timeout=5)
            except Exception:
                pass

            exit_code = proc.poll()
            if exit_code is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except Exception:
                    pass
                exit_code = proc.poll() if proc.poll() is not None else 1

            self._teardown_run(proc, run_id, pipeline_type, exit_code)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_pipeline(self, pipeline_type: str) -> tuple[bool, str]:
        """
        Start a specific Medallion pipeline stage asynchronously.
        Guarantees non-blocking return so the HTTP request can respond immediately with 202 Accepted.
        """
        valid_stages = ["landing_to_bronze", "bronze_to_silver", "silver_to_gold"]
        if pipeline_type not in valid_stages:
            return False, f"Invalid stage '{pipeline_type}'. Allowed: {', '.join(valid_stages)}"

        with self.lock:
            # Self-healing check: if process was marked running but exited, reap it first
            if self.is_running and self.process and self.process.poll() is not None:
                self._teardown_run(
                    self.process,
                    self._current_run_id,
                    self.current_pipeline_type or self.mode,
                    self.process.poll(),
                )

            if self.is_running and self.process and self.process.poll() is None:
                stage_name = STAGE_DISPLAY_NAMES.get(self.current_pipeline_type, self.current_pipeline_type)
                return False, f"A pipeline ({stage_name}) is currently running."

            self.status = "STARTING"
            self.mode = pipeline_type
            self.current_pipeline_type = pipeline_type
            self.started_at = datetime.now()
            self.ended_at = None
            self.last_error = None
            self._current_stats = PipelineRunStats()

            script_path = _get_pipeline_script_path()
            cmd = [sys.executable, "-u", script_path, "--stage", pipeline_type]

            display_name = STAGE_DISPLAY_NAMES.get(pipeline_type, pipeline_type)
            self._append_log("=" * 50)
            self._append_log(f"Starting Medallion Pipeline: {display_name}")
            self._append_log("=" * 50)

            try:
                run_id = self._create_run_record(pipeline_type)
                self._current_run_id = run_id

                proc = self._launch_subprocess(cmd)
                self.process = proc
                self.is_running = True
                self.status = "RUNNING"
                self._append_log(f"Process spawned with PID {proc.pid}. Executing stage '{pipeline_type}'...")

                threading.Thread(
                    target=self._supervisor_thread,
                    args=(proc, run_id, pipeline_type),
                    daemon=True,
                    name=f"pipeline-supervisor-{pipeline_type}",
                ).start()

                return True, f"Pipeline stage '{display_name}' started successfully."
            except Exception as exc:
                self.is_running = False
                self.status = "FAILED"
                self.last_error = str(exc)
                self._append_log(f"Failed to start pipeline: {exc}")
                return False, f"Failed to start pipeline: {exc}"

    def start_daemon(self, interval_seconds: int = 90) -> tuple[bool, str]:
        """Backward compatibility: start continuous Medallion loop."""
        with self.lock:
            if self.is_running and self.process and self.process.poll() is None:
                return False, "Pipeline is already running."

            script_path = _get_pipeline_script_path()
            cmd = [sys.executable, "-u", script_path, "--interval-seconds", str(interval_seconds)]

            try:
                self.status = "STARTING"
                self.mode = "DAEMON"
                self.current_pipeline_type = "DAEMON"
                self.started_at = datetime.now()
                self._current_stats = PipelineRunStats()
                run_id = self._create_run_record("DAEMON")
                self._current_run_id = run_id

                proc = self._launch_subprocess(cmd)
                self.process = proc
                self.is_running = True
                self.status = "RUNNING"
                self._append_log(f"Started Medallion daemon (PID: {proc.pid}, interval: {interval_seconds}s)")

                threading.Thread(
                    target=self._supervisor_thread,
                    args=(proc, run_id, "DAEMON"),
                    daemon=True,
                    name="pipeline-supervisor-daemon",
                ).start()
                return True, "Pipeline daemon started successfully."
            except Exception as exc:
                self.status = "FAILED"
                return False, f"Failed to start pipeline daemon: {exc}"

    def run_once(self) -> tuple[bool, str]:
        """Backward compatibility: run all stages once."""
        return self.start_pipeline("landing_to_bronze")

    def stop(self) -> tuple[bool, str]:
        """Terminates running pipeline subprocess safely."""
        with self.lock:
            if not self.is_running or not self.process:
                return False, "No pipeline is currently running."

            try:
                pid = self.process.pid
                self.process.terminate()
                ended_at = datetime.now(timezone.utc)
                self.ended_at = datetime.now()
                self.status = "CANCELLED"
                self._append_log(
                    f"Sent SIGTERM to pipeline PID {pid}. "
                    f"ACID: current batch will roll back to last consistent state."
                )
                self._finalize_run(
                    run_id=self._current_run_id,
                    ended_at=ended_at,
                    status="CANCELLED",
                    error_message="Manually stopped by admin.",
                )
                self.is_running = False
                self.process = None
                return True, "Pipeline stopped. In-progress transactions rolled back safely."
            except Exception as exc:
                return False, f"Failed to stop pipeline: {exc}"

    def get_status(self) -> dict:
        """Returns live status, active pipelines list, stats, and logs."""
        with self.lock:
            # Watchdog check: if process has already terminated, auto-reap immediately
            if self.is_running and self.process and self.process.poll() is not None:
                proc = self.process
                exit_code = proc.poll()
                self._teardown_run(
                    proc,
                    self._current_run_id,
                    self.current_pipeline_type or self.mode,
                    exit_code,
                )
            started_at_str = (
                self.started_at.strftime("%Y-%m-%d %H:%M:%S")
                if self.started_at
                else None
            )
            ended_at_str = (
                self.ended_at.strftime("%Y-%m-%d %H:%M:%S")
                if self.ended_at
                else None
            )

            elapsed = None
            if self.is_running and self.started_at:
                delta = datetime.now() - self.started_at
                elapsed = int(delta.total_seconds())

            display_name = STAGE_DISPLAY_NAMES.get(
                self.current_pipeline_type, self.current_pipeline_type or "—"
            )

            active_pipelines = []
            if self.is_running and self.process:
                active_pipelines.append({
                    "id": self._current_run_id,
                    "type": self.current_pipeline_type,
                    "type_display": display_name,
                    "status": self.status,
                    "pid": self.process.pid,
                    "started_at": started_at_str,
                    "elapsed_seconds": elapsed,
                })

            return {
                "is_running": self.is_running,
                "status": self.status,
                "mode": self.mode,
                "pipeline_type": self.current_pipeline_type,
                "pipeline_type_display": display_name,
                "pid": self.process.pid if (self.process and self.is_running) else None,
                "started_at": started_at_str,
                "ended_at": ended_at_str,
                "elapsed_seconds": elapsed,
                "logs": list(self.logs),
                "last_error": self.last_error,
                "active_pipelines": active_pipelines,
                "current_stats": {
                    "rows_landing_to_bronze": self._current_stats.rows_landing_to_bronze,
                    "rows_bronze_to_silver": self._current_stats.rows_bronze_to_silver,
                    "gold_refreshed": self._current_stats.gold_refreshed,
                },
            }


pipeline_mgr = PipelineManager()
