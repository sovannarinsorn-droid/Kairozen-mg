# 🎬 kz-vidbot — Kairozen Video Translator

Bot Telegram បកប្រែ video → **subtitle ខ្មែរ burn ចូល video** + TTS

| Stack | Tool |
|-------|------|
| Telegram | pyTelegramBotAPI |
| Speech-to-Text | Groq Whisper-large-v3-turbo |
| Translate + AI | Groq Llama-3.3-70b |
| Subtitle Burn | ffmpeg |
| TTS | edge-tts (SreymomNeural / PisethNeural) |
| Download | yt-dlp |

---

## ⚙️ Setup (VPS / Server)

```bash
git clone https://github.com/YOUR_USERNAME/kz-vidbot.git
cd kz-vidbot

# ដំឡើង ffmpeg + Khmer font
sudo apt update && sudo apt install -y ffmpeg fonts-khmeros

# Python venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Config
cp .env.example .env
nano .env
```

**.env:**
```
BOT_TOKEN=xxx
GROQ_API_KEY=xxx
ADMIN_ID=xxx
```

```bash
python bot.py
```

---

## 🐳 Docker

```bash
docker build -t kz-vidbot .
docker run -d --name kz-vidbot --restart unless-stopped \
  -e BOT_TOKEN=xxx \
  -e GROQ_API_KEY=xxx \
  -e ADMIN_ID=xxx \
  kz-vidbot
```

---

## 🚀 Render (Background Worker)

1. Push repo ទៅ GitHub
2. Render → **New Background Worker**
3. Connect repo → Language: **Docker**
4. Environment Variables → បន្ថែម `BOT_TOKEN`, `GROQ_API_KEY`, `ADMIN_ID`
5. Deploy!

---

## 🔄 systemd (auto-start)

```bash
sudo nano /etc/systemd/system/kz-vidbot.service
```

```ini
[Unit]
Description=kz-vidbot Kairozen Video Translator
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/kz-vidbot
EnvironmentFile=/home/ubuntu/kz-vidbot/.env
ExecStart=/home/ubuntu/kz-vidbot/venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable kz-vidbot
sudo systemctl start kz-vidbot
sudo systemctl status kz-vidbot
```

---

## 📁 Structure

```
kz-vidbot/
├── bot.py            # Main bot
├── config.py         # Load .env
├── requirements.txt
├── Dockerfile        # Docker + ffmpeg + fonts-khmeros
├── .env.example      # Template
├── .gitignore
└── README.md
```

---

> 💬 Support: [@smos_sne1](https://t.me/smos_sne1)
