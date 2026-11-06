/*
*********************************************************************************************************
* 文件 ：mbserial_master_port_lpuart1.c
* 作者 ：zqh			 
* 版本 ：
* 日期 ：2023/8/7
* 描述 ：Modbus串行主机通讯接口回调函数
*********************************************************************************************************
*/

#include "ddl.h"
#include "lpuart.h"

#include "system_def.h"

#include "app_lpuart1.h"
#include "app_sysctrl.h"
#include "app_lptim1.h"

#include "mbserial_master.h"

/*
*********************************************************************************************************
* 描述   ：打开Modbus主机端口
* 参数   ：port - 端口号
* 返回值 ：Modbus主机端口打开成功，返回MB_ERROR_FREE，否则返回错误代码。
*********************************************************************************************************
*/

static INT32S MBSerialMasterPort_LPUart1Open(INT32U port)
{	
    App_LPUart1PortCfg();
    App_LPUart1Init(57600); // 太阳能充放电控制器的通讯波特率是57600bps
	
    return (MB_ERROR_FREE); 
}

/*
*********************************************************************************************************
* 描述   ：关闭Modbus主机端口
* 参数   ：port - 端口号
* 返回值 ：Modbus主机端口关闭成功，返回MB_ERROR_FREE，否则返回错误代码。
*********************************************************************************************************
*/

static INT32S MBSerialMasterPort_LPUart1Close(INT32U port)
{
    return (MB_ERROR_FREE);
}

/*
*********************************************************************************************************
* 描述   ：写Modbus主机端口
* 参数   ：port - 端口号
*          pbuf - 写入数据的存储地址
*          num  - 写入数据的字节数 
* 返回值 ：写成功，返回实际写入的字节数。写失败，返回错误代码。 
*********************************************************************************************************
*/

static INT32S MBSerialMasterPort_LPUart1Write(INT32U port, INT8U *pbuf, INT32S num)
{
    int i;
	M0P_LPUART_TypeDef* lpuartx = M0P_LPUART1;
	INT32S bStatus;

	LPUart_DisableFunc(lpuartx, LPUartRenFunc); // 关闭接收器
    App_LPUart1RecvBufferClear();
    App_LPUart1Chip485DESet(1); // 使能485发送     
	
	for (i = 0; i < num; i++) {
        //LPUart_SendData(M0P_LPUART1, *(pbuf + i));
		
        //while(FALSE == LPUart_GetStatus(LPUARTx, LPUartTxe))
		while(0 == (bStatus = (lpuartx->ISR & 0x08)))
        {}
        lpuartx->SBUF_f.DATA = *(pbuf + i);
        //while(FALSE == LPUart_GetStatus(LPUARTx,LPUartTC))
	    while(0 == (bStatus = (lpuartx->ISR & 0x02)))
        {}
        //LPUart_ClrStatus(LPUARTx,LPUartTC);
        lpuartx->ICR &= 0xfd;			
    }	
		
    App_LPUart1TCHandle();

    return num;
}

/*
*********************************************************************************************************
* 描述   ：读Modbus主机端口
* 参数   ：port - 端口号
*          pbuf - 读入数据的存储地址
*          num  - 要读入数据的字节数 
* 返回值 ：读成功，返回实际读取数据的字节数。读失败，返回错误代码。
*********************************************************************************************************
*/

static INT32S MBSerialMasterPort_LPUart1Read(INT32U port, INT8U * pbuf, INT32S num)
{
    INT32S recv_count;
	INT32S tick_count_start;
	INT32S tick_count_end;
	
	App_LPTimer1CountReset(1);
	tick_count_end = App_LPTimer1CountGet(1) + MBSerialMasterGetResponseTimeout(port);
	
    while (1) {
        recv_count = App_LPUart1RecvCountGet();
        if (recv_count >= num) {
            return App_LPUart1RecvDataGet(pbuf, num);
		}
		else {
			if (App_LPTimer1CountGet(1) > tick_count_end) {
				return MB_ERROR_TIMEOUT;
            }				
		}
    }			
}

/*
*********************************************************************************************************
* 描述   ：设置Modbus主机通讯速度: 串口波特率
* 参数   ：port      - 端口号
*          baud_rate - 波特率
* 返回值 ：Modbus主机通讯速度设置成功，返回MB_ERROR_FREE，否则返回错误代码。
*********************************************************************************************************
*/

static INT32S MBSerialMasterPort_LPUart1SetSpeed(INT32U port, INT32S baud_rate)
{
	return (MB_ERROR_FREE);
}

/*
*********************************************************************************************************
* 描述   ：设置Modbus主机通讯参数: 串口波特率、校验、数据位、停止位
* 参数   ：port      - 端口号
*          baud_rate - 波特率
*          parity    - 校验
*          data_bits - 数据位
*          stop_bits - 停止位
* 返回值 ：Modbus主机通讯参数设置成功，返回MB_ERROR_FREE，否则返回错误代码。
*********************************************************************************************************
*/

static INT32S MBSerialMasterPort_LPUart1SetParam(INT32U port, INT32S baud_rate , INT32S parity, INT32S data_bits, INT32S stop_bits)
{
	return (MB_ERROR_FREE);
}

MBSERIAL_MASTER_COMM_IF MBSerialMasterCommIf_LPUart1 =
{
    MBSerialMasterPort_LPUart1Open,
    MBSerialMasterPort_LPUart1Close,
    MBSerialMasterPort_LPUart1Write,
    MBSerialMasterPort_LPUart1Read,
    MBSerialMasterPort_LPUart1SetSpeed,
    MBSerialMasterPort_LPUart1SetParam
};
