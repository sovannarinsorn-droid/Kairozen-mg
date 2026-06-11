# ╔══════════════════════════════════════════════════════════════╗
# ║      kz-vidbot  (Kairozen Video Translator)                  ║
# ║  🎬 Video + Subtitle ខ្មែរ burn + TTS                       ║
# ║  Stack: yt-dlp + Groq Whisper + ffmpeg + edge_tts           ║
# ║  Version: 4.0 — Subtitle Burn Edition                        ║
# ╚══════════════════════════════════════════════════════════════╝

import telebot
import os
import threading
import tempfile
import asyncio
import textwrap
import logging
import sys
import time
import re

from groq import Groq
import edge_tts
import yt_dlp

from config import BOT_TOKEN, GROQ_KEY, VOICES

# ══════ Logging ══════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ══════ Init ══════
bot    = telebot.TeleBot(BOT_TOKEN, threaded=False)
client = Groq(api_key=GROQ_KEY)

sessions = {}

def get_cfg(uid):
    if uid not in sessions:
        sessions[uid] = {"voice": "sreymom", "waiting_link": False}
    return sessions[uid]

# ══════ Subtitle Style ══════
# ពណ៌លឿង ផ្ទៃខ្មៅ — ខាងក្រោម
SUBTITLE_STYLE = (
    "FontName=Khmer OS,FontSize=22,"
    "PrimaryColour=&H00FFFF&,"     # លឿង (BGR hex)
    "BackColour=&H80000000&,"      # ខ្មៅ semi-transparent
    "BorderStyle=4,"               # box background
    "Outline=1,Shadow=0,"
    "Alignment=2,"                 # bottom center
    "MarginV=20"
)

# ══════════════════════════════════════════
# KEYBOARDS
# ══════════════════════════════════════════

def main_kb():
    kb = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("🎬 ផ្ញើ Video", "🔗 Link YouTube/TikTok")
    kb.row("⚙️ ជ្រើសសំឡេង", "ℹ️ របៀបប្រើ")
    return kb

def voice_kb():
    kb = telebot.types.InlineKeyboardMarkup()
    kb.row(
        telebot.types.InlineKeyboardButton("👩 ស្រីមុំ (SreymomNeural)", callback_data="v_sreymom"),
        telebot.types.InlineKeyboardButton("👨 ពិសិដ្ឋ (PisethNeural)",  callback_data="v_piseth"),
    )
    return kb


# ══════════════════════════════════════════
# AUDIO TOOLS
# ══════════════════════════════════════════

def extract_audio_from_video(video_path: str, out_path: str) -> bool:
    ret = os.system(
        f'ffmpeg -y -i "{video_path}" -vn -ar 16000 -ac 1 '
        f'-b:a 64k "{out_path}" -loglevel quiet'
    )
    return ret == 0


def download_video_url(url: str, out_path: str):
    """ទាញ video ពេញ (video+audio) ពី YouTube/TikTok/..."""
    ydl_opts = {
        "format": "bestvideo[height<=720]+bestaudio/bestvideo+bestaudio/best",
        "outtmpl": out_path,
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info     = ydl.extract_info(url, download=True)
        title    = info.get("title", "Video")
        duration = info.get("duration", 0)
    return title, duration


# ══════════════════════════════════════════
# WHISPER — transcribe with timestamps
# ══════════════════════════════════════════

def transcribe_with_timestamps(audio_path: str):
    """ត្រឡប់ segments [{start, end, text}] ពី Groq Whisper"""
    with open(audio_path, "rb") as f:
        data = f.read()
    result = client.audio.transcriptions.create(
        file=(os.path.basename(audio_path), data),
        model="whisper-large-v3-turbo",
        response_format="verbose_json",
        language=None,
        timestamp_granularities=["segment"],
    )
    segments = []
    for seg in result.segments:
        # Groq returns dict or object depending on version
        if isinstance(seg, dict):
            start = seg.get("start", 0)
            end   = seg.get("end", 0)
            text  = seg.get("text", "").strip()
        else:
            start = seg.start
            end   = seg.end
            text  = seg.text.strip()
        segments.append({"start": start, "end": end, "text": text})
    full_text = result.text if isinstance(result, object) and hasattr(result, "text") else ""
    return segments, full_text.strip()


# ══════════════════════════════════════════
# TRANSLATE segments → ខ្មែរ (Groq LLM batch)
# ══════════════════════════════════════════

def translate_segments_to_khmer(segments: list) -> list:
    """បកប្រែ segments ទាំងអស់ជាភាសាខ្មែរ ក្នុងការហៅ API តែមួយ"""
    if not segments:
        return []

    # Build numbered list for batch translate
    lines = "\n".join(f"{i+1}. {s['text']}" for i, s in enumerate(segments))
    prompt = f"""បកប្រែប្រយោគខាងក្រោមទៅជាភាសាខ្មែរ។
ត្រូវ​តប​ជា​លេខ​ដូច​គ្នា​ទៅ​ — មួយ​បន្ទាត់​ក្នុង​មួយ​ប្រយោគ។
មិន​ត្រូវ​បន្ថែម​ពាក្យ​ណា​ក្រៅ​ពី​ការ​បកប្រែ​ឡើយ។

{lines}

ចម្លើយ (ខ្មែរ):"""

    resp = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=3000,
    )
    raw = resp.choices[0].message.content.strip()

    # Parse "1. xxx\n2. xxx\n..."
    translated = []
    for line in raw.split("\n"):
        line = line.strip()
        m = re.match(r"^\d+\.\s*(.*)", line)
        if m:
            translated.append(m.group(1).strip())

    # Fallback: ប្រសិនបើ parse ខ្លះ
    result = []
    for i, seg in enumerate(segments):
        km_text = translated[i] if i < len(translated) else seg["text"]
        result.append({**seg, "text_km": km_text})
    return result


# ══════════════════════════════════════════
# SUMMARIZE full transcript
# ══════════════════════════════════════════

def summarize_with_groq(transcript: str) -> str:
    prompt = f"""អ្នកជាជំនួយការវិភាគ video ជំនាញ។
សូម​សម្រាយ​មាតិកា​ខាង​ក្រោម​ជា​ភាសា​ខ្មែរ​ច្បាស់​លាស់:

📌 ចំណុចសំខាន់ (bullet points)
📝 សេចក្តីសង្ខេបខ្លី (២-៣ ប្រយោគ)
💡 គន្លឹះ ឬ ចំណេះដឹងសំខាន់

មាតិកា:
{transcript[:6000]}

ចម្លើយជាភាសាខ្មែរទាំងស្រុង:"""

    resp = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1500,
    )
    return resp.choices[0].message.content.strip()


# ══════════════════════════════════════════
# SRT / ASS SUBTITLE BUILDER
# ══════════════════════════════════════════

def seconds_to_srt_time(s: float) -> str:
    h  = int(s // 3600)
    m  = int((s % 3600) // 60)
    sc = int(s % 60)
    ms = int((s - int(s)) * 1000)
    return f"{h:02d}:{m:02d}:{sc:02d},{ms:03d}"

def build_srt(segments_km: list) -> str:
    lines = []
    for i, seg in enumerate(segments_km, 1):
        t_start = seconds_to_srt_time(seg["start"])
        t_end   = seconds_to_srt_time(seg["end"])
        text    = seg.get("text_km", seg["text"])
        lines.append(f"{i}\n{t_start} --> {t_end}\n{text}\n")
    return "\n".join(lines)


# ══════════════════════════════════════════
# BURN SUBTITLE ចូល VIDEO
# ══════════════════════════════════════════

def burn_subtitle(video_path: str, srt_path: str, out_path: str) -> bool:
    """burn subtitle ខ្មែរ — ពណ៌លឿង ផ្ទៃខ្មៅ ខាងក្រោម"""
    # escape path for ffmpeg filter
    srt_escaped = srt_path.replace("\\", "/").replace(":", "\\:")
    cmd = (
        f'ffmpeg -y -i "{video_path}" '
        f'-vf "subtitles=\'{srt_escaped}\':force_style=\'{SUBTITLE_STYLE}\'" '
        f'-c:v libx264 -crf 23 -preset fast '
        f'-c:a copy '
        f'"{out_path}" -loglevel error'
    )
    ret = os.system(cmd)
    return ret == 0


# ══════════════════════════════════════════
# EDGE TTS
# ══════════════════════════════════════════

async def _tts_async(text: str, voice: str, path: str):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(path)

def make_tts(text: str, voice_key: str) -> str:
    voice = VOICES.get(voice_key, VOICES["sreymom"])
    tmp   = tempfile.mktemp(suffix=".mp3")
    asyncio.run(_tts_async(text, voice, tmp))
    return tmp


# ══════════════════════════════════════════
# CORE PROCESSOR — VIDEO + SUBTITLE
# ══════════════════════════════════════════

def process_video_with_subtitle(chat_id, uid, video_path, title="Video"):
    """
    flow:
    1. extract audio
    2. Whisper → segments + timestamps
    3. translate segments → ខ្មែរ
    4. build .srt
    5. ffmpeg burn subtitle ចូល video
    6. send video + text summary + TTS
    """
    cfg       = get_cfg(uid)
    tmp_audio = tempfile.mktemp(suffix=".mp3")
    tmp_srt   = tempfile.mktemp(suffix=".srt")
    tmp_out   = tempfile.mktemp(suffix=".mp4")

    try:
        # ── Step 1: Extract audio ──
        status = bot.send_message(chat_id, "🎙️ *កំពុង​ដក​សំឡេង...*", parse_mode="Markdown")
        ok = extract_audio_from_video(video_path, tmp_audio)
        if not ok or not os.path.exists(tmp_audio):
            bot.edit_message_text("❌ មិន​អាច​ដក​សំឡេង​បាន។", chat_id, status.message_id)
            return

        # ── Step 2: Whisper transcribe ──
        bot.edit_message_text("🎙️ *Whisper កំពុង​ស្តាប់...*", chat_id, status.message_id,
                              parse_mode="Markdown")
        segments, full_text = transcribe_with_timestamps(tmp_audio)

        if not segments or len(full_text) < 10:
            bot.edit_message_text("❌ មិន​អាច​ស្គាល់​សំឡេង​បាន។", chat_id, status.message_id)
            return

        # ── Step 3: Translate → ខ្មែរ ──
        bot.edit_message_text("🌐 *AI កំពុង​បកប្រែ subtitle...*", chat_id, status.message_id,
                              parse_mode="Markdown")
        segments_km = translate_segments_to_khmer(segments)

        # ── Step 4: Build SRT ──
        srt_content = build_srt(segments_km)
        with open(tmp_srt, "w", encoding="utf-8") as f:
            f.write(srt_content)

        # ── Step 5: Burn subtitle ──
        bot.edit_message_text("🔥 *ffmpeg កំពុង burn subtitle...*", chat_id, status.message_id,
                              parse_mode="Markdown")
        ok = burn_subtitle(video_path, tmp_srt, tmp_out)

        if not ok or not os.path.exists(tmp_out):
            bot.edit_message_text("❌ burn subtitle បរាជ័យ។", chat_id, status.message_id)
            return

        bot.delete_message(chat_id, status.message_id)

        # ── Step 6: Send video ──
        out_size_mb = os.path.getsize(tmp_out) / 1024 / 1024
        if out_size_mb > 50:
            bot.send_message(chat_id,
                f"⚠️ Video ធំ​ពេក ({out_size_mb:.1f}MB > 50MB)។\n"
                "Telegram មិន​អាច​ send បាន។ សូម​ប្រើ video ខ្លីជាង​នេះ។")
        else:
            with open(tmp_out, "rb") as vf:
                bot.send_video(
                    chat_id, vf,
                    caption=f"🎬 *{title[:50]}*\n📝 Subtitle ខ្មែរ burn ហើយ ✅",
                    parse_mode="Markdown",
                    supports_streaming=True,
                )

        # ── Step 7: Send text summary ──
        bot.send_message(chat_id, "🤖 *AI កំពុង​សម្រាយ...*", parse_mode="Markdown")
        summary_km = summarize_with_groq(full_text)
        header     = f"🎬 *{title[:60]}*\n\n"
        full_msg   = header + summary_km

        if len(full_msg) > 4000:
            for part in textwrap.wrap(full_msg, 3800):
                bot.send_message(chat_id, part, parse_mode="Markdown")
        else:
            bot.send_message(chat_id, full_msg, parse_mode="Markdown")

        # ── Step 8: TTS ──
        voice_key  = cfg.get("voice", "sreymom")
        voice_name = "ស្រីមុំ 👩" if voice_key == "sreymom" else "ពិសិដ្ឋ 👨"
        tts_msg    = bot.send_message(chat_id, "🔊 *កំពុង​បង្កើត TTS...*", parse_mode="Markdown")
        tts_path   = make_tts(summary_km[:900], voice_key)
        bot.delete_message(chat_id, tts_msg.message_id)

        with open(tts_path, "rb") as af:
            bot.send_voice(chat_id, af,
                           caption=f"🎤 {voice_name} — *{VOICES[voice_key]}*",
                           parse_mode="Markdown")
        os.remove(tts_path)
        log.info(f"[✅] Done: {title} uid={uid}")

    except Exception as e:
        log.error(f"[❌] Error: {e}")
        bot.send_message(chat_id, f"⚠️ Error: `{str(e)[:300]}`", parse_mode="Markdown")
    finally:
        for p in [tmp_audio, tmp_srt, tmp_out, video_path]:
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


# ══════════════════════════════════════════
# AUDIO-ONLY PROCESSOR (ស្តាប់ + សម្រាយ)
# ══════════════════════════════════════════

def process_audio_only(chat_id, uid, audio_path, title="Audio"):
    """សម្រាប់ audio file — text + TTS គ្មាន video"""
    cfg = get_cfg(uid)
    try:
        status = bot.send_message(chat_id, "🎙️ *Whisper កំពុង​ស្តាប់...*", parse_mode="Markdown")
        segments, full_text = transcribe_with_timestamps(audio_path)

        if not full_text or len(full_text) < 10:
            bot.edit_message_text("❌ មិន​អាច​ស្គាល់​សំឡេង​បាន។", chat_id, status.message_id)
            return

        bot.edit_message_text("🤖 *AI កំពុង​វិភាគ...*", chat_id, status.message_id,
                              parse_mode="Markdown")
        summary_km = summarize_with_groq(full_text)
        header     = f"🎵 *{title[:60]}*\n\n"
        full_msg   = header + summary_km

        bot.delete_message(chat_id, status.message_id)

        if len(full_msg) > 4000:
            for part in textwrap.wrap(full_msg, 3800):
                bot.send_message(chat_id, part, parse_mode="Markdown")
        else:
            bot.send_message(chat_id, full_msg, parse_mode="Markdown")

        voice_key  = cfg.get("voice", "sreymom")
        voice_name = "ស្រីមុំ 👩" if voice_key == "sreymom" else "ពិសិដ្ឋ 👨"
        tts_msg    = bot.send_message(chat_id, "🔊 *កំពុង​បង្កើត TTS...*", parse_mode="Markdown")
        tts_path   = make_tts(summary_km[:900], voice_key)
        bot.delete_message(chat_id, tts_msg.message_id)

        with open(tts_path, "rb") as af:
            bot.send_voice(chat_id, af,
                           caption=f"🎤 {voice_name} — *{VOICES[voice_key]}*",
                           parse_mode="Markdown")
        os.remove(tts_path)

    except Exception as e:
        log.error(f"[❌] audio_only error: {e}")
        bot.send_message(chat_id, f"⚠️ Error: `{str(e)[:300]}`", parse_mode="Markdown")
    finally:
        try:
            if os.path.exists(audio_path):
                os.remove(audio_path)
        except Exception:
            pass


# ══════════════════════════════════════════
# HANDLERS
# ══════════════════════════════════════════

@bot.message_handler(commands=["start"])
def cmd_start(msg):
    uid  = msg.from_user.id
    name = msg.from_user.first_name or "អ្នកប្រើ"
    get_cfg(uid)
    bot.send_message(
        msg.chat.id,
        f"🎬 *សួស្តី {name}!*\n\n"
        f"🤖 *Kairozen Video Translator*\n\n"
        f"✅ ផ្ញើ *video* → AI បកប្រែ + *burn subtitle ខ្មែរ* ចូល video\n"
        f"✅ ផ្ញើ *link* YouTube/TikTok → ទាញ + subtitle\n"
        f"✅ ផ្ញើ *audio* → សម្រាយ + TTS\n\n"
        f"🎤 Voices: `SreymomNeural` | `PisethNeural`\n\n"
        f"📩 ចាប់ផ្តើម​ដោយ​ផ្ញើ video ឬ link!",
        parse_mode="Markdown",
        reply_markup=main_kb()
    )


@bot.message_handler(func=lambda m: m.text == "ℹ️ របៀបប្រើ")
def cmd_help(msg):
    cfg = get_cfg(msg.from_user.id)
    vn  = "ស្រីមុំ 👩" if cfg["voice"] == "sreymom" else "ពិសិដ្ឋ 👨"
    bot.send_message(
        msg.chat.id,
        "📖 *របៀបប្រើ Kairozen Video Translator*\n\n"
        "1️⃣ ផ្ញើ *video* → ទទួល video + subtitle ខ្មែរ burn + សម្រាយ\n"
        "2️⃣ ផ្ញើ *link* YouTube/TikTok → ទទួលដូចគ្នា\n"
        "3️⃣ ផ្ញើ *audio* → ទទួលអត្ថបទ + TTS\n"
        "4️⃣ ជ្រើសសំឡេង TTS ក្រោម ⚙️\n\n"
        "*ទ្រង់ទ្រាយ​គាំទ្រ:*\n"
        "🎥 mp4, mov, avi, mkv, webm (max 50MB)\n"
        "🎵 mp3, m4a, ogg, wav, flac\n\n"
        f"⚙️ *ការ​កំណត់:*\n"
        f"🎤 {vn} | 🧠 Whisper-v3-turbo + Llama-3.3-70b",
        parse_mode="Markdown"
    )


@bot.message_handler(func=lambda m: m.text == "⚙️ ជ្រើសសំឡេង")
def cmd_voice(msg):
    bot.send_message(msg.chat.id, "🎤 *ជ្រើសសំឡេង TTS ខ្មែរ:*",
                     parse_mode="Markdown", reply_markup=voice_kb())


@bot.callback_query_handler(func=lambda c: c.data.startswith("v_"))
def cb_voice(call):
    uid = call.from_user.id
    key = call.data.replace("v_", "")
    get_cfg(uid)["voice"] = key
    label = "ស្រីមុំ 👩 — `SreymomNeural`" if key == "sreymom" \
            else "ពិសិដ្ឋ 👨 — `PisethNeural`"
    bot.answer_callback_query(call.id, "✅ បាន​ជ្រើស!")
    bot.edit_message_text(f"✅ *សំឡេង: {label}*",
                          call.message.chat.id, call.message.message_id,
                          parse_mode="Markdown")


@bot.message_handler(func=lambda m: m.text == "🔗 Link YouTube/TikTok")
def cmd_link_prompt(msg):
    get_cfg(msg.from_user.id)["waiting_link"] = True
    bot.send_message(msg.chat.id,
                     "🔗 *សូម​ផ្ញើ Link:*\n\nគាំទ្រ: YouTube, TikTok, Facebook, Instagram...",
                     parse_mode="Markdown")


@bot.message_handler(func=lambda m: m.text and m.text.startswith("http"))
def handle_link(msg):
    uid  = msg.from_user.id
    chat = msg.chat.id
    url  = msg.text.strip()
    get_cfg(uid)["waiting_link"] = False
    bot.send_message(chat, "⏳ *កំពុង​ទាញ video...*", parse_mode="Markdown")

    def run():
        tmp_video = tempfile.mktemp(suffix=".mp4")
        try:
            title, duration = download_video_url(url, tmp_video)
            # yt-dlp អាច rename file
            actual = tmp_video if os.path.exists(tmp_video) else tmp_video.replace(".mp4", "") + ".mp4"
            if not os.path.exists(actual):
                # fallback search
                base = tmp_video.replace(".mp4", "")
                for ext2 in [".mp4", ".mkv", ".webm"]:
                    if os.path.exists(base + ext2):
                        actual = base + ext2
                        break

            if not os.path.exists(actual):
                bot.send_message(chat, "❌ មិន​អាច​ទាញ video បាន។")
                return

            mins = f"{int(duration)//60}:{int(duration)%60:02d}" if duration else "?"
            bot.send_message(chat, f"✅ *{title[:50]}*\n⏱ `{mins}`", parse_mode="Markdown")
            process_video_with_subtitle(chat, uid, actual, title)
        except Exception as e:
            bot.send_message(chat, f"⚠️ Error: `{str(e)[:200]}`", parse_mode="Markdown")
            try:
                if os.path.exists(tmp_video): os.remove(tmp_video)
            except Exception: pass

    threading.Thread(target=run, daemon=True).start()


@bot.message_handler(content_types=["video", "document"])
def handle_video(msg):
    uid  = msg.from_user.id
    chat = msg.chat.id

    VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
    AUDIO_EXTS = {".mp3", ".m4a", ".ogg", ".wav", ".flac"}

    if msg.video:
        file_info = bot.get_file(msg.video.file_id)
        ext       = ".mp4"
        is_video  = True
    elif msg.document:
        fname    = msg.document.file_name or ""
        ext      = os.path.splitext(fname)[1].lower() or ".mp4"
        if ext not in VIDEO_EXTS | AUDIO_EXTS:
            bot.reply_to(msg, "❌ ទ្រង់ទ្រាយ​មិន​គាំទ្រ។")
            return
        file_info = bot.get_file(msg.document.file_id)
        is_video  = ext in VIDEO_EXTS
    else:
        return

    size_mb = getattr(file_info, "file_size", 0) / 1024 / 1024
    if size_mb > 50:
        bot.reply_to(msg, "⚠️ File ធំ​ពេក (>50MB)។ សូម​ប្រើ link ជំនួស​វិញ។")
        return

    bot.send_message(chat, "⬇️ *កំពុង​ទាញ file...*", parse_mode="Markdown")

    def run():
        tmp_file = tempfile.mktemp(suffix=ext)
        try:
            with open(tmp_file, "wb") as f:
                f.write(bot.download_file(file_info.file_path))

            title = (msg.document.file_name if msg.document else "Video") or "Video"

            if is_video:
                process_video_with_subtitle(chat, uid, tmp_file, title)
            else:
                process_audio_only(chat, uid, tmp_file, title)
        except Exception as e:
            bot.send_message(chat, f"⚠️ Error: `{str(e)[:200]}`", parse_mode="Markdown")
            try:
                if os.path.exists(tmp_file): os.remove(tmp_file)
            except Exception: pass

    threading.Thread(target=run, daemon=True).start()


@bot.message_handler(content_types=["audio", "voice"])
def handle_audio(msg):
    uid  = msg.from_user.id
    chat = msg.chat.id

    if msg.voice:
        file_info  = bot.get_file(msg.voice.file_id)
        ext, title = ".ogg", "Voice Message"
    else:
        file_info = bot.get_file(msg.audio.file_id)
        ext   = os.path.splitext(msg.audio.file_name or "")[1] or ".mp3"
        title = msg.audio.title or msg.audio.file_name or "Audio"

    bot.send_message(chat, "⬇️ *កំពុង​ទាញ​សំឡេង...*", parse_mode="Markdown")

    def run():
        tmp = tempfile.mktemp(suffix=ext)
        try:
            with open(tmp, "wb") as f:
                f.write(bot.download_file(file_info.file_path))
            process_audio_only(chat, uid, tmp, title)
        except Exception as e:
            bot.send_message(chat, f"⚠️ Error: `{str(e)[:200]}`", parse_mode="Markdown")

    threading.Thread(target=run, daemon=True).start()


@bot.message_handler(func=lambda m: m.text and not m.text.startswith("http")
                     and m.text not in ["🎬 ផ្ញើ Video","🔗 Link YouTube/TikTok",
                                        "⚙️ ជ្រើសសំឡេង","ℹ់ របៀបប្រើ","ℹ️ របៀបប្រើ"])
def handle_text(msg):
    if get_cfg(msg.from_user.id).get("waiting_link"):
        bot.reply_to(msg, "⚠️ Link ត្រូវ​ចាប់ផ្ដើម​ដោយ `https://`", parse_mode="Markdown")
    else:
        bot.reply_to(msg, "📩 សូម​ផ្ញើ *video*, *audio*, ឬ *link* មក!", parse_mode="Markdown")


# ══════════════════════════════════════════
# RUN
# ══════════════════════════════════════════

if __name__ == "__main__":
    log.info("🎬 kz-vidbot v4.0 started...")
    while True:
        try:
            log.info("🔄 Polling...")
            bot.infinity_polling(timeout=60, long_polling_timeout=30, allowed_updates=None)
        except Exception as e:
            log.error(f"[💥] Crash: {e}")
            log.info("⏳ Restart in 5s...")
            time.sleep(5)
