`timescale 1ns / 1ps

module qsim_tb;

    reg clk = 0;
    reg btn_n = 1;
    wire [5:0] led;
    wire uart_tx;

    // 27 MHz -> 37.037 ns period
    always #18.5 clk = ~clk;

    qsim uut(
        .clk(clk),
        .btn_n(btn_n),
        .led(led),
        .uart_tx(uart_tx)
    );

    // -----------------------------------------------------------
    // Direct state vector observation (hierarchical access)
    // -----------------------------------------------------------
    wire signed [15:0] amp_re [0:7];
    wire signed [15:0] amp_im [0:7];
    genvar gi;
    generate
        for (gi = 0; gi < 8; gi = gi + 1) begin : amp_obs
            assign amp_re[gi] = uut.u_sv.re[gi];
            assign amp_im[gi] = uut.u_sv.im[gi];
        end
    endgenerate

    wire [3:0] master_state = uut.mstate;
    wire [7:0] pc_val       = uut.pc_out;

    // -----------------------------------------------------------
    // UART capture
    // -----------------------------------------------------------
    localparam UART_BIT_PERIOD = 8681; // ns for 115200 baud

    reg [7:0] rx_byte;
    integer bc;

    initial begin
        forever begin
            @(negedge uart_tx);
            #(UART_BIT_PERIOD / 2);
            if (uart_tx == 0) begin
                for (bc = 0; bc < 8; bc = bc + 1) begin
                    #UART_BIT_PERIOD;
                    rx_byte[bc] = uart_tx;
                end
                #UART_BIT_PERIOD; // stop bit
                if (rx_byte >= 8'h20 && rx_byte <= 8'h7E)
                    $write("%c", rx_byte);
                else if (rx_byte == 8'h0A)
                    $write("\n");
                else if (rx_byte == 8'h0D)
                    ;
                else
                    $write("[%02X]", rx_byte);
            end
        end
    end

    // -----------------------------------------------------------
    // Helper tasks
    // -----------------------------------------------------------
    integer total_pass, total_fail;

    task reset_and_wait;
        begin
            btn_n = 0;
            #500;
            btn_n = 1;
            #500;
            wait(uut.rst == 0);
            #100;
        end
    endtask

    task wait_for_halt;
        begin
            wait(master_state == 4'd12);  // Q_HALT
            #1000;
        end
    endtask

    task check_amp;
        input [2:0] idx;
        input signed [15:0] exp_re;
        input signed [15:0] exp_im;
        input integer tolerance;
        begin
            if ((amp_re[idx] >= exp_re - tolerance) &&
                (amp_re[idx] <= exp_re + tolerance) &&
                (amp_im[idx] >= exp_im - tolerance) &&
                (amp_im[idx] <= exp_im + tolerance)) begin
                $display("  PASS: |%b%b%b> = %0d + %0di (expected %0d + %0di)",
                         idx[2], idx[1], idx[0],
                         amp_re[idx], amp_im[idx], exp_re, exp_im);
                total_pass = total_pass + 1;
            end else begin
                $display("  FAIL: |%b%b%b> = %0d + %0di (expected %0d + %0di)",
                         idx[2], idx[1], idx[0],
                         amp_re[idx], amp_im[idx], exp_re, exp_im);
                total_fail = total_fail + 1;
            end
        end
    endtask

    task load_program;
        input [15:0] p0, p1, p2, p3, p4, p5, p6, p7;
        begin
            uut.u_imem.rom[0] = p0;
            uut.u_imem.rom[1] = p1;
            uut.u_imem.rom[2] = p2;
            uut.u_imem.rom[3] = p3;
            uut.u_imem.rom[4] = p4;
            uut.u_imem.rom[5] = p5;
            uut.u_imem.rom[6] = p6;
            uut.u_imem.rom[7] = p7;
        end
    endtask

    // -----------------------------------------------------------
    // Test sequence
    // -----------------------------------------------------------
    initial begin
        $dumpfile("qsim.vcd");
        $dumpvars(0, qsim_tb);

        total_pass = 0;
        total_fail = 0;

        // ===== Test 1: Bell State =====
        $display("\n===== Test 1: Bell State (H q0, CNOT q1,q0) =====");
        load_program(
            16'h1000, // RESET
            16'h2000, // H 0
            16'h5400, // CNOT 1, 0
            16'hF000, // HALT
            16'h0000, 16'h0000, 16'h0000, 16'h0000
        );
        reset_and_wait;
        wait_for_halt;
        // Expected: |000>=1/√2=11585, |011>=1/√2=11585
        check_amp(0, 16'sd11585, 16'sd0, 2);
        check_amp(1, 16'sd0, 16'sd0, 0);
        check_amp(2, 16'sd0, 16'sd0, 0);
        check_amp(3, 16'sd11585, 16'sd0, 2);
        check_amp(4, 16'sd0, 16'sd0, 0);
        check_amp(5, 16'sd0, 16'sd0, 0);
        check_amp(6, 16'sd0, 16'sd0, 0);
        check_amp(7, 16'sd0, 16'sd0, 0);

        // ===== Test 2: GHZ State =====
        $display("\n===== Test 2: GHZ State (H q0, CNOT q1,q0, CNOT q2,q0) =====");
        load_program(
            16'h1000, // RESET
            16'h2000, // H 0
            16'h5400, // CNOT 1, 0
            16'h5800, // CNOT 2, 0
            16'hF000, // HALT
            16'h0000, 16'h0000, 16'h0000
        );
        reset_and_wait;
        wait_for_halt;
        // Expected: |000>=11585, |111>=11585
        check_amp(0, 16'sd11585, 16'sd0, 2);
        check_amp(7, 16'sd11585, 16'sd0, 2);
        check_amp(1, 16'sd0, 16'sd0, 0);
        check_amp(2, 16'sd0, 16'sd0, 0);
        check_amp(3, 16'sd0, 16'sd0, 0);
        check_amp(4, 16'sd0, 16'sd0, 0);
        check_amp(5, 16'sd0, 16'sd0, 0);
        check_amp(6, 16'sd0, 16'sd0, 0);

        // ===== Test 3: X gate =====
        $display("\n===== Test 3: X gate (|000> -> |001>) =====");
        load_program(
            16'h1000, // RESET
            16'h3000, // X 0
            16'hF000, // HALT
            16'h0000, 16'h0000, 16'h0000, 16'h0000, 16'h0000
        );
        reset_and_wait;
        wait_for_halt;
        check_amp(0, 16'sd0, 16'sd0, 0);
        check_amp(1, 16'sd16384, 16'sd0, 0);  // 1.0 in Q2.14

        // ===== Test 4: X on q1 (|000> -> |010>) =====
        $display("\n===== Test 4: X on q1 (|000> -> |010>) =====");
        load_program(
            16'h1000, // RESET
            16'h3400, // X 1
            16'hF000, // HALT
            16'h0000, 16'h0000, 16'h0000, 16'h0000, 16'h0000
        );
        reset_and_wait;
        wait_for_halt;
        check_amp(0, 16'sd0, 16'sd0, 0);
        check_amp(2, 16'sd16384, 16'sd0, 0);

        // ===== Test 5: X on q2 (|000> -> |100>) =====
        $display("\n===== Test 5: X on q2 (|000> -> |100>) =====");
        load_program(
            16'h1000, // RESET
            16'h3800, // X 2
            16'hF000, // HALT
            16'h0000, 16'h0000, 16'h0000, 16'h0000, 16'h0000
        );
        reset_and_wait;
        wait_for_halt;
        check_amp(0, 16'sd0, 16'sd0, 0);
        check_amp(4, 16'sd16384, 16'sd0, 0);

        // ===== Test 6: Z identity (H-Z-H = X) =====
        $display("\n===== Test 6: H-Z-H on q0 = X on q0 =====");
        load_program(
            16'h1000, // RESET
            16'h2000, // H 0
            16'h4000, // Z 0
            16'h2000, // H 0
            16'hF000, // HALT
            16'h0000, 16'h0000, 16'h0000
        );
        reset_and_wait;
        wait_for_halt;
        // H-Z-H = X, so |000> -> |001>
        check_amp(0, 16'sd0, 16'sd0, 1);
        check_amp(1, 16'sd16383, 16'sd0, 2); // ~16384 with rounding

        // ===== Test 7: H on all 3 qubits (uniform superposition) =====
        $display("\n===== Test 7: H on q0,q1,q2 (uniform superposition) =====");
        load_program(
            16'h1000, // RESET
            16'h2000, // H 0
            16'h2400, // H 1
            16'h2800, // H 2
            16'hF000, // HALT
            16'h0000, 16'h0000, 16'h0000
        );
        reset_and_wait;
        wait_for_halt;
        // Each amplitude = 1/sqrt(8) = 1/(2*sqrt(2)) = 11585/2 ≈ 5792
        // Actually: H^3|000> = 1/sqrt(8) for each
        // 1/sqrt(8) = 1/(2√2) = 0.35355... => Q2.14 = round(0.35355*16384) = 5793
        // Via computation: (1/√2)^3 = 11585 * 11585 / 16384 * 11585 / 16384
        //   = 8192 (approx, with rounding)
        // Let's just check they're all equal and positive
        begin : test7_check
            integer t7_i;
            reg t7_ok;
            t7_ok = 1;
            for (t7_i = 0; t7_i < 8; t7_i = t7_i + 1) begin
                if (amp_re[t7_i] < 16'sd5700 || amp_re[t7_i] > 16'sd5900) begin
                    $display("  FAIL: |%b%b%b> re=%0d (expected ~5793)",
                             t7_i[2], t7_i[1], t7_i[0], amp_re[t7_i]);
                    t7_ok = 0;
                    total_fail = total_fail + 1;
                end
                if (amp_im[t7_i] != 0) begin
                    $display("  FAIL: |%b%b%b> im=%0d (expected 0)",
                             t7_i[2], t7_i[1], t7_i[0], amp_im[t7_i]);
                    t7_ok = 0;
                    total_fail = total_fail + 1;
                end
            end
            if (t7_ok) begin
                $display("  PASS: All 8 amplitudes in range [5700,5900]");
                total_pass = total_pass + 1;
            end
        end

        // ===== Test 8: INITBASIS |101> =====
        $display("\n===== Test 8: INITBASIS 5 (|101>) =====");
        load_program(
            16'h8005, // INITBASIS 5
            16'hF000, // HALT
            16'h0000, 16'h0000, 16'h0000, 16'h0000, 16'h0000, 16'h0000
        );
        reset_and_wait;
        wait_for_halt;
        check_amp(5, 16'sd16384, 16'sd0, 0);
        check_amp(0, 16'sd0, 16'sd0, 0);

        // ===== Test 9: Bell sequential measurement correlation =====
        $display("\n===== Test 9: Bell measurement correlation =====");
        load_program(
            16'h1000, // RESET
            16'h2000, // H 0
            16'h5400, // CNOT 1, 0
            16'h6000, // MEASURE 0
            16'h6400, // MEASURE 1
            16'hF000, // HALT
            16'h0000, 16'h0000
        );
        reset_and_wait;
        wait_for_halt;
        // Renorm required: if M(0)=0 then M(1) must be 0 (amp[0] survives),
        //                  if M(0)=1 then M(1) must be 1 (amp[3] survives).
        // Without renorm, amp[0] and amp[3] would both be nonzero after first measure,
        // making the second measure probabilistic (anti-correlated outcomes possible).
        begin : test9_check
            reg t9_ok;
            t9_ok = 1;
            // All amplitudes other than amp[0] and amp[3] must be zero
            if (amp_re[1] != 0 || amp_re[2] != 0 || amp_re[4] != 0 ||
                amp_re[5] != 0 || amp_re[6] != 0 || amp_re[7] != 0) begin
                $display("  FAIL: Non-zero amplitude in unexpected slot");
                t9_ok = 0;
            end
            // Must not have BOTH amp[0] and amp[3] nonzero (means renorm failed)
            if (amp_re[0] != 0 && amp_re[3] != 0) begin
                $display("  FAIL: amp[0]=%0d amp[3]=%0d both nonzero (renorm not applied)",
                         amp_re[0], amp_re[3]);
                t9_ok = 0;
            end
            // Must have exactly one survivor
            if (amp_re[0] == 0 && amp_re[3] == 0) begin
                $display("  FAIL: Both amp[0] and amp[3] are zero");
                t9_ok = 0;
            end
            if (t9_ok) begin
                if (amp_re[0] != 0)
                    $display("  PASS: Correlated q0=q1=0, amp[0]=%0d", amp_re[0]);
                else
                    $display("  PASS: Correlated q0=q1=1, amp[3]=%0d", amp_re[3]);
                total_pass = total_pass + 1;
            end else
                total_fail = total_fail + 1;
        end

        // ===== Test 10: Repeated measurement idempotency =====
        $display("\n===== Test 10: Repeated measurement (H q0, MEASURE 0, MEASURE 0) =====");
        load_program(
            16'h1000, // RESET
            16'h2000, // H 0
            16'h6000, // MEASURE 0
            16'h6000, // MEASURE 0 again
            16'hF000, // HALT
            16'h0000, 16'h0000, 16'h0000
        );
        reset_and_wait;
        wait_for_halt;
        // After H + MEASURE: state collapses to |0> or |1> and is renormalized.
        // Second MEASURE on same qubit must give same outcome (idempotent).
        // Final state: amp[0] xor amp[1] nonzero; all others zero.
        begin : test10_check
            reg t10_ok;
            t10_ok = 1;
            if (amp_re[2] != 0 || amp_re[3] != 0 || amp_re[4] != 0 ||
                amp_re[5] != 0 || amp_re[6] != 0 || amp_re[7] != 0) begin
                $display("  FAIL: Non-zero amplitude in unexpected slot");
                t10_ok = 0;
            end
            if (amp_re[0] != 0 && amp_re[1] != 0) begin
                $display("  FAIL: amp[0]=%0d amp[1]=%0d both nonzero (second measure changed outcome)",
                         amp_re[0], amp_re[1]);
                t10_ok = 0;
            end
            if (amp_re[0] == 0 && amp_re[1] == 0) begin
                $display("  FAIL: Both amp[0] and amp[1] are zero");
                t10_ok = 0;
            end
            if (t10_ok) begin
                if (amp_re[0] != 0)
                    $display("  PASS: Idempotent, measured 0 twice, amp[0]=%0d", amp_re[0]);
                else
                    $display("  PASS: Idempotent, measured 1 twice, amp[1]=%0d", amp_re[1]);
                total_pass = total_pass + 1;
            end else
                total_fail = total_fail + 1;
        end

        // ===== Test 11: Shot mode — deterministic circuit =====
        $display("\n===== Test 11: Shot mode (SHOTS 3, X q0, MEASURE 0 x3) =====");
        load_program(
            16'h9003, // SHOTS 3
            16'hA000, // RUNSHOTS  -> body start = PC 2
            16'h1000, // RESET     <- shot body begin
            16'h3000, // X 0       -> |001>
            16'h6000, // MEASURE 0 -> always 1 (prob0=0)
            16'hF000, // HALT      -> rewind to PC 2 if shots remain
            16'h0000, 16'h0000
        );
        reset_and_wait;
        wait_for_halt;
        // X|000>=|001>, MEASURE q0 is always 1 (deterministic).
        // After 3 shots + renorm fix: final state amp[1]=16384, all others 0.
        check_amp(0, 16'sd0,     16'sd0, 0);
        check_amp(1, 16'sd16384, 16'sd0, 2);
        check_amp(2, 16'sd0,     16'sd0, 0);
        check_amp(3, 16'sd0,     16'sd0, 0);

        // ===== Summary =====
        $display("\n========================================");
        $display("TOTAL: %0d passed, %0d failed", total_pass, total_fail);
        if (total_fail == 0)
            $display(">>> ALL TESTS PASSED <<<");
        else
            $display(">>> SOME TESTS FAILED <<<");
        $display("========================================\n");

        $finish;
    end

    // Timeout watchdog
    initial begin
        #500_000_000;  // 500ms timeout
        $display("ERROR: Simulation timeout!");
        $finish;
    end

endmodule
