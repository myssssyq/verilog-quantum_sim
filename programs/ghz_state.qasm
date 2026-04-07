; GHZ State: (|000> + |111>) / sqrt(2)
; Three-qubit entanglement

RESET           ; Initialize to |000>
H 0             ; Superposition on qubit 0
CNOT 1, 0       ; Entangle qubit 1
CNOT 2, 0       ; Entangle qubit 2
DUMPSTATE       ; Print state: should show |000> and |111>
MEASURE 0
MEASURE 1
MEASURE 2       ; All three should be correlated
HALT
