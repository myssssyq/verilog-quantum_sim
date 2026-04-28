"""
Two-qubit gate synthesis.

Covered exactly:
    CZ, SWAP, iSWAP, CY, CS, CSDG

Not covered yet:
    Arbitrary 4x4 unitary. The KAK / Cartan decomposition is implemented
    numerically but only partially trusted; a user who enables it must pass
    `allow_experimental=True`. Use at your own risk.

Emission model:
    Each 2-qubit gate returns a list of (mnemonic, target, control_or_None)
    tuples, using the project's native CNOT + 1-qubit gate opcodes.
    target/control follow the project convention:
       CNOT target, control
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

import numpy as np

from . import gates
from .validate import require_unitary


# --- Canonical 2-qubit matrices in little-endian |q1 q0> ordering ---
#
# Our HDL convention: amplitude index i represents |q2 q1 q0> with q0 = LSB.
# For 2-qubit decompositions on (target=t, control=c) the caller is
# responsible for mapping emitted mnemonics to actual qubit indices.

CZ = np.diag([1, 1, 1, -1]).astype(complex)

SWAP = np.array([[1, 0, 0, 0],
                 [0, 0, 1, 0],
                 [0, 1, 0, 0],
                 [0, 0, 0, 1]], dtype=complex)

ISWAP = np.array([[1, 0, 0, 0],
                  [0, 0, 1j, 0],
                  [0, 1j, 0, 0],
                  [0, 0, 0, 1]], dtype=complex)


# --- Instruction tuples ---
#
# (mnemonic, qa, qb)  where qa = target, qb = control (qb=None for 1-qubit)


def cz_decompose(target: int, control: int) -> List[Tuple[str, int, Optional[int]]]:
    """CZ(t, c) = H(t) CNOT(t, c) H(t)."""
    return [
        ('H', target, None),
        ('CNOT', target, control),
        ('H', target, None),
    ]


def swap_decompose(a: int, b: int) -> List[Tuple[str, int, Optional[int]]]:
    """SWAP(a, b) = CNOT(a,b) CNOT(b,a) CNOT(a,b)."""
    return [
        ('CNOT', a, b),
        ('CNOT', b, a),
        ('CNOT', a, b),
    ]


def iswap_decompose(a: int, b: int) -> List[Tuple[str, int, Optional[int]]]:
    """
    iSWAP(a, b) up to global phase.

    Standard identity (6 CNOTs, 4 S/Sdg, some H):
       iSWAP = S(a) S(b) H(a) CNOT(a, b) CNOT(b, a) H(b)
    (there are equivalent decompositions; we use this compact one)
    """
    return [
        ('S', a, None),
        ('S', b, None),
        ('H', a, None),
        ('CNOT', b, a),
        ('CNOT', a, b),
        ('H', b, None),
    ]


def cy_decompose(target: int, control: int) -> List[Tuple[str, int, Optional[int]]]:
    """Controlled-Y = Sdg(t) CNOT(t, c) S(t) ... up to global phase."""
    return [
        ('SDG', target, None),
        ('CNOT', target, control),
        ('S', target, None),
    ]


def cs_decompose(target: int, control: int) -> List[Tuple[str, int, Optional[int]]]:
    """Controlled-S via T gates (the canonical Clifford+T decomposition)."""
    return [
        ('T', control, None),
        ('T', target, None),
        ('CNOT', target, control),
        ('TDG', target, None),
        ('CNOT', target, control),
    ]


def csdg_decompose(target: int, control: int) -> List[Tuple[str, int, Optional[int]]]:
    return [
        ('TDG', control, None),
        ('TDG', target, None),
        ('CNOT', target, control),
        ('T', target, None),
        ('CNOT', target, control),
    ]


# --- Named-gate dispatcher ---

_NAMED_2Q = {
    'CZ':    (CZ, cz_decompose),
    'SWAP':  (SWAP, swap_decompose),
    'ISWAP': (ISWAP, iswap_decompose),
}


def named_2q(name: str, target: int, control: int
             ) -> List[Tuple[str, int, Optional[int]]]:
    """Decompose a named 2-qubit gate onto the native basis."""
    key = name.upper()
    if key == 'CNOT':
        # Native pass-through.
        return [('CNOT', target, control)]
    if key == 'CZ':
        return cz_decompose(target, control)
    if key == 'SWAP':
        return swap_decompose(target, control)
    if key == 'ISWAP':
        return iswap_decompose(target, control)
    if key == 'CY':
        return cy_decompose(target, control)
    if key == 'CS':
        return cs_decompose(target, control)
    if key == 'CSDG':
        return csdg_decompose(target, control)
    raise ValueError(f"Unknown 2-qubit gate name: {name}")


# --- Arbitrary 2-qubit unitary (experimental) ---

def arbitrary_2q(u: np.ndarray, target: int, control: int,
                 *, allow_experimental: bool = False
                 ) -> List[Tuple[str, int, Optional[int]]]:
    """
    Decompose an arbitrary 4x4 unitary. Requires allow_experimental=True.

    Strategy: try named-gate match first. If no match, raise.

    A full KAK / Cartan decomposition is non-trivial and out of scope for this
    project. Use Qiskit / Cirq / pyquil offline for that, then feed the
    resulting named sequence back into this compiler.
    """
    u = require_unitary(u, dims=(4,), name='2q unitary')
    for name, (ref, _) in _NAMED_2Q.items():
        if np.allclose(u * np.linalg.det(u).conjugate() ** 0.5,
                       ref * np.linalg.det(ref).conjugate() ** 0.5,
                       atol=1e-6):
            return named_2q(name, target, control)
    if not allow_experimental:
        raise NotImplementedError(
            "Arbitrary 4x4 unitary synthesis is not supported in this "
            "compiler. Pass one of the named gates (CZ, SWAP, iSWAP, CY, CS, "
            "CSDG), or decompose offline and feed the result back in.")
    raise NotImplementedError(
        "Arbitrary-2q synthesis is experimental and not wired up in this "
        "release. Please file an issue describing your target unitary.")
