#!/usr/bin/env python3
"""
Quantum Simulator Assembler
Converts .qasm assembly files into program.hex for FPGA instruction memory.

Instruction format (16-bit):
  [15:12] opcode
  [11:10] qa (target qubit)
  [9:8]   qb (control qubit, CNOT)
  [7:0]   imm (immediate value)

Supported instructions:
  NOP
  RESET
  H <q>
  X <q>
  Z <q>
  CNOT <target>, <control>
  MEASURE <q>
  DUMPSTATE
  INITBASIS <n>
  SHOTS <n>
  RUNSHOTS
  T <q>
  TDG <q>
  S <q>
  SDG <q>
  HALT
"""

import sys
import re

OPCODES = {
    'NOP':       0x0,
    'RESET':     0x1,
    'H':         0x2,
    'X':         0x3,
    'Z':         0x4,
    'CNOT':      0x5,
    'MEASURE':   0x6,
    'DUMPSTATE': 0x7,
    'INITBASIS': 0x8,
    'SHOTS':     0x9,
    'RUNSHOTS':  0xA,
    'T':         0xB,
    'TDG':       0xC,
    'S':         0xD,
    'SDG':       0xE,
    'HALT':      0xF,
}

# Instructions that take one qubit argument
ONE_QUBIT = {'H', 'X', 'Z', 'MEASURE', 'T', 'TDG', 'S', 'SDG'}
# Instructions that take two qubit arguments
TWO_QUBIT = {'CNOT'}
# Instructions that take an immediate
IMM_INSTR = {'INITBASIS', 'SHOTS'}
# Instructions with no arguments
NO_ARG = {'NOP', 'RESET', 'DUMPSTATE', 'RUNSHOTS', 'HALT'}


def assemble_line(line, line_num):
    """Assemble a single line into a 16-bit machine word."""
    # Strip comments and whitespace
    line = line.split(';')[0].strip()
    if not line:
        return None

    parts = re.split(r'[,\s]+', line)
    mnemonic = parts[0].upper()

    if mnemonic not in OPCODES:
        raise ValueError(f"Line {line_num}: Unknown instruction '{mnemonic}'")

    opcode = OPCODES[mnemonic]
    qa = 0
    qb = 0
    imm = 0

    if mnemonic in ONE_QUBIT:
        if len(parts) < 2:
            raise ValueError(f"Line {line_num}: {mnemonic} requires a qubit argument")
        qa = int(parts[1])
        if qa > 2:
            raise ValueError(f"Line {line_num}: Qubit index must be 0-2, got {qa}")

    elif mnemonic in TWO_QUBIT:
        if len(parts) < 3:
            raise ValueError(f"Line {line_num}: CNOT requires target and control qubits")
        qa = int(parts[1])  # target
        qb = int(parts[2])  # control
        if qa > 2 or qb > 2:
            raise ValueError(f"Line {line_num}: Qubit indices must be 0-2")
        if qa == qb:
            raise ValueError(f"Line {line_num}: CNOT target and control must be different")

    elif mnemonic in IMM_INSTR:
        if len(parts) < 2:
            raise ValueError(f"Line {line_num}: {mnemonic} requires an immediate argument")
        imm = int(parts[1])
        if mnemonic == 'INITBASIS' and imm > 7:
            raise ValueError(f"Line {line_num}: INITBASIS argument must be 0-7")
        if mnemonic == 'SHOTS' and imm == 0:
            raise ValueError(f"Line {line_num}: SHOTS argument must be 1-255 (got 0)")
        if imm > 255:
            raise ValueError(f"Line {line_num}: Immediate must be 0-255")

    elif mnemonic not in NO_ARG:
        raise ValueError(f"Line {line_num}: Internal error for '{mnemonic}'")

    word = (opcode << 12) | (qa << 10) | (qb << 8) | imm
    return word


def assemble(source):
    """Assemble source text into list of 16-bit words."""
    words = []
    for i, line in enumerate(source.splitlines(), 1):
        word = assemble_line(line, i)
        if word is not None:
            words.append(word)
    return words


def main():
    if len(sys.argv) < 2:
        print("Usage: assembler.py <input.qasm> [output.hex]")
        print("")
        print("If output is not specified, writes to program.hex")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else 'program.hex'

    with open(input_file, 'r') as f:
        source = f.read()

    try:
        words = assemble(source)
    except ValueError as e:
        print(f"Assembly error: {e}", file=sys.stderr)
        sys.exit(1)

    with open(output_file, 'w') as f:
        for w in words:
            f.write(f"{w:04X}\n")

    print(f"Assembled {len(words)} instructions -> {output_file}")

    # Also print disassembly for verification
    print("\nDisassembly:")
    for i, w in enumerate(words):
        opcode = (w >> 12) & 0xF
        qa = (w >> 10) & 0x3
        qb = (w >> 8) & 0x3
        imm = w & 0xFF

        # Reverse lookup
        name = '???'
        for k, v in OPCODES.items():
            if v == opcode:
                name = k
                break

        if name in ONE_QUBIT:
            dis = f"{name} {qa}"
        elif name in TWO_QUBIT:
            dis = f"{name} {qa}, {qb}"
        elif name in IMM_INSTR:
            dis = f"{name} {imm}"
        else:
            dis = name

        print(f"  [{i:3d}] {w:04X}  {dis}")


if __name__ == '__main__':
    main()
