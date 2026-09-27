# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**local-voice-coach** is a Python CLI application that provides an interactive English conversation practice partner. It combines local speech recognition (Whisper), local text-to-speech (Kokoro), and a local LLM (Qwen via LM Studio) for a fully offline English practice experience.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    main.py (Entry Point)                        │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌─────────────┐       ┌─────────────┐       ┌──────────────┐
│  Whisper    │       │  Kokoro TTS │       │   LM Studio  │
│  (STT)      │       │  (TTS)      │       │   (LLM)      │
│  small.en   │       │  kokoro-v1.0│       │   qwen3-4b   │
└─────────────┘       │  voices-v1.0│       │localhost:1234│
                      └─────────────┘       └──────────────┘
                              │
        └─────────────────────┼─────────────────────┘
                              │
                              ▼
                    ┌───────────────────────────┐
                    │  english_practice_log.md  │
                    │  (Recording user sessions)│
                    └───────────────────────────┘
```

## Development Commands

### Installation & Setup
```bash
# Install dependencies
uv pip install -e .

# Verify installation
python main.py
```

### Run the Application
```bash
# Run the main application
python main.py

# Run with debug mode (if configured)
uv run python main.py
```

### Development Workflow
1. **Start the LM Studio server** (if not already running):
   - LM Studio should be running on `localhost:1234`
   - The model used is `qwen3-4b-2507`

2. **Run the application**:
   ```bash
   python main.py
   ```

3. **Use the application**:
   - Press SPACEBAR to start speaking
   - Press ANY KEY to stop recording
   - The app will transcribe, send to LLM, and play back the response

## Key Components

### Speech Recognition (Whisper)
- Model: `small.en` (CPU, int8 quantization)
- Sample rate: 16kHz
- Uses `faster-whisper` for optimized inference

### Text-to-Speech (Kokoro)
- Model: `kokoro-v1.0.onnx`
- Voice files: `voices-v1.0.bin`
- Voices: `am_puck` (American male)
- Uses `kokoro-onnx` for ONNX runtime

### LLM (Qwen via LM Studio)
- Model: `qwen3-4b-2507`
- Server: `http://localhost:1234/v1`
- Uses `openai` client compatibility layer

### Audio Recording
- Uses `sounddevice` for microphone input
- Callback-based recording with asyncio
- Raw terminal key handling for start/stop control

## File Structure

```
local-voice-coach/
├── main.py              # Main application entry point
├── pyproject.toml       # Project configuration
├── uv.lock              # Dependency lock file
├── kokoro-v1.0.onnx     # TTS model (310MB)
├── voices-v1.0.bin      # TTS voice files (26.9MB)
└── english_practice_log.md  # User session log
```

## Configuration

### LM Studio Server
- URL: `http://localhost:1234/v1`
- API Key: `lm-studio`
- Model: `qwen3-4b-2507`

### Audio Settings
- Sample rate: 16000 Hz
- Channels: 1 (mono)
- Data type: float32

## Dependencies

- `faster-whisper>=1.2.1` - Speech recognition
- `kokoro-onnx>=0.5.0` - Text-to-speech
- `numpy>=2.4.6` - Numerical computing
- `onnxruntime>=1.26.0` - ONNX runtime
- `openai>=2.41.0` - LLM client
- `sounddevice>=0.5.5` - Audio I/O
- `uv` - Python package manager

## Notes

- The application is designed for **fully offline** operation
- All models are loaded into local memory at startup
- Audio recording uses non-blocking I/O with asyncio
- Responses are streamed token-by-token and played back immediately to minimize perceived latency