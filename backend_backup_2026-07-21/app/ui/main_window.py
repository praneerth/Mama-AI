import threading
import customtkinter as ctk

from app.commands.router import process_command
from app.voice.speech_to_text import listen
from app.voice.tts import speak


ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class MamaAI(ctk.CTk):

    def __init__(self):
        super().__init__()

        self.title("🤖 Mama AI")
        self.geometry("1000x700")
        self.minsize(900, 600)

        # Header
        self.header = ctk.CTkLabel(
            self,
            text="🤖 Mama AI    🟢 Online",
            font=("Segoe UI", 24, "bold")
        )
        self.header.pack(pady=20)

        # Chat Area
        self.chat = ctk.CTkTextbox(
            self,
            width=900,
            height=500,
            font=("Segoe UI", 15)
        )
        self.chat.pack(fill="both", expand=True, padx=20)

        self.chat.insert("end", "🤖 Mama AI is ready!\n\n")

        # Bottom Frame
        bottom = ctk.CTkFrame(self)
        bottom.pack(fill="x", padx=20, pady=15)

        self.entry = ctk.CTkEntry(
            bottom,
            placeholder_text="Type your message..."
        )
        self.entry.pack(
            side="left",
            fill="x",
            expand=True,
            padx=(10, 5),
            pady=10
        )

        self.entry.bind("<Return>", self.send_message)

    def send_message(self, event=None):
        text = self.entry.get().strip()
        if text:
            self.chat.insert("end", f"You: {text}\n")
            self.entry.delete(0, "end")
            def run():
                try:
                    reply = process_command(text)
                except Exception as e:
                    reply = f"Error: {e}"
                self.chat.insert("end", f"Mama AI: {reply}\n\n")
            threading.Thread(target=run, daemon=True).start()