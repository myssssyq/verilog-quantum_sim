; Repeated measurement shots on a Bell state
; Run 10 shots to see statistical distribution

SHOTS 10
RUNSHOTS        ; This will repeat the following program 10 times

RESET
H 0
CNOT 1, 0
MEASURE 0
MEASURE 1
HALT
