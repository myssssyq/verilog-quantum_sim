"""
Peephole optimization passes for the compiled instruction stream.

Instructions at this stage are tuples of the form:
    (mnemonic, qa, qb)
where `qb is None` for 1-qubit gates. The passes preserve the full unitary
(up to global phase) and shorten or flatten the sequence.

Passes:
    remove_identity   - drop 'I' placeholders
    cancel_inverse    - T TDG, S SDG, H H, X X, Z Z, CNOT CNOT(same args)
    merge_phase       - S S -> Z, T T -> S (per qubit)
    merge_z_pairs     - Z Z -> identity (already covered by cancel_inverse)
    fuse_clifford_t   - very small BFS resynthesis of windows of length 4-6

The default pipeline runs cancel_inverse + merge_phase + remove_identity
until fixed point. fuse_clifford_t is opt-in (opt level >= 2) because it is
potentially costly.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

Instr = Tuple[str, int, Optional[int]]


def remove_identity(seq: Sequence[Instr]) -> List[Instr]:
    return [ins for ins in seq if ins[0] != 'I']


def cancel_inverse(seq: Sequence[Instr]) -> List[Instr]:
    """Cancel adjacent self-inverse or inverse-inverse pairs."""
    inverses = {
        'H': 'H', 'X': 'X', 'Z': 'Z',
        'S': 'SDG', 'SDG': 'S',
        'T': 'TDG', 'TDG': 'T',
    }
    out: List[Instr] = []
    for ins in seq:
        if out:
            prev = out[-1]
            if prev[0] == 'CNOT' and ins[0] == 'CNOT' and prev == ins:
                out.pop()
                continue
            inv = inverses.get(ins[0])
            if inv is not None and prev[0] == inv and prev[1] == ins[1] and prev[2] == ins[2]:
                out.pop()
                continue
        out.append(ins)
    return out


def merge_phase(seq: Sequence[Instr]) -> List[Instr]:
    """
    Fuse same-qubit phase gates: T T -> S, S S -> Z, Z Z -> I (drops),
    T T T T -> Z, S T -> ... (leave as-is; phase sums mod 2pi).

    We walk the sequence and maintain a running phase-count per qubit (in
    eighths of pi). Any non-phase gate flushes the accumulators into emitted
    instructions.
    """
    # Phase contribution per gate, measured in eighths of pi (mod 8):
    # T = 1, S = 2, Z = 4, SDG = 6, TDG = 7
    phase_values = {'T': 1, 'S': 2, 'Z': 4, 'SDG': 6, 'TDG': 7}
    value_to_gates = {
        0: [],
        1: ['T'],
        2: ['S'],
        3: ['S', 'T'],
        4: ['Z'],
        5: ['Z', 'T'],
        6: ['SDG'],
        7: ['TDG'],
    }

    out: List[Instr] = []
    acc: dict[int, int] = {}

    def flush(qubit: int) -> None:
        val = acc.pop(qubit, 0) & 7
        for g in value_to_gates[val]:
            out.append((g, qubit, None))

    for mnemonic, qa, qb in seq:
        if qb is None and mnemonic in phase_values:
            acc[qa] = (acc.get(qa, 0) + phase_values[mnemonic]) & 7
            continue
        # Non-phase gate on qa — flush qa first
        flush(qa)
        if qb is not None:
            # CNOT or similar — the operation doesn't commute through phase
            # gates on either qubit in general, so flush both.
            flush(qb)
        out.append((mnemonic, qa, qb))

    # Flush remaining accumulators
    for qubit in list(acc.keys()):
        flush(qubit)

    return out


def run_passes(seq: Sequence[Instr], *, level: int = 1) -> List[Instr]:
    """
    Top-level optimizer. Runs cancel_inverse + remove_identity at level >= 1;
    merge_phase at level >= 1; iterates until fixed point.

    level 0: no-op
    level 1: default (phase fusion, inverse cancellation, identity removal)
    level 2: reserved for future window-resynthesis (not wired up)
    """
    if level <= 0:
        return list(seq)
    prev = list(seq)
    while True:
        passes = remove_identity(prev)
        passes = merge_phase(passes)
        passes = cancel_inverse(passes)
        if passes == prev:
            return passes
        prev = passes
