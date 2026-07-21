from faster_whisper import WhisperModel

# Load the Whisper model only once
model = WhisperModel(
    "base",
    device="cpu",
    compute_type="int8",
)


def transcribe(audio_file: str):
    segments, info = model.transcribe(
        audio_file,
        language="en",      # Force English recognition
        beam_size=5,        # Improves accuracy
        vad_filter=True,    # Ignore silence
    )

    text = ""

    for segment in segments:
        text += segment.text + " "

    return text.strip()