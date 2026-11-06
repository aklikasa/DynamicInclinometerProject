/*---------------------------------------------------------------------------------------------------------------*/
/*---------------------------------------------------------------------------------------------------------------*/

#ifndef MBSERIAL_UTILS_H
#define MBSERIAL_UTILS_H

#include "mbserial_config.h"

/*---------------------------------------------------------------------------------------------------------------*/
/*---------------------------------------------------------------------------------------------------------------*/
#define GETU16(var, buf) { (var) = (*(INT8U *)(buf) << 8) & 0xFF00; (var) |= (*((INT8U *)(buf)+1) & 0xFF); }
/*---------------------------------------------------------------------------------------------------------------*/
/*---------------------------------------------------------------------------------------------------------------*/
#define PUTU16(buf, var) { (*(INT8U *)(buf)) = ((var) >> 8);  *((INT8U *)(buf)+1) = ((var) & 0xFF); }       

#define bcopy(from, to, count)  memcpy(to, from, count)

//INT16U CRC16(const INT8U *buf, INT32S len) C51_REENTRANT;
//INT8U  LRC(const INT8U *buf, INT32S len) C51_REENTRANT;
INT32S MBASCIIToData(INT8U *buf, const INT8U *dat, INT32S len) C51_REENTRANT;
INT32S MBDataToASCII(INT8U *buf, const INT8U *dat, INT32S len) C51_REENTRANT;

int    MBMakeADU( INT8U *buf, int protocol, INT8U address, const INT8U *pdu, int len, INT16U tid) C51_REENTRANT;
INT32S MBGetPDU(INT8U *buf, INT8U *adu, INT32S len) C51_REENTRANT;
int    MBMakePDU( INT8U *buf, INT8U function, INT8U *dat, int len) C51_REENTRANT;
INT8U  MBGetAddress( const INT8U *adu) C51_REENTRANT;
INT8U  MBGetFunctionCode( const INT8U *pdu) C51_REENTRANT;

void   MBDataToBigEndian(INT8U *pdst, INT16U *psrc, INT16U no) C51_REENTRANT;
void   MBGetAddressRange(INT8U *pdu, INT16U *addr, INT16U *range) C51_REENTRANT;
void   MBGetAddressRangeSize(INT8U *pdu, INT16U *addr, INT16U *range, INT8U *len) C51_REENTRANT;

int    MBExpectLenReadFIFOQueue(INT16U no, INT16U count) C51_REENTRANT;
int    MBExpectLenReadExceptionStatus(INT8U status) C51_REENTRANT;
int    MBExpectLenDiagnostic(INT16U subfunc, INT16U dat) C51_REENTRANT;
int    MBExpectLenGetCommEventCounter(INT16U status, INT16U eventcount) C51_REENTRANT;
int    MBExpectLenGetCommEventLog(INT8U no, INT16U status, INT16U eventcount, INT16U messagecount, INT8U *events) C51_REENTRANT;
int    MBRTULenToASCII(INT16U len) C51_REENTRANT;

#if MBF_READ_COILS_EN                 != 0 
INT32S MBReadCoils(INT8U *buf, INT16U coil_addr, INT16U num) C51_REENTRANT;
void   MBGetReadCoils(INT8U *pdu, INT16U *addr, INT16U *num) C51_REENTRANT;
INT32S MBGetResponseReadCoils(INT8U *pdu, INT8U *byte, INT8U *value, INT8U *exception_code) C51_REENTRANT;
INT32S MBExpectLenReadCoils(INT16U num) C51_REENTRANT;
#endif

#if MBF_READ_DECRETE_INPUTS_EN        != 0 
INT32S MBReadDecreteInputs(INT8U *buf, INT16U input_addr, INT16U num) C51_REENTRANT;
void   MBGetReadDecreteInputs(INT8U *pdu, INT16U *addr, INT16U *num) C51_REENTRANT;
INT32S MBGetResponseReadDecreteInputs(INT8U *pdu, INT8U *byte, INT8U *value, INT8U *exception_code) C51_REENTRANT;
INT32S MBExpectLenReadDecreteInputs(INT16U num) C51_REENTRANT;
#endif

#if MBF_READ_HOLDING_REGISTERS_EN     != 0 
INT32S MBReadHoldingRegisters(INT8U *buf, INT16U reg_addr, INT16U num) C51_REENTRANT;
void   MBGetReadHoldingRegisters(INT8U *pdu, INT16U *addr, INT16U *num) C51_REENTRANT;
INT32S MBGetResponseReadHoldingRegisters(INT8U *pdu, INT8U *size, INT16U *value, INT8U *exception_code) C51_REENTRANT;
INT32S MBExpectLenReadHoldingRegisters(INT16U num) C51_REENTRANT;
#endif

#if MBF_READ_INPUT_REGISTERS_EN       != 0 
INT32S MBReadInputRegisters(INT8U *buf, INT16U reg_addr, INT16U num) C51_REENTRANT;
void   MBGetReadInputRegisters(INT8U *pdu, INT16U *addr, INT16U *num) C51_REENTRANT;
INT32S MBGetResponseReadInputRegisters(INT8U *pdu, INT8U *size, INT16U *value, INT8U *exception_code) C51_REENTRANT;
INT32S MBExpectLenReadInputRegisters(INT16U num) C51_REENTRANT;
#endif

#if MBF_FORCE_SINGLE_COIL_EN          != 0 
INT32S MBForceSingleCoil(INT8U *buf, INT16U coil_addr, INT16U onoff) C51_REENTRANT;
void   MBGetForceSingleCoil(INT8U *pdu, INT16U *addr, INT16U *value) C51_REENTRANT;
INT32S MBGetResponseForceSingleCoil(INT8U *pdu, INT16U *address, INT16U *value, INT8U *exception_code) C51_REENTRANT;
INT32S MBExpectLenForceSingleCoil(void) C51_REENTRANT;
#endif

#if MBF_PRESET_SINGLE_REGISTER_EN      != 0 
INT32S MBPresetSingleRegister(INT8U *buf, INT16U reg_addr, INT16U value) C51_REENTRANT;
void   MBGetPresetSingleRegister(INT8U *pdu, INT16U *addr, INT16U *value) C51_REENTRANT;
INT32S MBGetResponsePresetSingleRegister(INT8U *pdu, INT16U *address, INT16U *value, INT8U *exception_code) C51_REENTRANT;
INT32S MBExpectLenPresetSingleRegister(void) C51_REENTRANT;
#endif

#if MBF_READ_EXCEPTION_STATUS_EN      != 0 
int     MBReadExceptionStatus(INT8U *buf) C51_REENTRANT;
int     MBResponseReadExceptionStatus(INT8U *buf, INT8U status) C51_REENTRANT;
int     MBGetResponseReadExceptionStatus(INT8U *buf, INT8U *status) C51_REENTRANT;
#endif

#if MBF_DIAGNOSTIC_EN                 != 0 
int     MBDiagnostic(INT8U *buf, INT16U subfunc, INT16U dat) C51_REENTRANT;
int     MBResponseDiagnostic(INT8U *buf, INT16U subfunc, INT16U dat) C51_REENTRANT;
int     MBGetResponseDiagnostic(INT8U *pdu, INT16U *subfunc, INT16U *dat) C51_REENTRANT;
#endif

#if MBF_GET_COMM_EVENT_COUNTER_EN     != 0 
int     MBGetCommEventCounter(INT8U *buf) C51_REENTRANT;
int     MBResponseGetCommEventCounter(INT8U *buf, INT16U status, INT16U eventcount) C51_REENTRANT;
int     MBGetResponseGetCommEventCounter(INT8U *pdu, INT16U *status, INT16U *eventcount) C51_REENTRANT;
#endif

#if MBF_GET_COMM_EVENT_LOG_EN         != 0 
int     MBGetCommEventLog(INT8U *buf) C51_REENTRANT;
int     MBResponseGetCommEventLog(INT8U *buf, INT8U no, INT16U status, INT16U eventcount, INT16U messagecount, INT8U *events) C51_REENTRANT;
int     MBGetResponseGetCommEventLog(INT8U *buf, INT16U *status, INT16U *eventcount, INT16U *messagecount, INT8U *events) C51_REENTRANT;
#endif

#if MBF_FORCE_MULTIPLE_COILS_EN       != 0 
INT32S MBForceMultipleCoils(INT8U *buf, INT16U coil_addr, INT16U num, INT8U byte, INT8U *value) C51_REENTRANT;
INT32S MBGetForceMultipleCoils(INT8U *pdu, INT16U *addr, INT16U *num, INT8U *size, INT8U *value) C51_REENTRANT;
INT32S MBGetResponseForceMultipleCoils(INT8U *pdu, INT16U *coil_addr, INT16U *num, INT8U *exception_code) C51_REENTRANT;
INT32S MBExpectLenForceMultipleCoils(void) C51_REENTRANT;
#endif

#if MBF_PRESET_MULTIPLE_REGISTERS_EN   != 0 
INT32S MBPresetMultipleRegisters(INT8U *buf, INT16U reg_addr, INT16U num, INT8U size, INT16U *value) C51_REENTRANT;
INT32S MBGetPresetMultipleRegisters(INT8U *pdu, INT16U *reg_addr, INT16U *num, INT8U *size, INT16U *value) C51_REENTRANT;
INT32S MBGetResponsePresetMultipleRegisters(INT8U *pdu, INT16U *reg_addr, INT16U *num, INT8U *exception_code) C51_REENTRANT;
INT32S MBExpectLenPresetMultipleRegisters(void) C51_REENTRANT;
#endif

#if MBF_REPORT_SLAVE_ID_EN            != 0 
int     MBReportSlaveID(INT8U *buf) C51_REENTRANT;
int     MBResponseReportSlaveID(INT8U *pdu, INT8U *buf, int len) C51_REENTRANT;
int     MBGetResponseReportSlaveID(INT8U *pdu, INT8U *slave_id, INT8U *status) C51_REENTRANT;
#endif

#if MBF_READ_FILE_RECORD_EN           != 0 
#endif

#if MBF_WRITE_FILE_RECORD_EN          != 0 
#endif

#if MBF_MASK_WRITE_REGISTER_EN        != 0 
INT32S MBMaskWriteRegister(INT8U *buf, INT16U reg_addr, INT16U andmask,INT16U ormask) C51_REENTRANT;
void   MBGetMaskWriteRegister(INT8U *pdu, INT16U *reg_addr, INT16U *andmask, INT16U *ormask) C51_REENTRANT;
INT32S MBGetResponseMaskWriteRegister(INT8U *pdu, INT16U *reg_addr, INT16U *andmask, INT16U *ormask, INT8U *exception_code) C51_REENTRANT; 
INT32S MBExpectLenMaskWriteRegister(void) C51_REENTRANT;
#endif

#if MBF_READ_WRITE_MULTIPLE_REGISTERS_EN  != 0 
INT32S MBReadWriteMultipleRegisters(INT8U *buf, INT16U reg_addr_rd, INT16U num_rd, INT16U reg_addr_wr, INT16U num_wr, INT8U size, INT16U *value_wr) C51_REENTRANT;
INT32S MBGetReadWriteMultipleRegisters(INT8U *pdu, INT16U *reg_addr_rd, INT16U *num_rd, INT16U *reg_addr_wr, INT16U *num_wr, INT8U *size, INT16U *value_wr) C51_REENTRANT;
INT32S MBGetResponseReadWriteMultipleRegisters(INT8U *pdu, INT8U *size, INT16U *value, INT8U *exception_code) C51_REENTRANT;
INT32S MBExpectLenReadWriteMultipleRegisters(INT16U num) C51_REENTRANT;
#endif

#if MBF_READ_FIFO_QUEUE_EN            != 0 
int     MBReadFIFOQueue(INT8U *buf, INT16U FIFOAddr) C51_REENTRANT;
int     MBResponseReadFIFOQueue(INT8U *buf, INT16U no, INT16U count, INT16U *value) C51_REENTRANT;
int     MBGetResponseReadFIFOQueue(INT8U *buf, INT16U *count, INT16U *value) C51_REENTRANT;
#endif

// MBF_READ_FILE_RECORD                 0x14
// MBF_WRITE_FILE_RECORD                0x15

int     MBGetReadFIFOQueue(INT8U *pdu, INT16U *FIFOAddr) C51_REENTRANT;
int     MBGetDiagnostic(INT8U *pdu, INT16U *subfunc, INT16U *dat) C51_REENTRANT;      // just for serial port

#endif

