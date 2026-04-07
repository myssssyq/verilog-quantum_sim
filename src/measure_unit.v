module measure_unit(
    input             clk,
    input             rst,
    input             start,
    input      [1:0]  qa,          // qubit to measure
    output reg        done,
    output reg        result,      // measurement outcome: 0 or 1
    // State vector interface (A-side only; registered addresses, 2-phase)
    output reg [2:0]  sv_addr_a,
    input  signed [15:0] sv_rd_a_re,
    input  signed [15:0] sv_rd_a_im,
    output reg signed [15:0] sv_wd_a_re,
    output reg signed [15:0] sv_wd_a_im,
    output reg        sv_we_a
);

    // FSM states
    localparam M_IDLE      = 4'd0;
    localparam M_ACC_ADDR  = 4'd1;  // set read address for accumulation
    localparam M_ACC_CALC  = 4'd2;  // read valid, compute |amp|^2, accumulate
    localparam M_THRESH    = 4'd3;  // compare LFSR to prob0, decide outcome + capture p_keep
    localparam M_COLL_ADDR = 4'd4;  // set read address for collapse
    localparam M_COLL_WR   = 4'd5;  // read valid, apply renorm, write result
    localparam M_DONE      = 4'd6;

    reg [3:0] state;
    reg [2:0] idx;           // iterates 0..7
    reg [1:0] lat_qa;

    // Probability accumulators (Q4.28 unsigned)
    reg [31:0] prob0, prob1;

    // Kept probability for renormalization
    reg [31:0] p_keep;

    // Squared magnitude of current amplitude: re*re + im*im (Q4.28)
    wire signed [31:0] sq_re = sv_rd_a_re * sv_rd_a_re;
    wire signed [31:0] sq_im = sv_rd_a_im * sv_rd_a_im;
    wire [31:0] amp_sq = sq_re[31:0] + sq_im[31:0];

    // -----------------------------------------------------------
    // 16-bit LFSR (Fibonacci, maximal-length)
    // Polynomial: x^16 + x^15 + x^13 + x^4 + 1
    // -----------------------------------------------------------
    reg [15:0] lfsr;
    wire lfsr_fb = lfsr[15] ^ lfsr[14] ^ lfsr[12] ^ lfsr[3];
    always @(posedge clk or posedge rst) begin
        if (rst) lfsr <= 16'hACE1;
        else     lfsr <= {lfsr[14:0], lfsr_fb};
    end

    // -----------------------------------------------------------
    // Renormalization LUT
    //   Index: p_keep[27:23] (5 bits = 32 entries)
    //   Output: 1/sqrt(p_keep) in Q3.13 (value * 2^-13 = float)
    //
    //   Q3.13 range [0, 7.9999], handles p >= 0.125 (renorm <= 2.83)
    //   Used in M_COLL_WR: signed_amp * renorm_factor, take bits [28:13]
    //   This gives Q2.14 result. Safe because |amp|^2 <= p_keep always.
    // -----------------------------------------------------------
    reg [15:0] renorm_factor;
    always @(*) begin
        if (p_keep[28]) begin
            // p_keep >= 1.0 in Q4.28: deterministic measurement, no scaling needed
            renorm_factor = 16'd8192;  // 1.0 in Q3.13
        end else begin
        case (p_keep[27:23])
            // p < 0.125: cap at sqrt(8) = 2.828 (won't occur in normal circuits)
            5'd0:  renorm_factor = 16'd23170;
            5'd1:  renorm_factor = 16'd23170;
            5'd2:  renorm_factor = 16'd23170;
            5'd3:  renorm_factor = 16'd23170;
            // p in [0.125, 0.250)
            5'd4:  renorm_factor = 16'd23170;  // 0.1250 → 2.8284
            5'd5:  renorm_factor = 16'd20730;  // 0.1563 → 2.5298
            5'd6:  renorm_factor = 16'd18919;  // 0.1875 → 2.3094
            5'd7:  renorm_factor = 16'd17519;  // 0.2188 → 2.1381
            // p in [0.250, 0.500)
            5'd8:  renorm_factor = 16'd16384;  // 0.2500 → 2.0000
            5'd9:  renorm_factor = 16'd15444;  // 0.2813 → 1.8856
            5'd10: renorm_factor = 16'd14654;  // 0.3125 → 1.7889
            5'd11: renorm_factor = 16'd13973;  // 0.3438 → 1.7057
            5'd12: renorm_factor = 16'd13378;  // 0.3750 → 1.6330
            5'd13: renorm_factor = 16'd12856;  // 0.4063 → 1.5693
            5'd14: renorm_factor = 16'd12386;  // 0.4375 → 1.5119
            5'd15: renorm_factor = 16'd11970;  // 0.4688 → 1.4606
            // p in [0.500, 1.000)
            5'd16: renorm_factor = 16'd11585;  // 0.5000 → 1.4142  (Bell/GHZ common case)
            5'd17: renorm_factor = 16'd11246;  // 0.5313 → 1.3725
            5'd18: renorm_factor = 16'd10923;  // 0.5625 → 1.3333
            5'd19: renorm_factor = 16'd10631;  // 0.5938 → 1.2978
            5'd20: renorm_factor = 16'd10362;  // 0.6250 → 1.2649
            5'd21: renorm_factor = 16'd10113;  // 0.6563 → 1.2344
            5'd22: renorm_factor = 16'd9880;   // 0.6875 → 1.2060
            5'd23: renorm_factor = 16'd9663;   // 0.7188 → 1.1796
            5'd24: renorm_factor = 16'd9459;   // 0.7500 → 1.1547
            5'd25: renorm_factor = 16'd9270;   // 0.7813 → 1.1314
            5'd26: renorm_factor = 16'd9089;   // 0.8125 → 1.1094
            5'd27: renorm_factor = 16'd8924;   // 0.8438 → 1.0893
            5'd28: renorm_factor = 16'd8757;   // 0.8750 → 1.0690
            5'd29: renorm_factor = 16'd8611;   // 0.9063 → 1.0512
            5'd30: renorm_factor = 16'd8460;   // 0.9375 → 1.0328
            5'd31: renorm_factor = 16'd8321;   // 0.9688 → 1.0157
            default: renorm_factor = 16'd8192; // 1.0 in Q3.13 (fallback)
        endcase
        end
    end

    // Combinational renorm multipliers (active in M_COLL_WR)
    // Q2.14 signed × Q3.13 unsigned → 33-bit signed product → take [28:13] = Q2.14
    wire signed [32:0] rprod_re = $signed(sv_rd_a_re) * $signed({1'b0, renorm_factor});
    wire signed [32:0] rprod_im = $signed(sv_rd_a_im) * $signed({1'b0, renorm_factor});
    wire signed [15:0] rnorm_re = rprod_re[28:13];
    wire signed [15:0] rnorm_im = rprod_im[28:13];

    // -----------------------------------------------------------
    // Main FSM
    // -----------------------------------------------------------
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            state    <= M_IDLE;
            done     <= 1'b0;
            sv_we_a  <= 1'b0;
            sv_addr_a<= 3'd0;
            result   <= 1'b0;
            p_keep   <= 32'd0;
        end else begin
            done    <= 1'b0;
            sv_we_a <= 1'b0;

            case (state)
                M_IDLE: begin
                    if (start) begin
                        lat_qa <= qa;
                        prob0  <= 32'd0;
                        prob1  <= 32'd0;
                        idx    <= 3'd0;
                        state  <= M_ACC_ADDR;
                    end
                end

                // --- Accumulation phase ---
                M_ACC_ADDR: begin
                    sv_addr_a <= idx;
                    state     <= M_ACC_CALC;
                end

                M_ACC_CALC: begin
                    // Address was set last cycle; read data is valid
                    if (idx[lat_qa] == 1'b0)
                        prob0 <= prob0 + amp_sq;
                    else
                        prob1 <= prob1 + amp_sq;

                    if (idx == 3'd7) begin
                        state <= M_THRESH;
                    end else begin
                        idx   <= idx + 3'd1;
                        state <= M_ACC_ADDR;
                    end
                end

                // --- Threshold decision + capture p_keep ---
                M_THRESH: begin
                    // {lfsr, 12'd0} scales LFSR to Q4.28 range [0, 2^28)
                    if ({lfsr, 12'd0} < prob0) begin
                        result <= 1'b0;
                        p_keep <= prob0;
                    end else begin
                        result <= 1'b1;
                        p_keep <= prob1;
                    end
                    idx   <= 3'd0;
                    state <= M_COLL_ADDR;
                end

                // --- Collapse + renormalization phase ---
                M_COLL_ADDR: begin
                    sv_addr_a <= idx;
                    state     <= M_COLL_WR;
                end

                M_COLL_WR: begin
                    // Address was set last cycle; read data valid.
                    // Renorm multipliers (rnorm_re, rnorm_im) are combinational
                    // from sv_rd_a_re/im and renorm_factor (stable since p_keep is a reg).
                    sv_we_a <= 1'b1;

                    if (idx[lat_qa] != result) begin
                        // Losing side: zero out
                        sv_wd_a_re <= 16'sh0000;
                        sv_wd_a_im <= 16'sh0000;
                    end else begin
                        // Winning side: renormalize so total probability = 1.0
                        sv_wd_a_re <= rnorm_re;
                        sv_wd_a_im <= rnorm_im;
                    end

                    if (idx == 3'd7) begin
                        state <= M_DONE;
                    end else begin
                        idx   <= idx + 3'd1;
                        state <= M_COLL_ADDR;
                    end
                    // sv_we_a takes effect next posedge. At that point sv_addr_a
                    // still holds the value from M_COLL_ADDR (not overwritten here),
                    // so the write goes to the correct address.
                end

                M_DONE: begin
                    done  <= 1'b1;
                    state <= M_IDLE;
                end

                default: state <= M_IDLE;
            endcase
        end
    end
endmodule
