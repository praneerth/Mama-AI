from app.database.database import Base, engine
from app.database.models import *

Base.metadata.create_all(bind=engine)

print("Database created successfully.")