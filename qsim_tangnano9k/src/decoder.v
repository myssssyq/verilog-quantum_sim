// -----------------------------------------------------------------------------
// decoder.v
//
// Combinational decode of a 16-bit instruction word into a compact RISC-style
// control bundle. Replaces the previous "one boolean per opcode" style.
//
// Instruction layout:
//   [15:12] opcode
//   [11:10] qa
//   [9:8]   qb
//   [7:0]   imm
//
// The decoder emits:
//   instr_class : top-level category (system, 1-qubit gate, 2-qubit gate, meas)
//   gate_id     : which native gate (valid only when instr_class is a gate)
//   sys_id      : which system/control op (valid only when instr_class == IC_SYS)
//   qa, qb, imm : pass-through operand fields
//
// Downstream modules dispatch on these small enums instead of a forest of
// per-gate boolean flags.
// -----------------------------------------------------------------------------

module decoder(
    input  [15:0] instr,

    // Pass-through fields
    output [3:0]  opcode,
    output [1:0]  qa,
    output [1:0]  qb,
    output [7:0]  imm,

    // Compact control bundle
    output reg [2:0] instr_class,
    output reg [2:0] gate_id,
    output reg [2:0] sys_id
);

    // ---------------------------------------------------------------
    // Encoding — shared with qsim.v / gate_engine.v via these defines.
    // Keep in lockstep with the Python-side tools/assembler.py and
    // tools/qcompiler/emit.py OPCODE tables.
    // ---------------------------------------------------------------
    // Instruction classes
    localparam IC_SYS   = 3'd0;
    localparam IC_GATE1 = 3'd1;
    localparam IC_GATE2 = 3'd2;
    localparam IC_MEAS  = 3'd3;

    // gate_id — used when instr_class == IC_GATE1 or IC_GATE2
    localparam GID_H    = 3'd0;
    localparam GID_X    = 3'd1;
    localparam GID_Z    = 3'd2;
    localparam GID_S    = 3'd3;
    localparam GID_SDG  = 3'd4;
    localparam GID_T    = 3'd5;
    localparam GID_TDG  = 3'd6;
    localparam GID_CNOT = 3'd7;

    // sys_id — used when instr_class == IC_SYS
    localparam SYS_NOP       = 3'd0;
    localparam SYS_RESET     = 3'd1;
    localparam SYS_HALT      = 3'd2;
    localparam SYS_DUMP      = 3'd3;
    localparam SYS_INITBASIS = 3'd4;
    localparam SYS_SHOTS     = 3'd5;
    localparam SYS_RUNSHOTS  = 3'd6;

    assign opcode = instr[15:12];
    assign qa     = instr[11:10];
    assign qb     = instr[9:8];
    assign imm    = instr[7:0];

    // Single opcode -> (class, gate_id, sys_id) decode table.
    // gate_id / sys_id are "don't care" when not applicable; we still assign
    // a defined value so simulation is predictable.
    always @(*) begin
        instr_class = IC_SYS;
        gate_id     = 3'd0;
        sys_id      = SYS_NOP;

        case (opcode)
            4'h0: begin instr_class = IC_SYS;   sys_id  = SYS_NOP;       end
            4'h1: begin instr_class = IC_SYS;   sys_id  = SYS_RESET;     end
            4'h2: begin instr_class = IC_GATE1; gate_id = GID_H;         end
            4'h3: begin instr_class = IC_GATE1; gate_id = GID_X;         end
            4'h4: begin instr_class = IC_GATE1; gate_id = GID_Z;         end
            4'h5: begin instr_class = IC_GATE2; gate_id = GID_CNOT;      end
            4'h6: begin instr_class = IC_MEAS;                           end
            4'h7: begin instr_class = IC_SYS;   sys_id  = SYS_DUMP;      end
            4'h8: begin instr_class = IC_SYS;   sys_id  = SYS_INITBASIS; end
            4'h9: begin instr_class = IC_SYS;   sys_id  = SYS_SHOTS;     end
            4'hA: begin instr_class = IC_SYS;   sys_id  = SYS_RUNSHOTS;  end
            4'hB: begin instr_class = IC_GATE1; gate_id = GID_T;         end
            4'hC: begin instr_class = IC_GATE1; gate_id = GID_TDG;       end
            4'hD: begin instr_class = IC_GATE1; gate_id = GID_S;         end
            4'hE: begin instr_class = IC_GATE1; gate_id = GID_SDG;       end
            4'hF: begin instr_class = IC_SYS;   sys_id  = SYS_HALT;      end
            default: begin
                instr_class = IC_SYS;
                sys_id      = SYS_NOP;
            end
        endcase
    end
endmodule
