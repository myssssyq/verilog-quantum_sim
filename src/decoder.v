module decoder(
    input  [15:0] instr,
    output [3:0]  opcode,
    output [1:0]  qa,
    output [1:0]  qb,
    output [7:0]  imm,
    output        is_gate,
    output        is_h,
    output        is_x,
    output        is_z,
    output        is_cnot,
    output        is_measure,
    output        is_dump,
    output        is_reset,
    output        is_initbasis,
    output        is_shots,
    output        is_runshots,
    output        is_halt
);
    assign opcode = instr[15:12];
    assign qa     = instr[11:10];
    assign qb     = instr[9:8];
    assign imm    = instr[7:0];

    assign is_reset    = (opcode == 4'h1);
    assign is_h        = (opcode == 4'h2);
    assign is_x        = (opcode == 4'h3);
    assign is_z        = (opcode == 4'h4);
    assign is_cnot     = (opcode == 4'h5);
    assign is_measure  = (opcode == 4'h6);
    assign is_dump     = (opcode == 4'h7);
    assign is_initbasis= (opcode == 4'h8);
    assign is_shots    = (opcode == 4'h9);
    assign is_runshots = (opcode == 4'hA);
    assign is_halt     = (opcode == 4'hF);
    assign is_gate     = is_h | is_x | is_z | is_cnot;
endmodule
