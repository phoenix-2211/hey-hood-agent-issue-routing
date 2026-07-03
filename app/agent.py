from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from typing import Any

from google.adk.agents.context import Context
from google.adk.apps.app import App
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.workflow import Workflow, node

current_dir = os.path.dirname(os.path.abspath(__file__))
shared_dir = os.path.abspath(os.path.join(current_dir, "..", "shared"))
if not os.path.exists(os.path.join(shared_dir, "firestore_client.py")):
    shared_dir = os.path.abspath(os.path.join(current_dir, "..", "..", "shared"))
sys.path.append(shared_dir)
import firestore_client  # noqa: E402
from firebase_admin import firestore  # noqa: E402

SEVERITY_DEADLINES = {
    "Emergency": 24,  # hours
    "High": 72,  # 3 days
    "Medium": 168,  # 7 days
    "Low": 336,  # 14 days
}

CATEGORY_DEPARTMENT = {
    "Road": "Highways and Minor Ports Department",
    "Sewage": "Municipal Administration and Water Supply",
    "Water": "Water Resources Department",
    "Electricity": "Energy Department",
    "Health": "Health and Family Welfare Department",
    "Safety": "Home, Prohibition and Excise Department",
    "Fire": "Fire and Rescue Service",
    "Garbage": "Municipal Administration and Water Supply",
    "Other": "Public Department",
}


def parse_node_input(node_input: Any) -> dict:
    if not node_input:
        return {}
    if isinstance(node_input, dict):
        return node_input
    if hasattr(node_input, "parts") and node_input.parts:
        text = ""
        for p in node_input.parts:
            if hasattr(p, "text") and p.text:
                text += p.text
        text = text.strip()
        try:
            return json.loads(text)
        except Exception:
            return {"description": text, "title": ""}
    if isinstance(node_input, str):
        try:
            return json.loads(node_input)
        except Exception:
            return {"description": node_input, "title": ""}
    return {}


@node
def lookup_ward_official(ctx: Context, node_input: Any):
    """Pure logic — no LLM. Finds correct official from ward."""
    data = parse_node_input(node_input)
    ward_id = data.get("ward_id")
    db = firestore_client.get_db()
    ward_doc = db.collection("wards").document(ward_id).get()

    if not ward_doc.exists:
        yield Event(output=data, actions=EventActions(route="error"))
        return

    ward_data = ward_doc.to_dict() or {}
    councillor_id = ward_data.get("councillor_id", "")

    ctx.state.update(
        {
            "ward_data": ward_data,
            "assigned_to": councillor_id,
            "assigned_role": "Ward Councillor",
        }
    )
    yield Event(output=data, actions=EventActions(route="assign_deadline"))


@node
def assign_deadline(ctx: Context, node_input: dict):
    """Pure logic — calculates deadline by severity."""
    severity = node_input.get("severity", "Medium")
    hours = SEVERITY_DEADLINES.get(severity, 168)
    deadline = datetime.utcnow() + timedelta(hours=hours)

    ctx.state.get("assigned_to")
    ctx.state.get("assigned_role")
    department = CATEGORY_DEPARTMENT.get(
        node_input.get("category", "Other"), "Public Department"
    )

    ctx.state.update(
        {"resolution_deadline": deadline.isoformat(), "department": department}
    )
    yield Event(output=node_input, actions=EventActions(route="update_firestore"))


@node
def update_firestore(ctx: Context, node_input: dict):
    """Writes assignment to Firestore and creates alert."""
    db = firestore_client.get_db()
    issue_id = node_input.get("issue_id")
    assigned_to = ctx.state.get("assigned_to")
    deadline = ctx.state.get("resolution_deadline")

    # Update issue document
    db.collection("issues").document(issue_id).update(
        {
            "assigned_to": assigned_to,
            "assigned_role": ctx.state.get("assigned_role"),
            "resolution_deadline": deadline,
            "status": "Notified",
            "timeline": firestore.ArrayUnion(
                [{"status": "Notified", "timestamp": datetime.utcnow().isoformat()}]
            ),
        }
    )

    # Create alert for official
    db.collection("alerts").add(
        {
            "user_id": assigned_to,
            "type": "New Issue Assigned",
            "title": "New Issue Assigned",
            "description": f"New {node_input.get('severity')} issue: {node_input.get('title')}",
            "issue_id": issue_id,
            "read": False,
            "created_at": datetime.utcnow().isoformat(),
        }
    )

    yield Event(
        output={"status": "success", "assigned_to": assigned_to, "deadline": deadline}
    )


root_agent = Workflow(
    name="issue_routing_workflow",
    edges=[
        ("START", lookup_ward_official, assign_deadline, update_firestore),
    ],
)

app = App(
    name="issue_routing_agent",
    root_agent=root_agent,
)


# trigger Vercel rebuild v2
