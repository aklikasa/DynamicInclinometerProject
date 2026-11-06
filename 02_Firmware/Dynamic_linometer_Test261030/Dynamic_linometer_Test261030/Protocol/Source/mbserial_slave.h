/*
*********************************************************************************************************
* 文件 : mbserial_slave.h
* 作者 : 施江肖			 
* 版本 : v2.0
* 日期 : 2009/3/23
* 描述 : mbserial_slave.c的头文件
* 历史 ：2009/3/23    施江肖    创建原始版本    v1.0
*        2017/2/22    zqh       整理原始版本    v2.0
*********************************************************************************************************
*/

#ifndef MBSERIAL_SLAVE_H
#define MBSERIAL_SLAVE_H

#include "mbserial_config.h"
#include "mbserial_defs.h"
#include "mbserial_utils.h" 

/*
*********************************************************************************************************
*                                       Modbus串行从机通讯接口回调函数集合，由用户实现，由本文引用
*********************************************************************************************************
*/

typedef struct mbserial_slave_comm_if
{
    int  (*fnMbReadCoils)                  (INT8U *presp, INT16U addr, INT16U num) C51_REENTRANT;
	int  (*fnMbReadInputDiscretes)         (INT8U *presp, INT16U addr, INT16U num) C51_REENTRANT;
    int  (*fnMbReadHoldingRegisters)       (INT16U *presp, INT16U addr, INT16U num) C51_REENTRANT;
    int  (*fnMbReadInputRegisters)         (INT16U *presp, INT16U addr, INT16U num) C51_REENTRANT;
    int  (*fnMbForceSingleCoil)            (INT16U addr, INT16U value) C51_REENTRANT;
    int  (*fnMbForceMultipleCoils)         (INT8U *value, INT16U addr, INT16U num) C51_REENTRANT;
	int  (*fnMbPresetMultipleRegisters)    (INT16U *value, INT16U addr, INT16U num) C51_REENTRANT;
	int  (*fnMbMaskWriteRegister)          (INT16U addr, INT16U andmask, INT16U ormask) C51_REENTRANT;
    int  (*fnMbReadWriteMultipleRegisters) (INT16U *value_rd, INT16U reg_addr_rd, INT16U num_rd, INT16U *value_wr, INT16U reg_addr_wr, INT16U num_wr) C51_REENTRANT;
} MBSERIAL_SLAVE_COMM_IF;

/*
*********************************************************************************************************
*                                       Modbus串行从机通讯信息数据结构
*********************************************************************************************************
*/

typedef struct mbserial_slave_info {
    INT8U                        MBMode;      // 串行传输模式, MB_RTU_PROTOCOL或MB_ASCII_PROTOCOL 
    INT8U                        MBSlaveAddr; // Modbus从机地址              
    const MBSERIAL_SLAVE_COMM_IF *pMBCommIf;  // Modbus串行从机通讯接口
} MBSERIAL_SLAVE_INFO;

/*
*********************************************************************************************************
*                                       全局函数声明
*********************************************************************************************************
*/

INT32S MBSerialSlaveInit(INT32U port, INT8U addr, INT8U mode, const MBSERIAL_SLAVE_COMM_IF *pif) C51_REENTRANT;  
volatile INT32S MBSerialSlaveFrameProcess(INT32U port, INT8U *presp_buf, INT8U *precv_buf, INT32S recv_len) C51_REENTRANT;

#endif 
