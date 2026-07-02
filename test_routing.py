import json
import os
import sys

from google.genai import types

# Add paths
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(current_dir, "app"))
sys.path.append(os.path.join(current_dir, "..", "shared"))

from google.adk.runners import InMemoryRunner  # noqa: E402

from app.agent import app  # noqa: E402

# Create runner
runner = InMemoryRunner(app=app)

# Create session first
session = runner.session_service.create_session_sync(
    app_name=app.name, user_id="test_user"
)
session_id = session.id
print(f"Created session: {session_id}")

payload = {
    "issue_id": "HH-TN-CHN-170-2026-10001",
    "title": "Sewage overflow near Adyar park",
    "category": "Sewage",
    "severity": "High",
    "ward_id": "TN-CHN-100",
    "ward_name": "Adyar",
    "description": "Drain overflowing near the main entrance",
}

# Construct new message
new_message = types.Content(
    role="user", parts=[types.Part.from_text(text=json.dumps(payload))]
)

print("Starting runner...")
try:
    events = list(
        runner.run(user_id="test_user", session_id=session_id, new_message=new_message)
    )
    print(f"Number of events: {len(events)}")
    for ev in events:
        print(f"Event: {ev.model_dump_json(indent=2)}")
except Exception:
    import traceback

    traceback.print_exc()
