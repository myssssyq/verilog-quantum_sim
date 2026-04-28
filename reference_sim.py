#!/usr/bin/env python3
"""
Reference 3-qubit quantum circuit simulator in Python.

This script is meant to validate the FPGA implementation from the repo.
It supports both:
  * floating-point simulation for easy inspection
  * fixed-point Q2.14 emulation that mirrors the HDL closely

It can also emit UART-compatible output so it can be piped directly into
uart_host.py.
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from typing import Iterable, List, Optional, Sequence

import numpy as np

# Q2.14 constants
Q14_ONE = 16384       # 1.0 in Q2.14
Q14_INV_SQRT2 = 11585 # 1/sqrt(2) in Q2.14


def clamp_i16(val: int) -> int:
    """Clamp an integer to the signed 16-bit range."""
    if val > 32767:
        return 32767
    if val < -32768:
        return -32768
    return val


def q14_mul(a: int, b: int) -> int:
    """Multiply two Q2.14 values, return Q2.14 result (HDL-style truncation)."""
    return clamp_i16((a * b) >> 14)


def q13_scale_i16(a: int, factor_q13: int) -> int:
    """Scale a signed Q2.14 value by an unsigned Q3.13 factor."""
    return clamp_i16((a * factor_q13) >> 13)


def to_q14(f: float) -> int:
    """Convert float to Q2.14."""
    return clamp_i16(int(round(f * 16384)))


def from_q14(q: int) -> float:
    """Convert Q2.14 to float."""
    return q / 16384.0


def renorm_factor_q13_from_q28(p_keep_q28: int) -> int:
    """Mirror the HDL measurement renormalization LUT exactly."""
    if p_keep_q28 & (1 << 28):
        return 8192  # 1.0 in Q3.13

    idx = (p_keep_q28 >> 23) & 0x1F
    lut = {
        0: 23170, 1: 23170, 2: 23170, 3: 23170,
        4: 23170, 5: 20730, 6: 18919, 7: 17519,
        8: 16384, 9: 15444, 10: 14654, 11: 13973,
        12: 13378, 13: 12856, 14: 12386, 15: 11970,
        16: 11585, 17: 11246, 18: 10923, 19: 10631,
        20: 10362, 21: 10113, 22: 9880, 23: 9663,
        24: 9459, 25: 9270, 26: 9089, 27: 8924,
        28: 8757, 29: 8611, 30: 8460, 31: 8321,
    }
    return lut.get(idx, 8192)


def fmt_q14_hex(val: int) -> str:
    """Format a signed 16-bit value as HDL/UART style ±XXXX."""
    sign = '+' if val >= 0 else '-'
    return f"{sign}{abs(val) & 0xFFFF:04X}"


class QuantumSim:
    """3-qubit quantum simulator with both float and Q2.14 modes."""

    def __init__(self, fixed_point: bool = False, rng: Optional[random.Random] = None, *, hdl_measure_lut: bool = False):
        self.fixed_point = fixed_point
        self.rng = rng or random.Random()
        self.hdl_measure_lut = hdl_measure_lut
        self.measurements: List[tuple[int, int]] = []
        self.reset()

    def reset(self) -> None:
        self.measurements.clear()
        if self.fixed_point:
            self.state = [(Q14_ONE, 0)] + [(0, 0)] * 7  # (re, im) pairs
        else:
            self.state = np.zeros(8, dtype=complex)
            self.state[0] = 1.0

    def init_basis(self, basis: int) -> None:
        if not (0 <= basis <= 7):
            raise ValueError(f"Basis state must be 0..7, got {basis}")
        self.measurements.clear()
        if self.fixed_point:
            self.state = [(0, 0)] * 8
            self.state[basis] = (Q14_ONE, 0)
        else:
            self.state = np.zeros(8, dtype=complex)
            self.state[basis] = 1.0

    @staticmethod
    def _pairs(q: int) -> list[tuple[int, int]]:
        """Generate (idx0, idx1) pairs for qubit q."""
        if q not in (0, 1, 2):
            raise ValueError(f"Qubit must be 0, 1, or 2 (got {q})")
        pairs: list[tuple[int, int]] = []
        for k in range(4):
            if q == 0:
                idx0 = ((k >> 1) << 2) | ((k & 1) << 1)
            elif q == 1:
                idx0 = ((k >> 1) << 2) | (k & 1)
            else:
                idx0 = ((k >> 1) << 1) | (k & 1)
            idx1 = idx0 | (1 << q)
            pairs.append((idx0, idx1))
        return pairs

    def x_gate(self, q: int) -> None:
        for i0, i1 in self._pairs(q):
            self.state[i0], self.state[i1] = self.state[i1], self.state[i0]

    def z_gate(self, q: int) -> None:
        for _, i1 in self._pairs(q):
            if self.fixed_point:
                re, im = self.state[i1]
                self.state[i1] = (-re, -im)
            else:
                self.state[i1] = -self.state[i1]

    def h_gate(self, q: int) -> None:
        for i0, i1 in self._pairs(q):
            if self.fixed_point:
                a_re, a_im = self.state[i0]
                b_re, b_im = self.state[i1]
                sum_re = a_re + b_re
                sum_im = a_im + b_im
                diff_re = a_re - b_re
                diff_im = a_im - b_im
                self.state[i0] = (q14_mul(sum_re, Q14_INV_SQRT2), q14_mul(sum_im, Q14_INV_SQRT2))
                self.state[i1] = (q14_mul(diff_re, Q14_INV_SQRT2), q14_mul(diff_im, Q14_INV_SQRT2))
            else:
                a = self.state[i0]
                b = self.state[i1]
                self.state[i0] = (a + b) / math.sqrt(2.0)
                self.state[i1] = (a - b) / math.sqrt(2.0)

    def cnot_gate(self, target: int, control: int) -> None:
        if target == control:
            raise ValueError("CNOT target and control must be different")
        for i0, i1 in self._pairs(target):
            if i0 & (1 << control):
                self.state[i0], self.state[i1] = self.state[i1], self.state[i0]

    def _phase_gate(self, q: int, phase_re: float, phase_im: float) -> None:
        """Apply diag(1, phase) on qubit q. Only touches amplitudes with bit q = 1."""
        if self.fixed_point:
            p_re = to_q14(phase_re)
            p_im = to_q14(phase_im)
            for _, i1 in self._pairs(q):
                re, im = self.state[i1]
                new_re = q14_mul(re, p_re) - q14_mul(im, p_im)
                new_im = q14_mul(re, p_im) + q14_mul(im, p_re)
                self.state[i1] = (new_re, new_im)
        else:
            phase = complex(phase_re, phase_im)
            for _, i1 in self._pairs(q):
                self.state[i1] *= phase

    def s_gate(self, q: int) -> None:
        self._phase_gate(q, 0.0, 1.0)

    def sdg_gate(self, q: int) -> None:
        self._phase_gate(q, 0.0, -1.0)

    def t_gate(self, q: int) -> None:
        inv_sqrt2 = 1.0 / math.sqrt(2.0)
        self._phase_gate(q, inv_sqrt2, inv_sqrt2)

    def tdg_gate(self, q: int) -> None:
        inv_sqrt2 = 1.0 / math.sqrt(2.0)
        self._phase_gate(q, inv_sqrt2, -inv_sqrt2)

    def _measure_fixed(self, q: int, random_val: Optional[float]) -> int:
        prob0 = 0
        prob1 = 0
        for i, (re, im) in enumerate(self.state):
            amp_sq = re * re + im * im  # Q4.28
            if i & (1 << q):
                prob1 += amp_sq
            else:
                prob0 += amp_sq

        if random_val is None:
            random_val = self.rng.random()
        threshold = int(random_val * (1 << 28))
        result = 0 if threshold < prob0 else 1
        p_keep = prob0 if result == 0 else prob1

        if p_keep == 0:
            # Defensive fallback for inconsistent or degenerate states.
            self.state = [(0, 0)] * 8
            return result

        if self.hdl_measure_lut:
            factor_q13 = renorm_factor_q13_from_q28(p_keep)
        else:
            p_keep_float = p_keep / float(1 << 28)
            factor_q13 = int(round((1.0 / math.sqrt(p_keep_float)) * (1 << 13)))

        new_state: list[tuple[int, int]] = []
        for i, (re, im) in enumerate(self.state):
            if ((i >> q) & 1) != result:
                new_state.append((0, 0))
            else:
                new_state.append((q13_scale_i16(re, factor_q13), q13_scale_i16(im, factor_q13)))
        self.state = new_state
        return result

    def _measure_float(self, q: int, random_val: Optional[float]) -> int:
        prob0 = float(sum(abs(self.state[i]) ** 2 for i in range(8) if not (i & (1 << q))))
        if random_val is None:
            random_val = self.rng.random()
        result = 0 if random_val < prob0 else 1

        mask = np.array([0 if ((i >> q) & 1) == result else 1 for i in range(8)], dtype=bool)
        self.state[mask] = 0.0
        norm = float(np.linalg.norm(self.state))
        if norm > 0.0:
            self.state /= norm
        return result

    def measure(self, q: int, random_val: Optional[float] = None) -> int:
        """Measure qubit q, collapse the state, and renormalize survivors."""
        if self.fixed_point:
            result = self._measure_fixed(q, random_val)
        else:
            result = self._measure_float(q, random_val)
        self.measurements.append((q, result))
        return result

    def dump_state(self, uart_compatible: bool = False, out: Optional[object] = None) -> None:
        """Print the current state vector."""
        out = out or sys.stdout
        if uart_compatible and self.fixed_point:
            for i, (re, im) in enumerate(self.state):
                bits = f"|{(i >> 2) & 1}{(i >> 1) & 1}{i & 1}>"
                print(f"{bits} {fmt_q14_hex(re)} {fmt_q14_hex(im)}i", file=out)
            return

        print("State vector:", file=out)
        for i in range(8):
            bits = f"|{(i >> 2) & 1}{(i >> 1) & 1}{i & 1}>"
            if self.fixed_point:
                re, im = self.state[i]
                print(
                    f"  {bits} = {re:+6d} {im:+6d}i  "
                    f"({from_q14(re):+.5f} {from_q14(im):+.5f}i)",
                    file=out,
                )
            else:
                amp = self.state[i]
                print(f"  {bits} = {amp.real:+.6f} {amp.imag:+.6f}i", file=out)


def run_program(
    program: Sequence[int],
    *,
    fixed_point: bool = False,
    verbose: bool = True,
    uart_compatible: bool = False,
    rng_seed: Optional[int] = None,
    hdl_measure_lut: bool = False,
) -> QuantumSim:
    """Execute a list of 16-bit instructions."""
    rng = random.Random(rng_seed)
    sim = QuantumSim(fixed_point=fixed_point, rng=rng, hdl_measure_lut=hdl_measure_lut)

    opcodes = {
        0x0: 'NOP', 0x1: 'RESET', 0x2: 'H', 0x3: 'X', 0x4: 'Z',
        0x5: 'CNOT', 0x6: 'MEASURE', 0x7: 'DUMPSTATE', 0x8: 'INITBASIS',
        0x9: 'SHOTS', 0xA: 'RUNSHOTS',
        0xB: 'T', 0xC: 'TDG', 0xD: 'S', 0xE: 'SDG',
        0xF: 'HALT'
    }

    shot_count = 1
    shot_start_pc: Optional[int] = None
    shot_remain = 0

    pc = 0
    while pc < len(program):
        word = program[pc]
        opcode = (word >> 12) & 0xF
        qa = (word >> 10) & 0x3
        qb = (word >> 8) & 0x3
        imm = word & 0xFF
        name = opcodes.get(opcode, '???')

        if verbose:
            print(f"  PC={pc:3d}: {name}", end="")
            if name in ('H', 'X', 'Z', 'MEASURE', 'T', 'TDG', 'S', 'SDG'):
                print(f" {qa}", end="")
            elif name == 'CNOT':
                print(f" {qa},{qb}", end="")
            elif name in ('INITBASIS', 'SHOTS'):
                print(f" {imm}", end="")
            print()

        if opcode == 0x1:
            sim.reset()
        elif opcode == 0x2:
            sim.h_gate(qa)
        elif opcode == 0x3:
            sim.x_gate(qa)
        elif opcode == 0x4:
            sim.z_gate(qa)
        elif opcode == 0x5:
            sim.cnot_gate(qa, qb)
        elif opcode == 0x6:
            result = sim.measure(qa)
            if uart_compatible and fixed_point:
                print(f"M({qa})={result}")
            elif verbose:
                print(f"         M({qa})={result}")
        elif opcode == 0x7:
            sim.dump_state(uart_compatible=uart_compatible)
        elif opcode == 0x8:
            sim.init_basis(imm & 0x7)
        elif opcode == 0x9:
            shot_count = imm
        elif opcode == 0xA:
            shot_start_pc = pc + 1
            shot_remain = shot_count
            pc = shot_start_pc
            continue
        elif opcode == 0xB:
            sim.t_gate(qa)
        elif opcode == 0xC:
            sim.tdg_gate(qa)
        elif opcode == 0xD:
            sim.s_gate(qa)
        elif opcode == 0xE:
            sim.sdg_gate(qa)
        elif opcode == 0xF:
            if shot_start_pc is not None and shot_remain > 1:
                shot_remain -= 1
                pc = shot_start_pc
                continue
            if verbose:
                print("  --- HALT ---")
            break

        pc += 1

    return sim


def load_hex(filename: str) -> list[int]:
    """Load program.hex into a list of 16-bit words."""
    words: list[int] = []
    with open(filename, 'r', encoding='utf-8') as f:
        for line_num, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            try:
                words.append(int(line, 16))
            except ValueError as exc:
                raise ValueError(f"Invalid hex word on line {line_num}: {raw.rstrip()}") from exc
    return words


def _built_in_programs() -> Iterable[tuple[str, list[int]]]:
    yield "Bell state (H q0, CNOT q1,q0)", [0x1000, 0x2000, 0x5400, 0x7000, 0xF000]
    yield "GHZ state (H q0, CNOT q1,q0, CNOT q2,q0)", [0x1000, 0x2000, 0x5400, 0x5800, 0x7000, 0xF000]
    yield "X gate (|000> -> |001>)", [0x1000, 0x3000, 0x7000, 0xF000]
    yield "Z identity (H q0, Z q0, H q0 = X q0)", [0x1000, 0x2000, 0x4000, 0x2000, 0x7000, 0xF000]


def main() -> int:
    parser = argparse.ArgumentParser(description='Reference simulator for the 3-qubit FPGA project')
    parser.add_argument('hexfile', nargs='?', help='Input program.hex file')
    parser.add_argument('--mode', choices=['float', 'fixed', 'both'], default='both', help='Simulation mode')
    parser.add_argument('--seed', type=int, default=None, help='Seed for measurement RNG')
    parser.add_argument('--quiet', action='store_true', help='Suppress PC trace')
    parser.add_argument('--uart', action='store_true', help='Emit UART-compatible raw lines (fixed mode only)')
    parser.add_argument('--hdl-measure-lut', action='store_true', help='Use the HDL measurement renormalization LUT instead of mathematically exact fixed-point renormalization')
    args = parser.parse_args()

    if args.uart and args.mode != 'fixed':
        parser.error('--uart requires --mode fixed')

    print("=== Quantum Simulator Reference (Python) ===\n")

    if args.hexfile:
        program = load_hex(args.hexfile)
        print(f"Loaded {len(program)} instructions from {args.hexfile}\n")

        modes = ['float', 'fixed'] if args.mode == 'both' else [args.mode]
        for idx, mode in enumerate(modes):
            if idx:
                print()
            if not args.uart:
                print(f"--- {mode.capitalize()} mode ---")
            run_program(
                program,
                fixed_point=(mode == 'fixed'),
                verbose=not args.quiet and not args.uart,
                uart_compatible=args.uart,
                rng_seed=args.seed,
                hdl_measure_lut=args.hdl_measure_lut,
            )
        return 0

    for idx, (title, program) in enumerate(_built_in_programs(), start=1):
        if idx > 1:
            print("\n" + "=" * 50 + "\n")
        print(f"Test {idx}: {title}")
        modes = ['float', 'fixed'] if args.mode == 'both' else [args.mode]
        for mode in modes:
            print(f"\n--- {mode.capitalize()} ---")
            run_program(
                program,
                fixed_point=(mode == 'fixed'),
                verbose=not args.quiet,
                uart_compatible=False,
                rng_seed=args.seed,
                hdl_measure_lut=args.hdl_measure_lut,
            )

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
