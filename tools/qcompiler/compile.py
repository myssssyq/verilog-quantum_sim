"""
Public API for the user-gate compiler.

Three entry points:

    compile_gate(name_or_matrix, qa, qb=None, **opts)
        Compile a single user-defined gate. Returns a list of native
        instructions plus a CompileReport with error metric and chosen path.

    compile_unitary(u, qubits, **opts)
        Compile an arbitrary 2x2 or 4x4 unitary applied to the given qubits.

    compile_circuit(circuit, **opts)
        Compile a list of user gates (as returned by the user's high-level
        description) into the final instruction sequence.

Options (all keyword-only):
    epsilon          - operator-distance tolerance (default 1e-2)
    max_depth        - BFS depth for single-qubit approximation (default 10)
    sk_depth         - Solovay-Kitaev recursion depth, 0 = disabled
    optimization_level - 0, 1, or 2
    seed             - deterministic seed for any randomized tie-breaking
                       (unused today, reserved)

All compiled outputs are in the native basis:
    H, X, Z, S, SDG, T, TDG, CNOT
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence, Tuple, Union

import numpy as np

from . import gates, synth1q, synth2q
from .classify import GateClass
from .emit import to_hex_words, to_qasm
from .optimize import run_passes
from .validate import (NotUnitaryError, UnsupportedDimensionError, operator_distance,
                       require_unitary)

Instr = Tuple[str, int, Optional[int]]


@dataclass
class CompileReport:
    instructions: List[Instr] = field(default_factory=list)
    operator_distance: float = 0.0
    path: Optional[GateClass] = None
    notes: List[str] = field(default_factory=list)

    @property
    def qasm(self) -> str:
        return to_qasm(self.instructions)

    @property
    def hex_words(self) -> List[int]:
        return to_hex_words(self.instructions)


# --- Single-gate compilation ---

def _resolve_input(name_or_matrix: Union[str, np.ndarray, Sequence]
                   ) -> Tuple[Optional[str], np.ndarray]:
    """Return (canonical_name_if_known, matrix). matrix is complex128."""
    if isinstance(name_or_matrix, str):
        name = name_or_matrix.upper()
        named_1q = {
            'I': gates.I2, 'X': gates.X, 'Y': gates.Y, 'Z': gates.Z,
            'H': gates.H, 'S': gates.S, 'SDG': gates.Sdg,
            'T': gates.T, 'TDG': gates.Tdg,
        }
        if name in named_1q:
            return name, named_1q[name]
        return name, None  # signals: 2-qubit named gate, let caller dispatch
    mat = np.asarray(name_or_matrix, dtype=complex)
    return None, mat


def compile_gate(name_or_matrix: Union[str, np.ndarray, Sequence],
                 qa: int,
                 qb: Optional[int] = None,
                 *,
                 epsilon: float = 1e-2,
                 max_depth: int = 10,
                 sk_depth: int = 0,
                 optimization_level: int = 1,
                 seed: Optional[int] = None) -> CompileReport:
    """
    Compile a single user-defined gate into the native instruction basis.

    name_or_matrix:
        - A string like 'H', 'Y', 'CZ', 'SWAP', 'CY' — resolved to canonical.
        - A 2x2 or 4x4 unitary matrix.
    qa, qb:
        Qubit indices. For 1-qubit gates pass qa only. For 2-qubit gates pass
        both qa (target) and qb (control/partner).
    """
    name, matrix = _resolve_input(name_or_matrix)

    # --- 2-qubit named gates resolved by name ---
    if matrix is None:
        if qb is None:
            raise ValueError(f"{name} looks like a 2-qubit gate but qb is None")
        instrs = synth2q.named_2q(name, qa, qb)
        optimized = run_passes(instrs, level=optimization_level)
        return CompileReport(instructions=optimized,
                             operator_distance=0.0,
                             path=GateClass.NATIVE,
                             notes=[f"2q named gate {name}"])

    matrix = require_unitary(matrix, dims=(2, 4), name='user gate')

    # --- 2-qubit matrix ---
    if matrix.shape == (4, 4):
        if qb is None:
            raise ValueError("4x4 unitary requires both qa and qb")
        # Named gate check first
        for named in ('CZ', 'SWAP', 'ISWAP'):
            report = _try_named_4x4(named, matrix, qa, qb, optimization_level)
            if report is not None:
                return report
        # Experimental arbitrary path
        instrs = synth2q.arbitrary_2q(matrix, qa, qb,
                                       allow_experimental=False)
        optimized = run_passes(instrs, level=optimization_level)
        return CompileReport(instructions=optimized,
                             path=GateClass.NATIVE,
                             notes=["matched 2-qubit named gate"])

    # --- 1-qubit matrix ---
    result = synth1q.synth_1q(matrix,
                               epsilon=epsilon,
                               max_depth=max_depth,
                               sk_depth=sk_depth)
    instrs: List[Instr] = [(g, qa, None) for g in result.word]
    optimized = run_passes(instrs, level=optimization_level)
    notes = []
    if result.operator_distance > epsilon:
        notes.append(
            f"WARNING: best approximation is {result.operator_distance:.4g} > "
            f"epsilon {epsilon}. Try raising max_depth or sk_depth.")
    return CompileReport(instructions=optimized,
                         operator_distance=result.operator_distance,
                         path=result.path,
                         notes=notes)


def _try_named_4x4(named: str, matrix: np.ndarray, qa: int, qb: int,
                   opt_level: int) -> Optional[CompileReport]:
    ref_matrix = {
        'CZ': synth2q.CZ, 'SWAP': synth2q.SWAP, 'ISWAP': synth2q.ISWAP,
    }[named]
    # Equivalence up to global phase
    trace = np.trace(ref_matrix.conj().T @ matrix) / 4.0
    if abs(abs(trace) - 1.0) < 1e-6:
        instrs = synth2q.named_2q(named, qa, qb)
        optimized = run_passes(instrs, level=opt_level)
        return CompileReport(instructions=optimized,
                             operator_distance=0.0,
                             path=GateClass.NATIVE,
                             notes=[f"matched 2-qubit named gate {named}"])
    return None


# --- Unitary helpers ---

def compile_unitary(u: np.ndarray, qubits: Sequence[int], **opts: Any
                    ) -> CompileReport:
    """Convenience wrapper for compile_gate with a matrix input."""
    u = np.asarray(u)
    if len(qubits) == 1:
        return compile_gate(u, qubits[0], **opts)
    if len(qubits) == 2:
        return compile_gate(u, qubits[0], qubits[1], **opts)
    raise UnsupportedDimensionError(
        f"compile_unitary currently supports 1 or 2 qubits, got {len(qubits)}")


# --- Circuit compilation ---

def compile_circuit(circuit: Sequence[Tuple[Any, ...]], **opts: Any
                    ) -> CompileReport:
    """
    Compile a whole list of gates. Each entry is a tuple:
        (name_or_matrix, qa)           - 1-qubit gate
        (name_or_matrix, qa, qb)       - 2-qubit gate
    """
    merged: List[Instr] = []
    per_gate_dist: List[float] = []
    notes: List[str] = []
    for entry in circuit:
        if len(entry) == 2:
            name, qa = entry
            report = compile_gate(name, qa, **opts)
        elif len(entry) == 3:
            name, qa, qb = entry
            report = compile_gate(name, qa, qb, **opts)
        else:
            raise ValueError(f"Bad circuit entry (expected 2 or 3 items): {entry}")
        merged.extend(report.instructions)
        per_gate_dist.append(report.operator_distance)
        notes.extend(report.notes)
    merged = run_passes(merged, level=opts.get('optimization_level', 1))
    return CompileReport(instructions=merged,
                         operator_distance=max(per_gate_dist) if per_gate_dist else 0.0,
                         path=None,
                         notes=notes)
