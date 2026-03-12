import asyncio
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from purchases.models import Purchases

from .models import Task, TaskRun
from .tasks import (
    VintedCompletionPermanentError,
    VintedConversationPermanentError,
    VintedScraperPlaywright,
    _run_vinted_purchase_completion,
    complete_vinted_purchase_task,
    fetch_vinted_conversations_task,
    _extract_non_completable_status,
)


class VintedScraperPlaywrightDescriptionTests(SimpleTestCase):
    def setUp(self):
        self.scraper = VintedScraperPlaywright(headless=True)

    def run_async(self, coroutine):
        return asyncio.run(coroutine)

    def test_extract_item_description_from_html_strips_title_prefix(self):
        html = (
            '<html><head>'
            '<meta name="description" content="Inktpatronen - Inktpatronen voor printer Brother LC 980&#10;Kleur magenta">'
            '</head></html>'
        )

        description = self.scraper.extract_item_description_from_html(html, "Inktpatronen")

        self.assertEqual(
            description,
            "Inktpatronen voor printer Brother LC 980 Kleur magenta",
        )

    def test_extract_item_description_from_html_returns_none_for_title_only(self):
        html = (
            '<html><head>'
            '<meta name="description" content="Inktpatronen">'
            '</head></html>'
        )

        description = self.scraper.extract_item_description_from_html(html, "Inktpatronen")

        self.assertIsNone(description)

    def test_get_item_description_falls_back_to_purchase_description(self):
        self.scraper.fetch_item_page_html = AsyncMock(return_value=None)

        description = self.run_async(
            self.scraper.get_item_description(
                item_url="https://www.vinted.de/items/example",
                item_title="Inktpatronen",
                purchase_description="Bundle 3 items",
            )
        )

        self.assertEqual(description, "Bundle 3 items")

    def test_get_item_description_uses_cache_for_same_item_url(self):
        html = (
            '<html><head>'
            '<meta name="description" content="Inktpatronen - Printer cartridges for Brother LC 980">'
            '</head></html>'
        )
        self.scraper.fetch_item_page_html = AsyncMock(return_value=html)

        first_description = self.run_async(
            self.scraper.get_item_description(
                item_url="https://www.vinted.de/items/example",
                item_title="Inktpatronen",
                purchase_description="Bundle 3 items",
            )
        )
        second_description = self.run_async(
            self.scraper.get_item_description(
                item_url="https://www.vinted.de/items/example",
                item_title="Inktpatronen",
                purchase_description="Different fallback",
            )
        )

        self.assertEqual(first_description, "Printer cartridges for Brother LC 980")
        self.assertEqual(second_description, "Printer cartridges for Brother LC 980")
        self.scraper.fetch_item_page_html.assert_awaited_once()

    def test_login_rejects_cookie_session_when_api_validation_fails(self):
        self.scraper.cookies_file_path = "/tmp/vinted-cookies.json"
        self.scraper.context = object()
        self.scraper.page = SimpleNamespace(goto=AsyncMock())
        self.scraper.validate_api_session = AsyncMock(return_value=False)
        self.scraper.auto_login = AsyncMock(return_value=False)
        self.scraper.get_cookies_dict = AsyncMock(return_value={"session": "cookie"})

        with patch("tasks.tasks.load_cookies", new=AsyncMock(return_value=True)), patch(
            "tasks.tasks.is_logged_in",
            new=AsyncMock(return_value=True),
        ), patch(
            "tasks.tasks.wait_for_manual_login",
            new=AsyncMock(return_value=False),
        ), patch(
            "tasks.tasks.save_cookies",
            new=AsyncMock(),
        ), patch(
            "tasks.tasks.asyncio.sleep",
            new=AsyncMock(),
        ):
            result = self.run_async(self.scraper.login())

        self.assertFalse(result)
        self.scraper.validate_api_session.assert_awaited_once()
        self.scraper.auto_login.assert_awaited_once()


class VintedConversationTaskTests(TestCase):
    def setUp(self):
        self.task = Task.objects.create(
            name="Vinted Conversations",
            slug="vinted-conversations",
            celery_task="fetch_vinted_conversations_task",
            allow_concurrent_runs=False,
        )

    def test_fetch_vinted_conversations_task_marks_failure_for_fatal_scraper_error(self):
        task_run = TaskRun.objects.create(task=self.task, status="PENDING", input_data={})

        with patch(
            "tasks.tasks.initialize_task_run_logger",
            return_value=SimpleNamespace(info=lambda *args, **kwargs: None),
        ), patch(
            "tasks.tasks._run_vinted_scraper",
            side_effect=VintedConversationPermanentError("Vinted login failed or session expired."),
        ):
            with self.assertRaises(VintedConversationPermanentError):
                fetch_vinted_conversations_task.run(task_run_id=task_run.id)

        task_run.refresh_from_db()
        self.assertEqual(task_run.status, "FAILURE")
        self.assertIn("login failed", task_run.detail.lower())


class TaskViewSetRunHistoryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            email="tasks@example.com",
            password="password",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_singleton_task_start_still_rejects_parallel_runs(self):
        task = Task.objects.create(
            name="Singleton Task",
            slug="singleton-task",
            celery_task="fetch_vinted_conversations_task",
            allow_concurrent_runs=False,
        )
        TaskRun.objects.create(task=task, status="RUNNING", input_data={})

        response = self.client.post(f"/api/tasks/{task.slug}/start/", {"input_data": {}}, format="json")

        self.assertEqual(response.status_code, 409)

    def test_concurrent_task_start_allows_parallel_runs(self):
        task = Task.objects.create(
            name="Concurrent Task",
            slug="concurrent-task",
            celery_task="complete_vinted_purchase_task",
            allow_concurrent_runs=True,
        )
        TaskRun.objects.create(task=task, status="RUNNING", input_data={})

        with patch("tasks.views.enqueue_task_run") as enqueue_mock:
            response = self.client.post(f"/api/tasks/{task.slug}/start/", {"input_data": {}}, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(TaskRun.objects.filter(task=task).count(), 2)
        enqueue_mock.assert_called_once()

    def test_task_summary_and_rerun_reuse_existing_row(self):
        task = Task.objects.create(
            name="Vinted Purchase Completion",
            slug="vinted-purchase-completion",
            celery_task="complete_vinted_purchase_task",
            allow_concurrent_runs=True,
        )
        failed_run = TaskRun.objects.create(
            task=task,
            status="FAILURE",
            input_data={"purchase_id": 1, "purchase_external_id": "conv-1", "transaction_id": "123"},
            title="Failed run",
        )
        TaskRun.objects.create(
            task=task,
            status="SUCCESS",
            input_data={"purchase_id": 2, "purchase_external_id": "conv-2", "transaction_id": "456"},
            title="Successful run",
        )

        summary_response = self.client.get(f"/api/tasks/{task.slug}/summary/")
        self.assertEqual(summary_response.status_code, 200)
        self.assertEqual(summary_response.json()["success_count"], 1)
        self.assertEqual(summary_response.json()["failure_count"], 1)
        self.assertEqual(summary_response.json()["in_progress_count"], 0)

        with patch("tasks.views.enqueue_task_run") as enqueue_mock:
            rerun_response = self.client.post(f"/api/tasks/{task.slug}/runs/{failed_run.id}/rerun/")

        self.assertEqual(rerun_response.status_code, 200)
        self.assertEqual(TaskRun.objects.filter(task=task).count(), 2)
        failed_run.refresh_from_db()
        self.assertEqual(failed_run.input_data, {"purchase_id": 1, "purchase_external_id": "conv-1", "transaction_id": "123"})
        self.assertEqual(failed_run.status, "PENDING")
        self.assertEqual(failed_run.detail, "Queued for execution.")
        self.assertIsNone(failed_run.started_at)
        self.assertIsNone(failed_run.finished_at)
        enqueue_mock.assert_called_once()

    def test_global_summary_and_rerun_reuse_existing_row(self):
        first_task = Task.objects.create(
            name="Vinted Purchase Completion",
            slug="vinted-purchase-completion",
            celery_task="complete_vinted_purchase_task",
            allow_concurrent_runs=True,
        )
        second_task = Task.objects.create(
            name="Vinted Conversations",
            slug="vinted-conversation-scraping",
            celery_task="fetch_vinted_conversations_task",
            allow_concurrent_runs=False,
        )
        source_run = TaskRun.objects.create(
            task=first_task,
            status="FAILURE",
            input_data={"purchase_id": 7},
            title="Failed purchase completion run",
        )
        TaskRun.objects.create(task=first_task, status="SUCCESS", input_data={})
        TaskRun.objects.create(task=second_task, status="PENDING", input_data={"days_to_fetch": 3})
        TaskRun.objects.create(task=second_task, status="RUNNING", input_data={"days_to_fetch": 1})

        summary_response = self.client.get("/api/tasks/summary/")
        self.assertEqual(summary_response.status_code, 200)
        self.assertEqual(summary_response.json()["success_count"], 1)
        self.assertEqual(summary_response.json()["failure_count"], 1)
        self.assertEqual(summary_response.json()["in_progress_count"], 2)

        runs_response = self.client.get("/api/tasks/runs/")
        self.assertEqual(runs_response.status_code, 200)
        self.assertEqual(runs_response.json()["count"], 4)

        with patch("tasks.views.enqueue_task_run") as enqueue_mock:
            rerun_response = self.client.post(f"/api/tasks/runs/{source_run.id}/rerun/")

        self.assertEqual(rerun_response.status_code, 200)
        self.assertEqual(TaskRun.objects.count(), 4)
        source_run.refresh_from_db()
        self.assertEqual(source_run.task, first_task)
        self.assertEqual(source_run.input_data, {"purchase_id": 7})
        self.assertEqual(source_run.status, "PENDING")
        self.assertEqual(source_run.detail, "Queued for execution.")
        enqueue_mock.assert_called_once()

    def test_global_runs_supports_task_type_filter(self):
        first_task = Task.objects.create(
            name="Vinted Purchase Completion",
            slug="vinted-purchase-completion",
            celery_task="complete_vinted_purchase_task",
            allow_concurrent_runs=True,
        )
        second_task = Task.objects.create(
            name="Vinted Conversations",
            slug="vinted-conversation-scraping",
            celery_task="fetch_vinted_conversations_task",
            allow_concurrent_runs=False,
        )
        TaskRun.objects.create(task=first_task, status="SUCCESS", input_data={})
        TaskRun.objects.create(task=second_task, status="FAILURE", input_data={})

        response = self.client.get("/api/tasks/runs/", {"task_slug": first_task.slug})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["task"]["slug"], first_task.slug)

    def test_global_runs_default_to_started_at_desc_with_nulls_last(self):
        task = Task.objects.create(
            name="History Ordering Task",
            slug="history-ordering-task",
            celery_task="fetch_vinted_conversations_task",
            allow_concurrent_runs=False,
        )
        older = TaskRun.objects.create(
            task=task,
            status="SUCCESS",
            input_data={},
            started_at=timezone.now() - timezone.timedelta(hours=2),
        )
        newer = TaskRun.objects.create(
            task=task,
            status="SUCCESS",
            input_data={},
            started_at=timezone.now() - timezone.timedelta(hours=1),
        )
        pending = TaskRun.objects.create(
            task=task,
            status="PENDING",
            input_data={},
            started_at=None,
        )

        response = self.client.get("/api/tasks/runs/")

        self.assertEqual(response.status_code, 200)
        result_ids = [row["id"] for row in response.json()["results"]]
        self.assertEqual(result_ids[:3], [newer.id, older.id, pending.id])

    def test_global_runs_support_text_filters(self):
        task = Task.objects.create(
            name="Filterable Task",
            slug="filterable-task",
            celery_task="fetch_vinted_conversations_task",
            allow_concurrent_runs=False,
        )
        other_user = get_user_model().objects.create_user(
            email="other@example.com",
            password="password",
        )
        matching_run = TaskRun.objects.create(
            task=task,
            status="FAILURE",
            title="Alpha run",
            started_by=self.user,
            input_data={},
            detail="Remote Vinted failure",
        )
        TaskRun.objects.create(
            task=task,
            status="SUCCESS",
            title="Beta run",
            started_by=other_user,
            input_data={},
            detail="Completed cleanly",
        )

        response = self.client.get(
            "/api/tasks/runs/",
            {
                "status": "FAILURE",
                "title": "Alpha",
                "started_by_email": self.user.email,
                "detail": "Vinted",
                "task_name": "Filterable",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["id"], matching_run.id)

    def test_task_runs_support_purchase_reference_and_datetime_filters(self):
        task = Task.objects.create(
            name="Purchase Completion Filter",
            slug="purchase-completion-filter",
            celery_task="complete_vinted_purchase_task",
            allow_concurrent_runs=True,
        )
        in_range = TaskRun.objects.create(
            task=task,
            status="SUCCESS",
            input_data={"purchase_id": 42, "purchase_external_id": "conv-42"},
            started_at=timezone.now() - timezone.timedelta(hours=1),
            finished_at=timezone.now() - timezone.timedelta(minutes=30),
        )
        TaskRun.objects.create(
            task=task,
            status="SUCCESS",
            input_data={"purchase_id": 99, "purchase_external_id": "conv-99"},
            started_at=timezone.now() - timezone.timedelta(days=2),
            finished_at=timezone.now() - timezone.timedelta(days=2, minutes=-10),
        )

        started_after = (timezone.now() - timezone.timedelta(hours=2)).replace(microsecond=0).isoformat()
        finished_before = timezone.now().replace(microsecond=0).isoformat()

        response = self.client.get(
            f"/api/tasks/{task.slug}/runs/",
            {
                "purchase_reference": "42",
                "started_at_start": started_after,
                "finished_at_end": finished_before,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["id"], in_range.id)

    def test_delete_finished_task_run_removes_row(self):
        task = Task.objects.create(
            name="Delete Task",
            slug="delete-task",
            celery_task="fetch_vinted_conversations_task",
            allow_concurrent_runs=False,
        )
        task_run = TaskRun.objects.create(task=task, status="FAILURE", input_data={})

        response = self.client.delete(f"/api/tasks/{task.slug}/runs/{task_run.id}/")

        self.assertEqual(response.status_code, 204)
        self.assertFalse(TaskRun.objects.filter(id=task_run.id).exists())

    def test_global_delete_finished_task_run_removes_row(self):
        task = Task.objects.create(
            name="Delete Global Task",
            slug="delete-global-task",
            celery_task="fetch_vinted_conversations_task",
            allow_concurrent_runs=False,
        )
        task_run = TaskRun.objects.create(task=task, status="SUCCESS", input_data={})

        response = self.client.delete(f"/api/tasks/runs/{task_run.id}/")

        self.assertEqual(response.status_code, 204)
        self.assertFalse(TaskRun.objects.filter(id=task_run.id).exists())

    def test_delete_rejects_running_task_run(self):
        task = Task.objects.create(
            name="Delete Protected Task",
            slug="delete-protected-task",
            celery_task="fetch_vinted_conversations_task",
            allow_concurrent_runs=False,
        )
        task_run = TaskRun.objects.create(task=task, status="RUNNING", input_data={})

        response = self.client.delete(f"/api/tasks/{task.slug}/runs/{task_run.id}/")

        self.assertEqual(response.status_code, 409)
        self.assertTrue(TaskRun.objects.filter(id=task_run.id).exists())

    @patch("scriptify_backend.celery.app.control.revoke")
    def test_cancel_running_task_run(self, revoke_mock):
        task = Task.objects.create(
            name="Cancelable Task",
            slug="cancelable-task",
            celery_task="fetch_vinted_conversations_task",
            allow_concurrent_runs=False,
        )
        task_run = TaskRun.objects.create(
            task=task,
            status="RUNNING",
            input_data={},
            celery_task_id="celery-123",
        )

        response = self.client.post(f"/api/tasks/{task.slug}/runs/{task_run.id}/cancel/")

        self.assertEqual(response.status_code, 200)
        task_run.refresh_from_db()
        self.assertEqual(task_run.status, "CANCELLED")
        self.assertEqual(task_run.detail, "Task cancelled by user.")
        self.assertIsNotNone(task_run.finished_at)
        revoke_mock.assert_called_once_with("celery-123", terminate=True)

    def test_global_cancel_rejects_finished_task_run(self):
        task = Task.objects.create(
            name="Finished Task",
            slug="finished-task",
            celery_task="fetch_vinted_conversations_task",
            allow_concurrent_runs=False,
        )
        task_run = TaskRun.objects.create(task=task, status="SUCCESS", input_data={})

        response = self.client.post(f"/api/tasks/runs/{task_run.id}/cancel/")

        self.assertEqual(response.status_code, 409)
        task_run.refresh_from_db()
        self.assertEqual(task_run.status, "SUCCESS")

    def test_global_rerun_respects_task_concurrency(self):
        task = Task.objects.create(
            name="Singleton Task",
            slug="singleton-task-global",
            celery_task="fetch_vinted_conversations_task",
            allow_concurrent_runs=False,
        )
        source_run = TaskRun.objects.create(task=task, status="FAILURE", input_data={})
        TaskRun.objects.create(task=task, status="RUNNING", input_data={})

        response = self.client.post(f"/api/tasks/runs/{source_run.id}/rerun/")

        self.assertEqual(response.status_code, 409)

    def test_rerun_rejects_same_row_when_already_running(self):
        task = Task.objects.create(
            name="Concurrent Task",
            slug="concurrent-task-rerun",
            celery_task="complete_vinted_purchase_task",
            allow_concurrent_runs=True,
        )
        source_run = TaskRun.objects.create(task=task, status="RUNNING", input_data={"purchase_id": 5})

        response = self.client.post(f"/api/tasks/{task.slug}/runs/{source_run.id}/rerun/")

        self.assertEqual(response.status_code, 409)
        source_run.refresh_from_db()
        self.assertEqual(source_run.status, "RUNNING")

    def test_global_rerun_rejects_same_row_when_already_pending(self):
        task = Task.objects.create(
            name="Concurrent Task",
            slug="concurrent-task-global-rerun",
            celery_task="complete_vinted_purchase_task",
            allow_concurrent_runs=True,
        )
        source_run = TaskRun.objects.create(task=task, status="PENDING", input_data={"purchase_id": 8})

        response = self.client.post(f"/api/tasks/runs/{source_run.id}/rerun/")

        self.assertEqual(response.status_code, 409)
        source_run.refresh_from_db()
        self.assertEqual(source_run.status, "PENDING")


class CompleteVintedPurchaseTaskTests(TestCase):
    def setUp(self):
        self.task = Task.objects.create(
            name="Vinted Purchase Completion",
            slug="vinted-purchase-completion",
            celery_task="complete_vinted_purchase_task",
            allow_concurrent_runs=True,
        )
        self.purchase = Purchases.objects.create(
            platform="vinted",
            external_id="conv-complete-1",
            product_title="Ink",
            platform_data={"transaction_id": "txn-1"},
        )

    def test_complete_vinted_purchase_task_marks_success_and_updates_purchase(self):
        task_run = TaskRun.objects.create(
            task=self.task,
            status="PENDING",
            input_data={
                "purchase_id": self.purchase.id,
                "purchase_external_id": self.purchase.external_id,
                "transaction_id": "txn-1",
            },
        )

        with patch(
            "tasks.tasks._run_vinted_purchase_completion",
            new=AsyncMock(return_value={
                "purchase_id": self.purchase.id,
                "purchase_external_id": self.purchase.external_id,
                "transaction_id": "txn-1",
                "http_status": 200,
            }),
        ):
            complete_vinted_purchase_task.run(task_run_id=task_run.id)

        task_run.refresh_from_db()
        self.purchase.refresh_from_db()
        self.assertEqual(task_run.status, "SUCCESS")
        self.assertTrue(self.purchase.platform_data["transaction_completed"])

    def test_complete_vinted_purchase_task_marks_failure_for_permanent_errors(self):
        task_run = TaskRun.objects.create(
            task=self.task,
            status="PENDING",
            input_data={
                "purchase_id": self.purchase.id,
                "purchase_external_id": self.purchase.external_id,
                "transaction_id": None,
            },
        )

        with patch(
            "tasks.tasks._run_vinted_purchase_completion",
            new=AsyncMock(side_effect=VintedCompletionPermanentError("Missing transaction_id in task input.")),
        ):
            with self.assertRaises(VintedCompletionPermanentError):
                complete_vinted_purchase_task.run(task_run_id=task_run.id)

        task_run.refresh_from_db()
        self.assertEqual(task_run.status, "FAILURE")
        self.assertIn("Missing transaction_id", task_run.detail)

    def test_run_vinted_purchase_completion_ignores_local_completed_state(self):
        self.purchase.order_status = "completed"
        self.purchase.platform_data = {
            "transaction_id": "txn-1",
            "transaction_completed": True,
        }
        self.purchase.save(update_fields=["order_status", "platform_data"])

        class FakePage:
            def __init__(self):
                self.goto = AsyncMock(side_effect=self._goto)
                self.url = "https://www.vinted.de/inbox/example?source=inbox"
                self._request_handler = None
                self.evaluate = AsyncMock(return_value={
                    "ok": True,
                    "status": 200,
                    "text": '{"code":0}',
                    "data": {"code": 0},
                    "csrfTokenPresent": True,
                    "anonIdPresent": True,
                    "pageUrl": self.url,
                })

            async def _goto(self, *args, **kwargs):
                await self.emit_request()

            def on(self, event, handler):
                if event == "request":
                    self._request_handler = handler

            async def emit_request(self):
                if self._request_handler:
                    self._request_handler(
                        SimpleNamespace(
                            headers={
                                "x-csrf-token": "csrf-1",
                                "x-anon-id": "anon-1",
                            }
                        )
                    )

        class FakeScraperBase:
            last_instance = None

            def __init__(self, base_url, headless, cookies_file_path=None, run_logger=None):
                self.base_url = base_url
                self.headless = headless
                self.cookies_file_path = cookies_file_path
                self.logger = run_logger
                self.page = FakePage()
                self.context = object()
                self.setup_browser = AsyncMock()
                self.login = AsyncMock(return_value=True)
                self.get_cookies_dict = AsyncMock(return_value={"csrf_token": "csrf-1", "anon_id": "anon-1"})
                self.cleanup = AsyncMock()
                FakeScraperBase.last_instance = self

        with patch("tasks.tasks.VintedScraperPlaywright", FakeScraperBase), patch(
            "tasks.tasks.save_cookies",
            new=AsyncMock(),
        ):
            result = asyncio.run(
                _run_vinted_purchase_completion(
                    task_run_id=1,
                    purchase_id=self.purchase.id,
                    purchase_external_id=self.purchase.external_id,
                    transaction_id="txn-1",
                    cookies_file_path="/tmp/vinted-cookies.json",
                    run_logger=AsyncMock(),
                )
            )

        fake_scraper = FakeScraperBase.last_instance
        fake_scraper.setup_browser.assert_awaited_once()
        fake_scraper.login.assert_awaited_once()
        fake_scraper.page.goto.assert_awaited_once_with(
            f"https://www.vinted.de/inbox/{self.purchase.external_id}?source=inbox",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        self.assertIsNotNone(fake_scraper.page._request_handler)
        fake_scraper.page.evaluate.assert_awaited_once()
        evaluate_script, evaluate_args = fake_scraper.page.evaluate.await_args.args
        self.assertIn("/api/v2/transactions/${transactionId}/complete", evaluate_script)
        self.assertEqual(
            evaluate_args,
            {"transactionId": "txn-1", "csrfToken": "csrf-1", "anonId": "anon-1"},
        )
        self.assertEqual(result["http_status"], 200)
        self.assertFalse(result["already_completed"])

    def test_run_vinted_purchase_completion_treats_status_450_validation_error_as_completed(self):
        class FakePage:
            def __init__(self):
                self.goto = AsyncMock(side_effect=self._goto)
                self.url = "https://www.vinted.de/inbox/example?source=inbox"
                self._request_handler = None
                self.evaluate = AsyncMock(return_value={
                    "ok": False,
                    "status": 400,
                    "text": "{\"code\":99,\"message\":\"Sorry, there are some errors\",\"message_code\":\"validation_error\"}",
                    "data": {
                        "code": 99,
                        "message": "Sorry, there are some errors",
                        "message_code": "validation_error",
                        "errors": [
                            {
                                "field": "base",
                                "value": "Transaction with status 450 can't be completed (transaction_id: txn-1)",
                            }
                        ],
                        "payload": {},
                    },
                    "csrfTokenPresent": True,
                    "anonIdPresent": True,
                    "pageUrl": self.url,
                })

            async def _goto(self, *args, **kwargs):
                await self.emit_request()

            def on(self, event, handler):
                if event == "request":
                    self._request_handler = handler

            async def emit_request(self):
                if self._request_handler:
                    self._request_handler(
                        SimpleNamespace(
                            headers={
                                "x-csrf-token": "csrf-1",
                                "x-anon-id": "anon-1",
                            }
                        )
                    )

        class FakeScraperBase:
            last_instance = None

            def __init__(self, base_url, headless, cookies_file_path=None, run_logger=None):
                self.base_url = base_url
                self.headless = headless
                self.cookies_file_path = cookies_file_path
                self.logger = run_logger
                self.page = FakePage()
                self.context = object()
                self.setup_browser = AsyncMock()
                self.login = AsyncMock(return_value=True)
                self.get_cookies_dict = AsyncMock(return_value={"anon_id": "anon-1"})
                self.cleanup = AsyncMock()
                FakeScraperBase.last_instance = self

        with patch("tasks.tasks.VintedScraperPlaywright", FakeScraperBase), patch(
            "tasks.tasks.save_cookies",
            new=AsyncMock(),
        ):
            result = asyncio.run(
                _run_vinted_purchase_completion(
                    task_run_id=2,
                    purchase_id=self.purchase.id,
                    purchase_external_id=self.purchase.external_id,
                    transaction_id="txn-1",
                    cookies_file_path="/tmp/vinted-cookies.json",
                    run_logger=AsyncMock(),
                )
            )

        self.assertEqual(result["http_status"], 400)
        self.assertTrue(result["already_completed"])
        self.assertEqual(result["completed_via"], "remote_response")

    def test_extract_non_completable_status_returns_waiting_status(self):
        payload = {
            "code": 99,
            "message": "Sorry, there are some errors",
            "message_code": "validation_error",
            "errors": [
                {
                    "field": "base",
                    "value": "Transaction with status 230 can't be completed (transaction_id: txn-1)",
                }
            ],
            "payload": {},
        }

        self.assertEqual(_extract_non_completable_status(payload), 230)
