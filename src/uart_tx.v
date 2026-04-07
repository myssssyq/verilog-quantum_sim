module uart_tx #(parameter DIV = 234) (
    input  clk,
    input  wr,
    input  [7:0] data,
    output reg busy = 0,
    output tx
);
    reg [3:0] bit_cnt;
    reg [8:0] shifter = 9'h1FF;
    reg [15:0] div_cnt;
    assign tx = shifter[0];
    always @(posedge clk) begin
        if (!busy && wr) begin
            busy     <= 1;
            shifter  <= {1'b1, data, 1'b0};
            bit_cnt  <= 0;
            div_cnt  <= 0;
        end else if (busy) begin
            div_cnt <= div_cnt + 1;
            if (div_cnt == DIV) begin
                div_cnt <= 0;
                shifter <= {1'b1, shifter[8:1]};
                bit_cnt <= bit_cnt + 1;
                if (bit_cnt == 9) busy <= 0;
            end
        end
    end
endmodule
