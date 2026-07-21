from app.ui.ui_clicker import click_ui

if click_ui("chrome_addressbar"):
    print("Clicked!")
else:
    print("Not Found")