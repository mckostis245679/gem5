#!/usr/bin/env python3

from __future__ import annotations

import argparse
import difflib
import json
import re
from dataclasses import (
    asdict,
    dataclass,
)
from pathlib import Path
from typing import Pattern

STATE_INJECTED_RE = re.compile(
    r"RUBY_FAULT_INJECTED\b.*?"
    r"tick=(?P<tick>\d+)\b.*?"
    r"cache=(?P<cache>\S+)\b.*?"
    r"level=(?P<level>L1|L2)\b.*?"
    r"idx=(?P<idx>\d+)\b.*?"
    r"line=(?P<line>0x[0-9a-fA-F]+)\b.*?"
    r"old_state=(?P<old_state>\S+)\b.*?"
    r"new_state=(?P<new_state>\S+)",
    re.IGNORECASE,
)

DATA_INJECTED_RE = re.compile(
    r"RUBY_DATA_FAULT_INJECTED\b.*?"
    r"tick=(?P<tick>\d+)\b.*?"
    r"cache=(?P<cache>\S+)\b.*?"
    r"level=(?P<level>L1|L2)\b.*?"
    r"idx=(?P<idx>\d+)\b.*?"
    r"line=(?P<line>0x[0-9a-fA-F]+)\b.*?"
    r"bit_position=(?P<bit_position>\d+)\b.*?"
    r"byte_offset=(?P<byte_offset>\d+)\b.*?"
    r"bit_in_byte=(?P<bit_in_byte>\d+)\b.*?"
    r"old_byte=(?P<old_byte>0x[0-9a-fA-F]+)\b.*?"
    r"new_byte=(?P<new_byte>0x[0-9a-fA-F]+)",
    re.IGNORECASE,
)

NOT_INJECTED_RE = re.compile(
    r"RUBY_FAULT_NOT_INJECTED\b.*?"
    r"tick=(?P<tick>\d+)\b.*?"
    r"cache=(?P<cache>\S+)\b.*?"
    r"reason=(?P<reason>\S+)",
    re.IGNORECASE,
)

CRASH_PATTERNS: list[tuple[str, Pattern[str]]] = [
    ("gem5 panic", re.compile(r"\bpanic\s*:", re.IGNORECASE)),
    ("gem5 fatal", re.compile(r"\bfatal\s*:", re.IGNORECASE)),
    (
        "invalid transition",
        re.compile(r"\binvalid transition\b", re.IGNORECASE),
    ),
    (
        "segmentation fault",
        re.compile(r"\bsegmentation fault\b|\bsegfault\b", re.IGNORECASE),
    ),
    ("core dump", re.compile(r"\bcore dumped\b|\bcore dump\b", re.IGNORECASE)),
    ("abort", re.compile(r"\baborted\b|\babort(?:ed|ing)?\b", re.IGNORECASE)),
    (
        "assertion failure",
        re.compile(r"\bassert(?:ion)?(?: .*?)? failed\b", re.IGNORECASE),
    ),
    (
        "uncaught exception",
        re.compile(
            r"\buncaught exception\b|\bterminate called\b", re.IGNORECASE
        ),
    ),
    (
        "ruby deadlock",
        re.compile(r"\bruby.*deadlock\b|\bdeadlock.*ruby\b", re.IGNORECASE),
    ),
]


DEFAULT_IGNORE_PATTERNS: list[Pattern[str]] = [
    re.compile(r"^\s*$"),
    re.compile(r"^\s*gem5 Simulator System", re.IGNORECASE),
    re.compile(r"^\s*gem5 is copyrighted", re.IGNORECASE),
    re.compile(r"^\s*gem5 version\b", re.IGNORECASE),
    re.compile(r"^\s*gem5 compiled\b", re.IGNORECASE),
    re.compile(r"^\s*gem5 started\b", re.IGNORECASE),
    re.compile(r"^\s*gem5 executing on\b", re.IGNORECASE),
    re.compile(r"^\s*command line:", re.IGNORECASE),
    re.compile(r"^\s*Global frequency set at\b", re.IGNORECASE),
    re.compile(r"^\s*build/.*:\s+(?:info|warn|warning):", re.IGNORECASE),
    re.compile(r"^\s*src/.*:\s+(?:info|warn|warning):", re.IGNORECASE),
    re.compile(
        r"^\s*.*RUBY_(?:DATA_)?FAULT_(?:INJECTED|NOT_INJECTED|SELECTED|INDEX_CHECK)\b",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*Exiting @ tick\b", re.IGNORECASE),
]


@dataclass
class Result:
    category: str
    reason: str
    confidence: str
    crash_marker: str = ""
    crash_line: str = ""
    baseline_program_lines: int = 0
    fault_program_lines: int = 0
    completion_signature: str = ""
    completion_seen: bool = False
    outputs_equal: bool = False
    first_difference: str = ""
    injection_seen: bool = False
    fault_type: str = ""
    injected_idx: int | None = None
    injected_address: str = ""
    injection_tick: int | None = None
    injection_level: str = ""
    injection_cache: str = ""
    injected_old_state: str = ""
    injected_new_state: str = ""
    injected_bit_position: int | None = None
    injected_byte_offset: int | None = None
    injected_bit_in_byte: int | None = None
    injected_old_byte: str = ""
    injected_new_byte: str = ""
    not_injected_reason: str = ""


def read_lines(path: Path) -> list[str]:
    return path.read_text(errors="replace").splitlines()


def find_injection(lines: list[str]) -> dict:
    for line in lines:
        match = DATA_INJECTED_RE.search(line)
        if match:
            return {
                "injection_seen": True,
                "fault_type": "data_bitflip",
                "injected_idx": int(match.group("idx")),
                "injected_address": match.group("line").lower(),
                "injection_tick": int(match.group("tick")),
                "injection_level": match.group("level").upper(),
                "injection_cache": match.group("cache"),
                "injected_old_state": "",
                "injected_new_state": "",
                "injected_bit_position": int(match.group("bit_position")),
                "injected_byte_offset": int(match.group("byte_offset")),
                "injected_bit_in_byte": int(match.group("bit_in_byte")),
                "injected_old_byte": match.group("old_byte").lower(),
                "injected_new_byte": match.group("new_byte").lower(),
                "not_injected_reason": "",
            }

    for line in lines:
        match = STATE_INJECTED_RE.search(line)
        if match:
            return {
                "injection_seen": True,
                "fault_type": "state",
                "injected_idx": int(match.group("idx")),
                "injected_address": match.group("line").lower(),
                "injection_tick": int(match.group("tick")),
                "injection_level": match.group("level").upper(),
                "injection_cache": match.group("cache"),
                "injected_old_state": match.group("old_state"),
                "injected_new_state": match.group("new_state"),
                "injected_bit_position": None,
                "injected_byte_offset": None,
                "injected_bit_in_byte": None,
                "injected_old_byte": "",
                "injected_new_byte": "",
                "not_injected_reason": "",
            }

    for line in lines:
        match = NOT_INJECTED_RE.search(line)
        if match:
            idx_match = re.search(r"\bidx=(\d+)\b", line)
            type_match = re.search(
                r"\bfault_type=(state|data_bitflip)\b",
                line,
                re.IGNORECASE,
            )
            line_match = re.search(
                r"\bline=(0x[0-9a-fA-F]+)\b",
                line,
            )

            return {
                "injection_seen": False,
                "fault_type": (
                    type_match.group(1).lower() if type_match else ""
                ),
                "injected_idx": int(idx_match.group(1)) if idx_match else None,
                "injected_address": (
                    line_match.group(1).lower() if line_match else ""
                ),
                "injection_tick": int(match.group("tick")),
                "injection_level": "",
                "injection_cache": match.group("cache"),
                "injected_old_state": "",
                "injected_new_state": "",
                "injected_bit_position": None,
                "injected_byte_offset": None,
                "injected_bit_in_byte": None,
                "injected_old_byte": "",
                "injected_new_byte": "",
                "not_injected_reason": match.group("reason"),
            }

    return {
        "injection_seen": False,
        "fault_type": "",
        "injected_idx": None,
        "injected_address": "",
        "injection_tick": None,
        "injection_level": "",
        "injection_cache": "",
        "injected_old_state": "",
        "injected_new_state": "",
        "injected_bit_position": None,
        "injected_byte_offset": None,
        "injected_bit_in_byte": None,
        "injected_old_byte": "",
        "injected_new_byte": "",
        "not_injected_reason": "no_injector_marker_found",
    }


def find_crash(lines: list[str]) -> tuple[str, str]:
    for line in lines:
        for name, regex in CRASH_PATTERNS:
            if regex.search(line):
                return name, line.strip()
    return "", ""


def compile_user_regexes(values: list[str]) -> list[Pattern[str]]:
    return [re.compile(value) for value in values]


def normalize_lines(
    lines: list[str],
    extra_ignore: list[Pattern[str]],
    include: Pattern[str] | None,
) -> list[str]:
    result: list[str] = []
    ignore_patterns = DEFAULT_IGNORE_PATTERNS + extra_ignore

    for raw in lines:
        line = raw.strip()

        if any(regex.search(line) for regex in ignore_patterns):
            continue

        if include is not None and not include.search(line):
            continue

        line = re.sub(r"\s+", " ", line).strip()

        if line:
            result.append(line)

    return result


def line_skeleton(line: str) -> str:
    text = line.strip()
    text = re.sub(r"0x[0-9a-fA-F]+", "<HEX>", text)
    text = re.sub(
        r"(?<![A-Za-z_])[-+]?\d+(?:\.\d+)?(?![A-Za-z_])",
        "<NUM>",
        text,
    )
    text = re.sub(r"\s+", " ", text)
    return text


def choose_completion_signature(
    baseline_program: list[str],
    explicit_regex: str | None,
) -> tuple[str, Pattern[str] | None]:
    if explicit_regex:
        return explicit_regex, re.compile(explicit_regex)

    if not baseline_program:
        return "", None

    skeleton = line_skeleton(baseline_program[-1])
    escaped = re.escape(skeleton)
    escaped = escaped.replace(re.escape("<HEX>"), r"0x[0-9a-fA-F]+")
    escaped = escaped.replace(re.escape("<NUM>"), r"[-+]?\d+(?:\.\d+)?")

    return skeleton, re.compile(rf"^{escaped}$")


def find_first_difference(a: list[str], b: list[str]) -> str:
    max_len = max(len(a), len(b))

    for idx in range(max_len):
        left = a[idx] if idx < len(a) else "<missing>"
        right = b[idx] if idx < len(b) else "<missing>"

        if left != right:
            return f"line {idx + 1}: baseline={left!r}; fault={right!r}"

    return ""


def classify(
    baseline_raw: list[str],
    fault_raw: list[str],
    extra_ignore: list[Pattern[str]],
    include: Pattern[str] | None,
    completion_regex: str | None,
) -> tuple[Result, list[str], list[str]]:
    crash_marker, crash_line = find_crash(fault_raw)
    injection = find_injection(fault_raw)

    baseline_program = normalize_lines(
        baseline_raw,
        extra_ignore,
        include,
    )
    fault_program = normalize_lines(
        fault_raw,
        extra_ignore,
        include,
    )

    signature_text, signature_re = choose_completion_signature(
        baseline_program,
        completion_regex,
    )

    completion_seen = False
    if signature_re is not None:
        completion_seen = any(
            signature_re.search(line) for line in fault_program
        )

    outputs_equal = baseline_program == fault_program
    first_diff = find_first_difference(
        baseline_program,
        fault_program,
    )

    if crash_marker:
        return (
            Result(
                category="SYSTEM_CRASH",
                reason=f"Explicit crash marker detected: {crash_marker}.",
                confidence="CONFIRMED",
                crash_marker=crash_marker,
                crash_line=crash_line,
                baseline_program_lines=len(baseline_program),
                fault_program_lines=len(fault_program),
                completion_signature=signature_text,
                completion_seen=completion_seen,
                outputs_equal=outputs_equal,
                first_difference=first_diff,
                **injection,
            ),
            baseline_program,
            fault_program,
        )

    if (
        not injection["injection_seen"]
        and injection["not_injected_reason"]
        and injection["not_injected_reason"] != "no_injector_marker_found"
    ):
        return (
            Result(
                category="NOT_INJECTED",
                reason=(
                    "The selected cache slot was not injected: "
                    f"{injection['not_injected_reason']}."
                ),
                confidence="CONFIRMED",
                baseline_program_lines=len(baseline_program),
                fault_program_lines=len(fault_program),
                completion_signature=signature_text,
                completion_seen=completion_seen,
                outputs_equal=outputs_equal,
                first_difference=first_diff,
                **injection,
            ),
            baseline_program,
            fault_program,
        )

    if not baseline_program:
        return (
            Result(
                category="SYSTEM_CRASH",
                reason=(
                    "No baseline workload output remained after filtering, so "
                    "normal completion could not be established."
                ),
                confidence="LOW",
                baseline_program_lines=0,
                fault_program_lines=len(fault_program),
                completion_signature=signature_text,
                completion_seen=completion_seen,
                outputs_equal=outputs_equal,
                first_difference=first_diff,
                **injection,
            ),
            baseline_program,
            fault_program,
        )

    if signature_re is not None and not completion_seen:
        return (
            Result(
                category="SYSTEM_CRASH",
                reason=(
                    "The faulty run did not reach the baseline's normal-completion "
                    "signature."
                ),
                confidence="INFERRED",
                baseline_program_lines=len(baseline_program),
                fault_program_lines=len(fault_program),
                completion_signature=signature_text,
                completion_seen=False,
                outputs_equal=outputs_equal,
                first_difference=first_diff,
                **injection,
            ),
            baseline_program,
            fault_program,
        )

    if outputs_equal:
        return (
            Result(
                category="NO_CHANGE",
                reason=(
                    "The faulty run reached normal completion and its normalized "
                    "workload output is identical to the baseline."
                ),
                confidence="CONFIRMED",
                baseline_program_lines=len(baseline_program),
                fault_program_lines=len(fault_program),
                completion_signature=signature_text,
                completion_seen=completion_seen,
                outputs_equal=True,
                **injection,
            ),
            baseline_program,
            fault_program,
        )

    return (
        Result(
            category="SDC",
            reason=(
                "The faulty run reached normal completion, but its normalized "
                "workload output differs from the known-good baseline."
            ),
            confidence="CONFIRMED",
            baseline_program_lines=len(baseline_program),
            fault_program_lines=len(fault_program),
            completion_signature=signature_text,
            completion_seen=completion_seen,
            outputs_equal=False,
            first_difference=first_diff,
            **injection,
        ),
        baseline_program,
        fault_program,
    )


def print_result(
    result: Result,
    baseline_program: list[str],
    fault_program: list[str],
    show_diff: bool,
) -> None:
    print()
    print("=" * 80)
    print("FAULT OUTCOME")
    print("=" * 80)
    print(f"Category:   {result.category}")
    print(f"Confidence: {result.confidence}")
    print(f"Reason:     {result.reason}")
    print(f"Injected:   {result.injection_seen}")

    if result.injection_seen:
        print(f"Fault type: {result.fault_type}")
        print(f"Index:      {result.injected_idx}")
        print(f"Address:    {result.injected_address}")
        print(f"Fault tick: {result.injection_tick}")
        print(f"Level:      {result.injection_level}")
        print(f"Cache:      {result.injection_cache}")

        if result.fault_type == "data_bitflip":
            print(f"Bit:        {result.injected_bit_position}")
            print(f"Byte:       {result.injected_byte_offset}")
            print(f"Bit/byte:   {result.injected_bit_in_byte}")
            print(
                f"Data:       {result.injected_old_byte}"
                f"->{result.injected_new_byte}"
            )
        else:
            print(
                f"State:      {result.injected_old_state}"
                f"->{result.injected_new_state}"
            )
    elif result.not_injected_reason:
        print(f"Fault type: {result.fault_type or '<unknown>'}")
        if result.injected_idx is not None:
            print(f"Index:      {result.injected_idx}")
        if result.injected_address:
            print(f"Address:    {result.injected_address}")
        print(f"Injection reason: {result.not_injected_reason}")

    if result.crash_line:
        print(f"Crash line: {result.crash_line}")

    print(f"Completion signature: {result.completion_signature or '<none>'}")
    print(f"Completion seen:      {result.completion_seen}")
    print(f"Baseline lines:       {result.baseline_program_lines}")
    print(f"Fault lines:          {result.fault_program_lines}")

    if result.first_difference:
        print(f"First difference:     {result.first_difference}")

    if show_diff and baseline_program != fault_program:
        print()
        print("=" * 80)
        print("NORMALIZED OUTPUT DIFF")
        print("=" * 80)

        diff = difflib.unified_diff(
            baseline_program,
            fault_program,
            fromfile="baseline",
            tofile="fault",
            lineterm="",
        )

        for line in diff:
            print(line)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Classify a gem5 fault run as NO_CHANGE, SDC, or SYSTEM_CRASH "
            "using captured textual output and a known-good baseline."
        )
    )

    parser.add_argument(
        "--baseline",
        required=True,
        type=Path,
        help="Known-good baseline stdout log.",
    )
    parser.add_argument(
        "--fault",
        required=True,
        type=Path,
        help="Fault-injected stdout log.",
    )
    parser.add_argument(
        "--completion-regex",
        help=(
            "Regex identifying normal workload completion. If omitted, the "
            "parser derives a signature from the final baseline workload line."
        ),
    )
    parser.add_argument(
        "--include-regex",
        help=(
            "Only compare lines matching this regex. Example: "
            "'thread|checksum|final value'."
        ),
    )
    parser.add_argument(
        "--ignore-regex",
        action="append",
        default=[],
        help=(
            "Additional regex for lines to ignore during comparison. "
            "May be specified multiple times."
        ),
    )
    parser.add_argument(
        "--show-diff",
        action="store_true",
        help="Print a unified diff when baseline and fault output differ.",
    )
    parser.add_argument(
        "--json",
        type=Path,
        help="Optional path for a JSON classification report.",
    )

    args = parser.parse_args()

    for path in (args.baseline, args.fault):
        if not path.exists():
            parser.error(f"File does not exist: {path}")

    extra_ignore = compile_user_regexes(args.ignore_regex)
    include = re.compile(args.include_regex) if args.include_regex else None

    result, baseline_program, fault_program = classify(
        read_lines(args.baseline),
        read_lines(args.fault),
        extra_ignore,
        include,
        args.completion_regex,
    )

    print_result(
        result,
        baseline_program,
        fault_program,
        args.show_diff,
    )

    if args.json:
        args.json.write_text(json.dumps(asdict(result), indent=2))


if __name__ == "__main__":
    main()
