from app.cognitive.observe import observe
from app.cognitive.think import think

state = observe()

action = think(
    "Open Chrome and search ChatGPT",
    state,
)

print("\nNext Action:")
print(action)