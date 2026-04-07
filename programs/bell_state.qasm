; Bell State: (|000> + |011>) / sqrt(2)
; Creates entanglement between qubit 0 and qubit 1

RESET           ; Initialize to |000>
H 0             ; Put qubit 0 in superposition
CNOT 1, 0       ; Entangle qubit 1 with qubit 0
DUMPSTATE       ; Print full state vector
MEASURE 0       ; Measure qubit 0
MEASURE 1       ; Measure qubit 1 (should correlate with q0)
HALT
