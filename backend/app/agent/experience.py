from app.database import experience_db

def history():
    return experience_db.get_all_experiences()
