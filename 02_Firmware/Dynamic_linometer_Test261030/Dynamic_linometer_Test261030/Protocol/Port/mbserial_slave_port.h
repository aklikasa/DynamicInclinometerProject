/*
*********************************************************************************************************
* 文件 : mbserial_slave_port.h
* 作者 : zqh			
* 版本 : V1.0
* 日期 : 2026/8/31
* 描述 : Modbus从机从端口接口头文件
* 历史 :
*********************************************************************************************************
*/

#ifndef MBSERIAL_SLAVE_PORT_H
#define MBSERIAL_SLAVE_PORT_H

#include "mbserial_slave.h"
#include "app_spi.h"

extern ASM330_DATA Asm330MBData;   // Modbus寄存器映射的ASM330六轴数据

extern const MBSERIAL_SLAVE_COMM_IF *MBSerialSlavePortCommIfPtr;   // Modbus从机通讯接口指针   // Modbus寄存器映射的ASM330六轴数据

#endif
