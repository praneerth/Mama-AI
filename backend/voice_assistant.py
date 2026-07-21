from app.voice.speech_to_text import listen
from app.voice.tts import speak
from app.commands.router import process_command

print("🎙️ Mama AI is ready!")

while True:
    user = listen()

    if not user:
        continue

    if user.lower() in ["exit", "quit", "stop"]:
        speak("Goodbye!")
        break

    answer = process_command(user)

    print("Mama:", answer)

    speak(answer)