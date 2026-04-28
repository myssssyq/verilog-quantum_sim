// -----------------------------------------------------------------------------
// gate_engine.v
//
// Executes one native-basis gate on the 3-qubit state vector. Accepts a
// compact 3-bit gate_id from the decoder instead of a bundle of boolean flags.
//
// Supported gates (single-qubit, acting on qa):
//   GID_H, GID_X, GID_Z, GID_S, GID_SDG, GID_T, GID_TDG
//
// Supported 2-qubit gate:
//   GID_CNOT  (target=qa, control=qb)
//
// Strategy: iterate over the 4 amplitude pairs for qubit qa. For each pair
// (idx0, idx1) read both amplitudes, then in S_WRITE apply the gate-specific
// update.
//
// H is special: it needs two multipliers per real/imag pair (INV_SQRT2), so
// an extra S_MULT stage is used. All other gates complete in S_LOAD->S_WRITE.
// -----------------------------------------------------------------------------

module gate_engine(
    input                  clk,
    input                  rst,

    // Control
    input                  start,
    input      [2:0]       gate_id,    // GID_* encoding (see decoder.v)
    input      [1:0]       qa,         // target qubit
    input      [1:0]       qb,         // control qubit (CNOT only)
    output reg             done,

    // State vector ports
    output     [2:0]       sv_addr_a,
    output     [2:0]       sv_addr_b,
    input  signed [15:0]   sv_rd_a_re,
    input  signed [15:0]   sv_rd_a_im,
    input  signed [15:0]   sv_rd_b_re,
    input  signed [15:0]   sv_rd_b_im,
    output reg signed [15:0] sv_wd_a_re,
    output reg signed [15:0] sv_wd_a_im,
    output reg signed [15:0] sv_wd_b_re,
    output reg signed [15:0] sv_wd_b_im,
    output reg             sv_we_a,
    output reg             sv_we_b
);

    // gate_id values — must match decoder.v localparams
    localparam GID_H    = 3'd0;
    localparam GID_X    = 3'd1;
    localparam GID_Z    = 3'd2;
    localparam GID_S    = 3'd3;
    localparam GID_SDG  = 3'd4;
    localparam GID_T    = 3'd5;
    localparam GID_TDG  = 3'd6;
    localparam GID_CNOT = 3'd7;

    // FSM states
    localparam S_IDLE  = 3'd0;
    localparam S_LOAD  = 3'd1;  // read data from sv is valid this cycle
    localparam S_MULT  = 3'd2;  // H only: latch multiply results
    localparam S_WRITE = 3'd3;  // assert write enable + data
    localparam S_NEXT  = 3'd4;  // advance pair counter or finish

    reg [2:0] state;
    reg [1:0] pair_cnt;

    // Latched operands / control (stable during gate execution)
    reg        [2:0] lat_gate_id;
    reg        [1:0] lat_qa, lat_qb;
    reg signed [15:0] lat_a_re, lat_a_im;
    reg signed [15:0] lat_b_re, lat_b_im;
    reg              lat_ctrl_set;   // CNOT: control bit of idx0

    // -----------------------------------------------------------
    // Pair index generation
    //   For qubit lat_qa, the four pairs differ only in bit lat_qa.
    //   idx0 has bit lat_qa = 0, idx1 has it = 1.
    // -----------------------------------------------------------
    wire [2:0] idx0;
    wire [2:0] idx1;

    assign idx0 = (lat_qa == 2'd0) ? {pair_cnt[1], pair_cnt[0], 1'b0} :
                  (lat_qa == 2'd1) ? {pair_cnt[1], 1'b0, pair_cnt[0]} :
                                     {1'b0, pair_cnt[1], pair_cnt[0]};
    assign idx1 = idx0 | (3'b001 << lat_qa);

    // Addresses are combinational — read data valid in the same cycle.
    assign sv_addr_a = idx0;
    assign sv_addr_b = idx1;

    // -----------------------------------------------------------
    // H gate butterfly: new0 = (a+b)/sqrt(2), new1 = (a-b)/sqrt(2)
    // -----------------------------------------------------------
    localparam signed [15:0] INV_SQRT2 = 16'sd11585;   // 1/sqrt(2) in Q2.14

    reg signed [15:0] sum_re, sum_im, diff_re, diff_im;

    wire signed [31:0] prod_sum_re  = sum_re  * INV_SQRT2;
    wire signed [31:0] prod_sum_im  = sum_im  * INV_SQRT2;
    wire signed [31:0] prod_diff_re = diff_re * INV_SQRT2;
    wire signed [31:0] prod_diff_im = diff_im * INV_SQRT2;

    // Truncate Q4.28 -> Q2.14
    wire signed [15:0] h_new0_re = prod_sum_re[29:14];
    wire signed [15:0] h_new0_im = prod_sum_im[29:14];
    wire signed [15:0] h_new1_re = prod_diff_re[29:14];
    wire signed [15:0] h_new1_im = prod_diff_im[29:14];

    // -----------------------------------------------------------
    // T / Tdg: multiply idx1 amplitude by (cos45 ± i sin45).
    //   T   : (re + i*im) * (c + i*s) = (re*c - im*s) + i*(re*s + im*c)
    //   Tdg : (re + i*im) * (c - i*s) = (re*c + im*s) + i*(-re*s + im*c)
    // with c = s = 1/sqrt(2).
    // -----------------------------------------------------------
    wire signed [31:0] t_re_c = lat_b_re * INV_SQRT2;
    wire signed [31:0] t_im_c = lat_b_im * INV_SQRT2;
    wire signed [31:0] t_re_s = lat_b_re * INV_SQRT2;  // semantic alias
    wire signed [31:0] t_im_s = lat_b_im * INV_SQRT2;

    wire signed [15:0] t_new_re   = t_re_c[29:14] - t_im_s[29:14];
    wire signed [15:0] t_new_im   = t_re_s[29:14] + t_im_c[29:14];
    wire signed [15:0] tdg_new_re = t_re_c[29:14] + t_im_s[29:14];
    wire signed [15:0] tdg_new_im = t_im_c[29:14] - t_re_s[29:14];

    // -----------------------------------------------------------
    // Main FSM
    // -----------------------------------------------------------
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            state       <= S_IDLE;
            done        <= 1'b0;
            sv_we_a     <= 1'b0;
            sv_we_b     <= 1'b0;
            pair_cnt    <= 2'd0;
            lat_qa      <= 2'd0;
            lat_qb      <= 2'd0;
            lat_gate_id <= 3'd0;
        end else begin
            done    <= 1'b0;
            sv_we_a <= 1'b0;
            sv_we_b <= 1'b0;

            case (state)
                S_IDLE: begin
                    if (start) begin
                        pair_cnt    <= 2'd0;
                        lat_gate_id <= gate_id;
                        lat_qa      <= qa;
                        lat_qb      <= qb;
                        state       <= S_LOAD;
                    end
                end

                S_LOAD: begin
                    // Read data is valid (addresses are combinational).
                    lat_a_re     <= sv_rd_a_re;
                    lat_a_im     <= sv_rd_a_im;
                    lat_b_re     <= sv_rd_b_re;
                    lat_b_im     <= sv_rd_b_im;
                    lat_ctrl_set <= idx0[lat_qb];

                    if (lat_gate_id == GID_H) begin
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
                    state      <= S_WRITE;
                end

                S_WRITE: begin
                    sv_we_a <= 1'b1;
                    sv_we_b <= 1'b1;

                    case (lat_gate_id)
                        // H: write data already staged in S_MULT; do nothing.
                        GID_H: ;

                        GID_X: begin
                            sv_wd_a_re <= lat_b_re;
                            sv_wd_a_im <= lat_b_im;
                            sv_wd_b_re <= lat_a_re;
                            sv_wd_b_im <= lat_a_im;
                        end

                        GID_Z: begin
                            sv_wd_a_re <= lat_a_re;
                            sv_wd_a_im <= lat_a_im;
                            sv_wd_b_re <= -lat_b_re;
                            sv_wd_b_im <= -lat_b_im;
                        end

                        GID_S: begin
                            // idx1 *= i  -> (re + i*im) -> (-im + i*re)
                            sv_wd_a_re <=  lat_a_re;
                            sv_wd_a_im <=  lat_a_im;
                            sv_wd_b_re <= -lat_b_im;
                            sv_wd_b_im <=  lat_b_re;
                        end

                        GID_SDG: begin
                            // idx1 *= -i -> (re + i*im) -> (im - i*re)
                            sv_wd_a_re <=  lat_a_re;
                            sv_wd_a_im <=  lat_a_im;
                            sv_wd_b_re <=  lat_b_im;
                            sv_wd_b_im <= -lat_b_re;
                        end

                        GID_T: begin
                            sv_wd_a_re <= lat_a_re;
                            sv_wd_a_im <= lat_a_im;
                            sv_wd_b_re <= t_new_re;
                            sv_wd_b_im <= t_new_im;
                        end

                        GID_TDG: begin
                            sv_wd_a_re <= lat_a_re;
                            sv_wd_a_im <= lat_a_im;
                            sv_wd_b_re <= tdg_new_re;
                            sv_wd_b_im <= tdg_new_im;
                        end

                        GID_CNOT: begin
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

                        default: begin
                            // Unknown gate_id: pass-through (no state change).
                            sv_wd_a_re <= lat_a_re;
                            sv_wd_a_im <= lat_a_im;
                            sv_wd_b_re <= lat_b_re;
                            sv_wd_b_im <= lat_b_im;
                        end
                    endcase

                    state <= S_NEXT;
                end

                S_NEXT: begin
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
