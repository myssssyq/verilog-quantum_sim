module reset_gen(
    input  wire clk,
    input  wire btn_n, // active‑LOW
    output wire rst    // active‑HIGH
);
    // power‑on counter (~9.5 µs @27 MHz)
    reg [7:0] por_cnt = 8'd0;
    wire por_done = &por_cnt;
    always @(posedge clk)
        if (!por_done) por_cnt <= por_cnt + 1;

    // two‑flipflop sync + invert
    reg [1:0] btn_sync = 2'b11;
    always @(posedge clk)
        btn_sync <= {btn_sync[0], btn_n};
    wire btn_pressed = ~btn_sync[1];

    assign rst = ~por_done | btn_pressed;
endmodule