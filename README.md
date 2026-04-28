# quantum_sim

A 3-qubit quantum circuit simulator for the Tang Nano 9K.

It is a classical hardware simulator of quantum state evolution. The design uses a custom 16-bit ISA, stores the full 3-qubit state vector in BRAM as Q2.14 fixed-point, applies a small native gate set in HDL, handles measurement with collapse and renormalization, and prints results over UART. There is also a Python assembler, a Python reference simulator, and a small host-side compiler for lowering higher-level gates to the native instruction stream.

I built this over spring break after finishing a RISC-V CPU on the same board. I was reading Nielsen & Chuang at the time and wanted one project that combined the hardware side with the quantum-information side instead of keeping them separate.

## What it does

- Stores the 8 complex amplitudes of a 3-qubit state in BRAM, with real and imaginary parts as signed 16-bit Q2.14 values.
- Runs these native gates in hardware: `H`, `X`, `Z`, `S`, `SDG`, `T`, `TDG`, `CNOT`.
- Runs these control and I/O operations: `RESET`, `INITBASIS`, `MEASURE`, `DUMPSTATE`, `SHOTS`, `RUNSHOTS`, `HALT`, `NOP`.
- Handles measurement by accumulating probabilities, picking a branch with an LFSR, collapsing the state, and renormalizing with a 32-entry `1/sqrt(p)` LUT.
- Supports shot mode with `SHOTS n` followed by `RUNSHOTS`.
- Emits state dumps and measurement results over UART.
- Assembles `.qasm` into `program.hex`.
- Includes a Python reference simulator that mirrors the HDL semantics.
- Includes `tools/qcompiler/` for lowering selected higher-level gates to the native instruction stream.

## Layout

```text
src/
  qsim.v          top-level FSM
  decoder.v       decode -> (instr_class, gate_id, sys_id, qa, qb, imm)
  gate_engine.v   1-qubit gates and CNOT
  state_vec.v     8 complex amplitudes in BRAM
  measure_unit.v  probability accumulation, collapse, renormalization
  uart_printer.v  UART output formatting
  uart_tx.v       UART transmitter
  pc.v            program counter
  imem.v          instruction ROM loaded from program.hex
  reset_gen.v     power-on reset + button sync

sim/
  qsim_tb.v       full-system testbench
  decoder_tb.v    decoder unit test

tools/
  assembler.py    .qasm -> program.hex
  qcompiler/      host-side gate compiler

reference_sim.py  Python reference simulator
uart_host.py      host-side UART receiver
program.hex       machine code loaded by imem.v
tangnano9k.cst    Tang Nano 9K pin constraints
```

The decoder emits a compact bundle (`instr_class`, `gate_id`, `sys_id`) instead of one boolean per opcode. Adding a new native gate is one line in `decoder.v` and one branch in `gate_engine.v`.

## Instruction set

Instruction format:

```text
[15:12] opcode | [11:10] qa | [9:8] qb | [7:0] imm
```

| Opcode | Mnemonic        |
|-------:|-----------------|
| `0x0`  | `NOP`           |
| `0x1`  | `RESET`         |
| `0x2`  | `H <q>`         |
| `0x3`  | `X <q>`         |
| `0x4`  | `Z <q>`         |
| `0x5`  | `CNOT <t>,<c>`  |
| `0x6`  | `MEASURE <q>`   |
| `0x7`  | `DUMPSTATE`     |
| `0x8`  | `INITBASIS <n>` |
| `0x9`  | `SHOTS <n>`     |
| `0xA`  | `RUNSHOTS`      |
| `0xB`  | `T <q>`         |
| `0xC`  | `TDG <q>`       |
| `0xD`  | `S <q>`         |
| `0xE`  | `SDG <q>`       |
| `0xF`  | `HALT`          |

A 1-qubit gate on qubit `k` only mixes amplitudes that differ in bit `k`. The gate engine iterates over the 4 affected pairs and applies a fixed-point update. `H` uses the shared `1/sqrt(2)` multiplier path. `S`, `SDG`, `T`, and `TDG` only modify the `|1>` side. `CNOT` is a conditional pair swap with no multiply.

Measurement accumulates `prob0` in Q4.28, compares a 16-bit LFSR output against the threshold, zeroes the losing amplitudes, and rescales the survivors through a 32-entry Q3.13 `1/sqrt(p_keep)` LUT, with a shortcut for the deterministic `p = 1.0` case.

## Running it

Assemble a program:

```bash
python tools/assembler.py programs/bell_state.qasm
```

Simulate the full design:

```bash
iverilog -g2005 -o sim/qsim_sim src/*.v sim/qsim_tb.v
vvp sim/qsim_sim
```

Run only the decoder test:

```bash
iverilog -g2005 -o sim/decoder_sim src/decoder.v sim/decoder_tb.v
vvp sim/decoder_sim
```

Run compiler tests:

```bash
python -m unittest tools.qcompiler.tests.test_compile
```

For FPGA runs, open the project in Gowin EDA, add the files in `src/`, set `qsim.v` as top, apply `tangnano9k.cst`, and upload to the Tang Nano 9K.

Example Bell-state program:

```text
RESET
H 0
CNOT 1, 0
DUMPSTATE
HALT
```

Expected result: `(|000> + |011>) / sqrt(2)`. In Q2.14 both nonzero amplitudes land at `11585`.

## Verification

Three test suites are in place:

- `sim/qsim_tb.v`: 15 sections and 41 amplitude checks. Covers Bell, GHZ, `X` on each qubit, `H-Z-H = X`, uniform superposition, `INITBASIS`, Bell measurement correlation, idempotent measurement, shot mode, `T` on `|001>`, `T·T = S`, `S·SDG = I`, and `T·TDG = I`.
- `sim/decoder_tb.v`: 21 checks covering every opcode value and operand pass-through.
- `tools/qcompiler/tests/test_compile.py`: 28 checks covering synthesis paths, peephole optimization, hex emission, and unitarity validation.

`reference_sim.py` implements the same semantics in Python, so HDL behavior can be checked against it.

## qcompiler

The compiler lives under `tools/qcompiler/`. You give it a gate by name, a 2x2 or 4x4 matrix, or a small circuit, and it returns a native instruction stream plus the numerical distance from the target.

It tries these paths in order:

1. Native gate match up to global phase.
2. Single-qubit Clifford match.
3. Short exact word in `{H, X, Z, S, SDG, T, TDG}` found by bounded-depth BFS.
4. Best bounded-depth approximation if no exact word is found, with the residual reported.
5. Named 2-qubit decompositions for `CZ`, `SWAP`, `ISWAP`, `CY`, `CS`, and `CSDG`.

After that it runs a peephole pass that cancels adjacent inverses and merges diagonal phase runs.

Minimal example:

```python
from tools.qcompiler import compile_circuit

r = compile_circuit([('H', 0), ('CNOT', 1, 0)])
r.hex_words  # [0x2000, 0x5400]
```

## Photo of tests run

Both Bell state and GHZ state coompiled on command prompt, verified using reference_sim.py against UART output from Gowin Programmer.
<img width="2560" height="1920" alt="photo_2026-04-28_11-20-11" src="https://github.com/user-attachments/assets/41286503-7645-4d01-b06a-2a6b0097bbea" />
