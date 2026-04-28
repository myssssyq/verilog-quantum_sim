module state_vec(
    input         clk,
    // Dual-port read/write
    input  [2:0]  raddr_a,
    input  [2:0]  raddr_b,
    output signed [15:0] rdata_a_re,
    output signed [15:0] rdata_a_im,
    output signed [15:0] rdata_b_re,
    output signed [15:0] rdata_b_im,
    input         we_a,
    input         we_b,
    input  signed [15:0] wdata_a_re,
    input  signed [15:0] wdata_a_im,
    input  signed [15:0] wdata_b_re,
    input  signed [15:0] wdata_b_im,
    // Initialization
    input         init_reset,
    input         init_basis,
    input  [2:0]  init_state
);
    // 8 complex amplitudes: Q2.14 signed fixed-point
    // 1.0 = 16'sh4000 = 16384
    reg signed [15:0] re [0:7];
    reg signed [15:0] im [0:7];

    // Combinational reads
    assign rdata_a_re = re[raddr_a];
    assign rdata_a_im = im[raddr_a];
    assign rdata_b_re = re[raddr_b];
    assign rdata_b_im = im[raddr_b];

    integer i;
    always @(posedge clk) begin
        if (init_reset) begin
            for (i = 0; i < 8; i = i + 1) begin
                re[i] <= (i == 0) ? 16'sh4000 : 16'sh0000;
                im[i] <= 16'sh0000;
            end
        end else if (init_basis) begin
            for (i = 0; i < 8; i = i + 1) begin
                re[i] <= (i[2:0] == init_state) ? 16'sh4000 : 16'sh0000;
                im[i] <= 16'sh0000;
            end
        end else begin
            if (we_a) begin
                re[raddr_a] <= wdata_a_re;
                im[raddr_a] <= wdata_a_im;
            end
            if (we_b) begin
                re[raddr_b] <= wdata_b_re;
                im[raddr_b] <= wdata_b_im;
            end
        end
    end
endmodule
