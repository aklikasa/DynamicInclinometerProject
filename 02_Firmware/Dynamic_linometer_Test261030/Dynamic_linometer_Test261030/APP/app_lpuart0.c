/*
*********************************************************************************************************
* 文件 : app_lpuart0.c
* 作者 : zqh			
* 版本 : V1.0
* 日期 : 2026/8/31
* 描述 : LPUART1应用层：LPUART1初始化及DMA收发Modbus从机数据，
*        接收空闲中断/发送完成中断通知收发完成
* 历史 :
*********************************************************************************************************
*/

#include "main.h"
#include "app_lpuart0.h"

#include "mbserial_defs.h"
#include "mbserial_config.h"
#include "mbserial_slave.h"
#include "mbserial_slave_port.h"

UART_HandleTypeDef hlpuart1;        // LPUART1句柄
DMA_HandleTypeDef hdma_lpuart_rx;   // LPUART1接收DMA句柄
DMA_HandleTypeDef hdma_lpuart_tx;   // LPUART1发送DMA句柄

UART_MB_SLAVE_CTRL LPUart0_MBSlaveCtrl;

/*
*********************************************************************************************************
* 函数名 : App_LPUart0OreFlagClear
* 入口参数 : 无
* 返回值 : 无
* 说明 : 清除LPUART1的ORE溢出错误标志(写ICR，同一次写顺带清NE/FE/PE)，仅供HAL_UART_ErrorCallback调用。
*********************************************************************************************************
*/

void App_LPUart0OreFlagClear(void)
{
    __HAL_UART_CLEAR_FLAG(&hlpuart1, UART_CLEAR_OREF | UART_CLEAR_NEF | UART_CLEAR_FEF | UART_CLEAR_PEF);
}

/*
*********************************************************************************************************
* 函数名 : App_LPUart0DmaRxRecfg
* 入口参数 : 无
* 返回值 : 无
* 说明 : 重新挂载LPUART1的DMA接收，接收空闲时由接收空闲中断通知
*********************************************************************************************************
*/

void App_LPUart0DmaRxRecfg(void)
{
    if (hlpuart1.RxState == HAL_UART_STATE_BUSY_RX) {
        HAL_UART_DMAStop(&hlpuart1);
    }

    HAL_UARTEx_ReceiveToIdle_DMA(&hlpuart1, (uint8_t *)&LPUart0_MBSlaveCtrl.RecvBuffer[0], (uint16_t)sizeof(LPUart0_MBSlaveCtrl.RecvBuffer));
}

/*
*********************************************************************************************************
* 函数名 : App_LPUart0Init
* 入口参数 : baudrate - 串口波特率
* 返回值 : 初始化成功返回HAL_OK，失败返回HAL_ERROR
* 说明 : LPUART1初始化：
*        帧格式寄存器配置(1起始位+8数据位+1停止位，即8N1)：
*          CR1.M[1:0]   = 00  -> 8位数据长度(UART_WORDLENGTH_8B)
*          CR1.PCE      = 0   -> 无校验(UART_PARITY_NONE)
*          CR2.STOP[1:0]= 00  -> 1个停止位(UART_STOPBITS_1)
*        接收使用DMA+接收空闲中断通知，发送使用DMA+发送完成中断通知
*********************************************************************************************************
*/

HAL_StatusTypeDef App_LPUart0Init(INT32U baudrate)
{
    hlpuart1.Instance                  = LPUART1;
    hlpuart1.Init.BaudRate             = baudrate;
    hlpuart1.Init.WordLength           = UART_WORDLENGTH_8B;  // CR1.M[1:0]=00，8位数据长度
    hlpuart1.Init.StopBits             = UART_STOPBITS_1;     // CR2.STOP[1:0]=00，1个停止位
    hlpuart1.Init.Parity               = UART_PARITY_NONE;    // CR1.PCE=0，无校验位
    hlpuart1.Init.Mode                 = UART_MODE_TX_RX;
    hlpuart1.Init.HwFlowCtl            = UART_HWCONTROL_NONE;
    hlpuart1.Init.OneBitSampling       = UART_ONE_BIT_SAMPLE_DISABLE;
    hlpuart1.AdvancedInit.AdvFeatureInit = UART_ADVFEATURE_NO_INIT;
    if (HAL_UART_Init(&hlpuart1) != HAL_OK) {
        return HAL_ERROR;
    }

    LPUart0_MBSlaveCtrl.RecvCount         = 0;
    LPUart0_MBSlaveCtrl.SendCount         = 0;
    LPUart0_MBSlaveCtrl.MBRespLen         = 0;
    LPUart0_MBSlaveCtrl.MBFrameIsReceived = FALSE;
    LPUart0_MBSlaveCtrl.MBFrameIsSent     = FALSE;

    // Modbus从机初始化
    MBSerialSlaveInit(LPUART0_MB_PORT, LPUART0_MB_SLAVE_ADDR, MB_SERIAL_MODE_RTU, MBSerialSlavePortCommIfPtr);

    App_LPUart0DmaRxRecfg(); // 挂载DMA接收，等待接收Modbus帧

    return HAL_OK;
}

/*
*********************************************************************************************************
* 函数名 : App_LPUart0TCHandle
* 入口参数 : 无
* 返回值 : 无
* 说明 : 复位收发计数，重新挂载DMA接收
*********************************************************************************************************
*/

void App_LPUart0TCHandle(void)
{
    LPUart0_MBSlaveCtrl.RecvCount         = 0;
    LPUart0_MBSlaveCtrl.SendCount         = 0;
    LPUart0_MBSlaveCtrl.MBRespLen         = 0;
    LPUart0_MBSlaveCtrl.MBFrameIsReceived = FALSE;
    LPUart0_MBSlaveCtrl.MBFrameIsSent     = FALSE;

    App_LPUart0DmaRxRecfg();   // 重新挂载DMA接收
}

/*
*********************************************************************************************************
* 函数名 : App_LPUart0RCIdleHandle
* 入口参数 : 无
* 返回值 : 无
* 说明 : 接收空闲中断处理：校验从机地址，设置Modbus帧接收完成标志
*********************************************************************************************************
*/

static void App_LPUart0RCIdleHandle(void)
{
    INT8U slave_addr_geted;

    if (LPUart0_MBSlaveCtrl.RecvCount < 4) { // 帧长过短(从机地址+功能码+CRC16)
        LPUart0_MBSlaveCtrl.MBFrameIsReceived = FALSE;
        App_LPUart0TCHandle();
        return;
    }

    // 校验从机地址
    slave_addr_geted = MBGetAddress(&LPUart0_MBSlaveCtrl.RecvBuffer[0]);
    if (slave_addr_geted != LPUART0_MB_SLAVE_ADDR) {
        LPUart0_MBSlaveCtrl.MBFrameIsReceived = FALSE;
        App_LPUart0TCHandle(); // 不是本机地址，重新进入接收
    } else {
        LPUart0_MBSlaveCtrl.MBFrameIsReceived = TRUE;
    }
}

/*
*********************************************************************************************************
* 函数名 : App_LPUart0RxEvent
* 入口参数 : Size - 本次接收到的字节数
* 返回值 : 无
* 说明 : 接收空闲中断事件处理：由中断层按串口实例路由调用
*********************************************************************************************************
*/

void App_LPUart0RxEvent(uint16_t Size)
{
    LPUart0_MBSlaveCtrl.RecvCount = Size;
    App_LPUart0RCIdleHandle();
}

/*
*********************************************************************************************************
* 函数名 : App_LPUart0TxCplt
* 入口参数 : 无
* 返回值 : 无
* 说明 : 发送完成中断事件处理：由中断层按串口实例路由调用
*********************************************************************************************************
*/

void App_LPUart0TxCplt(void)
{
    LPUart0_MBSlaveCtrl.MBFrameIsSent = TRUE;
}

/*
*********************************************************************************************************
* 函数名 : App_LPUart0MBFramePolling
* 入口参数 : 无
* 返回值 : 无
* 说明 : 轮询处理Modbus从机帧和应答帧发送完成状态
*********************************************************************************************************
*/

void App_LPUart0MBFramePolling(void)
{
    // 应答帧发送完成
    if (LPUart0_MBSlaveCtrl.MBFrameIsSent) {
        LPUart0_MBSlaveCtrl.MBFrameIsSent = FALSE;
		App_Asm330DataRefreshTxDone();
        App_LPUart0TCHandle();
        return;
    }

    // 收到完整Modbus帧
    if (LPUart0_MBSlaveCtrl.MBFrameIsReceived) {
        LPUart0_MBSlaveCtrl.MBFrameIsReceived = FALSE;

        // 处理Modbus从机帧，生成应答帧
        LPUart0_MBSlaveCtrl.MBRespLen = MBSerialSlaveFrameProcess(LPUART0_MB_PORT, LPUart0_MBSlaveCtrl.SendBuffer, LPUart0_MBSlaveCtrl.RecvBuffer, LPUart0_MBSlaveCtrl.RecvCount);
        if (LPUart0_MBSlaveCtrl.MBRespLen > 0) {
            LPUart0_MBSlaveCtrl.SendCount = 0;
            if (HAL_UART_Transmit_DMA(&hlpuart1, LPUart0_MBSlaveCtrl.SendBuffer, (uint16_t)LPUart0_MBSlaveCtrl.MBRespLen) != HAL_OK) {
                App_LPUart0TCHandle(); // 挂载发送DMA失败，重新进入接收
            }
        } 
		else if(LPUart0_MBSlaveCtrl.MBRespLen == 0){
            App_LPUart0TCHandle(); // 无应答帧，重新进入接收
        }
		else{
			App_LPUart0TCHandle(); // 无应答帧，重新进入接收
		}

    }
}
