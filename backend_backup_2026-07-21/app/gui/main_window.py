import customtkinter as ctk
from app.ui.main_window import MamaAI

def start_gui():
    """
    Launch the native CustomTkinter desktop interface for Mama AI.
    """
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")
    app = MamaAI()
    app.mainloop()