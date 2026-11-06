/*---------------------------------------------------------------------------*/
/*---------------------------------------------------------------------------*/

#ifndef MBSERIAL_DEFS_H
#define MBSERIAL_DEFS_H

//Data types
#ifndef INT16U
#define INT16U                               unsigned short
#endif

#ifndef INT8U
#define INT8U                                unsigned char
#endif

#ifndef INT8S
#define INT8S                                signed char
#endif

#ifndef INT16S
#define INT16S                               signed short
#endif

#ifndef INT32U
#define INT32U                               unsigned int
#endif

#ifndef INT32S
#define INT32S                               signed int
#endif

#ifndef BOLEAN   
#define BOLEAN                               unsigned char
#endif

#ifndef FALSE
#define FALSE                                0
#endif

#ifndef TRUE
#define TRUE                                 1
#endif

#define MB_TCP_PORT                          502
#define MAX_MB_RTU_FRAME_LENGTH              (252 + 4)     // 数据 + 地址 + 功能码 + CRC
#define MAX_MB_ASCII_FRAME_LENGTH            (504 + 6 + 3) // 数据 + 地址 + 功能码 + LRC + 起始符':' + 结束符'0x0d''0x0a'

//protocol select
#define MB_SERIAL_MODE_RTU                   0
#define MB_SERIAL_MODE_ASCII                 1
#define MB_TCP_PROTOCOL                      2

//modbus function id
#define MBF_READ_COILS                       0x01
#define MBF_READ_DECRETE_INPUTS              0x02 
#define MBF_READ_HOLDING_REGISTERS           0x03
#define MBF_READ_INPUT_REGISTERS             0x04
#define MBF_FORCE_SINGLE_COIL                0x05
#define MBF_PRESET_SINGLE_REGISTER           0x06
#define MBF_READ_EXCEPTION_STATUS            0x07
#define MBF_DIAGNOSTIC                       0x08
//0x09
//0x0A
#define MBF_GET_COMM_EVENT_COUNTER           0x0B
#define MBF_GET_COMM_EVENT_LOG               0x0C
//0x0D
//0x0E
#define MBF_FORCE_MULTIPLE_COILS             0x0F
#define MBF_PRESET_MULTIPLE_REGISTERS        0x10
#define MBF_REPORT_SLAVE_ID                  0x11
//0x12
//0x13
#define MBF_READ_FILE_RECORD                 0x14
#define MBF_WRITE_FILE_RECORD                0x15
#define MBF_MASK_WRITE_REGISTER              0x16
#define MBF_READ_WRITE_MULTIPLE_REGISTERS    0x17
#define MBF_READ_FIFO_QUEUE                  0x18
//0x19
//0x1A
//0x1B
//0x1C
//0x1D
//0x1E
//0x1F
//0x20
//0x21
//0x22
//0x23
//0x24
//0x25
//0x26
//0x27
//0x28
//0x29
//0x2A
#define MBF_READ_DEVICE_IDENTIFICATION       0x2B

#define MBF_HAS_EXCEPTION                    0x80
#define MBF_MASK                             0x7F

//Error code
#define MB_ERROR_FREE                        0  // 无错误
#define MB_ERROR_FORMAT                      -1
#define MB_ERROR_FRAME_LENGTH                -2 // 帧长度错误
#define MB_ERROR_UNSUPPORT_FUNC              -3
#define MB_ERROR_OPEN                        -4
#define MB_ERROR_TCP_NOT_CONNECTED           -5
#define MB_ERROR_NOT_OPENED                  -6
#define MB_ERROR_BUFFER_TOO_SHORT            -7
#define MB_ERROR_NO_FRAME                    -8
#define MB_ERROR_TIMEOUT                     -9  // 超时
#define MB_ERROR_EXECPTION                   -10
#define MB_ERROR_BAD_FD                      -11
#define MB_ERROR_NET                         -12
#define MB_ERROR_NO_FILE_HANDLE              -13
#define MB_ERROR_PROTOCOL                    -14 // 不符合Modbus协议规范
#define MB_ERROR_SLAVE_RESPONSE_VALUE        -15 // 从机响应值错误
#define MB_ERROR_MODE                        -16
#define MB_ERROR_NULL_FUNC                   -17 // 空函数
#define MB_ERROR_ADDR                        -18 // 地址错误
#define MB_ERROR_RANGE                       -19 // 数量等超出范围错误
#define MB_ERROR_FUNC_EXEC                   -20 // 函数执行错误
#define MB_ERROR_FUNC_PARAMETER              -21 // 函数参数错误
#define MB_ERROR_NULL_POINTER                -22 // 空指针
#define MB_ERROR_CHECK                       -23 // 校验错误
#define MB_ERROR_SLAVE_EXCEPTION_RESPONSE    -24 // 从机异常响应

#endif											
