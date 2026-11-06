/*
*********************************************************************************************************
* 文件 : asm330.h
* 作者 : zqh			
* 版本 : V1.0
* 日期 : 2026/8/31
* 描述 : ASM330LHH六轴传感器寄存器层头文件(含FIFO寄存器定义)
* 历史 :
*********************************************************************************************************
*/

#ifndef ASM330_H
#define ASM330_H

#include <stdint.h>

/*
*********************************************************************************************************
*                                          返回状态定义
*********************************************************************************************************
*/

#define ASM330_OK                     0    // 操作成功
#define ASM330_ERROR                  (-1) // 操作失败

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
*                                          ASM330LHH FIFO寄存器地址定义
*********************************************************************************************************
*/

#define ASM330_FIFO_CTRL1_REG     0x07   // FIFO控制寄存器1：水印阈值WTM[7:0]
#define ASM330_FIFO_CTRL2_REG     0x08   // FIFO控制寄存器2：WTM[8]、FIFO_TEMP_EN、STOP_ON_WTM
#define ASM330_FIFO_CTRL3_REG     0x09   // FIFO控制寄存器3：BDR_XL[7:4]、BDR_GY[3:0]
#define ASM330_FIFO_CTRL4_REG     0x0A   // FIFO控制寄存器4：温度批处理ODR(ODR_T)、时间戳抽取
#define ASM330_COUNTER_BDR_REG1   0x0B   // FIFO控制寄存器5：ODR_FIFO[6:3]、FIFO_MODE[2:0]
#define ASM330_COUNTER_BDR_REG2   0x0C   // FIFO控制寄存器5：ODR_FIFO[6:3]、FIFO_MODE[2:0]
#define ASM330_INT1_CTRL_REG      0x0D   // INT1引脚功能控制
#define ASM330_INT2_CTRL_REG      0x0E   // INT2引脚功能控制
#define ASM330_FIFO_STATUS1_REG   0x3A   // FIFO状态寄存器1：DIFF_FIFO[7:0]
#define ASM330_FIFO_STATUS2_REG   0x3B   // FIFO状态寄存器2：DIFF_FIFO[9:8]及各类标志
#define ASM330_FIFO_DATA_OUT_TAG_REG   0x78   // FIFO输出TAG寄存器
#define ASM330_FIFO_DATA_OUT_X_L_REG   0x79   // FIFO输出数据首字节(TAG之后)

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
#define ASM330_BDU_MSK            0x40   // 数据块更新
#define ASM330_H_LACTIVE_MSK      0x20   // 中断高电平有效
#define ASM330_PP_OD_MSK          0x10   // 推挽/开漏
#define ASM330_SIM_MSK            0x08   // SPI接口选择
#define ASM330_IF_INC_MSK         0x04   // 寄存器地址自动递增
#define ASM330_SW_RESET_MSK       0x01   // 软件复位

// CTRL4_C寄存器(0x13)位定义
#define ASM330_I2C_DISABLE_MSK    0x01   // I2C接口禁用

// STATUS_REG寄存器(0x1E)位定义
#define ASM330_XLDA_MSK           0x01   // 加速度计数据可用
#define ASM330_GDA_MSK            0x02   // 陀螺仪数据可用

// FIFO_CTRL2寄存器(0x07)位定义
#define ASM330_FIFO_WTM8_MSK          0x01   // 水印阈值WTM[8]
#define ASM330_FIFO_ODRCHG_EN_MSK     0x04   // ODR变化时清空FIFO使能
#define ASM330_FIFO_CFG_EN_MSK        0x10   // 配置信息批处理使能
#define ASM330_FIFO_CFG_DIS_MSK       0x00   // 配置信息批处理不进入FIF
#define ASM330_FIFO_STOP_ON_WTM_MSK   0x80   // 到达水印后停止采集

// FIFO_CTRL3寄存器(0x08)位定义
#define ASM330_FIFO_BDR_XL_POS        4      // 加速度计批处理速率位置
#define ASM330_FIFO_BDR_XL_MSK        0xF0   // 加速度计批处理速率
#define ASM330_FIFO_BDR_GY_MSK        0x0F   // 陀螺仪批处理速率

// FIFO_CTRL4寄存器(0x09)位定义
#define ASM330_FIFO_ODR_T_MSK         0x03   // 温度批处理输出速率

// FIFO_CTRL5寄存器(0x0A)位定义
#define ASM330_FIFO_ODR_FIFO_POS      3      // FIFO写入速率位置
#define ASM330_FIFO_ODR_FIFO_MSK      0x78   // FIFO写入速率
#define ASM330_FIFO_MODE_MSK          0x07   // FIFO工作模式

// FIFO_STATUS2寄存器(0x3B)位定义
#define ASM330_FIFO_STATUS_WTM_IA_MSK    0x80   // 水印中断标志
#define ASM330_FIFO_STATUS_OVR_IA_MSK    0x40   // 溢出中断标志
#define ASM330_FIFO_STATUS_FULL_IA_MSK   0x20   // FIFO满标志
#define ASM330_FIFO_STATUS_EMPTY_MSK     0x08   // FIFO空标志
#define ASM330_FIFO_STATUS_DIFF_H_MSK    0x03   // 未读数据量高2位

// INT1_CTRL/INT2_CTRL寄存器位定义
#define ASM330_INT_FTH_MSK            0x08   // FIFO水印(阈值)中断使能位(bit3)

/*
*********************************************************************************************************
*                                          ASM330LHH输出速率/量程值定义
*********************************************************************************************************
*/

// 加速度计输出数据速率(CTRL1_XL[7:4])与陀螺仪输出速率(CTRL2_G[7:4])
#define ASM330_ODR_OFF              0x00   // 关闭
#define ASM330_ODR_1_6HZ            0x0B   // 1.6Hz
#define ASM330_ODR_12_5HZ           0x01   // 12.5Hz
#define ASM330_ODR_26HZ             0x02  // 26Hz
#define ASM330_ODR_52HZ             0x03   // 52Hz
#define ASM330_ODR_104HZ            0x04   // 104Hz
#define ASM330_ODR_208HZ            0x05   // 208Hz
#define ASM330_ODR_416HZ            0x06   // 416Hz
#define ASM330_ODR_833HZ            0x07   // 833Hz
#define ASM330_ODR_1_66KHZ          0x08   // 1.66kHz
#define ASM330_ODR_3_33KHZ          0x09   // 3.33kHz
#define ASM330_ODR_6_66KHZ          0x0A   // 6.66kHz

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

// FIFO批处理速率(FIFO_CTRL3的BDR_XL/BDR_GY、FIFO_CTRL5的ODR_FIFO)
#define ASM330_BDR_NOT_BATCHED      0x00   // 不批处理
#define ASM330_BDR_12_5HZ           0x01   // 12.5Hz
#define ASM330_BDR_26HZ             0x02   // 26Hz
#define ASM330_BDR_52HZ             0x03   // 52Hz
#define ASM330_BDR_104HZ            0x04   // 104Hz
#define ASM330_BDR_208HZ            0x05   // 208Hz
#define ASM330_BDR_416HZ            0x06   // 416Hz
#define ASM330_BDR_833HZ            0x07   // 833Hz
#define ASM330_BDR_1_66KHZ          0x08   // 1.66kHz
#define ASM330_BDR_3_33KHZ          0x09   // 3.33kHz
#define ASM330_BDR_6_66KHZ          0x0A   // 6.66kHz

// FIFO工作模式(FIFO_CTRL5的FIFO_MODE[2:0])
#define ASM330_FIFO_MODE_BYPASS         0x00   // 旁路模式(FIFO关闭)
#define ASM330_FIFO_MODE_FIFO           0x01   // FIFO模式(满后停止写入)
#define ASM330_FIFO_MODE_STREAM_TO_FIFO 0x03   // 触发后转FIFO模式
#define ASM330_FIFO_MODE_BYPASS_STREAM  0x04   // 旁路转流模式
#define ASM330_FIFO_MODE_STREAM         0x06   // 流模式(满后覆盖最旧数据)
#define ASM330_FIFO_MODE_BYPASS_TO_FIFO 0x07   // 旁路转FIFO模式

// 温度批处理输出速率(FIFO_CTRL4的ODR_T[1:0])
#define ASM330_TEMP_NOT_BATCHED     0x00   // 温度不批处理
#define ASM330_TEMP_BATCH_1_6HZ     0x01   // 1.6Hz
#define ASM330_TEMP_BATCH_12_5HZ    0x02   // 12.5Hz
#define ASM330_TEMP_BATCH_52HZ      0x03   // 52Hz
// 时间批处理输出速率(FIFO_CTRL4的ODR_T[1:0])
#define ASM330_TIME_NOT_BATCHED     0x00   // 时间不批处理
#define ASM330_TIME_BATCH_1_6HZ     0x01   // odr
#define ASM330_TIME_BATCH_12_5HZ    0x02   // odr/8
#define ASM330_TIME_BATCH_52HZ      0x03   // odr/32

/*
*********************************************************************************************************
*                                          ASM330LHH FIFO数据TAG定义
*********************************************************************************************************
*/

#define ASM330_FIFO_TAG_POS         3      // TAG位于TAG字节的高5位
#define ASM330_FIFO_TAG_GYRO        0x01   // 陀螺仪数据
#define ASM330_FIFO_TAG_ACC         0x02   // 加速度计数据
#define ASM330_FIFO_TAG_TIMESTAMP   0x04   // 时间戳数据
#define ASM330_FIFO_TAG_TEMP        0x05   // 温度数据(需与手册核对)
#define ASM330_FIFO_TAG_EXT0        0x0F   // 外部传感器0数据
#define ASM330_FIFO_TAG_EXT1        0x10   // 外部传感器1数据
#define ASM330_FIFO_TAG_EXT2        0x11   // 外部传感器2数据

#define ASM330_FIFO_GYRO_LEN        6      // 陀螺仪数据字节数
#define ASM330_FIFO_ACC_LEN         6      // 加速度计数据字节数
#define ASM330_FIFO_TEMP_LEN        2      // 温度数据字节数(需与手册核对)
#define ASM330_FIFO_TS_LEN          4      // 时间戳数据字节数

/*
*********************************************************************************************************
*                                          函数声明
*********************************************************************************************************
*/

uint8_t  ASM330_ReadRegByte(uint8_t reg);                        // 读单个寄存器
int32_t  ASM330_WriteRegByte(uint8_t reg, uint8_t val);          // 写单个寄存器
int32_t  ASM330_ReadRegs(uint8_t reg, uint8_t *pbuf, uint16_t len);  // 连续读多个寄存器
int32_t  ASM330_WriteRegs(uint8_t reg, uint8_t *pbuf, uint16_t len); // 连续写多个寄存器

int32_t  ASM330_ReadFifoStatus(uint16_t *pwords, uint8_t *pflags);   // 读FIFO状态(未读字数与标志)
int32_t  ASM330_ReadFifoData(uint8_t *pbuf, uint16_t len);           // 连续读FIFO数据(自TAG寄存器起)
int32_t  ASM330_FifoReset(void);                                     // 复位FIFO(先BYPASS再切回)

#endif
