from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel
from app.services.ai_pipeline import process_request
from app.core.mama import run

router = APIRouter()

class ChatRequest(BaseModel):
    message: str

@router.post("/chat")
def chat(payload: ChatRequest, background_tasks: BackgroundTasks):
    user_message = payload.message.strip()
    
    # Process request through the AI pipeline
    result = process_request(user_message)
    intent = result.get("intent", "general_chat")
    decision = result.get("decision", "")
    
    # If the user intends to execute desktop automation, run the loop in the background
    if intent in ["open_application", "desktop_automation", "web_search"]:
        # Run cognitive loop asynchronously
        background_tasks.add_task(run, user_message)
        response_msg = f"Sure! I've started the autonomous cognitive loop to execute your request: '{user_message}'."
    else:
        response_msg = decision
        
    return {
        "response": response_msg,
        "intent": intent
    }
