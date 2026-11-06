/*
*********************************************************************************************************
* 文件 : app_spi.h
* 作者 : zqh			
* 版本 : V1.0
* 日期 : 2026/8/31
* 描述 : app_spi.c的头文件：SPI1接口及ASM330LHH FIFO数据采集应用层
* 历史 :
*********************************************************************************************************
*/

#ifndef APP_SPI_H
#define APP_SPI_H

#include "stm32l4xx_hal.h"
#include "asm330.h"

/*
*********************************************************************************************************
*                                          外部变量声明
*********************************************************************************************************
*/

extern SPI_HandleTypeDef hspi1;        // SPI1句柄

/*
*********************************************************************************************************
*                                          宏定义
*********************************************************************************************************
*/

#define ASM330_CS_PORT             GPIOA            // ASM330LHH片选引脚端口
#define ASM330_CS_PIN              GPIO_PIN_4       // ASM330LHH片选引脚
#define ASM330_SPI_READ_MSK        0x80             // SPI读操作时寄存器地址最高位置1

#define ASM330_INT_PORT            GPIOA            // ASM330LHH INT2中断引脚端口
#define ASM330_INT_PIN             GPIO_PIN_1       // ASM330LHH INT2中断引脚(接EXTI1)
#define ASM330_INT_EXTI_IRQn       EXTI1_IRQn       // INT2对应的EXTI中断号

#define ASM330_DATA_SRC_SIM        0                // 数据源：1=TIM6模拟(无器件时用)，0=真实器件(读输出寄存器或FIFO)
#define ASM330_DATA_SRC_DIRECT     1                // 数据源：1=节拍+STATUS_REG直读输出寄存器(测试用)，0=FIFO水印中断批量读取

#define ASM330_ODR_HZ              833              // 轴输出速率(Hz)
#define ASM330_BATCH_SAMPLES       16               // 每批样本数(与上传的16个一致)
#define ASM330_UPLOAD_SAMPLES      16               // 每次上传的样本数
#define ASM330_FIFO_DEPTH          520              // 轴数据环形队列深度(静态数组)
#define ASM330_TEMP_DEPTH          64               // 温度环形队列深度
#define ASM330_UNREAD_MAX          255              // 未读批次数饱和上限
#define ASM330_FIFO_WTM_WORDS      128              // FIFO水印阈值(16位字数)
#define ASM330_FIFO_MODE_CFG       ASM330_FIFO_MODE_FIFO   // FIFO工作模式(可改STREAM)

#define ASM330_FIFO_READ_MAX       512              // FIFO单次读出最大字节数
#define ASM330_TEMP_SIM_STEP       16               // 模拟温度更新间隔(节拍数)

// FIFO_State状态位定义(上传给上位机)
#define ASM330_STATE_SENSOR_OK     0x0001           // 器件在线
#define ASM330_STATE_SIM_MODE      0x0002           // 模拟数据模式
#define ASM330_STATE_FIFO_WTM      0x0010           // 水印中断标志
#define ASM330_STATE_FIFO_OVR      0x0020           // FIFO溢出标志
#define ASM330_STATE_FIFO_FULL     0x0040           // FIFO满标志
#define ASM330_STATE_FIFO_EMPTY    0x0080           // FIFO空标志
#define ASM330_STATE_TAG_UNKNOWN   0x0100           // 出现未知TAG

/*
*********************************************************************************************************
*                                          ASM330LHH传感器数据MODBUS结构定义
*********************************************************************************************************
*/

typedef struct asm330_data
{
	uint16_t DataUnRead;      // 未读取的FIFO批次数(0表示本次没有新数据)
    int16_t  AccX[16];        // 加速度计X轴原始值(16个样本)
    int16_t  AccY[16];        // 加速度计Y轴原始值(16个样本)
    int16_t  AccZ[16];        // 加速度计Z轴原始值(16个样本)
    int16_t  GyrX[16];        // 陀螺仪X轴原始值(16个样本)
    int16_t  GyrY[16];        // 陀螺仪Y轴原始值(16个样本)
    int16_t  GyrZ[16];        // 陀螺仪Z轴原始值(16个样本)
    int16_t  Temp;            // 温度原始值(每次只上传一个)
    uint16_t Time[2];         // 采样时间(HAL_GetTick低16位在前)

    uint16_t AccLevel;        // 加速度量程(g)
    uint16_t GyroLevel;       // 陀螺仪量程(dps)
    uint16_t DataODR;         // 轴输出速率(Hz)
    uint16_t FIFO_State;      // FIFO状态
} ASM330_DATA;

/*
*********************************************************************************************************
*                                          函数声明
*********************************************************************************************************
*/

HAL_StatusTypeDef App_SpiInit(void);                       // SPI1初始化(含片选/中断引脚配置)
uint8_t           App_SpiReadRegByte(uint8_t reg);         // SPI读单个寄存器
int32_t           App_SpiWriteRegByte(uint8_t reg, uint8_t val); // SPI写单个寄存器
int32_t           App_SpiReadRegs(uint8_t reg, uint8_t *pbuf, uint16_t len);  // SPI连续读多个寄存器
int32_t           App_SpiWriteRegs(uint8_t reg, uint8_t *pbuf, uint16_t len); // SPI连续写多个寄存器

void              App_Asm330DirectSample(void);                 // 直读模式：按定时节拍查询STATUS_REG(XLDA/GDA)，有新数据才读一组
int32_t           App_Asm330Init(void);                    // ASM330初始化(FIFO配置)
int32_t           App_Asm330SetParam(uint8_t odr_accel, uint8_t fs_accel, uint8_t odr_gyro, uint8_t fs_gyro); // ASM330设备参数变更
void              App_Asm330SimStep(void);                 // 模拟模式节拍处理(每833Hz节拍调用一次)
void              App_Asm330FifoRefresh(ASM330_DATA *pdata);  // 串口问询时刷新上传数据
uint16_t          App_Asm330GetUnread(void);               // 获取未读批次数
void              App_Asm330DataRefreshTxDone(void);            // 简单模式：上位机读取结束后更新公共区数据

#endif
