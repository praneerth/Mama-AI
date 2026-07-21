from app.voice.wake_word import listen_for_wake_word
from app.voice.recorder import record_audio
from app.voice.transcriber import transcribe
from app.voice.speaker import speak

from app.services.ai_service import ask_ai


def start_voice_assistant():

    while True:

        # Wait until user says "Hey Mama"
        listen_for_wake_word()

        speak("Yes?")

        print("🎤 Listening for command...")

        audio = record_audio(duration=5)

        text = transcribe(audio)

        print("You:", text)

        if not text.strip():
            speak("I didn't hear anything.")
            continue

        answer = ask_ai(text)

        print("Mama:", answer)

        speak(answer)