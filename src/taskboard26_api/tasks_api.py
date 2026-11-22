"""HTTP endpoints for creating and listing tasks."""

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException

from .task_schemas import TaskCreate, TaskOut
from .task_store import MAX_TASKS, TaskLimitReachedError, TaskStore, get_task_store

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["tasks"])

StoreDep = Annotated[TaskStore, Depends(get_task_store)]


@router.post(
    "/tasks",
    status_code=201,
    response_model=TaskOut,
    responses={409: {"description": "Task limit reached"}},
)
def create_task(body: TaskCreate, store: StoreDep) -> TaskOut:
    """Create a task."""
    try:
        task = store.add(body.title, body.due_date)
    except TaskLimitReachedError:
        logger.warning("task_limit_reached", limit=MAX_TASKS)
        raise HTTPException(status_code=409, detail="task limit reached") from None
    logger.info("task_created", task_id=str(task.id), task_count=len(store))
    return TaskOut.from_task(task)


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(store: StoreDep) -> list[TaskOut]:
    """List all tasks in creation order."""
    return [TaskOut.from_task(t) for t in store.list_all()]
