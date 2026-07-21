import logging
from .settings import settings

# Setup logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("mama_ai.log", encoding="utf-8")
    ]
)

logger = logging.getLogger("mama_ai")
