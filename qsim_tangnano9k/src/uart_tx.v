module uart_tx #(parameter DIV = 234) (
    input  clk,
    input  wr,
    input  [7:0] data,
    output reg busy = 0,
    output tx
);
    // 10-bit frame: start(0) + data[7:0] + stop(1). Shifter idles at all-ones.
    reg [3:0]  bit_cnt = 4'd0;
    reg [9:0]  shifter = 10'h3FF;
    reg [15:0] div_cnt = 16'd0;

    assign tx = shifter[0];

    always @(posedge clk) begin
        if (!busy && wr) begin
            busy    <= 1'b1;
            shifter <= {1'b1, data, 1'b0};  // stop | data | start
            bit_cnt <= 4'd0;
            div_cnt <= 16'd0;
        end else if (busy) begin
            if (div_cnt == DIV - 1) begin
                div_cnt <= 16'd0;
                if (bit_cnt == 4'd9) begin
                    busy    <= 1'b0;
                    shifter <= 10'h3FF;      // return to idle (tx = 1)
                end else begin
                    shifter <= {1'b1, shifter[9:1]};
                    bit_cnt <= bit_cnt + 4'd1;
                end
            end else begin
                div_cnt <= div_cnt + 16'd1;
            end
        end
    end
endmodule
