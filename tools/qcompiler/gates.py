"""
Canonical 2x2 matrices for the native basis, plus helpers for parameterized
single-qubit rotations (Rx/Ry/Rz) and U3(theta, phi, lam).

All matrices are numpy complex128 2x2 arrays. Global phase is not tracked —
compare unitaries up to global phase when checking equivalence.

The native instruction basis understood by the FPGA is:
    H, X, Z, S, Sdg, T, Tdg, CNOT
Y is intentionally absent; the compiler decomposes it.
"""

from __future__ import annotations

import math
from typing import Dict

import numpy as np


# --- Native single-qubit matrices ---

I2 = np.eye(2, dtype=complex)

X = np.array([[0, 1],
              [1, 0]], dtype=complex)

Y = np.array([[0, -1j],
              [1j, 0]], dtype=complex)

Z = np.array([[1, 0],
              [0, -1]], dtype=complex)

H = (1 / math.sqrt(2)) * np.array([[1, 1],
                                    [1, -1]], dtype=complex)

S = np.array([[1, 0],
              [0, 1j]], dtype=complex)

Sdg = np.array([[1, 0],
                [0, -1j]], dtype=complex)

T = np.array([[1, 0],
              [0, (1 + 1j) / math.sqrt(2)]], dtype=complex)

Tdg = np.array([[1, 0],
                [0, (1 - 1j) / math.sqrt(2)]], dtype=complex)


# Native single-qubit gates as (mnemonic, matrix). The compiler uses this as the
# BFS alphabet for approximate synthesis.
NATIVE_1Q: Dict[str, np.ndarray] = {
    'H':   H,
    'X':   X,
    'Z':   Z,
    'S':   S,
    'SDG': Sdg,
    'T':   T,
    'TDG': Tdg,
}


def rx(theta: float) -> np.ndarray:
    """Rotation around X axis by angle theta."""
    c = math.cos(theta / 2)
    s = math.sin(theta / 2)
    return np.array([[c, -1j * s],
                     [-1j * s, c]], dtype=complex)


def ry(theta: float) -> np.ndarray:
    """Rotation around Y axis by angle theta."""
    c = math.cos(theta / 2)
    s = math.sin(theta / 2)
    return np.array([[c, -s],
                     [s, c]], dtype=complex)


def rz(theta: float) -> np.ndarray:
    """Rotation around Z axis by angle theta."""
    e_neg = np.exp(-1j * theta / 2)
    e_pos = np.exp(1j * theta / 2)
    return np.array([[e_neg, 0],
                     [0, e_pos]], dtype=complex)


def u3(theta: float, phi: float, lam: float) -> np.ndarray:
    """OpenQASM-style U3(theta, phi, lam)."""
    c = math.cos(theta / 2)
    s = math.sin(theta / 2)
    return np.array([
        [c, -np.exp(1j * lam) * s],
        [np.exp(1j * phi) * s, np.exp(1j * (phi + lam)) * c],
    ], dtype=complex)
