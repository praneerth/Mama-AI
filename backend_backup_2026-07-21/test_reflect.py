from app.reasoning.confidence import confidence_manager
from app.reasoning.retry_manager import retry_manager
from app.cognitive.reflect import reflect_result

confidence_manager.set_score(0.95)
retry_manager.reset()

reflect_result()