/*---------------------------------------------------------------------------*/
/*---------------------------------------------------------------------------*/

#ifndef MBSERIAL_MASTER_H
#define MBSERIAL_MASTER_H

#include "mbserial_config.h"
#include "mbserial_defs.h"
#include "mbserial_utils.h"

#ifndef MAX_MB_MASTER_PORT_NUM
#error "max modbus port support not find, just def in modbus_config.h"
#endif

/*---------------------------------------------------------------------------*/
/**
  Modbus串行主机通讯接口回调函数集合，由用户实现，由本文件引用      
 */
/*---------------------------------------------------------------------------*/
typedef struct mbserial_master_comm_if
{
    INT32S (*fnSerialOpen)     (INT32U port);
    INT32S (*fnSerialClose)    (INT32U port);
    INT32S (*fnSerialWrite)    (INT32U port, INT8U *pbuf, INT32S num);
    INT32S (*fnSerialRead)     (INT32U port, INT8U *pbuf, INT32S num);
    INT32S (*fnSerialSetSpeed) (INT32U port, INT32S baud_rate);
    INT32S (*fnSerialSetParam) (INT32U port, INT32S baud_rate , INT32S parity, INT32S data_bits, INT32S stop_bits);
} MBSERIAL_MASTER_COMM_IF;

/*---------------------------------------------------------------------------*/
/**
  Modbus串行主机数据结构      
 */
/*---------------------------------------------------------------------------*/
typedef struct mbserial_master_info
{
    INT8U                   mode; 	         // 串行传输模式, MB_SERIAL_MODE_RTU或MB_SERIAL_MODE_ASCII 
    INT16U                  FrameTimeout;    // 帧超时时间
    INT16U                  CharTimeout;     // 字符超时时间
	INT16U                  ResponseTimeout; // 响应超时时间
    INT8U                   *ptx_buf;        // 发送数据缓存
    INT8U                   *prx_buf;        // 接收数据缓存
    MBSERIAL_MASTER_COMM_IF *pif;            // 通讯接口函数
} MBSERIAL_MASTER_INFO;

/*---------------------------------------------------------------------------*/
/**
  函数声明      
 */
/*---------------------------------------------------------------------------*/
INT32S MBSerialMasterOpen(INT32U port, MBSERIAL_MASTER_INFO *pinfo);
INT32S MBSerialMasterClose(INT32U port);

INT16U MBSerialMasterGetFrameTimeout(INT32U port);
void   MBSerialMasterSetFrameTimeout(INT32U port, INT16U timeout);
INT16U MBSerialMasterGetCharTimeout(INT32U port);
void   MBSerialMasterSetCharTimeout(INT32U port, INT16U timeout);
INT16U MBSerialMasterGetResponseTimeout(INT32U port);
void   MBSerialMasterSetResponseTimeout(INT32U port, INT16U timeout);

INT8U  MBSerialMasterGetSlaveAddress(const INT8U *adu);
INT32S MBSerialMasterGetPDU( INT8U *buf, INT8U *adu, INT32S len);

INT32S MBSerialMasterSetSpeed(INT32U port, INT32S baud_rate);
INT32S MBSerialMasterSetParam(INT32U port, INT32S baud_rate, INT32S data_bits, INT32S parity, INT32S stop_bits);

#if MBF_READ_DECRETE_INPUTS_EN                   != 0 
INT32S MBSerialMasterReadDecreteInputs(INT32U port, INT8U slave_addr, INT16U input_addr, INT16U num, INT8U *value, INT8U *exception_code);
#endif

#if MBF_READ_COILS_EN                            != 0
INT32S MBSerialMasterReadCoils(INT32U port, INT8U slave_addr, INT16U coil_addr, INT16U num, INT8U *value, INT8U *exception_code);
#endif

#if MBF_FORCE_SINGLE_COIL_EN                     != 0
INT32S MBSerialMasterForceSingleCoil(INT32U port, INT8U slave_addr, INT16U coil_addr, INT16U onoff, INT8U *exception_code);
#endif

#if MBF_FORCE_MULTIPLE_COILS_EN                  != 0
INT32S MBSerialMasterForceMultipleCoils(INT32S port, INT8U slave_addr, INT16U coil_addr, INT16U num, INT8U *value, INT8U *exception_code);
#endif

#if MBF_READ_INPUT_REGISTERS_EN                  != 0
INT32S MBSerialMasterReadInputRegisters(INT32U port, INT8U slave_addr, INT16U reg_addr, INT16U num, INT16U *value, INT8U *exception_code);
#endif

#if  MBF_READ_HOLDING_REGISTERS_EN               != 0
INT32S MBSerialMasterReadHoldingRegisters(INT32U port, INT8U slave_addr, INT16U reg_addr, INT16U num, INT16U *value, INT8U *exception_code);
#endif

#if MBF_PRESET_SINGLE_REGISTER_EN                != 0
INT32S MBSerialMasterPresetSingleRegister(INT32U port, INT8U slave_addr, INT16U reg_addr, INT16U *value, INT8U *exception_code);
#endif

#if  MBF_PRESET_MULTIPLE_REGISTERS_EN            != 0
INT32S MBSerialMasterPresetMultipleRegisters(INT32U port, INT8U slave_addr, INT16U reg_addr, INT16U num, INT16U *value, INT8U *exception_code);
#endif

#if  MBF_MASK_WRITE_REGISTER_EN                  != 0
INT32S MBSerialMasterMaskWriteRegister(INT32U port, INT8U slave_addr, INT16U reg_addr, INT16U andmask, INT16U ormask, INT8U *exception_code);
#endif

#if  MBF_READ_WRITE_MULTIPLE_REGISTERS_EN        != 0
INT32S MBSerialMasterReadWriteMultipleRegisters(INT32U port, INT8U slave_addr, INT16U reg_addr_rd, INT16U num_rd, INT16U *value_rd, INT16U reg_addr_wr, INT16U num_wr, INT16U *value_wr, INT8U *exception_code);
#endif

#if MBF_READ_FIFO_QUEUE_EN                       != 0
int MBMasterReadFIFOQueue(int port, INT8U address, INT16U FIFOAddr, INT16U *FIFOCount, INT16U *FIFOValue)
#endif

#if  MBF_READ_FILE_RECORD_EN                     != 0
#endif

#if  MBF_WRITE_FILE_RECORD_EN                    != 0
#endif

#if  MBF_READ_EXCEPTION_STATUS_EN                != 0
int MBMasterReadExceptionStatus(int port, INT8U address, INT8U *status);
#endif

#if  MBF_DIAGNOSTIC_EN                           != 0
int MBMasterDiagnostic(int port, INT8U address, INT16U subfunc, INT16U data);
#endif

#if  MBF_GET_COMM_EVENT_COUNTER_EN               != 0
int MBMasterGetCommEventCounter(int port, INT8U address, INT16U *status, INT16U *eventcount);
#endif

#if  MBF_GET_COMM_EVENT_LOG_EN                   != 0
int MBMasterGetCommEventLog(int port, INT8U address, INT16U *status, INT16U *eventcount, INT16U *messagecount, INT8U *events);
#endif

#if  MBF_REPORT_SLAVE_ID_EN                      != 0
int MBMasterReportSlaveID(int port, INT8U address, INT8U *slave_id, INT8U *status);
#endif

#endif

