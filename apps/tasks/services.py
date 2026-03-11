import logging
from importlib import import_module
from typing import Any, Optional

from django.utils import timezone

from .models import Task, TaskRun


logger = logging.getLogger(__name__)


def build_task_run_title(task: Task, task_run_id: int, prefix: Optional[str] = None) -> str:
    base = f"{task.name} task #{task_run_id}"
    return f"{prefix} {base}" if prefix else base


def create_task_run(
    *,
    task: Task,
    started_by=None,
    input_data: Optional[dict[str, Any]] = None,
    title_prefix: Optional[str] = None,
) -> TaskRun:
    task_run = TaskRun.objects.create(
        task=task,
        started_by=started_by,
        status="PENDING",
        input_data=input_data or {},
        detail="Queued for execution.",
        title="",
    )
    task_run.title = build_task_run_title(task, task_run.id, prefix=title_prefix)
    task_run.save(update_fields=["title"])
    return task_run


def reuse_task_run(
    *,
    task_run: TaskRun,
    started_by=None,
) -> TaskRun:
    task_run.started_by = started_by
    task_run.started_at = None
    task_run.finished_at = None
    task_run.status = "PENDING"
    task_run.celery_task_id = None
    task_run.progress = {}
    task_run.detail = "Queued for execution."
    task_run.logs_file = None
    task_run.save(
        update_fields=[
            "started_by",
            "started_at",
            "finished_at",
            "status",
            "celery_task_id",
            "progress",
            "detail",
            "logs_file",
        ]
    )
    return task_run


def delete_task_run(task_run: TaskRun) -> None:
    if task_run.logs_file:
        task_run.logs_file.delete(save=False)
    task_run.delete()


def task_has_running_run(task: Task) -> bool:
    return TaskRun.objects.filter(task=task, status__in=["PENDING", "RUNNING"]).exists()


def resolve_celery_callable(task: Task):
    celery_task_path = task.celery_task
    if "." not in celery_task_path:
        celery_task_path = f"tasks.tasks.{celery_task_path}"

    split_result = celery_task_path.rsplit(".", 1)
    if len(split_result) != 2:
        raise ValueError(
            f"Invalid celery_task format: '{task.celery_task}'. "
            "Expected format: 'module.path.function_name' or 'function_name'"
        )

    module_path, func_name = split_result
    module = import_module(module_path)
    return getattr(module, func_name)


def enqueue_task_run(task_run: TaskRun) -> TaskRun:
    try:
        celery_func = resolve_celery_callable(task_run.task)
        celery_result = celery_func.delay(task_run_id=task_run.id)
        task_run.celery_task_id = celery_result.id
        task_run.save(update_fields=["celery_task_id"])
        return task_run
    except Exception as exc:
        task_run.status = "FAILURE"
        task_run.detail = f"Failed to start: {exc}"
        task_run.finished_at = timezone.now()
        task_run.save(update_fields=["status", "detail", "finished_at"])
        raise


def enqueue_task_run_safely(task_run_id: int) -> None:
    try:
        task_run = TaskRun.objects.select_related("task").get(id=task_run_id)
    except TaskRun.DoesNotExist:
        logger.error("TaskRun %s not found when dispatching.", task_run_id)
        return

    try:
        enqueue_task_run(task_run)
    except Exception:
        logger.exception("Failed to dispatch TaskRun %s", task_run_id)
