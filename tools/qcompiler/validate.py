"""
Validation utilities: unitarity checks, global-phase-invariant comparisons,
and operator distance metrics.

Everything that needs to treat two unitaries as "equal up to a global phase
factor e^{i*alpha}" goes through this module.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple

import numpy as np


# --- Errors ---

class NotUnitaryError(ValueError):
    """Raised when a matrix fails the unitarity check."""


class UnsupportedDimensionError(ValueError):
    """Raised when a matrix has an unsupported dimension."""


# --- Core checks ---

def is_unitary(matrix: np.ndarray, tol: float = 1e-9) -> bool:
    """Return True iff matrix is a square unitary within the given tolerance."""
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
        return False
    n = matrix.shape[0]
    prod = matrix.conj().T @ matrix
    return bool(np.allclose(prod, np.eye(n), atol=tol))


def require_unitary(matrix: np.ndarray, *, dims: Optional[Tuple[int, ...]] = None,
                    tol: float = 1e-9, name: str = 'matrix') -> np.ndarray:
    """
    Validate shape + unitarity, raising a clear error on failure.
    Returns the matrix cast to complex128.

    If `dims` is provided, the matrix dimension must be in that tuple.
    """
    arr = np.asarray(matrix, dtype=complex)
    if arr.ndim != 2 or arr.shape[0] != arr.shape[1]:
        raise UnsupportedDimensionError(
            f"{name}: expected a square 2D matrix, got shape {arr.shape}")
    n = arr.shape[0]
    if dims is not None and n not in dims:
        raise UnsupportedDimensionError(
            f"{name}: dimension {n} not supported (allowed: {dims})")
    prod = arr.conj().T @ arr
    if not np.allclose(prod, np.eye(n), atol=tol):
        max_err = float(np.max(np.abs(prod - np.eye(n))))
        raise NotUnitaryError(
            f"{name}: matrix is not unitary (max |U^dag U - I| = {max_err:.3g} > {tol:.1g})")
    return arr


# --- Global-phase handling ---

def strip_global_phase(u: np.ndarray) -> np.ndarray:
    """
    Return a unitary equivalent to u with the arbitrary global phase removed.
    We divide by the phase of the first nonzero entry so that the first nonzero
    entry becomes real and positive.
    """
    flat = u.flatten()
    for entry in flat:
        if abs(entry) > 1e-12:
            phase = entry / abs(entry)
            return u / phase
    return u


def phase_equal(a: np.ndarray, b: np.ndarray, tol: float = 1e-6) -> bool:
    """
    Test whether unitaries a and b are equivalent up to a global phase.

    Uses |tr(a^dag b)| / n == 1 (process fidelity distance zero).
    """
    if a.shape != b.shape:
        return False
    n = a.shape[0]
    fidelity = abs(np.trace(a.conj().T @ b)) / n
    return fidelity >= 1.0 - tol


# --- Distance metrics ---

def operator_distance(target: np.ndarray, approx: np.ndarray) -> float:
    """
    Global-phase invariant operator distance.
    Returns 1 - |tr(target^dag approx)| / n, in [0, 1].
    """
    n = target.shape[0]
    return float(1.0 - abs(np.trace(target.conj().T @ approx)) / n)


def frobenius_distance(target: np.ndarray, approx: np.ndarray) -> float:
    """
    Frobenius norm distance AFTER aligning global phase.
    """
    inner = np.trace(target.conj().T @ approx)
    if abs(inner) < 1e-12:
        return float(np.linalg.norm(target - approx, ord='fro'))
    phase = inner / abs(inner)
    aligned = approx / phase
    return float(np.linalg.norm(target - aligned, ord='fro'))
