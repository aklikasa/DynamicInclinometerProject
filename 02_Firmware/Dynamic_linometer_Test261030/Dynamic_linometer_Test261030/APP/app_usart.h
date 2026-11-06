/*
*********************************************************************************************************
* 文件 : app_usart.h
* 作者 : zqh			
* 版本 : V1.0
* 日期 : 2026/8/31
* 描述 : app_usart.c的头文件：USART1 DMA收发Modbus从机数据(与LPUART1完全独立)
* 历史 :
*********************************************************************************************************
*/

#ifndef APP_USART_H
#define APP_USART_H

#include "stm32l4xx_hal.h"
#include "mbserial_defs.h"
#include "mbserial_config.h"

/*
*********************************************************************************************************
*                                          宏定义
*********************************************************************************************************
*/

#define USART1_RECV_FRAME_LEN      (1 + 1 + 2 + 2 + 1 + MAX_HOLDING_REGISTERS_NUM * 2 + 2) // 写多个寄存器(RTU模式)：从机地址+功能码+起始地址+寄存器数量+字节数+寄存器值+CRC16
#define USART1_RESP_FRAME_LEN      (1 + 1 + 1 + MAX_HOLDING_REGISTERS_NUM * 2 + 2)         // 读多个寄存器(RTU模式)：从机地址+功能码+字节数+寄存器值+CRC16

#define USART1_BAUDRATE            1500000         // USART1串口波特率
#define USART1_485_DE_PORT         GPIOA          // 485方向控制引脚端口(如未接485可改为任意空闲引脚)
#define USART1_485_DE_PIN          GPIO_PIN_15     // 485方向控制引脚(高电平发送，低电平接收)
#define USART1_MB_SLAVE_ADDR       0x01           // Modbus从机地址
#define USART1_MB_PORT             0              // Modbus从机端口号

/*
*********************************************************************************************************
*                                          外部变量声明
*********************************************************************************************************
*/

extern UART_HandleTypeDef huart1;          // USART1句柄
extern DMA_HandleTypeDef hdma_usart1_rx;   // USART1接收DMA句柄
extern DMA_HandleTypeDef hdma_usart1_tx;   // USART1发送DMA句柄

/*
*********************************************************************************************************
*                                          USART收发Modbus帧控制结构体
*********************************************************************************************************
*/

typedef struct usart_mb_slave_ctrl
{
    INT8U  RecvBuffer[USART1_RECV_FRAME_LEN]; // UART接收缓冲区
    INT8U  SendBuffer[USART1_RESP_FRAME_LEN]; // UART发送缓冲区
    INT32S RecvCount;                         // UART接收计数
    INT32S SendCount;                         // UART发送计数
    INT32S MBRespLen;                         // Modbus应答帧长度
    BOLEAN MBFrameIsReceived;                 // 已收到完整Modbus帧标志
    BOLEAN MBFrameIsSent;                     // Modbus应答帧发送完成标志
} USART_MB_SLAVE_CTRL;

extern USART_MB_SLAVE_CTRL USart1_MBSlaveCtrl;   // USART1 Modbus从机收发控制结构体

/*
*********************************************************************************************************
*                                          函数声明
*********************************************************************************************************
*/

void                App_USart1Chip485DESet(BOLEAN bVal);  // 485方向控制
void                App_USart1PortCfg(void);              // 485方向引脚配置
HAL_StatusTypeDef   App_USart1Init(INT32U baudrate);      // USART1初始化(8N1帧格式，DMA收发)
void                App_USart1DmaRxRecfg(void);           // 重新挂载DMA接收
void                App_USart1OreFlagClear(void);         // 清除ORE(溢出)等接收错误标志(错误回调用)
void                App_USart1TCHandle(void);             // 收发完成复位处理
void                App_USart1MBFramePolling(void);       // 轮询处理Modbus帧
void                App_USart1RxEvent(uint16_t Size);     // 接收空闲中断事件处理
void                App_USart1TxCplt(void);               // 发送完成中断事件处理

#endif
