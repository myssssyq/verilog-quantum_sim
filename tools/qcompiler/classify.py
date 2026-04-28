"""
Classify an arbitrary 2x2 unitary into one of:
    NATIVE   - already in NATIVE_1Q up to global phase (just emit the mnemonic)
    CLIFFORD - lies in the 24-element single-qubit Clifford group (use a short
               exact table)
    CLIFFORD_T_EXACT - expressible as a finite word over {H, S, T} (attempted
               by BFS first, falls back to APPROX if not)
    APPROX   - needs approximate synthesis via ZYZ + Rz approximator

Classification is conservative: when unsure, we downgrade to APPROX and let the
synthesis layer find a sequence.
"""

from __future__ import annotations

import enum
from typing import Dict, Optional, Tuple

import numpy as np

from . import gates
from .validate import phase_equal


class GateClass(enum.Enum):
    NATIVE = 'native'
    CLIFFORD = 'clifford'
    CLIFFORD_T_EXACT = 'clifford_t_exact'
    APPROX = 'approx'


def match_native(matrix: np.ndarray, tol: float = 1e-6) -> Optional[str]:
    """Return mnemonic if matrix equals a native gate up to global phase, else None."""
    for name, mat in gates.NATIVE_1Q.items():
        if phase_equal(matrix, mat, tol=tol):
            return name
    # I is not in the native dict — empty sequence
    if phase_equal(matrix, gates.I2, tol=tol):
        return 'I'
    return None


# --- 24-element single-qubit Clifford group, indexed by a short gate word ---
#
# We enumerate Clifford group once at import time: all words over {H, S} up to
# a length where the orbit saturates (24 elements). Each orbit member is stored
# with its shortest canonical word.
_CLIFFORD_TABLE: Dict[bytes, Tuple[str, ...]] = {}


def _canonical_key(u: np.ndarray) -> bytes:
    """
    Build a stable, global-phase-invariant hash key for a 2x2 unitary.

    Steps:
      1. Find the first entry (row-major) whose magnitude is clearly nonzero.
      2. Rotate the whole matrix so that that entry is real and positive.
         This cancels any global phase.
      3. Snap entries that are numerically close to 0 to exactly 0, and quantize
         remaining real/imag parts to a coarse 4-decimal grid. This is coarse
         enough to absorb the ~1e-7 drift that accumulates across repeated
         matrix products in the Clifford BFS, yet fine enough that distinct
         Clifford elements (which differ by >= 1/sqrt(2) - 1/2 ~ 0.2 in at
         least one entry) never collide.
    """
    tol = 1e-9
    flat = u.flatten()
    pivot = None
    for entry in flat:
        if abs(entry) > 1e-6:
            pivot = entry
            break

    if pivot is None:
        normed = u
    else:
        normed = u * (np.conjugate(pivot) / abs(pivot))

    # Snap tiny components to 0, then quantize to a coarse grid.
    snapped = np.where(np.abs(normed.real) < tol, 0.0, normed.real) + \
              1j * np.where(np.abs(normed.imag) < tol, 0.0, normed.imag)
    quantized = np.round(snapped, 4)
    return quantized.tobytes()


def _build_clifford_table() -> None:
    """BFS over {H, S, X, Z, Sdg, Y-via-ZX} until the 24-element group is reached."""
    frontier = [((), gates.I2)]
    seen: Dict[bytes, Tuple[str, ...]] = {_canonical_key(gates.I2): ()}
    alphabet = [('H', gates.H), ('S', gates.S), ('X', gates.X),
                ('Z', gates.Z), ('SDG', gates.Sdg)]
    while frontier and len(seen) < 24:
        new_frontier = []
        for word, u in frontier:
            for name, g in alphabet:
                nu = g @ u
                key = _canonical_key(nu)
                if key not in seen:
                    new_word = word + (name,)
                    seen[key] = new_word
                    new_frontier.append((new_word, nu))
        frontier = new_frontier
    _CLIFFORD_TABLE.update(seen)


_build_clifford_table()


def match_clifford(matrix: np.ndarray) -> Optional[Tuple[str, ...]]:
    """If matrix lies in the single-qubit Clifford group, return its word."""
    key = _canonical_key(matrix)
    return _CLIFFORD_TABLE.get(key)


def classify(matrix: np.ndarray, tol: float = 1e-6) -> GateClass:
    """Pick the cheapest synthesis path for this 2x2 unitary."""
    if match_native(matrix, tol=tol) is not None:
        return GateClass.NATIVE
    if match_clifford(matrix) is not None:
        return GateClass.CLIFFORD
    # We do not attempt an exact Clifford+T decision here — the BFS in synth1q
    # will settle it. Return APPROX so the pipeline enters that path.
    return GateClass.APPROX
