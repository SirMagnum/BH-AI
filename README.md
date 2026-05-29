# Privacy Assistant - BH-AI

A local, privacy-focused desktop assistant that captures a user-selected screen region, runs OCR, understands context, and draws a click-through overlay — all without sending data off-device.

---

## Features

| Feature | Details |
|---|---|
| 🖥️ Screen region capture | Drag-to-select any area; `mss` grabs frames at 0.2–3 FPS |
| 🔍 OCR | `pytesseract` extracts text from each frame |
| 🧠 Context analysis | Keyword rules detect login pages, search UIs, forms, checkout, errors, etc. |
| 🎙️ Voice feedback | `pyttsx3` speaks the top insight (toggle on/off) |
| 🪟 Overlay | Transparent, always-on-top, click-through window highlights the monitored region |
| ⏯️ Session control | Start / Pause (halts capture) / Stop |
| 📋 Live OCR log | Timestamped text output with scroll view |

---

## Setup

### 1. Install Tesseract OCR (required for OCR)

Download the Windows installer from:
https://github.com/UB-Mannheim/tesseract/wiki

> Default install path: `C:\Program Files\Tesseract-OCR\tesseract.exe`
> Add it to your **System PATH**.

### 2. Install Python dependencies

```powershell
cd C:\Users\sir_m\Projects\BH-AI
pip install -r requirements.txt
```

### 3. Run the application

```powershell
python main.py
```

---

## Usage

1. Click **⊡ Select Region** — drag on the screen to pick the area to monitor
2. Click **▶ Start Session** — capture begins, OCR runs, overlay appears
3. Watch the **Context Insights** panel update in real time
4. Click **⏸ Pause** — capture stops immediately, session state preserved
5. Click **▶ Resume** to continue, or **⏹ Stop** to end

### Overlay

The dashed coloured border appears around your monitored region:
- 🟦 Cyan = search interface
- 🟨 Amber = form
- 🔴 Red/Pink = login / password
- 🟥 Red = error page
- 🟩 Green = generic

The overlay is **click-through** — normal mouse interaction works underneath.

---

## Architecture

```
main.py                  Entry point
src/
  capture.py             mss-based screen capture (threaded)
  ocr.py                 pytesseract OCR wrapper
  analyzer.py            Keyword-based context rules → Insight objects
  voice.py               pyttsx3 TTS (non-blocking queue)
  overlay.py             Transparent tkinter overlay window
  region_selector.py     Full-screen drag-to-select UI
  ui.py                  Main control panel (tkinter)
```

---

## Privacy Notes

- **No network calls.** All processing is local.
- Screen frames are held only in RAM; never written to disk.
- OCR text is displayed in-app only; not logged to any file.
- Closing the window immediately stops all capture.
