/*
*********************************************************************************************************
* 文件 : Dynamic_linometer_parameter.c
* 作者 : zqh
* 版本 : V1.1
* 日期 : 2026/8/31
* 描述 : 设备参数：读取MCU唯一标识(96位UID)并映射成Modbus保持寄存器(3000起，只读)
* 历史 :
*********************************************************************************************************
*/

#include "Dynamic_linometer_parameter.h"

DYNAMICLINOMETER_PARAM DynamicLinometerParam;   // 设备参数(含MCU唯一标识)

/*
*********************************************************************************************************
* 函数名 : DynamicLinometerSNInit
* 入口参数 : 无
* 返回值 : 无
* 说明 : 读取STM32L431出厂唯一标识并生成Modbus寄存器映像：
*        UID_BASE=0x1FFF7590(系统数据区，只读)，共96位：
*          字0=晶圆上die的X/Y坐标、字1=晶圆号、字2=批次号(ASCII)；
*        96位拆成6个16位寄存器(3000~3005，高16位在前)，上位机用功能码0x03/0x04读取。
*        在main初始化阶段调用一次即可。
*********************************************************************************************************
*/

void DynamicLinometerSNInit(void)
{
    uint32_t uid0 = HAL_GetUIDw0();     // 0x1FFF7590: 晶圆上die的X/Y坐标(BCD)
    uint32_t uid1 = HAL_GetUIDw1();     // 0x1FFF7594: 晶圆号
    uint32_t uid2 = HAL_GetUIDw2();     // 0x1FFF7598: 批次号(ASCII)

    DynamicLinometerParam.MCU_UUID[0] = uid0;
    DynamicLinometerParam.MCU_UUID[1] = uid1;
    DynamicLinometerParam.MCU_UUID[2] = uid2;

    // Modbus寄存器映像(3000~3005)：每个32位字拆成"高16位寄存器+低16位寄存器"
    DynamicLinometerParam.UidReg[0] = (uint16_t)(uid0 >> 16);
    DynamicLinometerParam.UidReg[1] = (uint16_t)(uid0 & 0xFFFFU);
    DynamicLinometerParam.UidReg[2] = (uint16_t)(uid1 >> 16);
    DynamicLinometerParam.UidReg[3] = (uint16_t)(uid1 & 0xFFFFU);
    DynamicLinometerParam.UidReg[4] = (uint16_t)(uid2 >> 16);
    DynamicLinometerParam.UidReg[5] = (uint16_t)(uid2 & 0xFFFFU);

    DynamicLinometerParam.PICISN = 0;   // 预留
}