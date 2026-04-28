module uart_printer(
    input             clk,
    input             rst,
    // Commands
    input             print_state,   // start printing all 8 amplitudes
    input             print_meas,    // print measurement result
    input      [1:0]  meas_qubit,
    input             meas_result,
    output reg        busy,
    // State vector read (single port)
    output reg [2:0]  sv_addr,
    input  signed [15:0] sv_rd_re,
    input  signed [15:0] sv_rd_im,
    // UART
    output reg        uart_wr,
    output reg [7:0]  uart_data,
    input             uart_busy
);

    // FSM states
    localparam P_IDLE      = 4'd0;
    localparam P_DUMP_ADDR = 4'd1;  // set sv read address
    localparam P_DUMP_LATCH= 4'd2;  // latch data
    localparam P_SEND_HDR  = 4'd3;  // send "|bbb> "
    localparam P_SEND_RE   = 4'd4;  // send "+XXXX"
    localparam P_SEND_IM   = 4'd5;  // send " +XXXXi"
    localparam P_SEND_NL   = 4'd6;  // send "\r\n"
    localparam P_NEXT_AMP  = 4'd7;  // advance to next amplitude
    localparam P_MEAS_SEND = 4'd8;  // send "M(q)=r\r\n"

    reg [3:0] state;
    reg [2:0] amp_idx;     // current amplitude index (0..7)
    reg [3:0] byte_idx;    // position within current output field
    reg signed [15:0] lat_re, lat_im;

    // Hex conversion
    function [7:0] hex_char;
        input [3:0] val;
        hex_char = (val < 4'd10) ? (8'd48 + {4'd0, val}) : (8'd55 + {4'd0, val});
    endfunction

    // Break 16-bit value into sign + 4 hex digits
    wire [15:0] abs_re = lat_re[15] ? (-lat_re) : lat_re;
    wire [15:0] abs_im = lat_im[15] ? (-lat_im) : lat_im;
    wire [7:0] sign_re = lat_re[15] ? 8'h2D : 8'h2B; // '-' or '+'
    wire [7:0] sign_im = lat_im[15] ? 8'h2D : 8'h2B;

    // Pre-built message buffer for measurement: "M(q)=r\r\n"
    reg [7:0] meas_msg [0:7];
    reg [1:0] lat_mq;
    reg       lat_mr;

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            state   <= P_IDLE;
            busy    <= 1'b0;
            uart_wr <= 1'b0;
        end else begin
            uart_wr <= 1'b0;

            case (state)
                P_IDLE: begin
                    if (print_state) begin
                        busy    <= 1'b1;
                        amp_idx <= 3'd0;
                        state   <= P_DUMP_ADDR;
                    end else if (print_meas) begin
                        busy    <= 1'b1;
                        lat_mq  <= meas_qubit;
                        lat_mr  <= meas_result;
                        byte_idx<= 4'd0;
                        state   <= P_MEAS_SEND;
                    end
                end

                // --- DUMPSTATE path ---
                P_DUMP_ADDR: begin
                    sv_addr  <= amp_idx;
                    state    <= P_DUMP_LATCH;
                end

                P_DUMP_LATCH: begin
                    lat_re   <= sv_rd_re;
                    lat_im   <= sv_rd_im;
                    byte_idx <= 4'd0;
                    state    <= P_SEND_HDR;
                end

                P_SEND_HDR: begin
                    // Send "|bbb> " = 6 bytes: '|', b2, b1, b0, '>', ' '
                    if (!uart_busy && !uart_wr) begin
                        case (byte_idx)
                            4'd0: uart_data <= 8'h7C;                              // '|'
                            4'd1: uart_data <= 8'd48 + {7'd0, amp_idx[2]};         // q2 digit
                            4'd2: uart_data <= 8'd48 + {7'd0, amp_idx[1]};         // q1 digit
                            4'd3: uart_data <= 8'd48 + {7'd0, amp_idx[0]};         // q0 digit
                            4'd4: uart_data <= 8'h3E;                              // '>'
                            4'd5: uart_data <= 8'h20;                              // ' '
                            default: uart_data <= 8'h20;
                        endcase
                        uart_wr  <= 1'b1;
                        if (byte_idx == 4'd5) begin
                            byte_idx <= 4'd0;
                            state    <= P_SEND_RE;
                        end else begin
                            byte_idx <= byte_idx + 4'd1;
                        end
                    end
                end

                P_SEND_RE: begin
                    // Send sign + 4 hex digits of real part: "+XXXX"
                    if (!uart_busy && !uart_wr) begin
                        case (byte_idx)
                            4'd0: uart_data <= sign_re;
                            4'd1: uart_data <= hex_char(abs_re[15:12]);
                            4'd2: uart_data <= hex_char(abs_re[11:8]);
                            4'd3: uart_data <= hex_char(abs_re[7:4]);
                            4'd4: uart_data <= hex_char(abs_re[3:0]);
                            default: uart_data <= 8'h20;
                        endcase
                        uart_wr <= 1'b1;
                        if (byte_idx == 4'd4) begin
                            byte_idx <= 4'd0;
                            state    <= P_SEND_IM;
                        end else begin
                            byte_idx <= byte_idx + 4'd1;
                        end
                    end
                end

                P_SEND_IM: begin
                    // Send " " + sign + 4 hex digits + "i": " +XXXXi"
                    if (!uart_busy && !uart_wr) begin
                        case (byte_idx)
                            4'd0: uart_data <= 8'h20;                              // ' '
                            4'd1: uart_data <= sign_im;
                            4'd2: uart_data <= hex_char(abs_im[15:12]);
                            4'd3: uart_data <= hex_char(abs_im[11:8]);
                            4'd4: uart_data <= hex_char(abs_im[7:4]);
                            4'd5: uart_data <= hex_char(abs_im[3:0]);
                            4'd6: uart_data <= 8'h69;                              // 'i'
                            default: uart_data <= 8'h20;
                        endcase
                        uart_wr <= 1'b1;
                        if (byte_idx == 4'd6) begin
                            byte_idx <= 4'd0;
                            state    <= P_SEND_NL;
                        end else begin
                            byte_idx <= byte_idx + 4'd1;
                        end
                    end
                end

                P_SEND_NL: begin
                    // Send "\r\n"
                    if (!uart_busy && !uart_wr) begin
                        case (byte_idx)
                            4'd0: uart_data <= 8'h0D;  // '\r'
                            4'd1: uart_data <= 8'h0A;  // '\n'
                            default: uart_data <= 8'h0A;
                        endcase
                        uart_wr <= 1'b1;
                        if (byte_idx == 4'd1) begin
                            state <= P_NEXT_AMP;
                        end else begin
                            byte_idx <= byte_idx + 4'd1;
                        end
                    end
                end

                P_NEXT_AMP: begin
                    if (amp_idx == 3'd7) begin
                        busy  <= 1'b0;
                        state <= P_IDLE;
                    end else begin
                        amp_idx <= amp_idx + 3'd1;
                        state   <= P_DUMP_ADDR;
                    end
                end

                // --- MEASURE result path ---
                P_MEAS_SEND: begin
                    // Send "M(q)=r\r\n" = 8 bytes
                    if (!uart_busy && !uart_wr) begin
                        case (byte_idx)
                            4'd0: uart_data <= 8'h4D;                              // 'M'
                            4'd1: uart_data <= 8'h28;                              // '('
                            4'd2: uart_data <= 8'd48 + {6'd0, lat_mq};            // qubit digit
                            4'd3: uart_data <= 8'h29;                              // ')'
                            4'd4: uart_data <= 8'h3D;                              // '='
                            4'd5: uart_data <= 8'd48 + {7'd0, lat_mr};            // result digit
                            4'd6: uart_data <= 8'h0D;                              // '\r'
                            4'd7: uart_data <= 8'h0A;                              // '\n'
                            default: uart_data <= 8'h0A;
                        endcase
                        uart_wr <= 1'b1;
                        if (byte_idx == 4'd7) begin
                            busy  <= 1'b0;
                            state <= P_IDLE;
                        end else begin
                            byte_idx <= byte_idx + 4'd1;
                        end
                    end
                end

                default: state <= P_IDLE;
            endcase
        end
    end
endmodule
