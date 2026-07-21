from app.reasoning.retry_manager import retry_manager

print("Retry:", retry_manager.get_retry_count())

retry_manager.increment()

print("Retry:", retry_manager.get_retry_count())

print("Can Retry:", retry_manager.can_retry())

retry_manager.increment()
retry_manager.increment()

print("Retry:", retry_manager.get_retry_count())

print("Can Retry:", retry_manager.can_retry())