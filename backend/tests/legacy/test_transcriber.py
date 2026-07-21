from app.voice.transcriber import transcribe

text = transcribe("voice.wav")

print()
print("Recognized:")
print(text)