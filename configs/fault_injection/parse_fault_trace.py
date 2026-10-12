#!/usr/bin/env python3

import argparse
import csv
import json
import re
from dataclasses import (
    asdict,
    dataclass,
)
from pathlib import Path

PROTOCOL_RE = re.compile(
    r"^\s*(?P<tick>\d+)\s+(?P<controller>\d+)\s+"
    r"(?P<component>\S+)\s+(?P<event>\S+)\s+"
    r"(?P<transition>\S*>\S*)\s+"
    r"\[(?P<address>0x[0-9a-fA-F]+),\s*line\s+"
    r"(?P<line>0x[0-9a-fA-F]+)\]"
    r"(?:\s+(?P<extra>.*))?$"
)

GENERATED_RE = re.compile(
    r"^(?P<tick>\d+):\s+(?P<object>[^:]+):\s+.*?"
    r"state:\s*(?P<state>[A-Za-z0-9_]+),\s*"
    r"event:\s*(?P<event>[A-Za-z0-9_]+),\s*"
    r"addr:\s*(?P<addr>0x[0-9a-fA-F]+)"
)

ACTION_RE = re.compile(
    r"^(?P<tick>\d+):\s+(?P<object>[^:]+):\s+"
    r"executing\s+(?P<action>[A-Za-z0-9_]+)"
)

NEXT_STATE_RE = re.compile(
    r"^(?P<tick>\d+):\s+(?P<object>[^:]+):\s+"
    r"next_state:\s*(?P<state>[A-Za-z0-9_]+)"
)

SLICC_RE = re.compile(
    r"^(?P<tick>\d+):\s+(?P<object>[^:]+):\s+"
    r"(?P<source>MESI_Two_Level-[^:]+\.sm:\d+):\s+"
    r"(?P<message>.*)$"
)

ADDR_RE = re.compile(r"\b(?:Addr|addr|address)\s*[:=]\s*(0x[0-9a-fA-F]+)")
STATE_RE = re.compile(r"\bState\s*[:=]\s*([A-Za-z0-9_]+)")
TYPE_RE = re.compile(r"\bType\s*[:=]\s*([A-Za-z0-9_]+)")
REQ_RE = re.compile(r"\b(?:Req|Requestor|requestor)\s*[:=]\s*([A-Za-z0-9_-]+)")
PANIC_RE = re.compile(r"(panic:|fatal:|invalid transition)", re.IGNORECASE)


@dataclass
class Event:
    tick: int | None
    order: int
    source: str
    category: str
    component: str = ""
    event: str = ""
    old_state: str = ""
    new_state: str = ""
    line: str = ""
    message_type: str = ""
    requestor: str = ""
    detail: str = ""


def norm_addr(s: str) -> str:
    return hex(int(s, 16))


def component_from_object(obj: str) -> str:
    if "l1_controllers" in obj:
        return "L1"
    if "l2_controllers" in obj:
        return "L2"
    if "directory" in obj.lower():
        return "Directory"
    return "Ruby"


def extract(regex, text):
    m = regex.search(text)
    return m.group(1) if m else ""


def parse_trace(path: Path):
    events = []
    contexts = {}

    with path.open("r", errors="replace") as f:
        for order, raw in enumerate(f, 1):
            line = raw.rstrip("\n")

            m = PROTOCOL_RE.match(line)
            if m:
                old_state, new_state = m.group("transition").split(">", 1)
                component = m.group("component")
                event = m.group("event")

                if component == "Seq" and event == "Begin":
                    category = "CPU_REQUEST"
                elif component == "Seq" and event == "Done":
                    category = "CPU_COMPLETION"
                elif component == "L1Cache":
                    category = "L1_TRANSITION"
                elif component == "L2Cache":
                    category = "L2_TRANSITION"
                else:
                    category = "PROTOCOL_EVENT"

                events.append(
                    Event(
                        tick=int(m.group("tick")),
                        order=order,
                        source="ProtocolTrace",
                        category=category,
                        component=component,
                        event=event,
                        old_state=old_state,
                        new_state=new_state,
                        line=norm_addr(m.group("line")),
                        detail=(m.group("extra") or "").strip(),
                    )
                )
                continue

            m = GENERATED_RE.match(line)
            if m:
                obj = m.group("object")
                addr = norm_addr(m.group("addr"))
                state = m.group("state")
                event = m.group("event")
                contexts[obj] = (addr, state, event)

                events.append(
                    Event(
                        tick=int(m.group("tick")),
                        order=order,
                        source="RubyGenerated",
                        category="STATE_EVENT_ATTEMPT",
                        component=component_from_object(obj),
                        event=event,
                        old_state=state,
                        line=addr,
                    )
                )
                continue

            m = ACTION_RE.match(line)
            if m:
                obj = m.group("object")
                addr, state, event = contexts.get(obj, ("", "", ""))
                action = m.group("action")
                msg = ""
                for name in (
                    "Fwd_GETX",
                    "Fwd_GETS",
                    "GETX",
                    "GETS",
                    "UPGRADE",
                    "INV",
                    "ACK",
                    "DATA",
                ):
                    if name.upper() in action.upper():
                        msg = name
                        break

                events.append(
                    Event(
                        tick=int(m.group("tick")),
                        order=order,
                        source="RubyGenerated",
                        category="ACTION",
                        component=component_from_object(obj),
                        event=action,
                        old_state=state,
                        line=addr,
                        message_type=msg,
                    )
                )
                continue

            m = NEXT_STATE_RE.match(line)
            if m:
                obj = m.group("object")
                addr, old_state, event = contexts.get(obj, ("", "", ""))
                events.append(
                    Event(
                        tick=int(m.group("tick")),
                        order=order,
                        source="RubyGenerated",
                        category="NEXT_STATE",
                        component=component_from_object(obj),
                        event=event,
                        old_state=old_state,
                        new_state=m.group("state"),
                        line=addr,
                    )
                )
                continue

            m = SLICC_RE.match(line)
            if m:
                message = m.group("message")
                addr = extract(ADDR_RE, message)
                source = m.group("source")
                component = (
                    "L1"
                    if "L1cache.sm" in source
                    else (
                        "L2"
                        if "L2cache.sm" in source
                        else "Directory" if "-dir.sm" in source else "SLICC"
                    )
                )

                events.append(
                    Event(
                        tick=int(m.group("tick")),
                        order=order,
                        source="RubySlicc",
                        category="PROTOCOL_DETAIL",
                        component=component,
                        event=extract(TYPE_RE, message) or "SLICC_DETAIL",
                        old_state=extract(STATE_RE, message),
                        line=norm_addr(addr) if addr else "",
                        message_type=extract(TYPE_RE, message),
                        requestor=extract(REQ_RE, message),
                        detail=message,
                    )
                )
                continue

            if PANIC_RE.search(line):
                events.append(
                    Event(
                        tick=None,
                        order=order,
                        source="gem5",
                        category="FAILURE",
                        event=(
                            "INVALID_TRANSITION"
                            if "invalid transition" in line.lower()
                            else "PANIC_OR_FATAL"
                        ),
                        detail=line,
                    )
                )

    return events


def select_events(events, target_line, fault_tick):
    target_line = norm_addr(target_line)
    selected = []

    for e in events:
        if e.category == "FAILURE":
            selected.append(e)
            continue
        if e.tick is not None and e.tick < fault_tick:
            continue
        if e.line == target_line:
            selected.append(e)

    return selected


def infer_failure(events):
    attempts = [e for e in events if e.category == "STATE_EVENT_ATTEMPT"]
    if not attempts:
        return None

    last = attempts[-1]
    later = [e for e in events if e.order > last.order and e.line == last.line]
    completed = any(
        e.category in ("NEXT_STATE", "L1_TRANSITION", "L2_TRANSITION")
        for e in later
    )

    if completed:
        return None

    return Event(
        tick=last.tick,
        order=last.order + 1,
        source="Analysis",
        category="INFERRED_FAILURE",
        component=last.component,
        event="NO_VALID_TRANSITION_OBSERVED",
        old_state=last.old_state,
        line=last.line,
        detail=f"Last attempted state/event was {last.old_state} + {last.event}.",
    )


def print_timeline(events):
    print("\nFAULT PROPAGATION TIMELINE")
    print("=" * 112)
    print(
        f"{'TICK':<14}{'SOURCE':<16}{'CATEGORY':<22}{'COMP':<10}{'EVENT':<28}{'STATE':<12}DETAIL"
    )
    print("-" * 112)

    for e in events:
        tick = str(e.tick) if e.tick is not None else "?"
        state = f"{e.old_state}->{e.new_state}" if e.new_state else e.old_state
        details = []
        if e.message_type:
            details.append(f"msg={e.message_type}")
        if e.requestor:
            details.append(f"req={e.requestor}")
        if e.line:
            details.append(f"line={e.line}")
        if e.detail and e.category in ("FAILURE", "INFERRED_FAILURE"):
            details.append(e.detail)

        print(
            f"{tick:<14}{e.source:<16}{e.category:<22}{e.component:<10}"
            f'{e.event:<28}{state:<12}{" ".join(details)}'
        )


def print_summary(events, args):
    print("\nPROPAGATION SUMMARY")
    print("=" * 112)
    print(
        f"Injected fault: tick={args.fault_tick} line={norm_addr(args.line)} "
        f'{args.fault_level} {args.old_state or "?"}->{args.new_state or "?"}'
    )

    explicit_failure = next(
        (e for e in events if e.category == "FAILURE"), None
    )
    inferred_failure = next(
        (e for e in events if e.category == "INFERRED_FAILURE"), None
    )

    if explicit_failure:
        outcome = "ERROR_CONFIRMED"
        reason = explicit_failure.detail
    elif inferred_failure:
        outcome = "ERROR_LIKELY"
        reason = inferred_failure.detail
    elif any(e.category == "CPU_COMPLETION" for e in events):
        outcome = "NO_PROTOCOL_ERROR_OBSERVED"
        reason = "A CPU request on the target line completed and no failure was parsed."
    else:
        outcome = "PROPAGATION_OBSERVED"
        reason = "The trace shows post-fault protocol activity but does not prove success or failure."

    print(f"Outcome: {outcome}")
    print(f"Reason:  {reason}")

    last_attempt = next(
        (e for e in reversed(events) if e.category == "STATE_EVENT_ATTEMPT"),
        None,
    )
    if last_attempt:
        print(
            f"Last state/event attempt: tick={last_attempt.tick} "
            f"{last_attempt.component} {last_attempt.old_state} + {last_attempt.event}"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("trace", type=Path)
    parser.add_argument("--line", required=True)
    parser.add_argument("--fault-tick", type=int, required=True)
    parser.add_argument("--fault-level", choices=("L1", "L2"), default="L1")
    parser.add_argument("--old-state")
    parser.add_argument("--new-state")
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()

    if not args.trace.exists():
        parser.error(f"Trace file not found: {args.trace}")

    events = select_events(parse_trace(args.trace), args.line, args.fault_tick)

    injection = Event(
        tick=args.fault_tick,
        order=-1,
        source="FaultInjector",
        category="FAULT_INJECTION",
        component=args.fault_level,
        event="FORCED_STATE_CHANGE",
        old_state=args.old_state or "?",
        new_state=args.new_state or "?",
        line=norm_addr(args.line),
    )
    events.append(injection)

    inferred = infer_failure(events)
    if inferred:
        events.append(inferred)

    events.sort(
        key=lambda e: (e.tick if e.tick is not None else 10**30, e.order)
    )

    print_timeline(events)
    print_summary(events, args)

    if args.csv:
        with args.csv.open("w", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=Event.__dataclass_fields__.keys()
            )
            writer.writeheader()
            for e in events:
                writer.writerow(asdict(e))

    if args.json:
        args.json.write_text(json.dumps([asdict(e) for e in events], indent=2))


if __name__ == "__main__":
    main()
