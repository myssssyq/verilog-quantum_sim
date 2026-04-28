"""
Emit compiled instructions in the project's formats.

An emitted instruction is a tuple (mnemonic, qa, qb). We convert to:
    * .qasm text (for human review or re-assembly)
    * .hex words (for direct injection into program.hex)

The .hex encoding mirrors tools/assembler.py exactly. If you change the
assembler opcode table, update OPCODES here too.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Tuple

Instr = Tuple[str, int, Optional[int]]


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


def encode_instr(mnemonic: str, qa: int, qb: Optional[int]) -> int:
    if mnemonic not in OPCODES:
        raise ValueError(f"Unknown mnemonic: {mnemonic}")
    opcode = OPCODES[mnemonic]
    qb_enc = qb if qb is not None else 0
    return (opcode << 12) | ((qa & 3) << 10) | ((qb_enc & 3) << 8)


def to_qasm(seq: Sequence[Instr]) -> str:
    """Render the instruction stream as human-readable assembly."""
    lines: List[str] = []
    for mnemonic, qa, qb in seq:
        if mnemonic == 'CNOT':
            lines.append(f"CNOT {qa}, {qb}")
        elif qb is None and mnemonic in {'H', 'X', 'Z', 'T', 'TDG', 'S', 'SDG', 'MEASURE'}:
            lines.append(f"{mnemonic} {qa}")
        else:
            lines.append(mnemonic)
    return '\n'.join(lines)


def to_hex_words(seq: Sequence[Instr]) -> List[int]:
    """Encode the instruction stream as a list of 16-bit program words."""
    return [encode_instr(m, qa, qb) for m, qa, qb in seq]


def write_hex_file(path: str, words: Iterable[int]) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        for w in words:
            f.write(f"{w & 0xFFFF:04X}\n")
