/*
*********************************************************************************************************
* 文件 : asm330.h
* 作者 : zqh			
* 版本 : V1.0
* 日期 : 2026/8/31
* 描述 : ASM330LHH六轴传感器寄存器层头文件
* 历史 :
*********************************************************************************************************
*/

#ifndef ASM330_H
#define ASM330_H

#include "mbserial_defs.h"

/*
*********************************************************************************************************
*                                          ASM330LHH寄存器地址定义
*********************************************************************************************************
*/

#define ASM330_WHO_AM_I_REG       0x0F   // 芯片ID寄存器
#define ASM330_CTRL1_XL_REG       0x10   // 加速度计控制寄存器1：ODR_XL、FS_XL
#define ASM330_CTRL2_G_REG        0x11   // 陀螺仪控制寄存器2：ODR_G、FS_G
#define ASM330_CTRL3_C_REG        0x12   // 控制寄存器3：BOOT、BDU、IF_INC、SW_RESET
#define ASM330_CTRL4_C_REG        0x13   // 控制寄存器4：I2C_disable等
#define ASM330_CTRL6_C_REG        0x15   // 控制寄存器6：陀螺仪满量程配置
#define ASM330_CTRL7_G_REG        0x16   // 陀螺仪控制寄存器7
#define ASM330_CTRL8_XL_REG       0x17   // 加速度计控制寄存器8
#define ASM330_CTRL9_XL_REG       0x18   // 加速度计控制寄存器9
#define ASM330_CTRL10_C_REG       0x19   // 控制寄存器10
#define ASM330_STATUS_REG_REG     0x1E   // 状态寄存器：XLDA、GDA
#define ASM330_OUT_TEMP_L_REG     0x20   // 温度输出低字节
#define ASM330_OUT_TEMP_H_REG     0x21   // 温度输出高字节
#define ASM330_OUTX_L_G_REG       0x22   // 陀螺仪X轴输出低字节
#define ASM330_OUTX_H_G_REG       0x23   // 陀螺仪X轴输出高字节
#define ASM330_OUTY_L_G_REG       0x24   // 陀螺仪Y轴输出低字节
#define ASM330_OUTY_H_G_REG       0x25   // 陀螺仪Y轴输出高字节
#define ASM330_OUTZ_L_G_REG       0x26   // 陀螺仪Z轴输出低字节
#define ASM330_OUTZ_H_G_REG       0x27   // 陀螺仪Z轴输出高字节
#define ASM330_OUTX_L_XL_REG      0x28   // 加速度计X轴输出低字节
#define ASM330_OUTX_H_XL_REG      0x29   // 加速度计X轴输出高字节
#define ASM330_OUTY_L_XL_REG      0x2A   // 加速度计Y轴输出低字节
#define ASM330_OUTY_H_XL_REG      0x2B   // 加速度计Y轴输出高字节
#define ASM330_OUTZ_L_XL_REG      0x2C   // 加速度计Z轴输出低字节
#define ASM330_OUTZ_H_XL_REG      0x2D   // 加速度计Z轴输出高字节

#define ASM330_WHO_AM_I_VAL       0x6B   // ASM330LHH的WHO_AM_I固定值

/*
*********************************************************************************************************
*                                          ASM330LHH寄存器位定义
*********************************************************************************************************
*/

// CTRL1_XL寄存器(0x10)位定义
#define ASM330_ODR_XL_MSK         0xF0   // 加速度计输出数据速率
#define ASM330_FS_XL_MSK          0x0C   // 加速度计满量程
#define ASM330_LPF2_XL_EN_MSK     0x02   // 加速度计低通滤波器使能

// CTRL2_G寄存器(0x11)位定义
#define ASM330_ODR_G_MSK          0xF0   // 陀螺仪输出数据速率
#define ASM330_FS_G_MSK           0x0E   // 陀螺仪满量程
#define ASM330_FS_125_MSK         0x01   // 陀螺仪125dps量程使能

// CTRL3_C寄存器(0x12)位定义
#define ASM330_BOOT_MSK           0x80   // 重启
#define ASM330_BDU_MSK            0x40   // 数据块更新
#define ASM330_H_LACTIVE_MSK      0x20   // 中断高电平有效
#define ASM330_PP_OD_MSK          0x10   // 推挽/开漏
#define ASM330_SIM_MSK            0x08   // SPI接口选择
#define ASM330_IF_INC_MSK         0x02   // 寄存器地址自动递增
#define ASM330_SW_RESET_MSK       0x01   // 软件复位

// CTRL4_C寄存器(0x13)位定义
#define ASM330_I2C_DISABLE_MSK    0x01   // I2C接口禁用

// STATUS_REG寄存器(0x1E)位定义
#define ASM330_XLDA_MSK           0x01   // 加速度计数据可用
#define ASM330_GDA_MSK            0x02   // 陀螺仪数据可用

/*
*********************************************************************************************************
*                                          ASM330LHH输出速率/量程值定义
*********************************************************************************************************
*/

// 加速度计输出数据速率(CTRL1_XL[7:4])
#define ASM330_ODR_OFF              0x00   // 关闭
#define ASM330_ODR_1_6HZ            0x01   // 1.6Hz
#define ASM330_ODR_12_5HZ           0x02   // 12.5Hz
#define ASM330_ODR_26HZ             0x03   // 26Hz
#define ASM330_ODR_52HZ             0x04   // 52Hz
#define ASM330_ODR_104HZ            0x05   // 104Hz
#define ASM330_ODR_208HZ            0x06   // 208Hz
#define ASM330_ODR_416HZ            0x07   // 416Hz
#define ASM330_ODR_833HZ            0x08   // 833Hz
#define ASM330_ODR_1_66KHZ          0x09   // 1.66kHz
#define ASM330_ODR_3_33KHZ          0x0A   // 3.33kHz
#define ASM330_ODR_6_66KHZ          0x0B   // 6.66kHz

// 加速度计满量程(CTRL1_XL[3:2])
#define ASM330_FS_2G                0x00   // 正负2g
#define ASM330_FS_16G               0x01   // 正负16g
#define ASM330_FS_4G                0x02   // 正负4g
#define ASM330_FS_8G                0x03   // 正负8g

// 陀螺仪满量程(逻辑值，用于App_Asm330SetParam和灵敏度换算)
#define ASM330_FS_250DPS            0x00   // 正负250dps
#define ASM330_FS_500DPS            0x01   // 正负500dps
#define ASM330_FS_1000DPS           0x03   // 正负1000dps
#define ASM330_FS_2000DPS           0x04   // 正负2000dps
#define ASM330_FS_125DPS            0x05   // 正负125dps(逻辑值，寄存器配置特殊)

/*
*********************************************************************************************************
*                                          函数声明
*********************************************************************************************************
*/

INT8U  ASM330_ReadRegByte(INT8U reg);                        // 读单个寄存器
INT32S ASM330_WriteRegByte(INT8U reg, INT8U val);            // 写单个寄存器
INT32S ASM330_ReadRegs(INT8U reg, INT8U *pbuf, INT16U len);  // 连续读多个寄存器
INT32S ASM330_WriteRegs(INT8U reg, INT8U *pbuf, INT16U len); // 连续写多个寄存器

#endif
