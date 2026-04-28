// -----------------------------------------------------------------------------
// decoder_tb.v
//
// Unit tests for the instruction decoder. Sweeps every opcode value and checks
// that (instr_class, gate_id, sys_id) match the expected encoding.
//
// Run with:
//   iverilog -g2005 -o sim/decoder_sim src/decoder.v sim/decoder_tb.v
//   vvp sim/decoder_sim
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps

module decoder_tb;

    reg  [15:0] instr;
    wire [3:0]  opcode;
    wire [1:0]  qa, qb;
    wire [7:0]  imm;
    wire [2:0]  instr_class;
    wire [2:0]  gate_id;
    wire [2:0]  sys_id;

    decoder dut(
        .instr(instr),
        .opcode(opcode), .qa(qa), .qb(qb), .imm(imm),
        .instr_class(instr_class),
        .gate_id(gate_id),
        .sys_id(sys_id)
    );

    // Mirror the enum values from decoder.v
    localparam IC_SYS   = 3'd0;
    localparam IC_GATE1 = 3'd1;
    localparam IC_GATE2 = 3'd2;
    localparam IC_MEAS  = 3'd3;

    localparam GID_H    = 3'd0;
    localparam GID_X    = 3'd1;
    localparam GID_Z    = 3'd2;
    localparam GID_S    = 3'd3;
    localparam GID_SDG  = 3'd4;
    localparam GID_T    = 3'd5;
    localparam GID_TDG  = 3'd6;
    localparam GID_CNOT = 3'd7;

    localparam SYS_NOP       = 3'd0;
    localparam SYS_RESET     = 3'd1;
    localparam SYS_HALT      = 3'd2;
    localparam SYS_DUMP      = 3'd3;
    localparam SYS_INITBASIS = 3'd4;
    localparam SYS_SHOTS     = 3'd5;
    localparam SYS_RUNSHOTS  = 3'd6;

    integer passed, failed;

    task check(
        input [3:0] op_in,
        input [2:0] exp_class,
        input [2:0] exp_gate_id,
        input [2:0] exp_sys_id,
        input [127:0] label
    );
        begin
            instr = {op_in, 12'b0};
            #1;
            if (instr_class === exp_class &&
                (exp_class == IC_SYS
                    ? (sys_id === exp_sys_id)
                    : (gate_id === exp_gate_id))) begin
                $display("  PASS: %s  op=0x%h class=%0d gate_id=%0d sys_id=%0d",
                         label, op_in, instr_class, gate_id, sys_id);
                passed = passed + 1;
            end else begin
                $display("  FAIL: %s  op=0x%h got class=%0d gate_id=%0d sys_id=%0d",
                         label, op_in, instr_class, gate_id, sys_id);
                failed = failed + 1;
            end
        end
    endtask

    task check_operands(
        input [15:0] word,
        input [1:0]  exp_qa,
        input [1:0]  exp_qb,
        input [7:0]  exp_imm
    );
        begin
            instr = word;
            #1;
            if (qa === exp_qa && qb === exp_qb && imm === exp_imm) begin
                $display("  PASS: operand passthrough word=%04h qa=%0d qb=%0d imm=%0d",
                         word, qa, qb, imm);
                passed = passed + 1;
            end else begin
                $display("  FAIL: operand passthrough word=%04h got qa=%0d qb=%0d imm=%0d",
                         word, qa, qb, imm);
                failed = failed + 1;
            end
        end
    endtask

    initial begin
        passed = 0;
        failed = 0;
        $display("===== decoder_tb =====");

        // System ops
        check(4'h0, IC_SYS, 3'd0, SYS_NOP,       "NOP      ");
        check(4'h1, IC_SYS, 3'd0, SYS_RESET,     "RESET    ");
        check(4'h7, IC_SYS, 3'd0, SYS_DUMP,      "DUMPSTATE");
        check(4'h8, IC_SYS, 3'd0, SYS_INITBASIS, "INITBASIS");
        check(4'h9, IC_SYS, 3'd0, SYS_SHOTS,     "SHOTS    ");
        check(4'hA, IC_SYS, 3'd0, SYS_RUNSHOTS,  "RUNSHOTS ");
        check(4'hF, IC_SYS, 3'd0, SYS_HALT,      "HALT     ");

        // 1-qubit native gates
        check(4'h2, IC_GATE1, GID_H,   3'd0, "H        ");
        check(4'h3, IC_GATE1, GID_X,   3'd0, "X        ");
        check(4'h4, IC_GATE1, GID_Z,   3'd0, "Z        ");
        check(4'hB, IC_GATE1, GID_T,   3'd0, "T        ");
        check(4'hC, IC_GATE1, GID_TDG, 3'd0, "TDG      ");
        check(4'hD, IC_GATE1, GID_S,   3'd0, "S        ");
        check(4'hE, IC_GATE1, GID_SDG, 3'd0, "SDG      ");

        // 2-qubit native gate
        check(4'h5, IC_GATE2, GID_CNOT, 3'd0, "CNOT     ");

        // Measurement
        check(4'h6, IC_MEAS, 3'd0, 3'd0, "MEASURE  ");

        // Operand passthrough sanity checks
        // H qa=2 -> 0x2800
        check_operands(16'h2800, 2'd2, 2'd0, 8'd0);
        // CNOT qa=1, qb=0 -> 0x5400  (opcode 5 | qa<<10)
        check_operands(16'h5400, 2'd1, 2'd0, 8'd0);
        // CNOT qa=0, qb=1 -> 0x5100  (opcode 5 | qb<<8)
        check_operands(16'h5100, 2'd0, 2'd1, 8'd0);
        // INITBASIS imm=5 -> 0x8005
        check_operands(16'h8005, 2'd0, 2'd0, 8'd5);
        // SHOTS imm=64 -> 0x9040
        check_operands(16'h9040, 2'd0, 2'd0, 8'd64);

        $display("---");
        $display("decoder_tb summary: %0d passed, %0d failed", passed, failed);
        if (failed == 0)
            $display(">>> DECODER TESTS PASSED <<<");
        else
            $display(">>> DECODER TESTS FAILED <<<");
        $finish;
    end
endmodule
