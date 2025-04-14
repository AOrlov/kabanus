# Telegram Speech-to-Text Bot Todo Checklist

## 1. Project Setup & Environment
- [x] **Initialize Repository**
  - [x] Create a new git repository.
  - [x] Set up the basic folder structure.
- [x] **Main Script & Configuration**
  - [x] Create `main.py` with a minimal "Hello, World" Telegram bot skeleton.
  - [x] Create a configuration file (e.g., `.env` or `config.py`) to store environment variables (e.g., bot token, admin chat ID).
- [x] **Dependencies & Docker Setup**
  - [x] Create `requirements.txt` listing all dependencies (e.g., `python-telegram-bot`).
  - [x] Create a `Dockerfile` for containerizing the application.
- [x] **Initial Testing**
  - [x] Write a simple unit/integration test to verify that the bot starts and responds to a test message.

## 2. Telegram Voice Message Handling
- [x] **Voice Handler Implementation**
  - [x] Add a function in `main.py` to process voice messages.
  - [x] Register a voice message handler in the Telegram dispatcher.
  - [x] Log each received voice message.
- [x] **Placeholder Response**
  - [x] Send a placeholder response (e.g., "Voice received!") when a voice message is detected.
- [x] **Testing Voice Handler**
  - [x] Write tests to simulate a voice message update.
  - [x] Assert that the correct handler is called and responds with the placeholder message.

## 3. Audio Conversion & Whisper Transcription Integration
- [x] **Transcription Function**
  - [x] Create a function that accepts an audio file (or stream).
  - [x] Implement audio conversion using `ffmpeg` or `pydub` (if required for format compatibility).
  - [x] Integrate Whisper (small model) to transcribe the audio.
  - [x] Return the transcribed text.
- [x] **Replace Placeholder Response**
  - [x] Update the voice message handler to call the transcription function instead of the placeholder response.
- [x] **Transcription Testing**
  - [x] Write unit tests for the transcription function using a sample valid audio file.
  - [x] Write tests for handling invalid or low-quality audio inputs.

## 4. Logging & Error Handling
- [x] **Logging Setup**
  - [x] Configure Python’s logging module in `main.py` (or a dedicated logging module).
  - [x] Ensure logs are output to stdout and (optionally) stored in temporary log files.
- [x] **Error Handling in Transcription**
  - [x] Implement try/catch blocks in the transcription flow to catch exceptions.
  - [x] Log errors, and if transcription fails, ensure the bot replies with: "Извините, не удалось распознать речь."
- [x] **Error Handling Testing**
  - [x] Write tests to simulate errors (e.g., corrupted audio) and verify that the error message is sent.
  - [x] Verify logging output for error scenarios.

## 5. Admin Notifications for Critical Errors
- [x] **Notification Functionality**
  - [x] Update error handling logic to differentiate between minor and critical errors.
  - [x] Create a function to send a Telegram message to the admin’s chat ID.
  - [x] Integrate this function into critical error catch blocks.
- [x] **Admin Notifications Testing**
  - [x] Write integration tests to simulate a critical error.
  - [x] Assert that a notification message is sent to the admin.

## 6. Wiring & End-to-End Integration Testing
- [x] **Integrate All Components**
  - [x] Combine Telegram initialization, voice handling, transcription, logging, and error reporting in `main.py`.
  - [x] Remove any unused or orphaned code.
- [x] **End-to-End Testing**
  - [x] Write comprehensive tests to simulate:
    - A successful voice message processing flow.
    - An error during audio transcription.
    - A critical error triggering admin notifications.
- [x] **Containerized Environment**
  - [x] Update the Dockerfile if necessary.
  - [x] Build and run the container, and test overall behavior in the containerized environment.

## Final Steps
- [x] **Review & Refactor**
  - [x] Perform a code review to ensure all integration points work correctly.
  - [x] Refactor any parts of the code that can be simplified or improved.
- [x] **Documentation**
  - [x] Update documentation and in-code comments.
  - [x] Document the project setup, usage instructions, and testing procedures.
