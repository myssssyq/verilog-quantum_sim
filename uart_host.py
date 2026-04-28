#!/usr/bin/env python3
"""
UART host script for the FPGA 3-qubit simulator.

Features:
  * reads from a serial port or stdin
  * decodes raw UART state dumps and measurement lines
  * can also parse the reference simulator's human-readable fixed-point dumps
  * aggregates measurement statistics by qubit and, when possible, by shot bitstring

Examples:
  python uart_host.py COM3 --baud 115200
  python reference_sim.py program.hex --mode fixed --uart | python uart_host.py --stdin
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from typing import Dict, Iterable, Optional, Tuple

try:
    import serial
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

try:
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

RAW_STATE_RE = re.compile(r'^\|([01]{3})>\s+([+-][0-9A-Fa-f]{4})\s+([+-][0-9A-Fa-f]{4})i$')
REF_STATE_RE = re.compile(r'^\|([01]{3})>\s*=\s*([+-]?\d+)\s+([+-]?\d+)i(?:\s+\(.*\))?$')
MEASURE_RE = re.compile(r'^M\((\d)\)=(\d)$')
PC_TRACE_RE = re.compile(r'^PC=')
HALT_RE = re.compile(r'^--- HALT ---$')


def _parse_signed_hex(token: str) -> int:
    mag = int(token[1:], 16)
    return mag if token[0] == '+' else -mag


def parse_state_line(line: str) -> Optional[Tuple[int, int, int]]:
    """Parse either raw UART dump lines or reference-sim fixed-point lines."""
    m = RAW_STATE_RE.match(line)
    if m:
        bits, re_tok, im_tok = m.groups()
        return int(bits, 2), _parse_signed_hex(re_tok), _parse_signed_hex(im_tok)

    m = REF_STATE_RE.match(line)
    if m:
        bits, re_val, im_val = m.groups()
        return int(bits, 2), int(re_val), int(im_val)

    return None


def parse_measure_line(line: str) -> Optional[Tuple[int, int]]:
    m = MEASURE_RE.match(line)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def q14_to_float(val: int) -> float:
    return val / 16384.0


def format_state(state: Dict[int, Tuple[int, int]]) -> None:
    print("\n  Basis  |  Q2.14 Raw  |  Float Value  |  |amp|^2")
    print("  " + "-" * 55)
    total_prob = 0.0
    for i in range(8):
        re_val, im_val = state.get(i, (0, 0))
        re_f = q14_to_float(re_val)
        im_f = q14_to_float(im_val)
        prob = re_f * re_f + im_f * im_f
        total_prob += prob
        bits = f"|{(i >> 2) & 1}{(i >> 1) & 1}{i & 1}>"
        print(
            f"  {bits}  | {re_val:+6d} {im_val:+6d}i | "
            f"{re_f:+.4f} {im_f:+.4f}i | {prob:.4f}"
        )
    print(f"  {'':6s}  {'':13s}  {'':15s}  Σ = {total_prob:.4f}")


class ShotTracker:
    """Track measurement counts per qubit and, optionally, per shot bitstring."""

    def __init__(self, shot_layout: Optional[list[int]] = None):
        self.per_qubit = defaultdict(Counter)
        self.bitstring_counts: Counter[str] = Counter()
        self.current: Dict[int, int] = {}
        self.shot_layout = shot_layout or []
        self.layout_pos = 0

    def add(self, qubit: int, result: int) -> None:
        self.per_qubit[qubit][result] += 1

        if self.shot_layout:
            expected = self.shot_layout[self.layout_pos]
            if qubit != expected and self.current:
                self._finalize_current()
            self.current[qubit] = result
            if qubit == self.shot_layout[self.layout_pos]:
                self.layout_pos = (self.layout_pos + 1) % len(self.shot_layout)
                if self.layout_pos == 0:
                    self._finalize_current()
            return

        # Best-effort auto grouping: start a new shot when a qubit repeats.
        if qubit in self.current:
            self._finalize_current()
        self.current[qubit] = result

    def _finalize_current(self) -> None:
        if not self.current:
            return
        width = max(self.current) + 1
        bits = ''.join(str(self.current.get(q, 'x')) for q in range(width - 1, -1, -1))
        self.bitstring_counts[bits] += 1
        self.current = {}

    def finalize(self) -> None:
        self._finalize_current()

    def print_summary(self) -> None:
        self.finalize()
        if not self.per_qubit and not self.bitstring_counts:
            return

        print("\nMeasurement summary:")
        for qubit in sorted(self.per_qubit):
            counts = self.per_qubit[qubit]
            total = counts[0] + counts[1]
            if total == 0:
                continue
            print(
                f"  q{qubit}: |0>={counts[0]} ({100 * counts[0] / total:.1f}%), "
                f"|1>={counts[1]} ({100 * counts[1] / total:.1f}%)"
            )

        if self.bitstring_counts:
            print("  Shot bitstrings:")
            for bitstring, count in self.bitstring_counts.most_common():
                print(f"    {bitstring}: {count}")

    def plot(self, output_path: str) -> None:
        self.finalize()
        if not HAS_MATPLOTLIB:
            return
        if not self.per_qubit and not self.bitstring_counts:
            return

        figure_count = len(self.per_qubit) + (1 if self.bitstring_counts else 0)
        fig, axes = plt.subplots(1, figure_count, figsize=(4 * figure_count, 4))
        if figure_count == 1:
            axes = [axes]

        ax_iter = iter(axes)
        for qubit in sorted(self.per_qubit):
            ax = next(ax_iter)
            counts = self.per_qubit[qubit]
            total = counts[0] + counts[1]
            bars = ax.bar(['|0>', '|1>'], [counts[0], counts[1]])
            ax.set_title(f'q{qubit} ({total} meas.)')
            ax.set_ylabel('Count')
            for bar, val in zip(bars, [counts[0], counts[1]]):
                pct = (100 * val / total) if total else 0.0
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5, f'{val}\n({pct:.1f}%)', ha='center', va='bottom')

        if self.bitstring_counts:
            ax = next(ax_iter)
            labels = list(self.bitstring_counts.keys())
            values = [self.bitstring_counts[label] for label in labels]
            bars = ax.bar(labels, values)
            ax.set_title('Shot bitstrings')
            ax.set_ylabel('Count')
            for bar, val in zip(bars, values):
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5, str(val), ha='center', va='bottom')

        plt.tight_layout()
        plt.savefig(output_path, dpi=150)
        print(f"Saved plot to {output_path}")


def process_lines(lines: Iterable[str], tracker: ShotTracker, echo_other: bool = True) -> None:
    state: Dict[int, Tuple[int, int]] = {}

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        parsed_state = parse_state_line(line)
        if parsed_state:
            idx, re_val, im_val = parsed_state
            state[idx] = (re_val, im_val)
            if len(state) == 8:
                format_state(state)
                state = {}
            continue

        parsed_meas = parse_measure_line(line)
        if parsed_meas:
            qubit, result = parsed_meas
            print(f"  Measurement: qubit {qubit} = {result}")
            tracker.add(qubit, result)
            continue

        if PC_TRACE_RE.search(line) or line.startswith('===') or line.startswith('Loaded ') or HALT_RE.match(line):
            continue

        if echo_other:
            print(f"  > {line}")


def run_serial(port: str, baud: int, tracker: ShotTracker, echo_other: bool) -> None:
    if not HAS_SERIAL:
        print("ERROR: pyserial is not installed. Run: pip install pyserial", file=sys.stderr)
        raise SystemExit(1)

    print(f"Connecting to {port} at {baud} baud...")
    ser = serial.Serial(port, baud, timeout=1)
    print("Connected. Waiting for data...\n")
    line_buf = ""

    try:
        while True:
            data = ser.read(ser.in_waiting or 1)
            if not data:
                continue
            text = data.decode('ascii', errors='replace')
            line_buf += text
            while '\n' in line_buf:
                line, line_buf = line_buf.split('\n', 1)
                process_lines([line], tracker=tracker, echo_other=echo_other)
    except KeyboardInterrupt:
        print("\nDisconnected.")
    finally:
        ser.close()


def main() -> int:
    parser = argparse.ArgumentParser(description='Quantum simulator UART host')
    parser.add_argument('port', nargs='?', help='Serial port (for example COM3 or /dev/ttyUSB0)')
    parser.add_argument('--baud', type=int, default=115200, help='UART baud rate')
    parser.add_argument('--stdin', action='store_true', help='Force stdin mode even if a port argument is supplied')
    parser.add_argument('--shot-layout', help='Comma-separated qubit order per shot, e.g. 0,1 or 0,1,2')
    parser.add_argument('--plot', action='store_true', help='Generate a plot when matplotlib is available')
    parser.add_argument('--plot-file', default='shot_results.png', help='Output path for plot image')
    parser.add_argument('--quiet-other', action='store_true', help='Hide unparsed non-UART lines')
    args = parser.parse_args()

    layout = None
    if args.shot_layout:
        try:
            layout = [int(x.strip()) for x in args.shot_layout.split(',') if x.strip()]
        except ValueError as exc:
            raise SystemExit(f'Invalid --shot-layout value: {args.shot_layout}') from exc

    tracker = ShotTracker(shot_layout=layout)

    if args.port and not args.stdin:
        run_serial(args.port, args.baud, tracker=tracker, echo_other=not args.quiet_other)
    else:
        print("Reading from stdin...\n")
        process_lines(sys.stdin, tracker=tracker, echo_other=not args.quiet_other)

    tracker.print_summary()
    if args.plot:
        if HAS_MATPLOTLIB:
            tracker.plot(args.plot_file)
        else:
            print('matplotlib is not installed, so no plot was generated.')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
