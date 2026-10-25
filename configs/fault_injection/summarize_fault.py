#!/usr/bin/env python3
import argparse
import re
from collections import Counter

parser = argparse.ArgumentParser()
parser.add_argument("--stdout", required=True)
parser.add_argument("--trace", required=True)
parser.add_argument("--return-code", required=True, type=int)
args = parser.parse_args()

FIELDS = re.compile(r"(\w+)=(\S+)")
INJECTION = re.compile(
    r"\bRUBY_(FAULT_SELECTED|FAULT_INJECTED|"
    r"DATA_FAULT_INJECTED|FAULT_NOT_INJECTED)\b"
)
PROTOCOL = re.compile(
    r"^\s*(\d+):?\s+(\d+)\s+(\S+)\s+(\S+)\s+(\S*>\S*)\s+"
    r"\[(0x[0-9a-fA-F]+),\s*line\s+(0x[0-9a-fA-F]+)\]\s*(.*)$"
)
ERROR = re.compile(
    r"\b(?:fatal|panic):.*|Assertion.*failed.*|"
    r"invalid transition.*|possible deadlock.*|SIGSEGV.*|SIGABRT.*",
    re.I,
)

meta = {}
ticks = set()
result = "not confirmed"
diagnostic = None

# Read the injector's existing inform()/warn() messages.
with open(args.stdout, errors="replace") as stream:
    for line in stream:
        match = INJECTION.search(line)
        if match:
            values = dict(FIELDS.findall(line))
            meta.update(values)

            if "tick" in values:
                ticks.add(values["tick"])

            if match[1] == "FAULT_NOT_INJECTED":
                result = "skipped: " + values.get("reason", "unknown")
            elif match[1] in ("FAULT_INJECTED", "DATA_FAULT_INJECTED"):
                result = "applied"

        match = ERROR.search(line)
        if match and diagnostic is None:
            diagnostic = match[0].strip()[:160]

if len(ticks) > 1:
    parser.error("Use logs containing one injection per run.")

print(f"Injection: {result} at tick {meta.get('tick', '?')}")

if "line" not in meta or "tick" not in meta:
    print("Target activity: unavailable; injection address/tick missing.")
    print(f"Process return code: {args.return_code}")
    print("Diagnostic:", diagnostic or "none recorded")
    raise SystemExit(0)

address = int(meta["line"], 16)
injection_tick = int(meta["tick"])
cache = ".".join(meta.get("cache", "?").split(".")[-2:])

print(
    f"Target: {cache}, slot {meta.get('idx', '?')}, "
    f"address {address:#x}"
)

if "old_state" in meta:
    print(
        f"Forced state: {meta['old_state']} -> "
        f"{meta.get('new_state', '?')}"
    )
elif "bit_position" in meta:
    print(f"Data bit flipped: {meta['bit_position']}")

requests = Counter()
changes = []
change_count = 0
first_event = last_event = None

try:
    with open(args.trace, errors="replace") as stream:
        for line in stream:
            match = PROTOCOL.match(line)
            if not match:
                continue

            tick, node, controller, event, states, _, addr, detail = (
                match.groups()
            )
            tick = int(tick)

            if int(addr, 16) != address or tick < injection_tick:
                continue

            # Count request starts, without also counting Seq Done.
            if controller == "Seq":
                if event == "Begin" and detail:
                    requests[detail.split()[0]] += 1
                continue

            description = (
                f"{controller}-{node}: {event} {states} "
                f"(+{tick - injection_tick} ticks)"
            )
            first_event = first_event or description
            last_event = description

            old, new = states.split(">", 1)
            if old != new:
                change_count += 1
                if len(changes) < 3:
                    changes.append(description)

except FileNotFoundError:
    print("Trace: missing; check gem5 startup/debug options.")

print("First event:", first_event or "none recorded")
print(
    "Requests:",
    ", ".join(f"{kind}={count}" for kind, count in sorted(requests.items()))
    or "none recorded",
)
print(f"Subsequent state changes: {change_count}")

for description in changes:
    print("  " + description)

if change_count > len(changes):
    print(f"  ... {change_count - len(changes)} further changes")

print("Last event:", last_event or "none recorded")
print(f"Process return code: {args.return_code}")
print("Diagnostic:", diagnostic or "none recorded")