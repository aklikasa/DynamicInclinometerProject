/*
*********************************************************************************************************
* 文件 : app_dma.c
* 作者 : zqh			
* 版本 : V1.0
* 日期 : 2026/8/31
* 描述 : DMA应用层：DMA1/DMA2控制器时钟使能及通道中断初始化
* 历史 :
*********************************************************************************************************
*/

#include "main.h"
#include "app_dma.h"

/*
*********************************************************************************************************
* 函数名 : App_DmaInit
* 入口参数 : 无
* 返回值 : 无
* 说明 : DMA控制器初始化：
*        DMA1通道4/5用于USART1的TX/RX，DMA2通道6/7用于LPUART1的TX/RX
*********************************************************************************************************
*/

HAL_StatusTypeDef App_DmaInit(void)
{
    /* DMA控制器时钟使能 */
    __HAL_RCC_DMA2_CLK_ENABLE();
    __HAL_RCC_DMA1_CLK_ENABLE();

    /* DMA中断初始化 */
    /* DMA1_Channel4_IRQn中断配置(USART1_TX) */
    HAL_NVIC_SetPriority(DMA1_Channel4_IRQn, 0, 0);
    HAL_NVIC_EnableIRQ(DMA1_Channel4_IRQn);
    /* DMA1_Channel5_IRQn中断配置(USART1_RX) */
    HAL_NVIC_SetPriority(DMA1_Channel5_IRQn, 0, 0);
    HAL_NVIC_EnableIRQ(DMA1_Channel5_IRQn);
    /* DMA2_Channel6_IRQn中断配置(LPUART1_TX) */
    HAL_NVIC_SetPriority(DMA2_Channel6_IRQn, 0, 0);
    HAL_NVIC_EnableIRQ(DMA2_Channel6_IRQn);
    /* DMA2_Channel7_IRQn中断配置(LPUART1_RX) */
    HAL_NVIC_SetPriority(DMA2_Channel7_IRQn, 0, 0);
    HAL_NVIC_EnableIRQ(DMA2_Channel7_IRQn);
	return HAL_OK;
}
