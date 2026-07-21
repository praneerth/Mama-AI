class AnalyticsEngine:
    def log_event(self, name: str, data: dict = None):
        print(f"[Analytics] Event: {name} | Data: {data}")
analytics_engine = AnalyticsEngine()