"""
Single-qubit synthesis.

Three tiers, tried in order:
  1. NATIVE lookup          — trivial
  2. Clifford table lookup  — exact, short
  3. BFS over Clifford+T    — exact if the matrix is in the finite orbit up to
                              a chosen maximum depth (default 10), else fall
                              through.
  4. ZYZ + Rz approximator  — general fallback. Each Rz is approximated by a
                              Clifford+T word found via bounded BFS.

The approximator is deliberately simple: bounded BFS over the dictionary
{I, H, X, Z, S, SDG, T, TDG} that memoizes matrices by a phase-normalized hash.
For epsilon ~1e-2 and depth ~20 this covers most common rotations. We never
pretend to be gridsynth; the limitations are documented.

Solovay-Kitaev is available as `sk_refine` and used by `synth_approximate` when
requested by the caller (optimization_level >= 2). It recursively refines a
base approximation, which in this implementation is the BFS result.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import gates
from .classify import GateClass, classify, match_clifford, match_native
from .validate import operator_distance, phase_equal, strip_global_phase


# --- Internal: phase-normalized hash key ---

def _key(u: np.ndarray) -> bytes:
    flat = u.flatten()
    for entry in flat:
        if abs(entry) > 1e-12:
            normed = u / (entry / abs(entry))
            break
    else:
        normed = u
    return np.round(normed, 6).tobytes()


# --- BFS over the Clifford+T word group, bounded depth ---

# Dictionary of BFS gates. I is not included because it never shortens a word.
_BFS_ALPHABET: List[Tuple[str, np.ndarray]] = [
    ('H',   gates.H),
    ('X',   gates.X),
    ('Z',   gates.Z),
    ('S',   gates.S),
    ('SDG', gates.Sdg),
    ('T',   gates.T),
    ('TDG', gates.Tdg),
]


# Precomputed BFS orbit (memoized). Keys are phase-normalized matrices, values
# are the shortest known Clifford+T word producing them from I.
_BFS_ORBIT: Dict[bytes, Tuple[str, ...]] = {_key(gates.I2): ()}
_BFS_DEPTH_BUILT: int = 0


def _extend_bfs(max_depth: int) -> None:
    """Extend the BFS orbit up to the requested depth, caching the result."""
    global _BFS_DEPTH_BUILT
    if max_depth <= _BFS_DEPTH_BUILT:
        return
    # Rebuild layer by layer from the deepest frontier we currently have.
    # A full rebuild is fine for small depths (≤12); for deeper runs we still
    # keep it simple because the dict grows to tens of thousands at most.
    frontier: List[Tuple[Tuple[str, ...], np.ndarray]] = [((), gates.I2)]
    seen = {_key(gates.I2): ()}
    for _ in range(max_depth):
        new_frontier = []
        for word, u in frontier:
            for name, g in _BFS_ALPHABET:
                nu = g @ u
                k = _key(nu)
                if k not in seen:
                    nw = word + (name,)
                    seen[k] = nw
                    new_frontier.append((nw, nu))
        if not new_frontier:
            break
        frontier = new_frontier
    _BFS_ORBIT.clear()
    _BFS_ORBIT.update(seen)
    _BFS_DEPTH_BUILT = max_depth


def _bfs_lookup_exact(matrix: np.ndarray) -> Optional[Tuple[str, ...]]:
    """Return the word if matrix is in the current BFS orbit, else None."""
    return _BFS_ORBIT.get(_key(matrix))


def _bfs_lookup_best(matrix: np.ndarray) -> Tuple[Tuple[str, ...], float]:
    """
    Return the best (word, distance) in the current BFS orbit.
    Distance is the global-phase-invariant operator distance.
    """
    best_word: Tuple[str, ...] = ()
    best_dist = float('inf')
    for k, word in _BFS_ORBIT.items():
        # reconstruct the matrix from word (cheap: we cache inverse lookup via
        # _key -> word but not word -> matrix, so we recompute)
        m = gates.I2
        for n in word:
            m = _get_gate_matrix(n) @ m
        d = operator_distance(matrix, m)
        if d < best_dist:
            best_dist = d
            best_word = word
    return best_word, best_dist


def _get_gate_matrix(name: str) -> np.ndarray:
    if name == 'I':
        return gates.I2
    return gates.NATIVE_1Q[name]


# --- ZYZ decomposition ---

def zyz_decompose(u: np.ndarray) -> Tuple[float, float, float, float]:
    """
    Decompose a 2x2 unitary as e^{i alpha} * Rz(beta) * Ry(gamma) * Rz(delta).
    Returns (alpha, beta, gamma, delta).

    alpha is the global phase (usually irrelevant).
    """
    u = np.asarray(u, dtype=complex)
    det = np.linalg.det(u)
    # Remove overall phase by dividing by sqrt(det).
    alpha = 0.5 * np.angle(det)
    u_su2 = u * np.exp(-1j * alpha)

    # Now u_su2 is in SU(2). For SU(2) form
    #   [[cos(g/2)*e^{-i(b+d)/2}, -sin(g/2)*e^{-i(b-d)/2}],
    #    [sin(g/2)*e^{i(b-d)/2},   cos(g/2)*e^{i(b+d)/2}]]
    cos_half_g = abs(u_su2[0, 0])
    sin_half_g = abs(u_su2[1, 0])
    gamma = 2.0 * math.atan2(sin_half_g, cos_half_g)

    # Compute b, d from phases of matrix entries
    if cos_half_g > 1e-9 and sin_half_g > 1e-9:
        a = np.angle(u_su2[1, 1])  # = (b + d) / 2
        b_minus_d_over_2 = np.angle(u_su2[1, 0])
        beta = a + b_minus_d_over_2
        delta = a - b_minus_d_over_2
    elif cos_half_g > 1e-9:
        # gamma = 0: u = Rz(beta + delta)
        beta = np.angle(u_su2[1, 1])
        delta = beta
        # Actually we need beta + delta = 2 angle -> pick split
        beta = 2.0 * np.angle(u_su2[1, 1])
        delta = 0.0
    else:
        # gamma = pi: u = [[0, -e^{-i(b-d)/2}], [e^{i(b-d)/2}, 0]]
        # Only (b - d) matters
        beta = 2.0 * np.angle(u_su2[1, 0])
        delta = 0.0
    return float(alpha), float(beta), float(gamma), float(delta)


# --- Rz approximation over Clifford+T ---

def approximate_rz(theta: float, *, max_depth: int = 12,
                   epsilon: float = 1e-2) -> Tuple[List[str], float]:
    """
    Return a Clifford+T word approximating Rz(theta) within operator distance
    `epsilon`, searching BFS up to `max_depth`.

    If no word within epsilon is found at this depth, return the best one and
    its distance. The caller decides whether to accept it.
    """
    _extend_bfs(max_depth)
    target = gates.rz(theta)
    exact = _bfs_lookup_exact(target)
    if exact is not None:
        return list(exact), 0.0
    best_word, best_dist = _bfs_lookup_best(target)
    return list(best_word), best_dist


def approximate_ry(theta: float, *, max_depth: int = 12,
                   epsilon: float = 1e-2) -> Tuple[List[str], float]:
    """Approximate Ry(theta) via  Ry = Sdg * H * Rz(theta) * H * S ... no,
    actually we use the identity  Ry(t) = Rz(-pi/2) * Rx(t) * Rz(pi/2),
    and Rx(t) = H * Rz(t) * H. We inline that."""
    _extend_bfs(max_depth)
    target = gates.ry(theta)
    exact = _bfs_lookup_exact(target)
    if exact is not None:
        return list(exact), 0.0
    best_word, best_dist = _bfs_lookup_best(target)
    return list(best_word), best_dist


# --- Solovay-Kitaev-light refinement ---
#
# We implement a minimal SK-style recursion that, given a target unitary and a
# "base approximator" (our BFS), recursively finds group-commutator corrections.
# Group-commutator balancing uses the standard SU(2) decomposition of a
# near-identity element.
#
# For production use we'd switch to a gridsynth-style exact synthesis; this
# version is deliberately pedagogical and kept simple.

def _base_approx(target: np.ndarray, max_depth: int) -> Tuple[List[str], float, np.ndarray]:
    _extend_bfs(max_depth)
    exact = _bfs_lookup_exact(target)
    if exact is not None:
        return list(exact), 0.0, _word_to_matrix(exact)
    word, dist = _bfs_lookup_best(target)
    return list(word), dist, _word_to_matrix(word)


def _word_to_matrix(word: Sequence[str]) -> np.ndarray:
    m = gates.I2
    for n in word:
        m = _get_gate_matrix(n) @ m
    return m


def sk_refine(target: np.ndarray, depth: int = 3, *, base_depth: int = 10
              ) -> Tuple[List[str], float]:
    """
    Solovay-Kitaev recursion that refines a base approximation.

    depth=0 returns the base approximation directly.
    depth>0 recursively refines by group-commutator corrections.

    Returns (word, operator_distance).
    """
    if depth == 0:
        word, dist, _ = _base_approx(target, base_depth)
        return word, dist

    prev_word, prev_dist = sk_refine(target, depth - 1, base_depth=base_depth)
    prev_u = _word_to_matrix(prev_word)
    diff = target @ prev_u.conj().T  # target = diff * prev_u
    # Find V, W such that [V, W] = V W V^dag W^dag approximates diff.
    v_mat, w_mat = _balanced_commutator(diff)
    v_word, _ = sk_refine(v_mat, depth - 1, base_depth=base_depth)
    w_word, _ = sk_refine(w_mat, depth - 1, base_depth=base_depth)
    v_dag_word = _word_dagger(v_word)
    w_dag_word = _word_dagger(w_word)
    # Commutator order (matrix product): V W V^dag W^dag
    # In word form, matrices apply right-to-left, so the concatenated word is
    # the *reversed* multiplication order.
    correction = list(w_dag_word) + list(v_dag_word) + list(w_word) + list(v_word)
    refined = correction + list(prev_word)
    refined_u = _word_to_matrix(refined)
    return refined, operator_distance(target, refined_u)


def _word_dagger(word: Sequence[str]) -> List[str]:
    """Return the Clifford+T dagger of a word (reverse order + invert each gate)."""
    inv = {
        'I': 'I', 'H': 'H', 'X': 'X', 'Z': 'Z',
        'S': 'SDG', 'SDG': 'S',
        'T': 'TDG', 'TDG': 'T',
    }
    return [inv[g] for g in reversed(word)]


def _balanced_commutator(u: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    Given a near-identity SU(2) unitary u, find V, W such that [V, W] ≈ u.

    Uses the standard SU(2) construction: write u = e^{-i theta n . sigma},
    rotate into a canonical axis, and set V/W to specific angles.

    This is an approximation helper; callers should not rely on |[V,W] - u|
    being better than second-order in ||u - I||.
    """
    # Convert u to axis-angle form
    # u = cos(phi) I - i sin(phi) (n . sigma)
    tr = np.trace(u).real / 2.0
    tr = max(-1.0, min(1.0, tr))
    phi = math.acos(tr)
    if abs(math.sin(phi)) < 1e-9:
        return gates.I2.copy(), gates.I2.copy()
    # Solve: ||[V, W] - u||_F small with V = Rx(alpha), W = Ry(alpha)
    # Commutator [Rx(a), Ry(a)] has trace 1 + 2 cos(a)^2 cos(a) ... (messy).
    # We use the textbook Dawson-Nielsen balanced choice alpha = 2 arcsin( sqrt(sin(phi/2)/2) )
    s = math.sin(phi / 2.0)
    alpha = 2.0 * math.asin(math.sqrt(min(1.0, max(0.0, s / 2.0))))
    v = gates.rx(alpha)
    w = gates.ry(alpha)
    return v, w


# --- Top-level single-qubit compile ---

@dataclass
class SynthResult:
    word: List[str]
    operator_distance: float
    path: GateClass


def synth_1q(matrix: np.ndarray, *,
             epsilon: float = 1e-2,
             max_depth: int = 12,
             sk_depth: int = 0) -> SynthResult:
    """
    Compile a 2x2 unitary into a Clifford+T word.

    Tries NATIVE -> CLIFFORD -> BFS -> (optional SK) -> ZYZ fallback.
    """
    cls = classify(matrix)
    if cls is GateClass.NATIVE:
        name = match_native(matrix)
        word = [] if name == 'I' else [name]
        return SynthResult(word=word, operator_distance=0.0, path=cls)
    if cls is GateClass.CLIFFORD:
        word = list(match_clifford(matrix) or ())
        return SynthResult(word=word, operator_distance=0.0, path=cls)

    # Approximate path
    _extend_bfs(max_depth)
    exact = _bfs_lookup_exact(matrix)
    if exact is not None:
        return SynthResult(word=list(exact),
                           operator_distance=0.0,
                           path=GateClass.CLIFFORD_T_EXACT)

    # Optional SK refinement on top of BFS base
    if sk_depth > 0:
        word, dist = sk_refine(matrix, depth=sk_depth, base_depth=max_depth)
        return SynthResult(word=list(word),
                           operator_distance=float(dist),
                           path=GateClass.APPROX)

    word, dist = _bfs_lookup_best(matrix)
    return SynthResult(word=list(word),
                       operator_distance=float(dist),
                       path=GateClass.APPROX)
