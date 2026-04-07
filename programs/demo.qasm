; Demo: Various gate tests
; Tests X, Z, H gates and CNOT in sequence

; --- Test 1: X gate flips |000> to |001> ---
RESET
X 0
DUMPSTATE       ; Expected: |001> = 1.0

; --- Test 2: Z identity: H-Z-H = X ---
RESET
H 0
Z 0
H 0
DUMPSTATE       ; Expected: |001> = 1.0 (same as X on |000>)

; --- Test 3: Hadamard creates equal superposition ---
RESET
H 0
DUMPSTATE       ; Expected: |000> = 1/sqrt(2), |001> = 1/sqrt(2)

; --- Test 4: H on all 3 qubits (uniform superposition) ---
RESET
H 0
H 1
H 2
DUMPSTATE       ; Expected: all 8 amplitudes = 1/sqrt(8) ≈ 0.3536

; --- Test 5: Bell state ---
RESET
H 0
CNOT 1, 0
DUMPSTATE       ; Expected: |000> = |011> = 1/sqrt(2)
MEASURE 0
MEASURE 1

HALT
