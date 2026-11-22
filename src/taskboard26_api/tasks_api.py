"""HTTP endpoints for creating and listing tasks."""

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError

from .task_schemas import TaskCreate, TaskOut, with_contract_types
from .task_store import (
    MAX_TASKS,
    StorageUnavailableError,
    TaskLimitReachedError,
    TaskRepository,
    get_task_store,
)

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["tasks"])

StoreDep = Annotated[TaskRepository, Depends(get_task_store)]


@router.post(
    "/tasks",
    status_code=201,
    response_model=TaskOut,
    responses={
        409: {"description": "Task limit reached"},
        503: {"description": "Storage unavailable"},
    },
)
def create_task(body: TaskCreate, store: StoreDep) -> TaskOut:
    """Create a task."""
    try:
        task = store.add(body.title, body.due_date)
    except TaskLimitReachedError:
        logger.warning("task_limit_reached", limit=MAX_TASKS)
        raise HTTPException(status_code=409, detail="task limit reached") from None
    except StorageUnavailableError:
        raise HTTPException(status_code=503, detail="storage unavailable") from None
    logger.info("task_created", task_id=str(task.id))
    return TaskOut.from_task(task)


@router.get(
    "/tasks",
    response_model=list[TaskOut],
    responses={503: {"description": "Storage unavailable"}},
)
def list_tasks(store: StoreDep) -> list[TaskOut]:
    """List all tasks in creation order."""
    try:
        tasks = store.list_all()
    except StorageUnavailableError:
        raise HTTPException(status_code=503, detail="storage unavailable") from None
    return [TaskOut.from_task(t) for t in tasks]


async def validation_exception_handler(request: Request, exc: Exception) -> Response:
    """422 handler: POST /tasks title errors carry the contract rule ids."""
    assert isinstance(exc, RequestValidationError)
    if request.method == "POST" and request.url.path == "/tasks":
        exc = RequestValidationError(with_contract_types(exc.errors()), body=exc.body)
    return await request_validation_exception_handler(request, exc)
