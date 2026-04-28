"""
Verification harness. Runs a compiled instruction stream as a unitary product
and compares against the target unitary (up to global phase).

The harness uses numpy to build the full 2^n x 2^n operator for the 3-qubit
register. For a small fixed n = 3 this is cheap; for larger n the user
should plug in a different verifier.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np

from . import gates
from .compile import CompileReport
from .validate import operator_distance, phase_equal

Instr = Tuple[str, int, Optional[int]]

N_QUBITS = 3
DIM = 1 << N_QUBITS


def _one_qubit_op_on_register(g: np.ndarray, target: int) -> np.ndarray:
    """
    Build the full 8x8 operator that applies `g` to qubit `target` and I on
    the other two qubits. We use the little-endian |q2 q1 q0> convention: the
    target qubit corresponds to bit `target` in the state index.
    """
    ops = [g if i == target else gates.I2 for i in range(N_QUBITS)]
    # Kronecker order must match our index convention. |q2 q1 q0>:
    #   state index = q2*4 + q1*2 + q0
    # So the Kronecker product is  ops[2] ⊗ ops[1] ⊗ ops[0].
    result = ops[N_QUBITS - 1]
    for i in range(N_QUBITS - 2, -1, -1):
        result = np.kron(result, ops[i])
    return result


def _cnot_on_register(target: int, control: int) -> np.ndarray:
    """Build the 8x8 CNOT(target, control) operator."""
    u = np.zeros((DIM, DIM), dtype=complex)
    for i in range(DIM):
        if (i >> control) & 1:
            j = i ^ (1 << target)
        else:
            j = i
        u[j, i] = 1.0
    return u


def _instr_to_operator(mnemonic: str, qa: int, qb: Optional[int]
                       ) -> np.ndarray:
    if mnemonic == 'CNOT':
        if qb is None:
            raise ValueError("CNOT requires qb")
        return _cnot_on_register(qa, qb)
    if mnemonic in {'H', 'X', 'Z', 'S', 'SDG', 'T', 'TDG', 'Y'}:
        g = gates.NATIVE_1Q[mnemonic] if mnemonic in gates.NATIVE_1Q else gates.Y
        return _one_qubit_op_on_register(g, qa)
    raise ValueError(f"Unknown mnemonic for verification: {mnemonic}")


def instr_sequence_to_matrix(seq: Sequence[Instr]) -> np.ndarray:
    """Multiply out an instruction sequence into its full register operator."""
    u = np.eye(DIM, dtype=complex)
    for mnemonic, qa, qb in seq:
        u = _instr_to_operator(mnemonic, qa, qb) @ u
    return u


def embed_one_qubit(target_1q: np.ndarray, qubit: int) -> np.ndarray:
    return _one_qubit_op_on_register(target_1q, qubit)


def embed_two_qubit(target_2q: np.ndarray, qa: int, qb: int) -> np.ndarray:
    """
    Embed a 4x4 2-qubit operator in the 8x8 register on (qa, qb) where qa is
    the "first" target of the 2-qubit gate's internal ordering and qb is the
    "second". We use the convention that the 4x4 matrix acts in the basis
    |qa=0 qb=0>, |qa=0 qb=1>, |qa=1 qb=0>, |qa=1 qb=1>.
    """
    if qa == qb:
        raise ValueError("embed_two_qubit requires distinct qubits")
    u = np.zeros((DIM, DIM), dtype=complex)
    for i in range(DIM):
        a = (i >> qa) & 1
        b = (i >> qb) & 1
        idx_in = a * 2 + b
        for out in range(4):
            coeff = target_2q[out, idx_in]
            if abs(coeff) < 1e-15:
                continue
            a_out = (out >> 1) & 1
            b_out = out & 1
            j = i
            if a != a_out:
                j ^= (1 << qa)
            if b != b_out:
                j ^= (1 << qb)
            u[j, i] += coeff
    return u


# --- Public verifier ---

@dataclass
class VerifyResult:
    passed: bool
    operator_distance: float
    target_matrix: np.ndarray
    synthesized_matrix: np.ndarray
    message: str = ""


def verify(report: CompileReport,
           target_matrix: np.ndarray,
           qubits: Sequence[int],
           *,
           epsilon: float = 1e-2) -> VerifyResult:
    """
    Numerically verify that the compiled sequence realizes the target matrix
    on the given qubits (up to global phase) within `epsilon`.
    """
    target_matrix = np.asarray(target_matrix, dtype=complex)
    if target_matrix.shape == (2, 2):
        target_full = embed_one_qubit(target_matrix, qubits[0])
    elif target_matrix.shape == (4, 4):
        target_full = embed_two_qubit(target_matrix, qubits[0], qubits[1])
    else:
        raise ValueError(f"Unsupported target matrix shape: {target_matrix.shape}")

    synth_full = instr_sequence_to_matrix(report.instructions)
    dist = operator_distance(target_full, synth_full)
    ok = dist <= epsilon
    msg = (f"PASS: operator distance {dist:.4g} <= {epsilon}"
           if ok else
           f"FAIL: operator distance {dist:.4g} > {epsilon}")
    return VerifyResult(passed=ok,
                        operator_distance=float(dist),
                        target_matrix=target_full,
                        synthesized_matrix=synth_full,
                        message=msg)
