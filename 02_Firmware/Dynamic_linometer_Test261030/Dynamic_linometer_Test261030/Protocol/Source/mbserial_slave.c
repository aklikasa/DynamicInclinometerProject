/*
*********************************************************************************************************
* 文件 : mbserial_slave.c
* 作者 : 施江肖			 
* 版本 : v2.0
* 日期 : 2009/3/23
* 描述 : Modbus串行从机API
* 历史 ：2009/3/23    施江肖    创建原始版本    v1.0
*        2017/2/22    zqh       整理原始版本    v2.0
*********************************************************************************************************
*/

#include "mbserial_defs.h"
#include "mbserial_utils.h"
#include "mbserial_slave.h"
#include "crc16_lrc.h"

/*
*********************************************************************************************************
*                                       宏定义
*********************************************************************************************************
*/

#define ARRAY_SIZE(arr)               (sizeof(arr) / sizeof(arr[0]))
#define GetMBSerialSlaveInfo(port)    &MBSerialSlaveInfo[port]			

/*
*********************************************************************************************************
* 描述   : Modbus串行从机帧处理函数指针, 对于ASCII方式, 已经去除':'和尾部0x0d, 0x0a
* 参数   : pif      - 通讯接口函数集
           resp_buf - 存放响应帧的地址
           recv_buf - 接收到的Modbus帧
           recv_len - 接收到的Modbus帧长度
* 返回值 : > 0 返回帧长度
           < 0 错误代码                         
*********************************************************************************************************
*/

typedef INT32S (*MBSERIAL_SLAVE_PROC_FUNC)(const MBSERIAL_SLAVE_COMM_IF *pif, INT8U *resp_buf, INT8U *recv_buf, INT32S recv_len) C51_REENTRANT;

/*
*********************************************************************************************************
*                                       局部函数声明
*********************************************************************************************************
*/

volatile static INT32S MBSerialSlave_RTUProcess(const MBSERIAL_SLAVE_INFO *pinfo, INT8U *presp_buf, INT8U *ppdu, INT32S len) C51_REENTRANT;
static INT32S MBSerialSlave_ReadCoils(const MBSERIAL_SLAVE_COMM_IF *pif, INT8U *presp_buf, INT8U *ppdu, INT32S len) C51_REENTRANT;
static INT32S MBSerialSlave_ReadDecreteInputs(const MBSERIAL_SLAVE_COMM_IF *pif, INT8U *presp_buf, INT8U *ppdu, INT32S len) C51_REENTRANT;
static INT32S MBSerialSlave_ReadHoldingRegisters(const MBSERIAL_SLAVE_COMM_IF *pif, INT8U *presp_buf, INT8U *ppdu, INT32S len) C51_REENTRANT;
static INT32S MBSerialSlave_ReadInputRegisters(const MBSERIAL_SLAVE_COMM_IF *pif, INT8U *presp_buf, INT8U *ppdu, INT32S len) C51_REENTRANT;
static INT32S MBSerialSlave_ForceSingleCoil(const MBSERIAL_SLAVE_COMM_IF *pif, INT8U *presp_buf, INT8U *ppdu, INT32S len) C51_REENTRANT;
static INT32S MBSerialSlave_PresetSingleRegister(const MBSERIAL_SLAVE_COMM_IF *pif, INT8U *presp_buf, INT8U *ppdu, INT32S len) C51_REENTRANT;
static INT32S MBSerialSlave_ForceMultipleCoils(const MBSERIAL_SLAVE_COMM_IF *pif, INT8U *presp_buf, INT8U *ppdu, INT32S len) C51_REENTRANT;
static INT32S MBSerialSlave_PresetMultipleRegisters(const MBSERIAL_SLAVE_COMM_IF *pif, INT8U *presp_buf, INT8U *ppdu, INT32S len) C51_REENTRANT;
static INT32S MBSerialSlave_MaskWriteRegister(const MBSERIAL_SLAVE_COMM_IF *pif, INT8U *presp_buf, INT8U *ppdu, INT32S len) C51_REENTRANT;
static INT32S MBSerialSlave_ReadWriteMultipleRegisters(const MBSERIAL_SLAVE_COMM_IF *pif, INT8U *presp_buf, INT8U *ppdu, INT32S len) C51_REENTRANT;
static INT8U  MBSerialSlave_ErrorConvert(INT32S err) C51_REENTRANT;

/*
*********************************************************************************************************
*                                       Modbus串行从机帧处理函数集合
*********************************************************************************************************
*/

static MBSERIAL_SLAVE_PROC_FUNC const MBSerialSlaveProcFunc[] = 
{                                             // 功能码
    (MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x00 
#if MBF_READ_COILS_EN    
	MBSerialSlave_ReadCoils,                  // 0x01 读线圈
#else
	(MBSERIAL_SLAVE_PROC_FUNC)0,
#endif
#if MBF_READ_DECRETE_INPUTS_EN    
	MBSerialSlave_ReadDecreteInputs,          // 0x02 读离散量输入
#else 
	(MBSERIAL_SLAVE_PROC_FUNC)0,
#endif
#if MBF_READ_HOLDING_REGISTERS_EN
    MBSerialSlave_ReadHoldingRegisters,       // 0x03 读保持寄存器
#else
	(MBSERIAL_SLAVE_PROC_FUNC)0,
#endif
#if MBF_READ_INPUT_REGISTERS_EN
    MBSerialSlave_ReadInputRegisters,         // 0x04 读输入寄存器
#else
	(MBSERIAL_SLAVE_PROC_FUNC)0,
#endif
#if MBF_FORCE_SINGLE_COIL_EN                  // 0x05 强制单个线圈
	MBSerialSlave_ForceSingleCoil,
#else
	(MBSERIAL_SLAVE_PROC_FUNC)0,         
#endif
#if MBF_PRESET_SINGLE_REGISTER_EN    
	MBSerialSlave_PresetSingleRegister,       // 0x06 预置单个寄存器
#else    
	(MBSERIAL_SLAVE_PROC_FUNC)0,
#endif	
	(MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x07
    (MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x08
    (MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x09
    (MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x0A
    (MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x0B
    (MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x0C
    (MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x0D
    (MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x0E
#if MBF_FORCE_MULTIPLE_COILS_EN               // 0x0F 强制多个线圈
	MBSerialSlave_ForceMultipleCoils,     
#else
    (MBSERIAL_SLAVE_PROC_FUNC)0,         
#endif
#if MBF_PRESET_MULTIPLE_REGISTERS_EN    
	MBSerialSlave_PresetMultipleRegisters,    // 0x10 写多个寄存器
#else    
	(MBSERIAL_SLAVE_PROC_FUNC)0,
#endif    
	(MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x11
    (MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x12
    (MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x13
    (MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x14
    (MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x15
#if MBF_MASK_WRITE_REGISTER_EN    
	MBSerialSlave_MaskWriteRegister,          // 0x16 屏蔽写寄存器
#else    
	(MBSERIAL_SLAVE_PROC_FUNC)0,
#endif
#if MBF_READ_WRITE_MULTIPLE_REGISTERS_EN 
	MBSerialSlave_ReadWriteMultipleRegisters, // 0x17 读/写多个寄存器
#else
	(MBSERIAL_SLAVE_PROC_FUNC)0,         
#endif    
	(MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x18
    (MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x19
    (MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x1A
    (MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x1B
    (MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x1C
    (MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x1D
    (MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x1E
    (MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x1F
    (MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x20
    (MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x21
    (MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x22
    (MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x23
    (MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x24
    (MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x25
    (MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x26
    (MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x27
    (MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x28
    (MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x29
    (MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x2A
    (MBSERIAL_SLAVE_PROC_FUNC)0,              // 0x2B
};

/*
*********************************************************************************************************
*                                       Modbus串行从机通讯信息
*********************************************************************************************************
*/

static MBSERIAL_SLAVE_INFO MBSerialSlaveInfo[MAX_MB_SLAVE_PORT_NUM];

/*
*********************************************************************************************************
* 描述   ：Modbus串行从机初始化
* 参数   ：port - 串口号，从0开始计数
*          addr - 从机地址  
*          mode - Modbus串行传输模式, MB_SERIAL_MODE_RTU或者MB_SERIAL_MODE_ASCII
*          pif  - 通讯接口函数集
* 返回值 ：初始化成功，返回MB_ERROR_FREE；初始化失败，返回错误代码。
*********************************************************************************************************
*/

INT32S MBSerialSlaveInit(INT32U port, INT8U addr, INT8U mode, const MBSERIAL_SLAVE_COMM_IF *pif) C51_REENTRANT  
{
    if (port >= MAX_MB_SLAVE_PORT_NUM)
    {
        return MB_ERROR_FUNC_PARAMETER;
    }

    MBSerialSlaveInfo[port].MBSlaveAddr = addr;
    MBSerialSlaveInfo[port].MBMode      = mode;
    MBSerialSlaveInfo[port].pMBCommIf   = pif;
    
	return MB_ERROR_FREE;
}

/*
*********************************************************************************************************
* 描述   ：Modbus串行从机通讯帧处理
* 参数   ：port      - 串口号，从0开始计数   
*          presp_buf - 存放响应帧的地址
*          precv_buf - 接收到的Modbus帧
*          recv_len  - 接收到的Modbus帧长度, ASCII方式下包含: 0x0d 0x0a标记的长度
* 返回值 ：>= 0 响应帧长度, RTU最大256字节, ASCII最大 (512 + 3)
*          < 0 错误代码
*********************************************************************************************************
*/

volatile INT32S MBSerialSlaveFrameProcess(INT32U port, INT8U *presp_buf, INT8U *precv_buf, INT32S recv_len) C51_REENTRANT
{                          
    volatile INT16U              crc, org_crc;
    volatile INT8U               lrc_value;
    volatile INT32S              resp_len = 0;
    volatile MBSERIAL_SLAVE_INFO *pinfo;
	
	if ((port >= MAX_MB_SLAVE_PORT_NUM) || (presp_buf == (INT8U *)0) || (precv_buf == (INT8U *)0))
		return MB_ERROR_FUNC_PARAMETER;

    pinfo = GetMBSerialSlaveInfo(port);
	if (pinfo == (MBSERIAL_SLAVE_INFO *)0)
		return MB_ERROR_NULL_POINTER;
	
    if (pinfo->MBMode == MB_SERIAL_MODE_RTU)        // RTU帧方式 
    {
        if (recv_len < 4)
        {                                           // 从机地址(1) + 功能码(1) + 校验码CRC(2)     
            return MB_ERROR_FRAME_LENGTH;
        }
        if (precv_buf[0] != pinfo->MBSlaveAddr) 
        {                                           // 非本机地址, 不需要制作响应帧                             
            return MB_ERROR_ADDR;
        }
        crc = crc16(precv_buf, recv_len - 2);
		GETU16(org_crc, precv_buf + recv_len - 2);
        if (crc != org_crc)                         // CRC校验出错，不需要制作返回帧         
        {
            return MB_ERROR_CHECK;
        }   
        presp_buf[0] = pinfo->MBSlaveAddr;          // 响应帧的从机地址                                              
        resp_len     = MBSerialSlave_RTUProcess(pinfo, presp_buf + 1, precv_buf + 1, recv_len - 3); 
    }
    else if (pinfo->MBMode == MB_SERIAL_MODE_ASCII) // ASCII帧方式 
    {                                                                                    
        if (recv_len < 9)                           // :(1) + 地址(2) + 功能(2) + LRC(2) + CR,LF(2)
		{
		    return 0;			
		}
				
		if ((precv_buf[0] != ':') || (precv_buf[recv_len - 2] != 0x0d) || (precv_buf[recv_len - 1] != 0x0a))
        {
           return 0;
        }
		
        recv_len  -= 3;
        precv_buf += 1;
        if (recv_len & 0x01) // 帧长度为2的整数倍
        {                    
            return 0;
        }
        recv_len = MBASCIIToData(precv_buf, precv_buf, recv_len);
        if (precv_buf[0] != pinfo->MBSlaveAddr) 
        {                                       // 非本机地址, 不需要制做返回帧
            return 0;
        }        
        lrc_value = lrc(precv_buf, recv_len - 1);
        if (lrc_value != precv_buf[recv_len - 1])     // 校验码LRC出错, 不需要制做返回帧
        {                                   
            return 0;
        }

        presp_buf[0] = ':';                     // 返回帧头 
        presp_buf[1] = pinfo->MBSlaveAddr;      // 返回设备地址       
        resp_len     = MBSerialSlave_RTUProcess(pinfo, presp_buf + 2, precv_buf + 1, recv_len - 2);
    }

    if (resp_len > 0)
    {
        if (pinfo->MBMode == MB_SERIAL_MODE_RTU)  
        {                                      // 添加地址, 添加CRC校验                                        
            resp_len++;                        // 地址码的预留空间                                             
            crc = crc16(presp_buf, resp_len);
            PUTU16(presp_buf + resp_len, crc);
            resp_len += 2;
        } 
        else if (pinfo->MBMode == MB_SERIAL_MODE_ASCII)
        {
            resp_len++;                        // 地址码的预留空间                                             
            lrc_value = lrc(presp_buf + 1, resp_len);    
            presp_buf[++resp_len] = lrc;        
            resp_len = MBDataToASCII(presp_buf + 1, presp_buf + 1,  resp_len); // 转化成ASCII帧方式      
            resp_len = resp_len + 1;                                         // 加上前缀':'的长度1     
            presp_buf[resp_len++] = 0x0d;
            presp_buf[resp_len++] = 0x0a;
        }
    }

    return resp_len;
}

/*
*********************************************************************************************************
* 描述   ：Modbus串行从机RTU帧处理函数, 如果是ASCII方式下, 应先转化成RTU
* 参数   ：pinfo     - Modbus串行从机通讯信息指针
           presp_buf - 存放响应帧的地址
           ppdu      - 接收到的PDU数据包
           len       - 接收到的PDU数据包长度
* 返回值 ：>= 0 响应帧长度 
*          < 0 错误代码
*********************************************************************************************************
*/

volatile static INT32S MBSerialSlave_RTUProcess(const MBSERIAL_SLAVE_INFO *pinfo, INT8U *presp_buf, INT8U *ppdu, INT32S len) C51_REENTRANT
{
    const  MBSERIAL_SLAVE_COMM_IF *pif;
    INT8U  cmd;
    INT32S err = MB_ERROR_UNSUPPORT_FUNC;

	if ((pinfo == (MBSERIAL_SLAVE_INFO *)0) || (presp_buf == (INT8U *)0) || (ppdu == (INT8U *)0))
	    return MB_ERROR_FUNC_PARAMETER;
	
    pif = pinfo->pMBCommIf;            // Modbus通讯接口                         
    cmd = ppdu[0];
    
    if (cmd < ARRAY_SIZE(MBSerialSlaveProcFunc))
    {
        if (MBSerialSlaveProcFunc[cmd])
        {
            err = MBSerialSlaveProcFunc[cmd](pif, presp_buf + 1, ppdu, len);
        }
	    else
	        err = MB_ERROR_UNSUPPORT_FUNC;
    }
    else
    {
        err = MB_ERROR_UNSUPPORT_FUNC;
    }
      
    if (err > 0)
    {
        presp_buf[0] = cmd;
        return (err + 1);
    }
    else
    {
        presp_buf[0] = cmd | 0x80;
        presp_buf[1] = MBSerialSlave_ErrorConvert(err);
        return 2;
    }
}

/*
*********************************************************************************************************
* 描述   ：将程序内部<0的错误代码转化成Modbus所定义的4类错误代码
* 参数   ：err - 程序内部<0的错误代码
* 返回值 ：Modbus定义的错误代码:
*          1 - 非法功能
*          2 - 非法数据地址
*          3 - 非法数据值
*          4 - 从站设备故障
*********************************************************************************************************
*/

static INT8U MBSerialSlave_ErrorConvert(INT32S err) C51_REENTRANT
{
    switch(err)
    {
        case  MB_ERROR_UNSUPPORT_FUNC:
            return 1;
        case  MB_ERROR_ADDR:
            return 2;
        case  MB_ERROR_RANGE:
            return 3;
        case  MB_ERROR_FUNC_EXEC:
            return 4;
        default:
            return 4;
    }
}

#if MBF_READ_COILS_EN 
/*
*********************************************************************************************************
* 描述   ：Modbus串行从机读线圈处理函数
* 参数   ：pif       - 通讯接口函数集
           presp_buf - 存放响应帧的地址
           ppdu      - 接收到的PDU数据包
           len       - 接收到的PDU数据包长度
* 返回值 ：> 0 响应帧长度
           < 0 错误代码
*********************************************************************************************************
*/

static INT32S MBSerialSlave_ReadCoils(const MBSERIAL_SLAVE_COMM_IF *pif, INT8U *presp_buf, INT8U *ppdu, INT32S len) C51_REENTRANT
{
    INT16U addr;
    INT16U num;
    INT8U  *presp;
    INT32S err;

    presp = presp_buf;
    MBGetReadCoils(ppdu, &addr, &num);
	
	if (len != 5)
	{
		return MB_ERROR_FRAME_LENGTH;
	}
	
    if ((num < 1) || (num > 0x7D0)) 
    {
        return MB_ERROR_RANGE;
    }
	
    if (!pif->fnMbReadCoils)
    {
        return MB_ERROR_UNSUPPORT_FUNC;
    }
	
    if ((err = pif->fnMbReadCoils(presp + 1, addr, num)) < 0)
    {
        return err;
    }
	
    num      = (num + 7) >> 3;
    *presp++ = num;
    presp   += num;
	
    return (presp - presp_buf);
}
#endif

#if MBF_READ_DECRETE_INPUTS_EN
/*
*********************************************************************************************************
* 描述   ：Modbus串行从机读离散量输入处理函数
* 参数   ：pif       - 通讯接口函数集
           presp_buf - 存放响应帧的地址
           ppdu      - 接收到的PDU数据包
           len       - 接收到的PDU数据包长度
* 返回值 ：> 0 响应帧长度
           < 0 错误代码
*********************************************************************************************************
*/

static INT32S MBSerialSlave_ReadDecreteInputs(const MBSERIAL_SLAVE_COMM_IF *pif, INT8U *presp_buf, INT8U *ppdu, INT32S len) C51_REENTRANT
{   
    INT16U addr;
    INT16U num;
    INT8U  *presp;
    INT32S err;

    presp = presp_buf; 
    MBGetReadDecreteInputs(ppdu, &addr, &num);

	if (len != 5)
	{
		return MB_ERROR_FRAME_LENGTH;
	}
	
    if ((num < 1) || (num > 0x7D0)) 
    {
        return MB_ERROR_RANGE;
    }
	
    if (!pif->fnMbReadInputDiscretes)
    {
        return MB_ERROR_UNSUPPORT_FUNC;
    }
	
    if ((err = pif->fnMbReadInputDiscretes(presp + 1, addr, num)) < 0)
    {
        return err;
    }
	
    num      = (num + 7) >> 3;
    *presp++ = num;
    presp    += num;
	
    return presp - presp_buf;
}
#endif

#if MBF_READ_HOLDING_REGISTERS_EN
/*
*********************************************************************************************************
* 描述   ：Modbus串行从机读保持寄存器处理函数
* 参数   ：pif       - 通讯接口函数集
           presp_buf - 存放响应帧的地址
           ppdu      - 接收到的PDU数据包
           len       - 接收到的PDU数据包长度
* 返回值 ：> 0 响应帧长度
           < 0 错误代码
*********************************************************************************************************
*/

static INT32S MBSerialSlave_ReadHoldingRegisters(const MBSERIAL_SLAVE_COMM_IF *pif, INT8U *presp_buf, INT8U *ppdu, INT32S len) C51_REENTRANT
{   
    INT16U temp[MAX_HOLDING_REGISTERS_NUM];
    INT16U addr;
    volatile INT16U num;
    INT8U  *presp;
    INT32S err;
	
	if ((pif == (MBSERIAL_SLAVE_COMM_IF *)0) || (presp_buf == (INT8U *)0) || (ppdu == (INT8U *)0))
	    return MB_ERROR_FUNC_PARAMETER;

    presp = presp_buf; 
    MBGetReadHoldingRegisters(ppdu, &addr, &num);

	if (len != 5)                // 功能码(1) + 起始地址(2) + 寄存器数量(2)
	{
		return MB_ERROR_FRAME_LENGTH;
	}
	
    if ((num < 1) || (num > 0x7E)) 
    {
        return MB_ERROR_RANGE;
    }
	
    if (!pif->fnMbReadHoldingRegisters)
    {
        return MB_ERROR_UNSUPPORT_FUNC;
    } 
	
    if ((err = pif->fnMbReadHoldingRegisters(temp, addr, num)) < 0)
    {
        return err;
    }

    *presp++ = num * 2;
    MBDataToBigEndian(presp, temp, num);
    presp   += num * 2;
	
    return presp - presp_buf ;
}
#endif

#if MBF_READ_INPUT_REGISTERS_EN
/*
*********************************************************************************************************
* 描述   ：Modbus串行从机读输入寄存器处理函数
* 参数   ：pif       - 通讯接口函数集
           presp_buf - 存放响应帧的地址
           ppdu      - 接收到的PDU数据包
           len       - 接收到的PDU数据包长度
* 返回值 ：> 0 返回帧长度
           < 0 错误代码
*********************************************************************************************************
*/

static INT32S MBSerialSlave_ReadInputRegisters(const MBSERIAL_SLAVE_COMM_IF *pif, INT8U *presp_buf, INT8U *ppdu, INT32S len) C51_REENTRANT
{   
    INT16U temp[MAX_INPUT_REGISTERS_NUM];
    INT16U addr;
    INT16U num;
    INT8U  *presp;
    INT32S err;
	
	if ((pif == (MBSERIAL_SLAVE_COMM_IF *)0) || (presp_buf == (INT8U *)0) || (ppdu == (INT8U *)0))
	    return MB_ERROR_FUNC_PARAMETER;	

    presp = presp_buf; 
    MBGetReadInputRegisters(ppdu, &addr, &num);
	
	if (len != 5)                // 功能码(1) + 起始地址(2) + 寄存器数量(2)
	{
		return MB_ERROR_FRAME_LENGTH;
	}
	
    if ((num < 1) || (num > 0x7D)) 
    {
        return MB_ERROR_RANGE;
    }	
	
    if (!pif->fnMbReadInputRegisters)
    {
        return MB_ERROR_UNSUPPORT_FUNC;
    }
	
    if ((err = pif->fnMbReadInputRegisters(temp, addr, num)) < 0)
    {
        return err;
    }
    
    *presp++  = num * 2;
    MBDataToBigEndian(presp, temp, num);
    presp    += num * 2;
	
    return presp - presp_buf ;
}
#endif

#if MBF_FORCE_SINGLE_COIL_EN
/*
*********************************************************************************************************
* 描述   ：Modbus串行从机强制单个线圈处理函数
* 参数   ：pif       - 通讯接口函数集
           presp_buf - 存放响应帧的地址
           ppdu      - 接收到的PDU数据包
           len       - 接收到的PDU数据包长度
* 返回值 ：> 0 返回帧长度
           < 0 错误代码
*********************************************************************************************************
*/

static INT32S MBSerialSlave_ForceSingleCoil(const MBSERIAL_SLAVE_COMM_IF *pif, INT8U *presp_buf, INT8U *ppdu, INT32S len) C51_REENTRANT
{   
    INT16U addr;
    INT16U value;
    INT8U  *presp;
    INT32S err;

    presp = presp_buf; 
    MBGetForceSingleCoil(ppdu, &addr, &value);
	
	if (len != 5)
	{
		return MB_ERROR_FRAME_LENGTH;
	}
	
    if ((value != 0xFF00) && (value != 0x0000))
    {
        return MB_ERROR_RANGE;
    }
	
    if (!pif->fnMbForceSingleCoil)
    {
        return MB_ERROR_UNSUPPORT_FUNC;
    }
	
    if ((err = pif->fnMbForceSingleCoil(addr, value)) < 0)
    {
        return err;
    }
 
    PUTU16(presp, addr);
    PUTU16(presp + 2, value);
    presp += 4;
	
    return presp - presp_buf;
}
#endif

#if MBF_PRESET_SINGLE_REGISTER_EN
/*
*********************************************************************************************************
* 描述   ：Modbus串行从机预置单个寄存器处理函数
* 参数   ：pif       - 通讯接口函数集
           presp_buf - 存放响应帧的地址
           ppdu      - 接收到的PDU数据包
           len       - 接收到的PDU数据包长度
* 返回值 ：> 0 返回帧长度
           < 0 错误代码
*********************************************************************************************************
*/

static INT32S MBSerialSlave_PresetSingleRegister(const MBSERIAL_SLAVE_COMM_IF *pif, INT8U *presp_buf, INT8U *ppdu, INT32S len) C51_REENTRANT
{  
    INT16U addr;
    INT16U value;
    INT8U  *presp;
    INT32S err;

    presp = presp_buf; 
    MBGetPresetSingleRegister(ppdu, &addr, &value);
	
    if (len != 5)
    {
        return MB_ERROR_FRAME_LENGTH;
    }
	
    if (!pif->fnMbPresetMultipleRegisters)
    {
        return MB_ERROR_UNSUPPORT_FUNC;
    }
	
    if ((err = pif->fnMbPresetMultipleRegisters(&value, addr, 1)) < 0)
    {
        return err;
    }
  
    PUTU16(presp, addr);
    PUTU16(presp + 2, value);
    presp += 4;
	
    return presp - presp_buf;
}
#endif

#if MBF_FORCE_MULTIPLE_COILS_EN 
/*
*********************************************************************************************************
* 描述   ：Modbus串行从机强制多个线圈处理函数
* 参数   ：pif       - 通讯接口函数集
           presp_buf - 存放响应帧的地址
           ppdu      - 接收到的PDU数据包
           len       - 接收到的PDU数据包长度
* 返回值 ：> 0 返回帧长度
           < 0 错误代码
*********************************************************************************************************
*/

static INT32S MBSerialSlave_ForceMultipleCoils(const MBSERIAL_SLAVE_COMM_IF *pif, INT8U *presp_buf, INT8U *ppdu, INT32S len) C51_REENTRANT
{   
    INT8U  tmp[MAX_COILS_NUM];
	INT16U addr;
	INT16U num;
	INT8U  size;
    INT16U value;
    INT8U  *presp;
    INT32S err;

    presp = presp_buf; 
    err   = MBGetForceMultipleCoils(ppdu, &addr, &num, &size, tmp);
	if (err != MB_ERROR_FREE)
		return err;
	
	if (len != 6 + size)
	{
		return MB_ERROR_FRAME_LENGTH;
	}
	
	if ((num < 1) || (num > 0x7B0) || (size != ((num+7) / 8)))
    {
        return MB_ERROR_RANGE;
    } 
	
    if (!pif->fnMbForceMultipleCoils)
    {
        return MB_ERROR_UNSUPPORT_FUNC;
    }
	
    if ((err = pif->fnMbForceMultipleCoils(tmp, addr, num)) < 0)
    {
        return err;
    }
 
    PUTU16(presp, addr);
    PUTU16(presp + 2, num);
    presp += 4;
	
    return presp - presp_buf;
}
#endif

#if MBF_PRESET_MULTIPLE_REGISTERS_EN
/*
*********************************************************************************************************
* 描述   ：Modbus串行从机预置多个寄存器处理函数
* 参数   ：pif       - 通讯接口函数集
           presp_buf - 存放响应帧的地址
           ppdu      - 接收到的PDU数据包
           len       - 接收到的PDU数据包长度
* 返回值 ：> 0 返回帧长度
           < 0 错误代码
*********************************************************************************************************
*/

static INT32S MBSerialSlave_PresetMultipleRegisters(const MBSERIAL_SLAVE_COMM_IF *pif, INT8U *presp_buf, INT8U *ppdu, INT32S len) C51_REENTRANT
{  
    INT16U tmp[MAX_HOLDING_REGISTERS_NUM];
    INT16U addr;
    INT16U num;
    INT8U  bytes;
    INT8U  *presp;
    INT32S err;
    INT32S i;

    presp = presp_buf; 
    err   = MBGetPresetMultipleRegisters(ppdu, &addr, &num, &bytes, tmp);
	if (err != MB_ERROR_FREE)
		return err;
    
	if (len != 6 + bytes)
	{
		return MB_ERROR_FRAME_LENGTH;
	}
	
	if ((num < 1) || (num > 0x7B) || (bytes != num * 2))
    {
        return MB_ERROR_RANGE;
    } 
	
    if (!pif->fnMbPresetMultipleRegisters)
    {
        return MB_ERROR_UNSUPPORT_FUNC;
    }
    else
    {
        if ((err = pif->fnMbPresetMultipleRegisters(tmp, addr, num)) < 0)
        {
            return err;
        }
		
        PUTU16(presp, addr);
        PUTU16(presp + 2, num);
        presp  += 4;
    }
	
    return presp - presp_buf;
}
#endif

#if MBF_MASK_WRITE_REGISTER_EN
/*
*********************************************************************************************************
* 描述   ：Modbus串行从机屏蔽写寄存器处理函数
* 参数   ：pif       - 通讯接口函数集
           presp_buf - 存放响应帧的地址
           ppdu      - 接收到的PDU数据包
           len       - 接收到的PDU数据包长度
* 返回值 ：> 0 返回帧长度
           < 0 错误代码
*********************************************************************************************************
*/

static INT32S MBSerialSlave_MaskWriteRegister(const MBSERIAL_SLAVE_COMM_IF *pif, INT8U *presp_buf, INT8U *ppdu, INT32S len) C51_REENTRANT
{
    INT16U addr;
    INT16U andmask;
    INT16U ormask;
    INT8U  *presp;
    INT32S err;

    presp = presp_buf; 
    MBGetMaskWriteRegister(ppdu, &addr, &andmask, &ormask);
    
	if (len != 7)
    {
        return MB_ERROR_FRAME_LENGTH;
    }
	
    if (!pif->fnMbMaskWriteRegister)
    {
        return MB_ERROR_UNSUPPORT_FUNC;
    }
	
    if ((err = pif->fnMbMaskWriteRegister(addr, andmask, ormask)) < 0)
    {
        return err;
    }
 
    PUTU16(presp, addr);
    PUTU16(presp + 2, andmask);
    PUTU16(presp + 4, ormask);
    presp += 6;
	
    return presp - presp_buf;
}

#endif

#if MBF_READ_WRITE_MULTIPLE_REGISTERS_EN
/*
*********************************************************************************************************
* 描述   ：Modbus串行从机读写多个寄存器处理函数
* 参数   ：pif       - 通讯接口函数集
           presp_buf - 存放响应帧的地址
           ppdu      - 接收到的PDU数据包
           len       - 接收到的PDU数据包长度
* 返回值 ：> 0 返回帧长度
           < 0 错误代码
*********************************************************************************************************
*/

static INT32S MBSerialSlave_ReadWriteMultipleRegisters(const MBSERIAL_SLAVE_COMM_IF *pif, INT8U *presp_buf, INT8U *ppdu, INT32S len) C51_REENTRANT
{
	INT16U value_rd[MAX_HOLDING_REGISTERS_NUM];
	INT16U reg_addr_rd;
	INT16U num_rd;
	INT16U reg_addr_wr;
	INT16U num_wr;
	INT8U  size;
	INT16U value_wr[MAX_HOLDING_REGISTERS_NUM];
	INT8U *presp;
	INT32S err;

	presp = presp_buf;
	err   = MBGetReadWriteMultipleRegisters(ppdu, &reg_addr_rd, &num_rd, &reg_addr_wr, &num_wr, &size, value_wr);
	if (err != MB_ERROR_FREE)
		return err;

	if (len != 10 + size)
    {
        return MB_ERROR_FRAME_LENGTH;
    }

	if (!pif->fnMbReadWriteMultipleRegisters)
    {
        return MB_ERROR_UNSUPPORT_FUNC;
    }
	
    if ((err = pif->fnMbReadWriteMultipleRegisters(value_rd, reg_addr_rd, num_rd, value_wr, reg_addr_wr, num_wr)) < 0)
    {
        return err;
    }

	*presp++ = num_rd * 2;
    MBDataToBigEndian(presp, value_rd, num_rd);
    presp   += num_rd * 2;
	
    return presp - presp_buf;
}

#endif
