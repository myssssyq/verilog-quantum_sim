module imem(
    input  [7:0]  addr,
    output [15:0] instr
);
    reg [15:0] rom [0:255];
    initial $readmemh("program.hex", rom);
    assign instr = rom[addr];
endmodule
