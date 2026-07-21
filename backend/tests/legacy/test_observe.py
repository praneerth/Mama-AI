from app.cognitive.observe import observe

state = observe()

print("\nObservation Complete")

print("\nKeys:")

for k in state:
    print("-", k)