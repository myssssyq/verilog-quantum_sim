"""
Unit tests and regression tests for the qcompiler.

Run with:
    python -m unittest tools.qcompiler.tests.test_compile

These tests cover:
    - NATIVE gate recognition
    - CLIFFORD table hits (Y, SX, HS, etc.)
    - CLIFFORD+T exact recognition (T dagger, T squared, etc.)
    - APPROX path for arbitrary rotations (verified within epsilon)
    - Named 2-qubit gates (CZ, SWAP, iSWAP, CY)
    - Circuit compilation end-to-end
    - Peephole optimizer (inverse cancellation, phase merge)
    - Unitarity validation errors
"""

from __future__ import annotations

import math
import unittest

import numpy as np

from tools.qcompiler import (CompileReport, NotUnitaryError,
                              UnsupportedDimensionError, compile_circuit,
                              compile_gate, compile_unitary, verify)
from tools.qcompiler import gates
from tools.qcompiler.classify import GateClass, classify
from tools.qcompiler.optimize import (cancel_inverse, merge_phase, remove_identity,
                                       run_passes)
from tools.qcompiler.validate import operator_distance, phase_equal
from tools.qcompiler.verify import (embed_one_qubit, embed_two_qubit,
                                     instr_sequence_to_matrix)


# --- Helpers ---

def _full_target_1q(u2: np.ndarray, qubit: int) -> np.ndarray:
    return embed_one_qubit(u2, qubit)


def _full_target_2q(u4: np.ndarray, qa: int, qb: int) -> np.ndarray:
    return embed_two_qubit(u4, qa, qb)


class TestNativePath(unittest.TestCase):
    def test_h_is_native(self):
        report = compile_gate('H', 0)
        self.assertEqual(report.instructions, [('H', 0, None)])
        self.assertEqual(report.path, GateClass.NATIVE)
        self.assertAlmostEqual(report.operator_distance, 0.0)

    def test_t_is_native(self):
        report = compile_gate(gates.T, 1)
        self.assertEqual(report.instructions, [('T', 1, None)])
        self.assertAlmostEqual(report.operator_distance, 0.0)

    def test_i_emits_empty(self):
        report = compile_gate(gates.I2, 0)
        self.assertEqual(report.instructions, [])
        self.assertAlmostEqual(report.operator_distance, 0.0)


class TestCliffordPath(unittest.TestCase):
    def test_y_decomposes(self):
        report = compile_gate(gates.Y, 2)
        v = verify(report, gates.Y, [2])
        self.assertTrue(v.passed, v.message)

    def test_s_squared_is_z(self):
        # S S = Z (up to global phase). Passing S squared numerically.
        m = gates.S @ gates.S
        report = compile_gate(m, 0)
        v = verify(report, m, [0])
        self.assertTrue(v.passed, v.message)


class TestCliffordTExact(unittest.TestCase):
    def test_t_squared_recognized(self):
        m = gates.T @ gates.T  # = S up to phase
        report = compile_gate(m, 0)
        v = verify(report, m, [0])
        self.assertTrue(v.passed, v.message)


class TestApproximate(unittest.TestCase):
    def test_rz_pi_over_4_exact(self):
        # Rz(pi/4) equals T up to global phase
        report = compile_gate(gates.rz(math.pi / 4), 0, max_depth=6)
        v = verify(report, gates.rz(math.pi / 4), [0], epsilon=1e-2)
        self.assertTrue(v.passed, v.message)

    def test_rz_pi_over_2_exact(self):
        # Rz(pi/2) = S up to global phase
        report = compile_gate(gates.rz(math.pi / 2), 0, max_depth=6)
        v = verify(report, gates.rz(math.pi / 2), [0], epsilon=1e-2)
        self.assertTrue(v.passed, v.message)

    def test_rx_pi_over_2_approximated(self):
        # Rx(pi/2) is Clifford — should appear in the 24-element table
        target = gates.rx(math.pi / 2)
        report = compile_gate(target, 1, max_depth=8, epsilon=1e-2)
        v = verify(report, target, [1], epsilon=1e-2)
        self.assertTrue(v.passed, v.message)

    def test_random_rz_small_angle_best_effort(self):
        # Small random Rz: should be within epsilon for max_depth 10
        np.random.seed(0)
        theta = 0.13
        target = gates.rz(theta)
        report = compile_gate(target, 0, max_depth=10, epsilon=0.3)
        v = verify(report, target, [0], epsilon=0.3)
        self.assertTrue(v.passed, f"{v.message}, reported {report.operator_distance}")


class TestTwoQubitNamed(unittest.TestCase):
    def test_cz_named(self):
        report = compile_gate('CZ', 0, 1)
        v = verify(report, gates.I2, [0])  # trivial to make shape valid
        # Compare full operator directly
        synth = instr_sequence_to_matrix(report.instructions)
        from tools.qcompiler.synth2q import CZ
        target = _full_target_2q(CZ, 0, 1)
        self.assertTrue(phase_equal(synth, target), "CZ decomposition mismatch")

    def test_swap_named(self):
        report = compile_gate('SWAP', 0, 1)
        from tools.qcompiler.synth2q import SWAP
        target = _full_target_2q(SWAP, 0, 1)
        synth = instr_sequence_to_matrix(report.instructions)
        self.assertTrue(phase_equal(synth, target), "SWAP decomposition mismatch")

    def test_iswap_named(self):
        report = compile_gate('ISWAP', 0, 1)
        from tools.qcompiler.synth2q import ISWAP
        target = _full_target_2q(ISWAP, 0, 1)
        synth = instr_sequence_to_matrix(report.instructions)
        self.assertTrue(phase_equal(synth, target), "iSWAP decomposition mismatch")

    def test_cz_matrix_input_matches_named(self):
        from tools.qcompiler.synth2q import CZ
        report = compile_gate(CZ, 0, 1)
        target = _full_target_2q(CZ, 0, 1)
        synth = instr_sequence_to_matrix(report.instructions)
        self.assertTrue(phase_equal(synth, target), "CZ via matrix mismatch")


class TestCircuit(unittest.TestCase):
    def test_bell_circuit_compiles_to_native(self):
        circ = [
            ('H', 0),
            ('CNOT', 1, 0),
        ]
        report = compile_circuit(circ)
        self.assertEqual(report.instructions,
                         [('H', 0, None), ('CNOT', 1, 0)])

    def test_y_as_circuit(self):
        circ = [
            ('Y', 0),
        ]
        report = compile_circuit(circ)
        synth = instr_sequence_to_matrix(report.instructions)
        target = _full_target_1q(gates.Y, 0)
        self.assertTrue(phase_equal(synth, target))


class TestOptimizer(unittest.TestCase):
    def test_inverse_cancellation(self):
        seq = [('H', 0, None), ('H', 0, None),
               ('T', 1, None), ('TDG', 1, None)]
        out = cancel_inverse(seq)
        self.assertEqual(out, [])

    def test_phase_merge(self):
        # T T T T -> Z  (4 eighths = 4)
        seq = [('T', 0, None)] * 4
        out = merge_phase(seq)
        self.assertEqual(out, [('Z', 0, None)])

    def test_phase_merge_accumulate(self):
        # S T T  -> 2 + 1 + 1 = 4 -> Z
        seq = [('S', 0, None), ('T', 0, None), ('T', 0, None)]
        out = merge_phase(seq)
        self.assertEqual(out, [('Z', 0, None)])

    def test_phase_flushed_by_non_phase(self):
        seq = [('S', 0, None), ('H', 0, None), ('T', 0, None)]
        out = merge_phase(seq)
        self.assertEqual(out, [('S', 0, None), ('H', 0, None), ('T', 0, None)])

    def test_remove_identity(self):
        seq = [('I', 0, None), ('H', 0, None), ('I', 1, None)]
        out = remove_identity(seq)
        self.assertEqual(out, [('H', 0, None)])

    def test_full_pipeline_idempotent(self):
        seq = [('H', 0, None), ('T', 0, None), ('TDG', 0, None), ('H', 0, None)]
        out = run_passes(seq, level=1)
        # H T TDG H -> H H -> I
        self.assertEqual(out, [])


class TestValidation(unittest.TestCase):
    def test_non_unitary_rejected(self):
        bad = np.array([[1, 0], [0, 2]], dtype=complex)
        with self.assertRaises(NotUnitaryError):
            compile_gate(bad, 0)

    def test_wrong_dimension_rejected(self):
        bad = np.eye(3, dtype=complex)
        with self.assertRaises(UnsupportedDimensionError):
            compile_gate(bad, 0)


class TestClassify(unittest.TestCase):
    def test_native_identified(self):
        self.assertEqual(classify(gates.T), GateClass.NATIVE)

    def test_y_is_clifford(self):
        self.assertEqual(classify(gates.Y), GateClass.CLIFFORD)

    def test_rz_arbitrary_is_approx(self):
        self.assertEqual(classify(gates.rz(0.123)), GateClass.APPROX)


class TestHexEmission(unittest.TestCase):
    def test_hex_encoding_matches_assembler(self):
        # H 0 -> 0x2000, T 1 -> 0xB400, CNOT 1, 0 -> 0x5400
        report = compile_circuit([('H', 0), ('T', 1), ('CNOT', 1, 0)])
        words = report.hex_words
        self.assertEqual(words, [0x2000, 0xB400, 0x5400])


if __name__ == '__main__':
    unittest.main()
