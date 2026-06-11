# config.py
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
GROQ_KEY  = os.environ["GROQ_API_KEY"]
ADMIN_ID  = int(os.environ.get("ADMIN_ID", "0"))

VOICES = {
    "sreymom": "km-KH-SreymomNeural",
    "piseth":  "km-KH-PisethNeural",
}
