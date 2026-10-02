import re
from unittest.mock import patch, MagicMock
from django.test import SimpleTestCase, Client
from fastapi.testclient import TestClient
from backend.main import app as fastapi_app
from library.views import get_medallion_metrics
from library.pipeline_manager import PipelineManager, STAGE_DISPLAY_NAMES


class HealthCheckApiTests(SimpleTestCase):
    """Test suite covering the enhanced /health API payload."""

    def setUp(self):
        self.client = Client()
        self.ts_regex = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

    def test_django_health_payload_schema_and_timestamp(self):
        """Validates Django /health endpoint response schema and high-precision UTC timestamp."""
        res = self.client.get('/health')
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertIn("status", data)
        self.assertIn("backend", data)
        self.assertIn("database", data)
        self.assertIn("web", data)
        self.assertIn("cache-server", data)
        self.assertIn("timestamp", data)

        self.assertEqual(data["backend"], "ok")
        self.assertEqual(data["web"], "ok")
        # Validate high-precision ISO-8601 UTC timestamp format
        self.assertTrue(
            bool(self.ts_regex.match(data["timestamp"])),
            f"Timestamp '{data['timestamp']}' does not match expected format YYYY-MM-DDTHH:mm:ss.sssZ"
        )

    def test_fastapi_health_payload_schema_and_timestamp(self):
        """Validates FastAPI /health endpoint response schema and high-precision UTC timestamp."""
        import asyncio
        from backend.main import health_check as fastapi_health_check
        data = asyncio.run(fastapi_health_check())

        self.assertIn("status", data)
        self.assertIn("backend", data)
        self.assertIn("database", data)
        self.assertIn("web", data)
        self.assertIn("cache-server", data)
        self.assertIn("timestamp", data)

        self.assertEqual(data["backend"], "ok")
        self.assertTrue(
            bool(self.ts_regex.match(data["timestamp"])),
            f"Timestamp '{data['timestamp']}' does not match expected format YYYY-MM-DDTHH:mm:ss.sssZ"
        )


class MedallionTierRowMetricsTests(SimpleTestCase):
    """Test suite covering distinct tier row metrics calculation."""

    def test_tier_metrics_contains_distinct_tiers(self):
        """Verifies get_medallion_metrics provides separate Landing, Bronze, and Silver tier row counts."""
        metrics = get_medallion_metrics()

        # Check distinct tier keys exist
        self.assertIn("landing_rows", metrics)
        self.assertIn("bronze_rows", metrics)
        self.assertIn("silver_rows", metrics)

        # Check table breakdown keys exist
        self.assertIn("landing_books_total", metrics)
        self.assertIn("landing_borrow_total", metrics)
        self.assertIn("landing_unprocessed", metrics)
        self.assertIn("bronze_books", metrics)
        self.assertIn("bronze_borrow_records", metrics)
        self.assertIn("bronze_errors", metrics)
        self.assertIn("silver_books", metrics)
        self.assertIn("silver_borrowers", metrics)
        self.assertIn("silver_active_loans", metrics)
        self.assertIn("silver_overdue_loans", metrics)

        # Non-negative integers
        self.assertGreaterEqual(metrics["landing_rows"], 0)
        self.assertGreaterEqual(metrics["bronze_rows"], 0)
        self.assertGreaterEqual(metrics["silver_rows"], 0)


class PipelineExecutionAndLifecycleTests(SimpleTestCase):
    """Test suite covering pipeline trigger 202 status and lifecycle state management."""

    def setUp(self):
        self.client = Client()

    @patch("library.views.pipeline_mgr.start_pipeline")
    def test_pipeline_start_returns_202_accepted(self, mock_start):
        """Verifies POST /api/pipeline/start/ immediately returns HTTP 202 Accepted on success."""
        mock_start.return_value = (True, "Pipeline stage 'Landing to Bronze' started successfully.")
        
        response = self.client.post('/api/pipeline/start/', {'pipeline_type': 'landing_to_bronze'})
        self.assertEqual(response.status_code, 202)
        data = response.json()
        self.assertEqual(data["status"], "accepted")
        self.assertTrue(data["success"])
        self.assertIn("Landing to Bronze", data["message"])
        self.assertIn("pipeline", data)

    @patch("library.views.pipeline_mgr.start_pipeline")
    def test_pipeline_start_conflict_returns_409(self, mock_start):
        """Verifies POST /api/pipeline/start/ returns HTTP 409 Conflict when a pipeline is already running."""
        mock_start.return_value = (False, "A pipeline (Landing to Bronze) is currently running.")
        
        response = self.client.post('/api/pipeline/start/', {'pipeline_type': 'landing_to_bronze'})
        self.assertEqual(response.status_code, 409)
        data = response.json()
        self.assertEqual(data["status"], "error")
        self.assertFalse(data["success"])

    def test_pipeline_status_endpoint(self):
        """Verifies GET /api/pipeline/status/ returns structured status and telemetry."""
        response = self.client.get('/api/pipeline/status/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("pipeline", data)
        self.assertIn("metrics", data)
        self.assertIn("status", data["pipeline"])
        self.assertIn("active_pipelines", data["pipeline"])

    def test_pipeline_manager_lifecycle_teardown(self):
        """Tests that PipelineManager cleanly reaps exit code and transitions to COMPLETED or FAILED."""
        mgr = PipelineManager()
        
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_proc.returncode = 0
        mock_proc.stdout = None

        # Simulate teardown with exit code 0
        mgr.is_running = True
        mgr.status = "RUNNING"
        mgr.process = mock_proc
        mgr._teardown_run(mock_proc, None, "landing_to_bronze", 0)

        self.assertFalse(mgr.is_running)
        self.assertEqual(mgr.status, "COMPLETED")
        self.assertIsNone(mgr.process)

        # Simulate teardown with exit code 1 (failure)
        mock_fail_proc = MagicMock()
        mock_fail_proc.poll.return_value = 1
        mock_fail_proc.returncode = 1
        mgr.is_running = True
        mgr.status = "RUNNING"
        mgr.process = mock_fail_proc
        mgr._teardown_run(mock_fail_proc, None, "landing_to_bronze", 1)

        self.assertFalse(mgr.is_running)
        self.assertEqual(mgr.status, "FAILED")
        self.assertIn("non-zero code", mgr.last_error)


class GlobalBrandingTests(SimpleTestCase):
    """Test suite ensuring all 'Athena' occurrences have been replaced with 'JTG'."""

    def setUp(self):
        self.client = Client()

    def test_home_page_branding(self):
        """Validates home page contains JTG branding and no Athena references."""
        res = self.client.get('/')
        content = res.content.decode("utf-8")
        self.assertIn("JTG", content)
        self.assertNotIn("Athena", content)

    def test_books_page_branding(self):
        """Validates books page contains JTG branding and no Athena references."""
        res = self.client.get('/books/')
        content = res.content.decode("utf-8")
        self.assertIn("JTG", content)
        self.assertNotIn("Athena", content)

    def test_location_page_branding(self):
        """Validates location/due-books page contains JTG branding and no Athena references."""
        res = self.client.get('/location/')
        content = res.content.decode("utf-8")
        self.assertIn("JTG", content)
        self.assertNotIn("Athena", content)

    def test_admin_dashboard_branding(self):
        """Validates admin dashboard contains JTG branding and no Athena references."""
        res = self.client.get('/admin-dashboard/')
        content = res.content.decode("utf-8")
        self.assertIn("JTG", content)
        self.assertNotIn("Athena", content)
