from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app.core.engine import engine
from app.core.mama import run
from app.core.task import TaskRequest, TaskStatus
from app.services.ai_pipeline import process_request


router = APIRouter(tags=["Chat"])


AUTOMATION_INTENTS = {
    "open_application",
    "desktop_automation",
    "web_search",
}


class ChatRequest(BaseModel):
    message: str


@router.post("/chat")
def chat(
    payload: ChatRequest,
    background_tasks: BackgroundTasks,
):
    user_message = payload.message.strip()

    if not user_message:
        raise HTTPException(
            status_code=400,
            detail="Message cannot be empty.",
        )

    pipeline_result = process_request(user_message)

    intent = pipeline_result.get(
        "intent",
        "general_chat",
    )

    decision = pipeline_result.get(
        "decision",
        "",
    )

    if intent in AUTOMATION_INTENTS:
        task_request = TaskRequest(
            command=user_message,
            source="api",
            autonomy_level=2,
        )

        engine.registry.register(task_request)

        background_tasks.add_task(
            run,
            task_request,
        )

        return {
            "success": True,
            "response": (
                "Mama AI accepted the automation task and "
                "started background execution."
            ),
            "intent": intent,
            "task_id": task_request.task_id,
            "task_status": TaskStatus.PENDING.value,
        }

    return {
        "success": True,
        "response": decision,
        "intent": intent,
        "task_id": None,
        "task_status": "completed",
    }