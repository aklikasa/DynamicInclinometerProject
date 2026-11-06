/*---------------------------------------------------------------------------*/
/*---------------------------------------------------------------------------*/

#ifndef MBSERIAL_CONFIG_H
#define MBSERIAL_CONFIG_H

#define MAX_MB_MASTER_PORT_NUM                  2     // 最大Modbus/MTP主机端口数量
#define MAX_MB_SLAVE_PORT_NUM                  2     // 最大Modbus从机端口数量
#define MAX_COILS_NUM                           8     // 最大线圈数量   
#define MAX_DECRETE_INPUT_NUM                   16    // 最大离散输入数量
#define MAX_HOLDING_REGISTERS_NUM               256    // 最大保持寄存器数量 
#define MAX_INPUT_REGISTERS_NUM                 64    // 最大输入寄存器数量 

#define MBF_READ_COILS_EN                       0
#define MBF_READ_DECRETE_INPUTS_EN              0
#define MBF_READ_HOLDING_REGISTERS_EN           1
#define MBF_READ_INPUT_REGISTERS_EN             1
#define MBF_FORCE_SINGLE_COIL_EN                0
#define MBF_PRESET_SINGLE_REGISTER_EN           0
#define MBF_READ_EXCEPTION_STATUS_EN            0
#define MBF_DIAGNOSTIC_EN                       0
#define MBF_GET_COMM_EVENT_COUNTER_EN           0
#define MBF_GET_COMM_EVENT_LOG_EN               0
#define MBF_FORCE_MULTIPLE_COILS_EN             0
#define MBF_PRESET_MULTIPLE_REGISTERS_EN        1
#define MBF_REPORT_SLAVE_ID_EN                  0
#define MBF_READ_FILE_RECORD_EN                 0
#define MBF_WRITE_FILE_RECORD_EN                0
#define MBF_MASK_WRITE_REGISTER_EN              0
#define MBF_READ_WRITE_MULTIPLE_REGISTERS_EN    1
#define MBF_READ_FIFO_QUEUE_EN                  0

// 51单片机的常量放入Flash区
// Keil C51编译的函数声明为可重入
#ifdef __C51__
    #define C51_CODE         code
	#define C51_REENTRANT    reentrant
#else
    #define C51_CODE
	#define C51_REENTRANT    
#endif

#endif

 