# quantum_sim

I made this little project during spring break to combine my knowledge about FPGA from RISC-V CPU creation and reading Nielsen & Chuang Quantum Computing and Information book.

This project was aimed to use my theoretical quantum computing knowledge in a practical environment.

This is a 3-qubit quantum circuit simulator for the Tang Nano 9K. 

It supports:

- custom 16-bit instruction set 
-  stores the full state vector in fixed-point format 
-  applies a few basic quantum gates, 
-  performs measurement, 
- and sends results through UART.

It is not a real quantum computer. It is a classical hardware simulator of quantum state evolution.

## What the project does

- simulates a 3-qubit state vector on FPGA
- uses Q2.14 fixed-point numbers for real and imaginary parts
- supports `H`, `X`, `Z`, `CNOT`, `MEASURE`, `RESET`, `INITBASIS`, `DUMPSTATE`, `SHOTS`, `RUNSHOTS`, `HALT`
- stores the 8 complex amplitudes of the state
- prints state / measurement information through UART
- uses a Python assembler to turn custom `.qasm` code into `program.hex`

## Why only 3 qubits

For `n` qubits, a full state vector needs `2^n` complex amplitudes.

So for 3 qubits:

- `2^3 = 8` amplitudes

I choose 3 because it would be a hustle to make 16 amplitudes and 2 qubits sounded too easy.

## Main idea

The simulator stores a state like

`|psi> = a0|000> + a1|001> + a2|010> + ... + a7|111>`

where each `a_k` is a complex amplitude.

Each amplitude has real and imaginary part

Both are stored in signed Q2.14 fixed-point format.

So for example:

- `1.0 = 16384 = 0x4000`
- `1/sqrt(2) ≈ 0.7071 ≈ 11585`

This project keeps the full 3-qubit state in memory and updates it gate by gate.

## Important math behind the project

### 1. State vector

A 3-qubit system is represented by 8 basis states:

- `|000>`
- `|001>`
- `|010>`
- `|011>`
- `|100>`
- `|101>`
- `|110>`
- `|111>`

So the full state is

`|psi> = sum(a_k |k>)`

with normalization

`sum(|a_k|^2) = 1`

This is the main object the FPGA stores and updates.

### 2. Single-qubit gates work on pairs of amplitudes

A gate acting on one qubit does not touch amplitudes one by one randomly. It works on pairs of basis states that differ only in that qubit.

Example: if the gate acts on qubit 0, the pairs are:

- `|000>` and `|001>`
- `|010>` and `|011>`
- `|100>` and `|101>`
- `|110>` and `|111>`

That is why the gate engine processes the state as pairs.

### 3. Hadamard gate

For one pair of amplitudes `(a, b)`, the Hadamard update is:

`a' = (a + b) / sqrt(2)`

`b' = (a - b) / sqrt(2)`

### 4. X gate

The `X` gate swaps the two amplitudes in a pair.

### 5. Z gate

The `Z` gate leaves the `0` side unchanged and multiplies the `1` side by `-1`.

### 6. CNOT gate

`CNOT` uses one control qubit and one target qubit.

If the control bit is `1`, the target pair is swapped.
If the control bit is `0`, nothing happens.

### 7. Measurement

Measurement is based on probabilities.

If the amplitudes of all basis states where measured qubit = 0 are collected into one set, and the amplitudes where measured qubit = 1 are collected into another set, then:

- probability of result 0 = sum of squared magnitudes on the 0 side
- probability of result 1 = sum of squared magnitudes on the 1 side

The hardware accumulates these probabilities, chooses an outcome using an LFSR-based pseudo-random source, collapses the losing side to zero, and renormalizes the surviving side.

## File structure

```text
src/
  qsim.v          top-level control and FSM
  decoder.v       instruction decoder
  gate_engine.v   executes H, X, Z, CNOT
  state_vec.v     stores the 8 complex amplitudes
  measure_unit.v  probability calculation, collapse, renormalization
  uart_printer.v  UART formatting for state / measurement output
  uart_tx.v       UART transmitter
  pc.v            program counter
  imem.v          instruction ROM loaded from program.hex
  reset_gen.v     power-on reset + button synchronizer

sim/
  qsim_tb.v       testbench

programs/
  bell_state.qasm
  ghz_state.qasm
  measure_shots.qasm
  demo.qasm

tools/
  assembler.py    converts .qasm into program.hex

program.hex       machine code loaded by instruction memory
tangnano9k.cst    pin constraints for Tang Nano 9K
```

## Current instruction set

- `NOP`
- `RESET`
- `INITBASIS <n>`
- `H <q>`
- `X <q>`
- `Z <q>`
- `CNOT <target>, <control>`
- `MEASURE <q>`
- `DUMPSTATE`
- `SHOTS <n>`
- `RUNSHOTS`
- `HALT`

## How to use it right now

### 1. Assemble a program

```bash
python tools/assembler.py programs/bell_state.qasm
```

This generates `program.hex`.

### 2. Simulate in Verilog

```bash
iverilog -o qsim_sim sim/qsim_tb.v src/qsim.v src/decoder.v \
  src/gate_engine.v src/state_vec.v src/measure_unit.v \
  src/uart_printer.v src/uart_tx.v src/pc.v src/imem.v src/reset_gen.v
vvp qsim_sim
```

### 3. Synthesize for FPGA

Open the project in Gowin EDA, add the files from `src/`, set `qsim.v` as top module, apply `tangnano9k.cst`, then synthesize and upload to the Tang Nano 9K.

## Example idea

A Bell state can be prepared with:

```text
RESET
H 0
CNOT 1,0
DUMPSTATE
HALT
```

This should create a state equivalent to:

`(|000> + |011>) / sqrt(2)`

## Limitations

- only 3 qubits
- full state vector approach, so it does not scale well
- fixed-point precision is limited
- measurement randomness is pseudo-random, not physical randomness
- only a small basic gate set is implemented right now

## Future plans

- add `reference_sim.py` for software-side simulation / checking
- add `uart_host.py` to make UART output easier to read and use
- add quantum gate decomposition using the Solovay-Kitaev theorem
