Below is a detailed, step-by-step blueprint for implementing the Telegram speech-to-text bot project. Each section is broken down into small, iterative prompts. You can use these prompts with a code-generation LLM to generate code in a test-driven, incremental fashion.

---

### Overall Blueprint

1. **Project Setup & Environment**  
   - Create the project structure with a main script, configuration files, requirements.txt, and a Dockerfile.  
   - Create a simple “Hello, World” Telegram bot skeleton that connects to Telegram and responds (for testing basic integration).

2. **Telegram Voice Message Handling**  
   - Add a Telegram handler to receive voice messages.  
   - Validate that the bot correctly identifies the voice message update and logs or replies with a placeholder.

3. **Audio Conversion & Whisper Integration**  
   - Integrate audio conversion (if needed) using either ffmpeg or pydub.  
   - Wire in the Whisper small model for transcription and return the transcribed text.  
   - Write unit tests to simulate various audio inputs.

4. **Logging & Error Handling**  
   - Integrate Python’s `logging` library.  
   - Write tests and code to handle errors such as transcription failures.  
   - Ensure the bot replies with a generic error message on failure.

5. **Admin Notifications for Critical Errors**  
   - Implement logic to send a Telegram message to the admin if a critical error or crash occurs.  
   - Write integration tests for this flow.

6. **Wiring & Integration Testing**  
   - Combine all pieces together (Telegram reception, transcription, logging, error handling).  
   - Write end-to-end tests simulating real Telegram updates.

Below, each phase is broken into incremental prompts.

---

````text
Prompt 1: SETUP PROJECT STRUCTURE & ENVIRONMENT

Overview:
- Initialize a new Python project for the Telegram bot.
- Create a basic repository structure including a main script, requirements.txt, a configuration file, and a Dockerfile.
- Build a minimal "Hello, World" Telegram bot using the python-telegram-bot library. This bot should connect to Telegram and reply to any message with a test confirmation.
- Write initial unit tests to ensure that the bot starts without errors.

Expected Actions:
1. Create a file structure and initialize a git repository.
2. Create main.py with a basic Telegram bot skeleton.
3. Write requirements.txt listing dependencies (e.g., python-telegram-bot).
4. Create a Dockerfile for containerizing the application.
5. Create a basic configuration file for environment variables (e.g., bot token).
6. Write a simple test (unit or integration) to verify that the bot starts and can respond to a test message.
````

---

````text
Prompt 2: ADD TELEGRAM VOICE MESSAGE HANDLING

Overview:
- Extend the bot to handle voice messages.
- Wire up a Telegram handler that detects voice message updates.
- For now, whenever a voice message is received, log the event and send a placeholder response (e.g., "Voice received!").
- Create a corresponding unit/integration test to simulate a voice message update and assert that the correct handler is called.

Expected Actions:
1. Add a new function in main.py to process voice messages.
2. Update the bot's dispatcher to register a voice handler.
3. Insert logging to record each received voice update.
4. Write tests that simulate a voice message update and check that the bot replies with the expected placeholder.
````

---

````text
Prompt 3: INTEGRATE AUDIO CONVERSION & WHISPER TRANSCRIPTION

Overview:
- Implement integration with Whisper for transcription.
- If needed, add audio processing (via ffmpeg or pydub) to ensure the input audio is in the correct format.
- Replace the placeholder response with a call to the transcription function that uses the Whisper small model.
- Write tests that simulate valid and invalid audio inputs and assert that transcription is correctly performed or gracefully fails.

Expected Actions:
1. Create a transcription function that:
   - Accepts an audio file path (or audio stream).
   - Performs any necessary conversion.
   - Calls the Whisper small model and returns transcribed text.
2. Update the voice message handler to call this transcription function.
3. Add unit tests verifying the transcription function with:
   - A sample valid audio.
   - An invalid or low-quality audio file.
````

---

````text
Prompt 4: IMPLEMENT LOGGING & ERROR HANDLING

Overview:
- Integrate Python’s built-in logging for structured logging to stdout and temporary log files.
- Ensure that errors during transcription or audio processing are caught.
- When an error occurs (e.g., transcription failure), the bot should reply with: "Извините, не удалось распознать речь."
- Write unit tests to simulate errors (e.g., injection of corrupted audio) and check that the error message is sent.

Expected Actions:
1. Configure logging in main.py (or a separate logging module), ensuring logs are output to stdout.
2. In the transcription flow, catch exceptions and log errors.
3. Modify the voice message handler to send the default error message on failure.
4. Write tests to simulate an error during audio processing and validate both logging output and the error reply.
````

---

````text
Prompt 5: ADD ADMIN NOTIFICATIONS FOR CRITICAL ERRORS

Overview:
- Implement a mechanism to detect critical failures (e.g., bot crashes).
- When a critical error is detected, send a Telegram message to the admin’s chat ID.
- Ensure that this functionality is wired into the error handling process.
- Write integration tests simulating a critical error and asserting that a notification is sent to the admin.

Expected Actions:
1. Update the error handling logic to differentiate between minor and critical errors.
2. Create a function to send a notification message to a pre-configured admin chat ID.
3. Trigger this function within critical error catch blocks.
4. Write an integration test that simulates a crash or critical error and asserts that the admin receives the notification.
````

---

````text
Prompt 6: WIRING & END-TO-END INTEGRATION TESTS

Overview:
- Wire all previously developed components together (project setup, Telegram voice handling, transcription, logging, admin notifications).
- Ensure no orphan code remains by integrating each component.
- Write comprehensive end-to-end tests that simulate real Telegram updates, covering success, transcription failure, and critical error notifications.
- Validate the overall behavior of the bot in a containerized environment using Docker.

Expected Actions:
1. Combine all functions (Telegram bot initialization, voice handling, transcription, error reporting) in main.py.
2. Review the integration points and remove any unused code.
3. Write end-to-end tests (or integration tests) that:
   - Simulate a successful voice message processing flow.
   - Simulate an error during audio transcription.
   - Simulate a critical error triggering admin notifications.
4. Update the Dockerfile if necessary to reflect any project changes and test by building and running the container.
````

---

This series of prompts guides you through building the bot incrementally and test-driven, ensuring each step is tested and integrated before moving on. Use these prompts one after the other with your code-generation LLM to implement the complete project in manageable steps.