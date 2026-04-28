module pc(
    input        clk,
    input        rst,
    input        hold,
    input        load,
    input  [7:0] pcIn,
    output reg [7:0] pcOut
);
    always @(posedge clk or posedge rst) begin
        if (rst)
            pcOut <= 8'd0;
        else if (load)
            pcOut <= pcIn;
        else if (!hold)
            pcOut <= pcOut + 8'd1;
    end
endmodule
