from app.reasoning.confidence import confidence_manager
from app.reasoning.retry_manager import retry_manager
from app.reasoning.self_reflection import reflect

confidence_manager.set_score(0.60)
retry_manager.reset()

print(reflect())

confidence_manager.set_score(0.95)

print(reflect())