from app.reasoning.confidence import confidence_manager

confidence_manager.set_score(0.65)

print("Confidence:", confidence_manager.get_score())
print("High Confidence:", confidence_manager.is_confident())

confidence_manager.set_score(0.92)

print("Confidence:", confidence_manager.get_score())
print("High Confidence:", confidence_manager.is_confident())