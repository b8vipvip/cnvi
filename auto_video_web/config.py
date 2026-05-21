import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
AUDIO_DIR = os.path.join(OUTPUT_DIR, "audio")
IMAGE_DIR = os.path.join(OUTPUT_DIR, "images")
VIDEO_DIR = os.path.join(OUTPUT_DIR, "videos")
SUBTITLE_DIR = os.path.join(OUTPUT_DIR, "subtitles")
FINAL_DIR = os.path.join(OUTPUT_DIR, "final")
TEMP_DIR = os.path.join(BASE_DIR, "temp")

MAX_IMAGE_SIZE_MB = 20
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}

OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

DEFAULT_SCRIPT_MODEL = "gpt-5.5"
DEFAULT_TTS_MODEL = "gpt-4o-mini-tts"
DEFAULT_IMAGE_MODEL = "gpt-image-2"
DEFAULT_IMAGE_QUALITY = "medium"

PORTRAIT_SIZE = (1080, 1920)
LANDSCAPE_SIZE = (1920, 1080)

OPENAI_TTS_VOICES = [
    "alloy", "ash", "ballad", "coral", "echo", "fable", "nova",
    "onyx", "sage", "shimmer", "verse", "marin", "cedar"
]

EDGE_TTS_VOICE_FALLBACK = "zh-CN-XiaoxiaoNeural"
