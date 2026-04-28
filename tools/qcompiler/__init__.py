"""
qcompiler: a compiler from user-defined gates to the native instruction basis
of the 3-qubit FPGA simulator.

Public API:
    compile_gate(name_or_matrix, qa, qb=None, **opts) -> CompileReport
    compile_unitary(u, qubits, **opts) -> CompileReport
    compile_circuit(circuit, **opts) -> CompileReport
    verify(report, target_matrix, qubits) -> VerifyResult

Target instruction basis (a.k.a. "native"):
    H, X, Z, S, SDG, T, TDG, CNOT
"""

from .compile import (CompileReport, compile_circuit, compile_gate,
                      compile_unitary)
from .validate import (NotUnitaryError, UnsupportedDimensionError,
                       operator_distance, frobenius_distance, phase_equal,
                       strip_global_phase)
from .verify import VerifyResult, verify

__all__ = [
    'CompileReport',
    'compile_circuit',
    'compile_gate',
    'compile_unitary',
    'verify',
    'VerifyResult',
    'NotUnitaryError',
    'UnsupportedDimensionError',
    'operator_distance',
    'frobenius_distance',
    'phase_equal',
    'strip_global_phase',
]
