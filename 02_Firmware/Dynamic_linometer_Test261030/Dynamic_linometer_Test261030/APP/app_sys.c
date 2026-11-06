/*
*********************************************************************************************************
* 文件 : app_sys.c
* 作者 : zqh			
* 版本 : V1.0
* 日期 : 2026/8/31
* 描述 : 系统级应用层：RCC系统时钟、GPIO、CAN1、RTC等初始化
* 历史 :
*********************************************************************************************************
*/

#include "app_sys.h"
#include "stm32l4xx_hal.h"

CAN_HandleTypeDef hcan1;   // CAN1句柄
RTC_HandleTypeDef hrtc;    // RTC句柄

/*
*********************************************************************************************************
* 函数名 : App_SysClockCfg
* 入口参数 : 无
* 返回值 : 初始化成功返回HAL_OK，失败返回HAL_ERROR
* 说明 : RCC系统时钟初始化：HSE 8MHz经PLL倍频，SYSCLK=80MHz
*        配置电源电压档位、振荡器(LSI/HSE)与总线时钟分频
*********************************************************************************************************
*/

HAL_StatusTypeDef App_SysClockCfg(void)
{
    RCC_OscInitTypeDef RCC_OscInitStruct = {0};
    RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

    /** 配置主内部稳压器输出电压
    */
    if (HAL_PWREx_ControlVoltageScaling(PWR_REGULATOR_VOLTAGE_SCALE1) != HAL_OK) {
        return HAL_ERROR;
    }

    /** 初始化RCC振荡器
    */
    RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_LSI | RCC_OSCILLATORTYPE_HSE;
    RCC_OscInitStruct.HSEState = RCC_HSE_ON;
    RCC_OscInitStruct.LSIState = RCC_LSI_ON;
    RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
    RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSE;
    RCC_OscInitStruct.PLL.PLLM = 1;
    RCC_OscInitStruct.PLL.PLLN = 20;
    RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV7;
    RCC_OscInitStruct.PLL.PLLQ = RCC_PLLQ_DIV2;
    RCC_OscInitStruct.PLL.PLLR = RCC_PLLR_DIV2;
    if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK) {
        return HAL_ERROR;
    }

    /** 初始化CPU、AHB和APB总线时钟
    */
    RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_SYSCLK
                                | RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
    RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
    RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
    RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV1;
    RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;
    if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_4) != HAL_OK) {
        return HAL_ERROR;
    }

    return HAL_OK;
}

/*
*********************************************************************************************************
* 函数名 : App_SysGpioInit
* 入口参数 : 无
* 返回值 : 初始化成功返回HAL_OK
* 说明 : GPIO初始化：使能GPIOH、GPIOA端口时钟
*********************************************************************************************************
*/

HAL_StatusTypeDef App_SysGpioInit(void)
{
    __HAL_RCC_GPIOH_CLK_ENABLE();
    __HAL_RCC_GPIOA_CLK_ENABLE();
	__HAL_RCC_GPIOB_CLK_ENABLE();
	__HAL_RCC_GPIOD_CLK_ENABLE();
	
	GPIO_InitTypeDef GPIO_InitStruct = {0};
	
	GPIO_InitStruct.Pin   = GPIO_PIN_6;
    GPIO_InitStruct.Mode  = GPIO_MODE_OUTPUT_PP;
    GPIO_InitStruct.Pull  = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);
	HAL_GPIO_WritePin(GPIOB, GPIO_PIN_6, GPIO_PIN_RESET);

	
	GPIO_InitStruct.Pin   = GPIO_PIN_2;
    GPIO_InitStruct.Mode  = GPIO_MODE_OUTPUT_PP;
    GPIO_InitStruct.Pull  = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(GPIOD, &GPIO_InitStruct);
	HAL_GPIO_WritePin(GPIOD, GPIO_PIN_5, GPIO_PIN_RESET);
    return HAL_OK;
}

/*
*********************************************************************************************************
* 函数名 : App_SysCanInit
* 入口参数 : 无
* 返回值 : 初始化成功返回HAL_OK，失败返回HAL_ERROR
* 说明 : CAN1初始化
*********************************************************************************************************
*/

HAL_StatusTypeDef App_SysCanInit(void)
{
    hcan1.Instance = CAN1;
    hcan1.Init.Prescaler = 16;
    hcan1.Init.Mode = CAN_MODE_NORMAL;
    hcan1.Init.SyncJumpWidth = CAN_SJW_1TQ;
    hcan1.Init.TimeSeg1 = CAN_BS1_8TQ;
    hcan1.Init.TimeSeg2 = CAN_BS2_8TQ;
    hcan1.Init.TimeTriggeredMode = DISABLE;
    hcan1.Init.AutoBusOff = DISABLE;
    hcan1.Init.AutoWakeUp = DISABLE;
    hcan1.Init.AutoRetransmission = DISABLE;
    hcan1.Init.ReceiveFifoLocked = DISABLE;
    hcan1.Init.TransmitFifoPriority = DISABLE;
    if (HAL_CAN_Init(&hcan1) != HAL_OK) {
        return HAL_ERROR;
    }

    return HAL_OK;
}

/*
*********************************************************************************************************
* 函数名 : App_SysRtcInit
* 入口参数 : 无
* 返回值 : 初始化成功返回HAL_OK，失败返回HAL_ERROR
* 说明 : RTC初始化(LSI时钟源)
*********************************************************************************************************
*/

HAL_StatusTypeDef App_SysRtcInit(void)
{
    hrtc.Instance = RTC;
    hrtc.Init.HourFormat = RTC_HOURFORMAT_24;
    hrtc.Init.AsynchPrediv = 127;
    hrtc.Init.SynchPrediv = 255;
    hrtc.Init.OutPut = RTC_OUTPUT_DISABLE;
    hrtc.Init.OutPutRemap = RTC_OUTPUT_REMAP_NONE;
    hrtc.Init.OutPutPolarity = RTC_OUTPUT_POLARITY_HIGH;
    hrtc.Init.OutPutType = RTC_OUTPUT_TYPE_OPENDRAIN;
    if (HAL_RTC_Init(&hrtc) != HAL_OK) {
        return HAL_ERROR;
    }

    return HAL_OK;
}

/*
*********************************************************************************************************
* 函数名 : App_SysInit
* 入口参数 : 无
* 返回值 : 全部成功返回HAL_OK，任一失败返回HAL_ERROR
* 说明 : 系统级外设初始化汇总：RCC时钟 -> GPIO -> CAN1 -> RTC
*********************************************************************************************************
*/

HAL_StatusTypeDef App_SysInit(void)
{
    if (App_SysClockCfg() != HAL_OK) {
        return HAL_ERROR;
    }
    if (App_SysGpioInit() != HAL_OK) {
        return HAL_ERROR;
    }
//    if (App_SysCanInit() != HAL_OK) {
//        return HAL_ERROR;
//    }
    if (App_SysRtcInit() != HAL_OK) {
        return HAL_ERROR;
    }

    return HAL_OK;
}
