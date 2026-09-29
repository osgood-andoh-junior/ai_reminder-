"""Translate server-issued time references before validating application tool inputs.

The model selects a reference and, where explicitly requested, a wall-clock time.
It never performs calendar arithmetic. Persisted proposals contain resolved instants,
so accepting tomorrow's proposal tomorrow does not move it forward another day.
"""

from copy import deepcopy
from datetime import date, datetime
from app.core.time_context import local_instant, resolve_mentions, unresolved_relative_time

INSTANT_FIELDS = {
    "deadline",
    "start_time",
    "end_time",
    "not_before",
    "not_after",
    "reminder_time",
    "until",
    "start",
    "end",
}
SCHEDULE_TOOLS = {"schedule_task", "reschedule_task", "find_available_time"}


class TimeArguments:
    def __init__(self, context, message=""):
        self.context = context
        self.message = message
        self.references = resolve_mentions(message, context)
        self.needs_clarification = unresolved_relative_time(message)
        self.known_instants = set()

    def explicit_instant(self, value):
        # Absolute dates may come from the current user or an authenticated read tool,
        # never from a model's guess or a stale assistant message.
        text = str(value)
        return (
            text in self.message
            or text[:10] in self.message
            or (not self.references and text in self.known_instants)
        )

    def reference(self, ident):
        if not isinstance(ident, str) or ident not in self.references:
            raise ValueError(
                "Use a time reference from the current request, or ask the user to clarify the date"
            )
        return self.references[ident]

    def instant(self, value):
        if not isinstance(value, dict) or set(value) - {"reference", "edge", "local_time"}:
            raise ValueError("Use reference, edge and optional local_time for a relative timestamp")
        ref = self.reference(value.get("reference"))
        edge = value.get("edge", "start")
        if edge not in {"start", "end"}:
            raise ValueError("Time reference edge must be start or end")
        if value.get("local_time") is not None:
            if ref["kind"] != "day" or edge != "start":
                raise ValueError("A local clock time requires a day reference and start edge")
            return local_instant(
                date.fromisoformat(ref["local_date"]), value["local_time"], self.context.zone
            ).isoformat()
        if ref["kind"] == "day" and "edge" not in value:
            raise ValueError("A day requires an explicit start/end edge or local_time")
        if ref[edge] is None:
            raise ValueError("An elapsed-time reference has no end; use its start instant")
        return ref[edge]

    def schema(self, model):
        schema = deepcopy(model.model_json_schema())
        reference = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "reference": {"type": "string", "enum": list(self.references)},
                "edge": {"type": "string", "enum": ["start", "end"]},
                "local_time": {"type": "string", "pattern": r"^([01]\d|2[0-3]):[0-5]\d$"},
            },
            "required": ["reference"],
            "description": "Server-resolved time. For a day provide local_time or edge; end is exclusive next midnight.",
        }

        def visit(node):
            if isinstance(node, dict):
                for name, prop in list(node.get("properties", {}).items()):
                    if name in INSTANT_FIELDS and self.references:
                        node["properties"][name] = {"anyOf": [prop, reference]}
                    elif name == "excluded_dates" and self.references:
                        prop["items"] = {"anyOf": [prop["items"], reference]}
                if node.get("title") == "ScheduleInput" and self.references:
                    node["properties"]["time_window"] = {
                        "type": "string",
                        "enum": list(self.references),
                        "description": "Required for a relative target day/time; server bounds availability and scheduling.",
                    }
                    node["properties"]["deadline_reference"] = {
                        "type": "string",
                        "enum": list(self.references),
                        "description": "For a relative due/by deadline: search from now through that day, rather than only on it.",
                    }
                # Only descend into definitions, not the reference schema we just injected.
                for child in node.get("$defs", {}).values():
                    visit(child)

        visit(schema)
        return schema

    def normalize(self, name, arguments):
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be an object")
        if self.needs_clarification and name in SCHEDULE_TOOLS | {
            "reschedule_multiple_tasks",
            "create_calendar_event",
            "update_calendar_event",
            "create_reminder",
            "snooze_reminder",
            "detect_conflicts",
        }:
            raise ValueError(
                "This relative time needs clarification. Ask for an explicit date/time before scheduling"
            )

        def walk(data):
            result = {}
            for key, value in data.items():
                if key in INSTANT_FIELDS and value is not None:
                    if isinstance(value, dict):
                        ref = self.reference(value.get("reference"))
                        if (
                            key in {"reminder_time", "start_time", "end_time"}
                            and ref["kind"] == "day"
                            and not value.get("local_time")
                        ):
                            raise ValueError(
                                "Ask for an explicit local clock time for this reminder or event"
                            )
                        value = self.instant(value)
                    elif self.message and not self.explicit_instant(value):
                        raise ValueError(
                            "Do not calculate relative timestamps. Use the current request's server time references"
                        )
                elif key == "local_date" and value is not None and self.message:
                    if (
                        value not in [ref["expression"] for ref in self.references.values()]
                        and value not in self.message
                    ):
                        raise ValueError(
                            "Keep local_date as the user's relative phrase; do not invent its date"
                        )
                    value = self.context.day(value).isoformat()
                elif key == "excluded_dates":
                    dates = []
                    for item in value:
                        if isinstance(item, dict):
                            if set(item) != {"reference"}:
                                raise ValueError("Excluded dates require only a reference")
                            ref = self.reference(item["reference"])
                            if ref["kind"] != "day":
                                raise ValueError("Excluded dates require a day reference")
                            dates.append(ref["local_date"])
                        elif self.message and item not in self.message:
                            raise ValueError("Use a server reference for relative excluded dates")
                        else:
                            dates.append(item)
                    value = dates
                elif isinstance(value, dict):
                    value = walk(value)
                result[key] = value
            return result

        def schedule(data):
            data = dict(data)
            window = data.pop("time_window", None)
            deadline = data.pop("deadline_reference", None)
            parsed = walk(data)
            if deadline is not None:
                ref = self.reference(deadline)
                end = datetime.fromisoformat(ref["end"] or ref["start"])
                if parsed.get("not_after"):
                    end = min(end, datetime.fromisoformat(parsed["not_after"]))
                parsed["not_after"] = end.isoformat()
            if window is not None:
                ref = self.reference(window)
                start = max(self.context.now, datetime.fromisoformat(ref["start"]))
                if parsed.get("not_before"):
                    start = max(start, datetime.fromisoformat(parsed["not_before"]))
                parsed["not_before"] = start.isoformat()
                if ref["end"]:
                    end = datetime.fromisoformat(ref["end"])
                    if parsed.get("not_after"):
                        end = min(end, datetime.fromisoformat(parsed["not_after"]))
                    parsed["not_after"] = end.isoformat()
            elif self.references and deadline is None and not data.get("excluded_dates"):
                raise ValueError(
                    "Select time_window from the server references before searching or scheduling a relative time"
                )
            return parsed

        if name in SCHEDULE_TOOLS:
            return schedule(arguments)
        if name == "reschedule_multiple_tasks":
            return {**arguments, "tasks": [schedule(item) for item in arguments.get("tasks", [])]}
        return walk(arguments)
