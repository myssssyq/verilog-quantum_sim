module qsim(
    input  wire clk,
    input  wire btn_n,
    output wire [5:0] led,
    output wire uart_tx
);

    // -------------------------------------------------------
    // Reset
    // -------------------------------------------------------
    wire rst;
    reset_gen u_rst(.clk(clk), .btn_n(btn_n), .rst(rst));

    // -------------------------------------------------------
    // Program Counter
    // -------------------------------------------------------
    wire [7:0] pc_out;
    reg        pc_hold;
    reg        pc_load;
    reg  [7:0] pc_in;
    pc u_pc(.clk(clk), .rst(rst), .hold(pc_hold),
            .load(pc_load), .pcIn(pc_in), .pcOut(pc_out));

    // -------------------------------------------------------
    // Instruction Memory
    // -------------------------------------------------------
    wire [15:0] instr;
    imem u_imem(.addr(pc_out), .instr(instr));

    // -------------------------------------------------------
    // Decoder
    // -------------------------------------------------------
    wire [3:0] opcode;
    wire [1:0] qa, qb;
    wire [7:0] imm;
    wire is_gate, is_h, is_x, is_z, is_cnot;
    wire is_measure, is_dump, is_reset_instr, is_initbasis;
    wire is_shots, is_runshots, is_halt;
    decoder u_dec(
        .instr(instr), .opcode(opcode), .qa(qa), .qb(qb), .imm(imm),
        .is_gate(is_gate), .is_h(is_h), .is_x(is_x), .is_z(is_z),
        .is_cnot(is_cnot), .is_measure(is_measure), .is_dump(is_dump),
        .is_reset(is_reset_instr), .is_initbasis(is_initbasis),
        .is_shots(is_shots), .is_runshots(is_runshots), .is_halt(is_halt)
    );

    // -------------------------------------------------------
    // State Vector — port mux signals
    // -------------------------------------------------------
    reg  [2:0]        sv_raddr_a, sv_raddr_b;
    wire signed [15:0] sv_rdata_a_re, sv_rdata_a_im;
    wire signed [15:0] sv_rdata_b_re, sv_rdata_b_im;
    reg               sv_we_a, sv_we_b;
    reg  signed [15:0] sv_wdata_a_re, sv_wdata_a_im;
    reg  signed [15:0] sv_wdata_b_re, sv_wdata_b_im;
    reg               sv_init_reset, sv_init_basis;

    state_vec u_sv(
        .clk(clk),
        .raddr_a(sv_raddr_a), .raddr_b(sv_raddr_b),
        .rdata_a_re(sv_rdata_a_re), .rdata_a_im(sv_rdata_a_im),
        .rdata_b_re(sv_rdata_b_re), .rdata_b_im(sv_rdata_b_im),
        .we_a(sv_we_a), .we_b(sv_we_b),
        .wdata_a_re(sv_wdata_a_re), .wdata_a_im(sv_wdata_a_im),
        .wdata_b_re(sv_wdata_b_re), .wdata_b_im(sv_wdata_b_im),
        .init_reset(sv_init_reset), .init_basis(sv_init_basis),
        .init_state(imm[2:0])
    );

    // -------------------------------------------------------
    // Gate Engine
    // -------------------------------------------------------
    reg         ge_start;
    wire        ge_done;
    wire [2:0]  ge_addr_a, ge_addr_b;
    wire signed [15:0] ge_wd_a_re, ge_wd_a_im;
    wire signed [15:0] ge_wd_b_re, ge_wd_b_im;
    wire        ge_we_a, ge_we_b;

    gate_engine u_ge(
        .clk(clk), .rst(rst),
        .start(ge_start), .is_h(is_h), .is_x(is_x), .is_z(is_z), .is_cnot(is_cnot),
        .qa(qa), .qb(qb), .done(ge_done),
        .sv_addr_a(ge_addr_a), .sv_addr_b(ge_addr_b),
        .sv_rd_a_re(sv_rdata_a_re), .sv_rd_a_im(sv_rdata_a_im),
        .sv_rd_b_re(sv_rdata_b_re), .sv_rd_b_im(sv_rdata_b_im),
        .sv_wd_a_re(ge_wd_a_re), .sv_wd_a_im(ge_wd_a_im),
        .sv_wd_b_re(ge_wd_b_re), .sv_wd_b_im(ge_wd_b_im),
        .sv_we_a(ge_we_a), .sv_we_b(ge_we_b)
    );

    // -------------------------------------------------------
    // Measure Unit
    // -------------------------------------------------------
    reg         mu_start;
    wire        mu_done;
    wire        mu_result;
    wire [2:0]  mu_addr_a;
    wire signed [15:0] mu_wd_a_re, mu_wd_a_im;
    wire        mu_we_a;

    measure_unit u_mu(
        .clk(clk), .rst(rst),
        .start(mu_start), .qa(qa), .done(mu_done), .result(mu_result),
        .sv_addr_a(mu_addr_a),
        .sv_rd_a_re(sv_rdata_a_re), .sv_rd_a_im(sv_rdata_a_im),
        .sv_wd_a_re(mu_wd_a_re), .sv_wd_a_im(mu_wd_a_im),
        .sv_we_a(mu_we_a)
    );

    // -------------------------------------------------------
    // UART
    // -------------------------------------------------------
    wire        uart_busy;
    wire        pr_uart_wr;
    wire [7:0]  pr_uart_data;
    wire        pr_busy;
    wire [2:0]  pr_sv_addr;

    uart_tx #(.DIV(234)) u_uart(
        .clk(clk), .wr(pr_uart_wr), .data(pr_uart_data),
        .busy(uart_busy), .tx(uart_tx)
    );

    reg  pr_print_state;
    reg  pr_print_meas;

    uart_printer u_pr(
        .clk(clk), .rst(rst),
        .print_state(pr_print_state), .print_meas(pr_print_meas),
        .meas_qubit(qa), .meas_result(mu_result),
        .busy(pr_busy),
        .sv_addr(pr_sv_addr),
        .sv_rd_re(sv_rdata_a_re), .sv_rd_im(sv_rdata_a_im),
        .uart_wr(pr_uart_wr), .uart_data(pr_uart_data),
        .uart_busy(uart_busy)
    );

    // -------------------------------------------------------
    // State vector port mux
    // -------------------------------------------------------
    // Owner: 0=none, 1=gate_engine, 2=measure_unit, 3=printer
    reg [1:0] sv_owner;

    always @(*) begin
        sv_raddr_a   = 3'd0;
        sv_raddr_b   = 3'd0;
        sv_we_a      = 1'b0;
        sv_we_b      = 1'b0;
        sv_wdata_a_re= 16'sh0000;
        sv_wdata_a_im= 16'sh0000;
        sv_wdata_b_re= 16'sh0000;
        sv_wdata_b_im= 16'sh0000;

        case (sv_owner)
            2'd1: begin // gate_engine
                sv_raddr_a    = ge_addr_a;
                sv_raddr_b    = ge_addr_b;
                sv_we_a       = ge_we_a;
                sv_we_b       = ge_we_b;
                sv_wdata_a_re = ge_wd_a_re;
                sv_wdata_a_im = ge_wd_a_im;
                sv_wdata_b_re = ge_wd_b_re;
                sv_wdata_b_im = ge_wd_b_im;
            end
            2'd2: begin // measure_unit (A-side only)
                sv_raddr_a    = mu_addr_a;
                sv_we_a       = mu_we_a;
                sv_wdata_a_re = mu_wd_a_re;
                sv_wdata_a_im = mu_wd_a_im;
            end
            2'd3: begin // printer (read-only)
                sv_raddr_a    = pr_sv_addr;
                sv_raddr_b    = 3'd0;
            end
            default: ;
        endcase
    end

    // -------------------------------------------------------
    // Master FSM
    // -------------------------------------------------------
    localparam Q_INIT    = 4'd0;
    localparam Q_FETCH   = 4'd1;
    localparam Q_DECODE  = 4'd2;
    localparam Q_WAIT    = 4'd3;   // wait for sub-engine done
    localparam Q_DUMP    = 4'd5;   // DUMPSTATE: start printer
    localparam Q_DUMP_W  = 4'd6;   // wait for printer done
    localparam Q_MEAS    = 4'd7;   // MEASURE: start measure_unit
    localparam Q_MEAS_W  = 4'd8;   // wait for measure done
    localparam Q_MEAS_PR = 4'd9;   // print measurement result
    localparam Q_MEAS_PW = 4'd10;  // wait for print done
    localparam Q_ADVANCE = 4'd11;
    localparam Q_HALT    = 4'd12;

    reg [3:0] mstate;

    // Shot counting
    reg [7:0] shot_count;
    reg [7:0] shot_remain;
    reg       in_shots;
    reg [7:0] shot_start_pc;  // PC of first instruction in shot body

    // Heartbeat
    reg [24:0] blink;
    always @(posedge clk) blink <= blink + 1;

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            mstate         <= Q_INIT;
            pc_hold        <= 1'b1;
            pc_load        <= 1'b0;
            pc_in          <= 8'd0;
            ge_start       <= 1'b0;
            mu_start       <= 1'b0;
            pr_print_state <= 1'b0;
            pr_print_meas  <= 1'b0;
            sv_init_reset  <= 1'b0;
            sv_init_basis  <= 1'b0;
            sv_owner       <= 2'd0;
            shot_count     <= 8'd0;
            shot_remain    <= 8'd0;
            in_shots       <= 1'b0;
            shot_start_pc  <= 8'd0;
        end else begin
            // Default: deassert pulses
            ge_start       <= 1'b0;
            mu_start       <= 1'b0;
            pr_print_state <= 1'b0;
            pr_print_meas  <= 1'b0;
            sv_init_reset  <= 1'b0;
            sv_init_basis  <= 1'b0;
            pc_load        <= 1'b0;

            case (mstate)
                Q_INIT: begin
                    // Initialize state to |000>
                    sv_init_reset <= 1'b1;
                    pc_hold       <= 1'b1;
                    mstate        <= Q_FETCH;
                end

                Q_FETCH: begin
                    // PC output is valid, instruction is on the bus
                    pc_hold <= 1'b1;
                    mstate  <= Q_DECODE;
                end

                Q_DECODE: begin
                    // Instruction decoded combinationally; dispatch
                    if (is_reset_instr) begin
                        sv_init_reset <= 1'b1;
                        mstate        <= Q_ADVANCE;
                    end else if (is_initbasis) begin
                        sv_init_basis <= 1'b1;
                        mstate        <= Q_ADVANCE;
                    end else if (is_gate) begin
                        ge_start <= 1'b1;
                        sv_owner <= 2'd1;
                        mstate   <= Q_WAIT;
                    end else if (is_measure) begin
                        mu_start <= 1'b1;
                        sv_owner <= 2'd2;
                        mstate   <= Q_MEAS;
                    end else if (is_dump) begin
                        sv_owner       <= 2'd3;
                        pr_print_state <= 1'b1;
                        mstate         <= Q_DUMP;
                    end else if (is_shots) begin
                        shot_count <= imm;
                        mstate     <= Q_ADVANCE;
                    end else if (is_runshots) begin
                        // Record body start = instruction immediately after RUNSHOTS
                        shot_start_pc  <= pc_out + 8'd1;
                        shot_remain    <= shot_count;
                        in_shots       <= 1'b1;
                        pc_load        <= 1'b1;
                        pc_in          <= pc_out + 8'd1;
                        mstate         <= Q_FETCH;
                    end else if (is_halt) begin
                        if (in_shots && shot_remain > 8'd1) begin
                            // More shots remaining: rewind to shot body start.
                            // The body's own RESET instruction clears state.
                            shot_remain <= shot_remain - 8'd1;
                            pc_load     <= 1'b1;
                            pc_in       <= shot_start_pc;
                            mstate      <= Q_FETCH;
                        end else begin
                            in_shots <= 1'b0;
                            mstate   <= Q_HALT;
                        end
                    end else begin
                        // NOP or unknown: advance
                        mstate <= Q_ADVANCE;
                    end
                end

                Q_WAIT: begin
                    // Wait for gate engine
                    if (ge_done) begin
                        sv_owner <= 2'd0;
                        mstate   <= Q_ADVANCE;
                    end
                end

                Q_MEAS: begin
                    // Wait one cycle for mu_start pulse to propagate
                    mstate <= Q_MEAS_W;
                end

                Q_MEAS_W: begin
                    if (mu_done) begin
                        // Print the result
                        sv_owner      <= 2'd3;
                        pr_print_meas <= 1'b1;
                        mstate        <= Q_MEAS_PR;
                    end
                end

                Q_MEAS_PR: begin
                    // Wait one cycle for print_meas pulse to propagate,
                    // then wait for printer to finish
                    if (pr_busy) begin
                        mstate <= Q_MEAS_PW;
                    end
                end

                Q_MEAS_PW: begin
                    // Wait for measurement print done
                    if (!pr_busy) begin
                        sv_owner <= 2'd0;
                        mstate   <= Q_ADVANCE;
                    end
                end

                Q_DUMP: begin
                    // Wait one cycle for print_state pulse to propagate,
                    // then wait for printer to finish
                    if (pr_busy) begin
                        mstate <= Q_DUMP_W;
                    end
                end

                Q_DUMP_W: begin
                    // Wait for DUMPSTATE print done
                    if (!pr_busy) begin
                        sv_owner <= 2'd0;
                        mstate   <= Q_ADVANCE;
                    end
                end

                Q_ADVANCE: begin
                    // Let PC increment
                    pc_hold <= 1'b0;
                    mstate  <= Q_FETCH;
                end

                Q_HALT: begin
                    pc_hold <= 1'b1;
                    // Stay halted
                end

                default: mstate <= Q_INIT;
            endcase
        end
    end

    // -------------------------------------------------------
    // LEDs
    // -------------------------------------------------------
    assign led[0] = ~blink[24];                        // heartbeat
    assign led[1] = (mstate == Q_HALT) ? 1'b0 : 1'b1; // lit when halted
    assign led[2] = ~uart_tx;                          // UART activity
    assign led[3] = ~blink[23];
    assign led[4] = 1'b1;
    assign led[5] = 1'b1;

endmodule
