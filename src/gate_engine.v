module gate_engine(
    input             clk,
    input             rst,
    // Control
    input             start,
    input             is_h,
    input             is_x,
    input             is_z,
    input             is_cnot,
    input      [1:0]  qa,       // target qubit (or single-qubit gate target)
    input      [1:0]  qb,       // control qubit (CNOT only)
    output reg        done,
    // State vector ports (addresses are combinational outputs)
    output     [2:0]  sv_addr_a,
    output     [2:0]  sv_addr_b,
    input  signed [15:0] sv_rd_a_re,
    input  signed [15:0] sv_rd_a_im,
    input  signed [15:0] sv_rd_b_re,
    input  signed [15:0] sv_rd_b_im,
    output reg signed [15:0] sv_wd_a_re,
    output reg signed [15:0] sv_wd_a_im,
    output reg signed [15:0] sv_wd_b_re,
    output reg signed [15:0] sv_wd_b_im,
    output reg        sv_we_a,
    output reg        sv_we_b
);

    // FSM states
    localparam S_IDLE  = 3'd0;
    localparam S_LOAD  = 3'd1;  // latch read data (addr already valid combinationally)
    localparam S_MULT  = 3'd2;  // H gate: latch multiply results
    localparam S_WRITE = 3'd3;  // assert write enable + data
    localparam S_NEXT  = 3'd4;  // advance pair counter or finish

    reg [2:0] state;
    reg [1:0] pair_cnt;  // 0..3: four amplitude pairs per gate

    // Latched read data
    reg signed [15:0] lat_a_re, lat_a_im;
    reg signed [15:0] lat_b_re, lat_b_im;
    reg        lat_ctrl_set;  // CNOT: is control bit set in idx0?

    // Latched gate type (stable during execution)
    reg lat_is_h, lat_is_x, lat_is_z, lat_is_cnot;
    reg [1:0] lat_qa, lat_qb;

    // --- Pair index generation (combinational) ---
    // For qubit qa, insert 0 at bit position qa into 2-bit counter pair_cnt
    // idx0: bit qa = 0, idx1: bit qa = 1
    wire [2:0] idx0;
    wire [2:0] idx1;

    assign idx0 = (lat_qa == 2'd0) ? {pair_cnt[1], pair_cnt[0], 1'b0} :
                  (lat_qa == 2'd1) ? {pair_cnt[1], 1'b0, pair_cnt[0]} :
                                     {1'b0, pair_cnt[1], pair_cnt[0]};
    assign idx1 = idx0 | (3'b001 << lat_qa);

    // --- Address outputs are combinational (not registered) ---
    // This ensures read data is valid in the same cycle
    assign sv_addr_a = idx0;
    assign sv_addr_b = idx1;

    // --- H gate: 1/sqrt(2) = 11585 in Q2.14 ---
    localparam signed [15:0] INV_SQRT2 = 16'sd11585;

    // Sum and difference for H gate butterfly
    reg signed [15:0] sum_re, sum_im, diff_re, diff_im;

    // Combinational multipliers (4 parallel, uses DSP blocks)
    wire signed [31:0] prod_sum_re  = sum_re  * INV_SQRT2;
    wire signed [31:0] prod_sum_im  = sum_im  * INV_SQRT2;
    wire signed [31:0] prod_diff_re = diff_re * INV_SQRT2;
    wire signed [31:0] prod_diff_im = diff_im * INV_SQRT2;

    // Truncate Q4.28 -> Q2.14: take bits [29:14]
    wire signed [15:0] h_new0_re = prod_sum_re[29:14];
    wire signed [15:0] h_new0_im = prod_sum_im[29:14];
    wire signed [15:0] h_new1_re = prod_diff_re[29:14];
    wire signed [15:0] h_new1_im = prod_diff_im[29:14];

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            state    <= S_IDLE;
            done     <= 1'b0;
            sv_we_a  <= 1'b0;
            sv_we_b  <= 1'b0;
            pair_cnt <= 2'd0;
            lat_qa   <= 2'd0;
            lat_qb   <= 2'd0;
        end else begin
            done    <= 1'b0;
            sv_we_a <= 1'b0;
            sv_we_b <= 1'b0;

            case (state)
                S_IDLE: begin
                    if (start) begin
                        pair_cnt   <= 2'd0;
                        lat_is_h   <= is_h;
                        lat_is_x   <= is_x;
                        lat_is_z   <= is_z;
                        lat_is_cnot<= is_cnot;
                        lat_qa     <= qa;
                        lat_qb     <= qb;
                        state      <= S_LOAD;
                    end
                end

                S_LOAD: begin
                    // Addresses are combinational from idx0/idx1, read data valid now
                    lat_a_re <= sv_rd_a_re;
                    lat_a_im <= sv_rd_a_im;
                    lat_b_re <= sv_rd_b_re;
                    lat_b_im <= sv_rd_b_im;
                    lat_ctrl_set <= idx0[lat_qb];

                    if (lat_is_h) begin
                        sum_re  <= sv_rd_a_re + sv_rd_b_re;
                        sum_im  <= sv_rd_a_im + sv_rd_b_im;
                        diff_re <= sv_rd_a_re - sv_rd_b_re;
                        diff_im <= sv_rd_a_im - sv_rd_b_im;
                        state   <= S_MULT;
                    end else begin
                        state <= S_WRITE;
                    end
                end

                S_MULT: begin
                    // H gate: multiply results available combinationally from
                    // registered sum/diff. Latch into write data.
                    sv_wd_a_re <= h_new0_re;
                    sv_wd_a_im <= h_new0_im;
                    sv_wd_b_re <= h_new1_re;
                    sv_wd_b_im <= h_new1_im;
                    state <= S_WRITE;
                end

                S_WRITE: begin
                    // Assert write enable. Address is still idx0/idx1
                    // (pair_cnt hasn't changed, so combinational addr is stable).
                    // Write takes effect at next posedge when we_a/we_b=1.
                    sv_we_a <= 1'b1;
                    sv_we_b <= 1'b1;

                    if (lat_is_x) begin
                        sv_wd_a_re <= lat_b_re;
                        sv_wd_a_im <= lat_b_im;
                        sv_wd_b_re <= lat_a_re;
                        sv_wd_b_im <= lat_a_im;
                    end else if (lat_is_z) begin
                        sv_wd_a_re <= lat_a_re;
                        sv_wd_a_im <= lat_a_im;
                        sv_wd_b_re <= -lat_b_re;
                        sv_wd_b_im <= -lat_b_im;
                    end else if (lat_is_cnot) begin
                        if (lat_ctrl_set) begin
                            sv_wd_a_re <= lat_b_re;
                            sv_wd_a_im <= lat_b_im;
                            sv_wd_b_re <= lat_a_re;
                            sv_wd_b_im <= lat_a_im;
                        end else begin
                            sv_wd_a_re <= lat_a_re;
                            sv_wd_a_im <= lat_a_im;
                            sv_wd_b_re <= lat_b_re;
                            sv_wd_b_im <= lat_b_im;
                        end
                    end
                    // H gate: wd already set in S_MULT (retained)

                    state <= S_NEXT;
                end

                S_NEXT: begin
                    // we_a/we_b=1 takes effect at THIS posedge (from S_WRITE).
                    // Addresses still point to idx0/idx1 since pair_cnt is
                    // updated at the END of this posedge (NBA). So the write
                    // to state_vec uses the correct old address. Safe.
                    if (pair_cnt == 2'd3) begin
                        done  <= 1'b1;
                        state <= S_IDLE;
                    end else begin
                        pair_cnt <= pair_cnt + 2'd1;
                        state    <= S_LOAD;
                    end
                end

                default: state <= S_IDLE;
            endcase
        end
    end
endmodule
