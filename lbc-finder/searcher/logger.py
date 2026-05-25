import logging
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# File management
data_dir = os.getenv("LBC_DATA_DIR", os.path.join(os.getcwd(), "data"))
timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
file_path: str = os.path.join(data_dir, "logs", f"log_{timestamp}.log")
os.makedirs(os.path.join(data_dir, "logs"), exist_ok=True)

# Config logging
logger = logging.getLogger("lbc-finder")
logger.handlers.clear()

formatter = logging.Formatter(
    "[%(asctime)s] [%(levelname)s] [%(threadName)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
logger.addHandler(stream_handler)
logger.setLevel(logging.INFO)

# Log File
file_handler = logging.FileHandler(file_path, mode="w", encoding="utf-8")
file_handler.setLevel(logging.WARNING)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)
