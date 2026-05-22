import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "output"
AUDIO_DIR = OUTPUT_DIR / "audio"
IMAGE_DIR = OUTPUT_DIR / "images"
VIDEO_DIR = OUTPUT_DIR / "videos"
SUBTITLE_DIR = OUTPUT_DIR / "subtitles"
FINAL_DIR = OUTPUT_DIR / "final"
TEMP_DIR = BASE_DIR / "temp"

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}

OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_SCRIPT_MODEL = os.getenv("OPENAI_SCRIPT_MODEL", "")
OPENAI_TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
OPENAI_IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "change-me")
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "200"))

DEFAULT_SCRIPT_MODEL = os.getenv("DEFAULT_SCRIPT_MODEL", "gpt-5.5")
DEFAULT_TTS_MODEL = OPENAI_TTS_MODEL
DEFAULT_IMAGE_MODEL = OPENAI_IMAGE_MODEL
DEFAULT_IMAGE_QUALITY = "medium"

PORTRAIT_SIZE = (1080, 1920)
LANDSCAPE_SIZE = (1920, 1080)

OPENAI_TTS_VOICES = [
    "alloy", "ash", "ballad", "coral", "echo", "fable", "nova",
    "onyx", "sage", "shimmer", "verse", "marin", "cedar"
]

EDGE_TTS_VOICE_FALLBACK = "zh-CN-XiaoxiaoNeural"

MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "auto_video")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "auto_video_db")
MYSQL_CHARSET = os.getenv("MYSQL_CHARSET", "utf8mb4")
