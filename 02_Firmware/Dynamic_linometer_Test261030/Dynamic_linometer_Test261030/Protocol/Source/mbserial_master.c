/*---------------------------------------------------------------------------*/
/**
  @file     mbserial_master.c
  @brief    Example modbus serial master API define file

  This file contains higher level modbus serial master utility functions.
  It supports both RTU and ASCII protocol and converts them implicity.

  History:
  Date          Author             Comment
  08-02-2005    AceLan Kao.        Create it.
  06-04-2017    zqh	               整理及完善源代码
  @author AceLan Kao.(acelan_kao@moxa.com.tw)
 */
/*---------------------------------------------------------------------------*/
#include "mbserial_defs.h"
#include "mbserial_utils.h"
#include "mbserial_master.h"
#include "crc16_lrc.h"

static MBSERIAL_MASTER_INFO MBSerialMasterInfo[MAX_MB_MASTER_PORT_NUM];

/*---------------------------------------------------------------------------*/
/**
  @brief    open modbus serial master port for modbus protocol
  @param    port     port number
  @param    pinfo    point to modbus serial master info
  @return   MB_ERROR_FREE for success, on error return error code
 */
/*---------------------------------------------------------------------------*/
INT32S MBSerialMasterOpen(INT32U port, MBSERIAL_MASTER_INFO *pinfo)
{
    if (port > MAX_MB_MASTER_PORT_NUM)
        return (MB_ERROR_FUNC_PARAMETER);
    if (pinfo == (MBSERIAL_MASTER_INFO *)0)
        return (MB_ERROR_FUNC_PARAMETER);

    MBSerialMasterInfo[port] = *pinfo;

	if (!MBSerialMasterInfo[port].pif->fnSerialOpen)
        return (MB_ERROR_NULL_POINTER);
    return MBSerialMasterInfo[port].pif->fnSerialOpen(port);		
}

/*---------------------------------------------------------------------------*/
/**
  @brief    close the modbus serial master port
  @param    port    port number
  @return   MB_ERROR_FREE for success, on error return error code
 */
/*---------------------------------------------------------------------------*/
INT32S MBSerialMasterClose(INT32U port)
{
    MBSERIAL_MASTER_COMM_IF *pif;

	if (port > MAX_MB_MASTER_PORT_NUM)
        return (MB_ERROR_FUNC_PARAMETER);

    pif = MBSerialMasterInfo[port].pif;

	if (pif == (MBSERIAL_MASTER_COMM_IF *)0)
		return MB_ERROR_NULL_POINTER;
	if (!pif->fnSerialClose)
		return MB_ERROR_NULL_POINTER;

    return pif->fnSerialClose(port);
}

/*---------------------------------------------------------------------------*/
/**
  @brief    get transmit pdu buf
  @param    port   port number
  @param    buf    temp buf pointer
  @return   transmit pdu buf pointer
 */
/*---------------------------------------------------------------------------*/
static INT8U *MBSerialMaster_GetTxPduBuf(INT32U port, INT8U *buf)
{
    INT8U *pdu;

    if (MBSerialMasterInfo[port].ptx_buf != (INT8U *)0) {
        pdu = MBSerialMasterInfo[port].ptx_buf;
    } else {
        pdu = buf;
    }

    if (MBSerialMasterInfo[port].mode == MB_SERIAL_MODE_RTU) {
        pdu += 1;
    } else if (MBSerialMasterInfo[port].mode == MB_SERIAL_MODE_ASCII) {
        pdu += 2;
    }

    return pdu;
}

/*---------------------------------------------------------------------------*/
/**
  @brief    get receive adu buf
  @param    port   port number
  @param    buf    temp buf pointer
  @return   receive adu buf pointer
 */
/*---------------------------------------------------------------------------*/
static INT8U *MBSerialMaster_GetRxAduBuf(INT32U port, INT8U *buf)
{
    INT8U *adu;

    if (MBSerialMasterInfo[port].prx_buf != (INT8U *)0) {
        adu = MBSerialMasterInfo[port].prx_buf;
    } else {
        adu = buf;
    }    

    return adu;                                                   
}

/*---------------------------------------------------------------------------*/
/**
  @brief    make ADU packet and write ADU packet to port
  @param    port         port number
  @param    slave_addr   slave address
  @param    pdu          PDU packet
  @param    len          PDU size
  @return   length of data actually write, on error return error code
 */
/*---------------------------------------------------------------------------*/
static INT32S MBSerialMaster_WriteAdu(INT32U port, INT8U slave_addr, INT8U *pdu, INT32S len)
{
    INT8U  lrc_value;
    INT16U crc;
    MBSERIAL_MASTER_COMM_IF *pif;

    pif = MBSerialMasterInfo[port].pif;
	if (pif == (MBSERIAL_MASTER_COMM_IF *)0)
	{
		return MB_ERROR_NULL_POINTER;
	}

    switch(MBSerialMasterInfo[port].mode)
    {
        case MB_SERIAL_MODE_ASCII:
            *(pdu - 2) = ':';
            *(pdu - 1) = slave_addr;
            lrc_value = lrc(pdu - 1, len + 1);
            pdu[len] = lrc_value;
            len  = MBDataToASCII(pdu-1, pdu-1, len + 2);
            pdu[len - 1] = 0x0d;
            pdu[len]     = 0x0a;
            if (pif->fnSerialWrite)
            {
                return  pif->fnSerialWrite(port, (pdu - 2), len + 3);
            }
            else
            {
                return MB_ERROR_NULL_FUNC;
            }
        case MB_SERIAL_MODE_RTU:
            *(pdu - 1) = slave_addr;
            crc = crc16(pdu-1, len + 1);
            PUTU16(pdu + len, crc);
            if (pif->fnSerialWrite)
            {
                return  pif->fnSerialWrite(port, (pdu - 1), len + 3);
            }
            else
            {
                return MB_ERROR_NULL_FUNC;
            }
        default:
            return MB_ERROR_PROTOCOL;
    }
}

/*---------------------------------------------------------------------------*/
/**
  @brief    send adu packet and wait response adu from slave
  @param    port         port number
  @param    slave_addr   slave address
  @param    buf          input buffer for receive adu from slave
  @param    expect_len   expect length of response 
  @param    pdu          pdu data prepare to send to slave
  @param    len          pdu length
  @return   >= 0 RTU方式下通讯数据的长度, 去除校验, ASCII方式去除':'0x0d, 0x0a
            < 0  错误代码 
 */
/*---------------------------------------------------------------------------*/
static INT32S MBSerialMaster_SendAndWaitResponse(INT32U port, INT8U slave_addr, INT8U *buf, INT32S expect_len, INT8U *pdu, INT32S pdu_len)
{
    INT16U lrc_value, crc, org_crc;
    MBSERIAL_MASTER_COMM_IF *pif;
    INT32S ret_len = 0;
        
    pif = MBSerialMasterInfo[port].pif;
	if (pif == (MBSERIAL_MASTER_COMM_IF *)0)
	{
        return MB_ERROR_NULL_POINTER;
	}
    if (!pif->fnSerialRead)
	{
        return MB_ERROR_NULL_FUNC;
	}

    ret_len = MBSerialMaster_WriteAdu(port, slave_addr, pdu, pdu_len);
	if (ret_len < 0) 
	{
        return ret_len;
	}

    if (MBSerialMasterInfo[port].mode == MB_SERIAL_MODE_RTU)
    {
        ret_len = pif->fnSerialRead(port, buf, expect_len);
        if (ret_len < 0)                               // 无正常响应！
		{
            ret_len = pif->fnSerialRead(port, buf, 5); // 是否有异常响应？地址(1) + 差错码(1) + 异常码(1) + CRC(2)
			if (ret_len < 0)                           // 超时，无任何数据返回！
			    return ret_len;
        }
        if (ret_len < 4)                              // 地址(1) + 功能码(1) + CRC(2)
		{
           return MB_ERROR_FRAME_LENGTH;
        }
        crc= crc16(buf, ret_len - 2);
        GETU16(org_crc, buf + ret_len- 2);
        if( crc != org_crc)
        {
           return MB_ERROR_CHECK;
        }
        return ret_len - 2;
    }
    else if (MBSerialMasterInfo[port].mode == MB_SERIAL_MODE_ASCII)
    {
        expect_len = MBRTULenToASCII(expect_len);
        ret_len    = pif->fnSerialRead(port, buf, expect_len);
        if (ret_len < 0)                                // 无正常响应！
		{
            ret_len = pif->fnSerialRead(port, buf, 11); // 是否有异常响应？:(1) + 地址(2) + 差错码(2) + 异常码(2) + LRC(2) + 0x0d、0x0a(2)
			if (ret_len < 0)                            // 超时，无任何数据返回！
			    return ret_len;            
        }
        if (ret_len < 9)                               // :(1) + 地址(2) + 功能码(2) + LRC(2) + 0x0d、0x0a(2)
		{
           return MB_ERROR_FRAME_LENGTH;
        }
        ret_len = MBASCIIToData(buf, &buf[1], ret_len - 3);
        lrc_value = lrc(buf, ret_len - 1);
        if (lrc_value != buf[ret_len - 1])
        {
          return MB_ERROR_CHECK;
        }
        return ret_len - 1;
    }
    else
    {
        return MB_ERROR_PROTOCOL;
    }
}

/*---------------------------------------------------------------------------*/
/**
  @brief    get frame timeout
  @param    port    port number
  @return   frame timeout value
 */
/*---------------------------------------------------------------------------*/
INT16U MBSerialMasterGetFrameTimeout(INT32U port)
{
    return MBSerialMasterInfo[port].FrameTimeout;
}

/*---------------------------------------------------------------------------*/
/**
  @brief    set frame timeout
  @param    port       port number
  @param    timeout    new frame timeout value
  @return   none
 */
/*---------------------------------------------------------------------------*/
void MBSerialMasterSetFrameTimeout(INT32U port, INT16U timeout)
{
    MBSerialMasterInfo[port].FrameTimeout = timeout;
}

/*---------------------------------------------------------------------------*/
/**
  @brief    get char timeout
  @param    port    port number
  @return   char timeout value
 */
/*---------------------------------------------------------------------------*/
INT16U MBSerialMasterGetCharTimeout(INT32U port)
{
    return MBSerialMasterInfo[port].CharTimeout;
}

/*---------------------------------------------------------------------------*/
/**
  @brief    set char timeout
  @param    port       port number
  @param    timeout    new frame timeout value
  @return   none
 */
/*---------------------------------------------------------------------------*/
void MBSerialMasterSetCharTimeout(INT32U port, INT16U timeout)
{
    MBSerialMasterInfo[port].CharTimeout = timeout;
}

/*---------------------------------------------------------------------------*/
/**
  @brief    get response timeout
  @param    port    port number
  @return   response timeout value
 */
/*---------------------------------------------------------------------------*/
INT16U MBSerialMasterGetResponseTimeout(INT32U port)
{
    return MBSerialMasterInfo[port].ResponseTimeout;
}

/*---------------------------------------------------------------------------*/
/**
  @brief    set new response timeout
  @param    port       port number
  @param    timeout    new response timeout value
  @return   none
 */
/*---------------------------------------------------------------------------*/
void MBSerialMasterSetResponseTimeout(INT32U port, INT16U timeout)
{
    MBSerialMasterInfo[port].ResponseTimeout = timeout;
}

/*---------------------------------------------------------------------------*/
/**
  @brief    get device address from ADU
  @param    adu    ADU data
  @return   none
 */
/*---------------------------------------------------------------------------*/
INT8U MBSerialMasterGetSlaveAddress(const INT8U *adu)
{
    return MBGetAddress(adu);
}

/*---------------------------------------------------------------------------*/
/**
  @brief    get PDU part from ADU data
  @param    buf    output buffer
  @param    adu    ADU data with error check code
  @param    len    length of the adu data
  @return   the length of PDU data
 */
/*---------------------------------------------------------------------------*/
INT32S MBSerialMasterGetPDU(INT8U *buf, INT8U *adu, INT32S len)
{
    return MBGetPDU(buf, adu, len);
}

/*---------------------------------------------------------------------------*/
/**
  @brief    set modbus serial master communication speed eg: serial baud rate
  @param    port         port number
  @param    baud_rate    baud rate
  @return   return MB_ERROR_FREE for success, on error return error code
 */
/*---------------------------------------------------------------------------*/
INT32S MBSerialMasterSetSpeed(INT32U port, INT32S baud_rate)
{
    MBSERIAL_MASTER_COMM_IF *pif;    
	
    if (port > MAX_MB_MASTER_PORT_NUM)
        return (MB_ERROR_FUNC_PARAMETER);  

    pif = (MBSERIAL_MASTER_COMM_IF *)MBSerialMasterInfo[port].pif;

	if (pif == (MBSERIAL_MASTER_COMM_IF *)0)
	    return (MB_ERROR_NULL_POINTER);
	if (!pif->fnSerialSetSpeed)
		return (MB_ERROR_NULL_POINTER);

    return pif->fnSerialSetSpeed(port, baud_rate);
}

/*---------------------------------------------------------------------------*/
/**
  @brief    set modbus serial master communication parameter eg: serial baud rate、data bis、parity bits、stop bits 
  @param    port         port number
  @param    baud_rate    baud rate
  @param    data_bits    data bis
  @param    parity       parity bits
  @param    stop_bits    stop bis
  @return   return MB_ERROR_FREE for success, on error return error code
 */
/*---------------------------------------------------------------------------*/
INT32S MBSerialMasterSetParam(INT32U port, INT32S baud_rate, INT32S data_bits, INT32S parity, INT32S stop_bits)
{
    MBSERIAL_MASTER_COMM_IF *pif;    
	
	if (port > MAX_MB_MASTER_PORT_NUM)
        return (MB_ERROR_FUNC_PARAMETER);  

    pif = (MBSERIAL_MASTER_COMM_IF *)MBSerialMasterInfo[port].pif;

	if (pif == (MBSERIAL_MASTER_COMM_IF *)0)
	    return (MB_ERROR_NULL_POINTER);
	if (!pif->fnSerialSetParam)
		return (MB_ERROR_NULL_POINTER);

    return pif->fnSerialSetParam(port, baud_rate, parity, data_bits, stop_bits);
}

/* Modbus serial master function */

#if MBF_READ_DECRETE_INPUTS_EN               != 0 
/*---------------------------------------------------------------------------*/
/**
  @brief    send Read Decrete Inputs request and get response(0x02)
  @param    port              which port to use
  @param    slave_addr        slave device address
  @param    input_addr        starting decrete inputs number
  @param    num               number of decrete inputs, between 1 ~ 2000
  @param    value             decrete inputs status slave returned
  @param    exception_code    exception code for exception response
  @return   MB_ERROR_FREE for success, MB_ERROR_SLAVE_EXCEPTION_RESPONSE for exception response, on error return error code
 */
/*---------------------------------------------------------------------------*/
INT32S MBSerialMasterReadDecreteInputs(INT32U port, INT8U slave_addr, INT16U input_addr, INT16U num, INT8U *value, INT8U *exception_code)
{
    INT8U  buf[(1 + 1 + 1 + ((MAX_DECRETE_INPUT_NUM + 7) / 8)) * 2 + 2 + 3]; // ASCII模式：从机地址 + 功能码 + 字节数 + 输入状态  + LRC + 起始符':' + 结束符'0x0d''0x0a'
    INT32S pdu_len, adu_len, expect_len, ret;
    INT8U  ret_bytes;
    INT8U  *adu, *pdu;

	if ((port > MAX_MB_MASTER_PORT_NUM) || (num > MAX_DECRETE_INPUT_NUM) || (value == (INT8U *)0) || (exception_code == (INT8U *)0))
        return (MB_ERROR_FUNC_PARAMETER);

    pdu = MBSerialMaster_GetTxPduBuf(port, buf);
    adu = MBSerialMaster_GetRxAduBuf(port, buf);

    pdu_len    = MBReadDecreteInputs(pdu, input_addr, num);
    expect_len = MBExpectLenReadDecreteInputs(num);
    adu_len    = MBSerialMaster_SendAndWaitResponse(port, slave_addr, adu, expect_len, pdu, pdu_len);

    if( adu_len < 0)
        return adu_len;

    pdu = adu + 1;  
    ret = MBGetResponseReadDecreteInputs(pdu, &ret_bytes, value, exception_code);
    if (ret < 0)
        return ret;

    if (ret_bytes != (num + 7)/8)
        return MB_ERROR_SLAVE_RESPONSE_VALUE;

	return MB_ERROR_FREE;
}
#endif

#if MBF_READ_COILS_EN                        != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    send Read Coils request and get response(0x01)
  @param    port              which port to use
  @param    slave_addr        slave device address
  @param    coil_addr         coil address 
  @param    num               number of coil, between 1 ~ 2000
  @param    value             coils status slave returned
  @param    exception_code    exception code for exception response
  @return   MB_ERROR_FREE for success, MB_ERROR_SLAVE_EXCEPTION_RESPONSE for exception response, on error return error code
 */
/*---------------------------------------------------------------------------*/
INT32S MBSerialMasterReadCoils(INT32U port, INT8U slave_addr, INT16U coil_addr, INT16U num, INT8U *value, INT8U *exception_code)
{
    INT8U  buf[(1 + 1 + 1 + ((MAX_COILS_NUM + 7) / 8)) * 2 + 2 + 3]; // ASCII模式：从机地址 + 功能码 + 字节数 + 线圈状态  + LRC + 起始符':' + 结束符'0x0d''0x0a'
    INT32S pdu_len, adu_len, expect_len, ret;
    INT8U  ret_bytes;
    INT8U  *adu, *pdu;

	if ((port > MAX_MB_MASTER_PORT_NUM) || (num > MAX_COILS_NUM) || (value == (INT8U *)0) || (exception_code == (INT8U *)0))
        return (MB_ERROR_FUNC_PARAMETER);

    pdu = MBSerialMaster_GetTxPduBuf(port, buf);
    adu = MBSerialMaster_GetRxAduBuf(port, buf);

    pdu_len    = MBReadCoils(pdu, coil_addr, num); // make PDU
    expect_len = MBExpectLenReadCoils(num);
    adu_len    = MBSerialMaster_SendAndWaitResponse(port, slave_addr, adu, expect_len, pdu, pdu_len);

    if(adu_len < 0)
        return adu_len;

    pdu = adu + 1;  
    ret = MBGetResponseReadCoils(pdu, &ret_bytes, value, exception_code);
    if (ret < 0)
        return ret;

    if (ret_bytes != (num + 7)/8)
        return MB_ERROR_SLAVE_RESPONSE_VALUE;

	return MB_ERROR_FREE;
}
#endif

#if MBF_FORCE_SINGLE_COIL_EN                 != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    send Force Single Coil request and get response(0x05)
  @param    port              which port to use
  @param    slave_addr        slave device address
  @param    coil_addr         start coil number
  @param    onoff             0xFF00 for on,0x0000 for off.
  @param    exception_code    exception code for exception response
  @return   MB_ERROR_FREE for success, MB_ERROR_SLAVE_EXCEPTION_RESPONSE for exception response, on error return error code
 */
/*---------------------------------------------------------------------------*/
INT32S MBSerialMasterForceSingleCoil(INT32U port, INT8U slave_addr, INT16U coil_addr, INT16U onoff, INT8U *exception_code)
{
    INT8U  buf[(1 + 1 + 2 + 2) * 2 + 2 + 3]; // ASCII模式：从机地址 + 功能码 + 线圈地址 + 线圈状态  + LRC + 起始符':' + 结束符'0x0d''0x0a'
    INT32S pdu_len, adu_len, expect_len, ret;
    INT16U ret_addr, ret_value;
    INT8U  *adu, *pdu;

	if ((port > MAX_MB_MASTER_PORT_NUM) || (exception_code == (INT8U *)0))
        return (MB_ERROR_FUNC_PARAMETER);

    pdu = MBSerialMaster_GetTxPduBuf(port, buf);
    adu = MBSerialMaster_GetRxAduBuf(port, buf);

    pdu_len    = MBForceSingleCoil(pdu, coil_addr, onoff);    // make PDU
    expect_len = MBExpectLenForceSingleCoil();
    adu_len    = MBSerialMaster_SendAndWaitResponse(port, slave_addr, adu, expect_len, pdu, pdu_len);

    if( adu_len < 0)
        return adu_len;

    pdu = adu + 1;  
    ret = MBGetResponseForceSingleCoil( pdu, &ret_addr, &ret_value, exception_code);
    if ( ret < 0)
        return ret;

    if ((ret_addr != coil_addr) || ( ret_value != onoff))
        return MB_ERROR_SLAVE_RESPONSE_VALUE;

    return MB_ERROR_FREE;
}
#endif

#if MBF_FORCE_MULTIPLE_COILS_EN              != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    send Force Multiple Coils request and get response(0x0F)
  @param    port              which port to use
  @param    slave_addr        slave device address
  @param    coil_addr         starting coil number
  @param    num               number of coils, between 1 ~ 2000
  @param    value             value to write
  @param    exception_code    exception code for exception response
  @return   MB_ERROR_FREE for success, MB_ERROR_SLAVE_EXCEPTION_RESPONSE for exception response, on error return error code
 */
/*---------------------------------------------------------------------------*/
INT32S MBSerialMasterForceMultipleCoils(INT32S port, INT8U slave_addr, INT16U coil_addr, INT16U num, INT8U *value, INT8U *exception_code)
{
    INT8U  buf[(1 + 1 + 2 + 2 + 1 + ((MAX_COILS_NUM + 7) / 8)) * 2 + 2 + 3]; // ASCII模式：从机地址 + 功能码 + 线圈地址 + 输出数量 + 字节数 + 输出值 + LRC + 起始符':' + 结束符'0x0d''0x0a'
    INT32S pdu_len, adu_len, expect_len, ret;
    INT8U  byte;
    INT16U ret_addr, ret_num;
    INT8U  *adu, *pdu;

	if ((port > MAX_MB_MASTER_PORT_NUM) || (num > MAX_COILS_NUM) || (value == (INT8U *)0) || (exception_code == (INT8U *)0))
        return (MB_ERROR_FUNC_PARAMETER);

    pdu = MBSerialMaster_GetTxPduBuf(port, buf);
    adu = MBSerialMaster_GetRxAduBuf(port, buf);

    byte = (INT8U)(num + 7) / 8;

    pdu_len    = MBForceMultipleCoils(pdu, coil_addr, num, byte, value); // make PDU
    expect_len = MBExpectLenForceMultipleCoils();
    adu_len    = MBSerialMaster_SendAndWaitResponse(port, slave_addr, adu, expect_len, pdu, pdu_len);

    if (adu_len < 0)
        return adu_len;

    pdu= adu + 1;  
    ret= MBGetResponseForceMultipleCoils(pdu, &ret_addr, &ret_num, exception_code);
    if (ret < 0)
        return ret;

    if ((ret_addr != coil_addr) || (ret_num != num))
        return MB_ERROR_SLAVE_RESPONSE_VALUE;

    return MB_ERROR_FREE;
}
#endif

#if MBF_READ_INPUT_REGISTERS_EN              != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    send Read Input Registers request and get response(0x04)
  @param    port              which port to use
  @param    slave_addr        slave device address
  @param    reg_addr          input register address
  @param    num               number of registers, between 1 ~ 125
  @param    value             register value slave returned 
  @param    exception_code    exception code for exception response
  @return   MB_ERROR_FREE for success, MB_ERROR_SLAVE_EXCEPTION_RESPONSE for exception response, on error return error code
 */
/*---------------------------------------------------------------------------*/
INT32S MBSerialMasterReadInputRegisters(INT32U port, INT8U slave_addr, INT16U reg_addr, INT16U num, INT16U *value, INT8U *exception_code)
{
    INT8U  buf[(MAX_INPUT_REGISTERS_NUM * 2 + 1) * 2 + 6 + 3]; // ASCII模式：寄存器值 + 字节数 + 从机地址 + 功能码 + LRC + 起始符':' + 结束符'0x0d''0x0a'
    INT32S pdu_len, adu_len, expect_len, ret;
    INT8U  ret_byte;
    INT8U  *adu, *pdu;

	if ((port > MAX_MB_MASTER_PORT_NUM) || (num > MAX_INPUT_REGISTERS_NUM) || (value == (INT16U *)0) || (exception_code == (INT8U *)0))
		return MB_ERROR_FUNC_PARAMETER;

    pdu = MBSerialMaster_GetTxPduBuf(port, buf);
    adu = MBSerialMaster_GetTxPduBuf(port, buf);
    
    pdu_len    = MBReadInputRegisters(pdu, reg_addr, num); // make PDU
    expect_len = MBExpectLenReadInputRegisters(num);
    adu_len    = MBSerialMaster_SendAndWaitResponse(port, slave_addr, adu, expect_len, pdu, pdu_len);

    if( adu_len < 0)
        return adu_len;

    pdu= adu + 1;  
    ret= MBGetResponseReadInputRegisters(pdu, &ret_byte, value, exception_code);
    if( ret < 0)
        return ret;

	if (ret_byte != (num * 2))
		return MB_ERROR_SLAVE_RESPONSE_VALUE;

	return MB_ERROR_FREE;
}
#endif

#if MBF_READ_HOLDING_REGISTERS_EN            != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    send Read Holding Registers request and get response(0x03)
  @param    port              which port to use
  @param    slave_addr        slave device address
  @param    reg_addr          holding register address
  @param    num               number of registers, between 1 ~ 125
  @param    value             register value slave returned 
  @param    exception_code    exception code for exception response
  @return   MB_ERROR_FREE for success, MB_ERROR_SLAVE_EXCEPTION_RESPONSE for exception response, on error return error code
 */
/*---------------------------------------------------------------------------*/
INT32S MBSerialMasterReadHoldingRegisters(INT32U port, INT8U slave_addr, INT16U reg_addr, INT16U num, INT16U *value, INT8U *exception_code)
{
    INT8U  buf[(MAX_HOLDING_REGISTERS_NUM * 2 + 1) * 2 + 6 + 3]; // ASCII模式：寄存器值 + 字节数 + 从机地址 + 功能码 + LRC + 起始符':' + 结束符'0x0d''0x0a'
    INT32S pdu_len, adu_len, expect_len, ret;
    INT8U  ret_byte;
    INT8U  *adu, *pdu;

	if ((port > MAX_MB_MASTER_PORT_NUM) || (num > MAX_HOLDING_REGISTERS_NUM) || (value == (INT16U *)0) || (exception_code == (INT8U *)0))
		return MB_ERROR_FUNC_PARAMETER;

    pdu = MBSerialMaster_GetTxPduBuf(port, buf);
    adu = MBSerialMaster_GetRxAduBuf(port, buf);
    
    pdu_len    = MBReadHoldingRegisters(pdu, reg_addr, num); //make PDU
    expect_len = MBExpectLenReadHoldingRegisters(num);
    adu_len    = MBSerialMaster_SendAndWaitResponse(port, slave_addr, adu, expect_len, pdu, pdu_len);

    if (adu_len < 0)
        return adu_len;

    pdu = adu + 1;  
    ret = MBGetResponseReadHoldingRegisters(pdu, &ret_byte, value, exception_code);
    if(ret < 0)
        return ret;

    if (ret_byte != (num * 2))
		return MB_ERROR_SLAVE_RESPONSE_VALUE;

	return MB_ERROR_FREE;
}
#endif

#if MBF_PRESET_SINGLE_REGISTER_EN             != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    send Preset Single Register request and get response(0x06)
  @param    port              which port to use
  @param    slave_addr        slave device address
  @param    reg_addr          register address
  @param    value             value write to slave for success, exception code for exception response。
  @param    exception_code    exception code for exception response
  @return   MB_ERROR_FREE for success, MB_ERROR_SLAVE_EXCEPTION_RESPONSE for exception response, on error return error code
  */
/*---------------------------------------------------------------------------*/
INT32S MBSerialMasterPresetSingleRegister(INT32U port, INT8U slave_addr, INT16U reg_addr, INT16U *value, INT8U *exception_code)
{
    INT8U  buf[(1 + 1 + 2 + 2) * 2 + 2 + 3]; // ASCII模式：从机地址 + 功能码 + 寄存器地址 + 寄存器值 + LRC + 起始符':' + 结束符'0x0d''0x0a'
    INT32S pdu_len, adu_len, expect_len, ret;
    INT16U ret_addr, ret_value;
    INT8U  *adu, *pdu;

	if ((port > MAX_MB_MASTER_PORT_NUM) || (value == (INT16U *)0) || (exception_code == (INT8U *)0))
		return MB_ERROR_FUNC_PARAMETER;

    pdu = MBSerialMaster_GetTxPduBuf(port, buf);
    adu = MBSerialMaster_GetRxAduBuf(port, buf);

    pdu_len    = MBPresetSingleRegister(pdu, reg_addr, *value); // make PDU
    expect_len = MBExpectLenPresetSingleRegister();
    adu_len    = MBSerialMaster_SendAndWaitResponse(port, slave_addr, adu, expect_len, pdu, pdu_len);

    if( adu_len < 0)
        return adu_len;

    pdu = adu + 1;  
    ret = MBGetResponsePresetSingleRegister(pdu, &ret_addr, &ret_value, exception_code);
    if (ret < 0)
		return ret;

    if ((ret_addr != reg_addr) || (ret_value != (*value)))
        return MB_ERROR_SLAVE_RESPONSE_VALUE;

    return MB_ERROR_FREE;
}
#endif

#if MBF_PRESET_MULTIPLE_REGISTERS_EN          != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    send Preset Multiple Registers request and get response(0x10)
  @param    port              which port to use
  @param    slave_addr        slave device address
  @param    reg_addr          register address
  @param    num               number of registers, between 1 ~ 120
  @param    value             register value write to slave 
  @param    exception_code    exception code for exception response
  @return   MB_ERROR_FREE for success, MB_ERROR_SLAVE_EXCEPTION_RESPONSE for exception response, on error return error code
 */
/*---------------------------------------------------------------------------*/
INT32S MBSerialMasterPresetMultipleRegisters(INT32U port, INT8U slave_addr, INT16U reg_addr, INT16U num, INT16U *value, INT8U *exception_code)
{
    INT8U  buf[(1 + 1 + 2 + 2 + 1 + (MAX_HOLDING_REGISTERS_NUM * 2)) * 2 + 2 + 3]; // ASCII模式：从机地址 + 功能码 + 起始地址 + 寄存器数量 + 字节数 + 寄存器值 + LRC + 起始符':' + 结束符'0x0d''0x0a'
    INT32S pdu_len, adu_len, expect_len, ret;
	INT8U  byte;
    INT16U ret_addr, ret_value;
    INT8U  *adu, *pdu;

	if ((port > MAX_MB_MASTER_PORT_NUM) || (num > MAX_HOLDING_REGISTERS_NUM) || (value == (INT16U *)0) || (exception_code == (INT8U *)0))
		return MB_ERROR_FUNC_PARAMETER;

    pdu = MBSerialMaster_GetTxPduBuf(port, buf);
    adu = MBSerialMaster_GetTxPduBuf(port, buf);

	byte = num * 2;

    pdu_len    = MBPresetMultipleRegisters(pdu, reg_addr, num, byte, value); // make PDU
    expect_len = MBExpectLenPresetMultipleRegisters();
    adu_len    = MBSerialMaster_SendAndWaitResponse(port, slave_addr, adu, expect_len, pdu, pdu_len);

    if( adu_len < 0)
        return adu_len;

    pdu = adu + 1;  
    ret = MBGetResponsePresetMultipleRegisters(pdu, &ret_addr, &ret_value, exception_code);
    if (ret < 0)
		return ret;

    if ((ret_addr != reg_addr) || (ret_value != num))
        return MB_ERROR_SLAVE_RESPONSE_VALUE;

    return MB_ERROR_FREE;
}
#endif

#if MBF_MASK_WRITE_REGISTER_EN               != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    send Mask Write Register request and get response(0x16)
  @param    port              which port to use
  @param    slave_addr        slave device address
  @param    reg_addr          register address
  @param    andmask           and mask
  @param    ormask            or mask
  @param    exception_code    exception code for exception response
  @return   MB_ERROR_FREE for success, MB_ERROR_SLAVE_EXCEPTION_RESPONSE for exception response, on error return error code
 */
/*---------------------------------------------------------------------------*/
INT32S MBSerialMasterMaskWriteRegister(INT32U port, INT8U slave_addr, INT16U reg_addr, INT16U andmask, INT16U ormask, INT8U *exception_code)
{
    INT8U  buf[(1 + 1 + 2 + 2 + 2) * 2 + 2 + 3]; // ASCII模式：从机地址 + 功能码 + 寄存器地址 + And_Mask  + Or_Mask  + LRC + 起始符':' + 结束符'0x0d''0x0a'
    INT32S pdu_len, adu_len, expect_len, ret;
    INT16U ret_reg_addr, ret_and_mask, ret_or_mask;
    INT8U  *adu, *pdu;

	if ((port > MAX_MB_MASTER_PORT_NUM) || (exception_code == (INT8U *)0))
		return MB_ERROR_FUNC_PARAMETER;

    pdu = MBSerialMaster_GetTxPduBuf(port, buf);
    adu = MBSerialMaster_GetRxAduBuf(port, buf);
    
    pdu_len    = MBMaskWriteRegister(pdu, reg_addr, andmask, ormask); // make PDU
    expect_len = MBExpectLenMaskWriteRegister();
    adu_len    = MBSerialMaster_SendAndWaitResponse(port, slave_addr, adu, expect_len, pdu, pdu_len);

    if(adu_len < 0)
        return adu_len;

    pdu = adu + 1;  
    ret = MBGetResponseMaskWriteRegister(pdu, &ret_reg_addr, &ret_and_mask, &ret_or_mask, exception_code);

    if (ret < 0)
        return ret;
    
	if ((ret_reg_addr != reg_addr) || (ret_and_mask != andmask) || ( ret_or_mask != ormask))
        return MB_ERROR_SLAVE_RESPONSE_VALUE;

    return MB_ERROR_FREE;
}
#endif

#if MBF_READ_WRITE_MULTIPLE_REGISTERS_EN     != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    send Read Write Multiple Registers request and get response(0x17)
  @param    port              which port to use
  @param    slave_addr        slave device address
  @param    reg_addr_rd       starting register number to read
  @param    num_rd            number of registers ro read, between 1 ~ 120
  @param    value_rd          registers value slave returned
  @param    reg_addr_wr       starting register number to write
  @param    num_wr            number of registers ro write, between 1 ~ 120
  @param    value_wr          value to write
  @param    exception_code    exception code for exception response
  @return   MB_ERROR_FREE for success, MB_ERROR_SLAVE_EXCEPTION_RESPONSE for exception response, on error return error code。
 */
/*---------------------------------------------------------------------------*/
INT32S MBSerialMasterReadWriteMultipleRegisters(INT32U port, INT8U slave_addr, INT16U reg_addr_rd, INT16U num_rd, INT16U *value_rd, INT16U reg_addr_wr, INT16U num_wr, INT16U *value_wr, INT8U *exception_code)
{
    INT8U  buf[(1 + 1 + 2 + 2 + 2 + 2 + 1 + (MAX_HOLDING_REGISTERS_NUM * 2) + (MAX_HOLDING_REGISTERS_NUM * 2)) * 2 + 2 + 3]; // ASCII模式：从机地址 + 功能码 + 读起始地址 + 读数量 + 写起始地址 + 写数量 + 写字节数 + 写寄存器值 + 读寄存器值 + LRC + 起始符':' + 结束符'0x0d''0x0a'
    INT32S pdu_len, adu_len, expect_len, ret;
	INT8U  byte_wr;
    INT8U  ret_size;
    INT8U  *adu, *pdu;

	if ((port > MAX_MB_MASTER_PORT_NUM) || (num_rd > MAX_HOLDING_REGISTERS_NUM) || (num_wr > MAX_HOLDING_REGISTERS_NUM) || (value_rd == (INT16U *)0) || (value_wr == (INT16U *)0) || (exception_code == (INT8U *)0))
		return MB_ERROR_FUNC_PARAMETER;

    pdu = MBSerialMaster_GetTxPduBuf(port, buf);
    adu = MBSerialMaster_GetTxPduBuf(port, buf);

	byte_wr = num_wr * 2;
    
    pdu_len    = MBReadWriteMultipleRegisters(pdu, reg_addr_rd, num_rd, reg_addr_wr, num_wr, byte_wr, value_wr); // make PDU
    expect_len = MBExpectLenReadWriteMultipleRegisters(num_rd);
	adu_len    = MBSerialMaster_SendAndWaitResponse(port, slave_addr, adu, expect_len, pdu, pdu_len);

    if(adu_len < 0)
        return adu_len;

    pdu = adu + 1;  
    ret = MBGetResponseReadWriteMultipleRegisters(pdu, &ret_size, value_rd, exception_code);

    if( ret < 0)
        return ret;

    if(ret_size != (num_rd * 2))
        return MB_ERROR_SLAVE_RESPONSE_VALUE;

    return MB_ERROR_FREE;
}
#endif

#if MBF_READ_FIFO_QUEUE_EN                   != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    send Read FIFO Queue request and get response(0x18)
  @param    port        which port to use
  @param    address        slave device address
  @param    FIFOAddr    FIFO address
  @param    FIFOCount    FIFO value buffer size(<=31)
  @param    FIFOValue    values of FIFO register
  @return    MB_ERROR_FREE for success, on error return error code
 */
/*---------------------------------------------------------------------------*/
int    MBMasterReadFIFOQueue(int port, INT8U address, INT16U FIFOAddr, INT16U *FIFOCount, INT16U *FIFOValue)
{
    INT8U buf[MB_ASCII_ADU_MAX_LENGTH];
    int pdu_len, adu_len, expect_len, ret;
    INT8U *adu, *pdu;

    pdu = MBMasterGetTxTempBuf(port, buf);
    adu = MBMasterGetRxTempBuf(port, buf);
    /// make PDU
    pdu_len= MBReadFIFOQueue( pdu, FIFOAddr);

    adu_len= MBSerialMaster_SendAndWaitResponse( port, adu, expect_len, pdu, pdu_len, address);

    if( adu_len < 0)
        return adu_len;

    pdu= adu + 1;  //pdu_len = MBGetPDU( pdu, adu, adu_len);
    ret= MBGetResponseReadFIFOQueue( pdu, FIFOCount, FIFOValue);

    if( ret < 0)
        return ret;

    return MB_ERROR_FREE;
}
#endif

#if MBF_READ_EXCEPTION_STATUS_EN             != 0
/* Modbus master function over serial only */
/*---------------------------------------------------------------------------*/
/**
  @brief    send Read Exception Status request and get response(0x07)
  @param    port        which port to use
  @param    address        slave device address
  @param    status        eight exception status in one byte
  @return    MB_ERROR_FREE for success, on error return error code
 */
/*---------------------------------------------------------------------------*/
int    MBMasterReadExceptionStatus(int port, INT8U address, INT8U *status)
{
    INT8U buf[MB_ASCII_ADU_MAX_LENGTH];
    int pdu_len, adu_len, expect_len, ret;
    INT8U *adu, *pdu;

    pdu = MBMasterGetTxTempBuf(port, buf);
    adu = MBMasterGetRxTempBuf(port, buf);
    /// make PDU
    pdu_len= MBReadExceptionStatus( pdu);

    adu_len= MBSerialMaster_SendAndWaitResponse( port, adu, expect_len, pdu, pdu_len, address);

    if( adu_len < 0)
        return adu_len;

    pdu= adu + 1;  //pdu_len = MBGetPDU( pdu, adu, adu_len);
    ret= MBGetResponseReadExceptionStatus( pdu, status);

    if( ret < 0)
        return ret;

    return MB_ERROR_FREE;
}
#endif

#if MBF_DIAGNOSTIC_EN                        != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    send Diagnostic request and get response(0x08)
  @param    port        which port to use
  @param    address        slave device address
  @param    subfunc        subfunction code
  @param    data        data to be sent to slave device
  @return    MB_ERROR_FREE for success, on error return error code
 */
/*---------------------------------------------------------------------------*/
int    MBMasterDiagnostic(int port, INT8U address, INT16U subfunc, INT16U data)
{
    INT8U buf[MB_ASCII_ADU_MAX_LENGTH];
    int pdu_len, adu_len, expect_len, ret;
    INT16U ret_subfunc, ret_data;
    INT8U *adu, *pdu;

    pdu = MBMasterGetTxTempBuf(port, buf);
    adu = MBMasterGetRxTempBuf(port, buf);
    /// make PDU
    pdu_len= MBDiagnostic( pdu, subfunc, data);

    adu_len= MBSerialMaster_SendAndWaitResponse( port, adu, expect_len, pdu, pdu_len, address);

    if( adu_len < 0)
        return adu_len;

    pdu= adu + 1;  //pdu_len = MBGetPDU( pdu, adu, adu_len);
    ret= MBGetResponseDiagnostic( pdu, &ret_subfunc, &ret_data);

    if( ret < 0)
        return ret;
    if( ( ret_subfunc != subfunc) || ( ret_data != data))
        return MB_ERROR_PROTOCOL;

    return MB_ERROR_FREE;
}
#endif

#if MBF_GET_COMM_EVENT_COUNTER_EN            != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    send Get Comm Event Counter request and get response(0x0B)
  @param    port        which port to use
  @param    address        slave device address
  @param    status        status of Comm Conuter
  @param    eventcount    event counter
  @return    MB_ERROR_FREE for success, on error return error code
 */
/*---------------------------------------------------------------------------*/
int    MBMasterGetCommEventCounter(int port, INT8U address, INT16U *status, INT16U *eventcount)
{
    INT8U buf[MB_ASCII_ADU_MAX_LENGTH];
    int pdu_len, adu_len, expect_len, ret;
    INT8U *adu, *pdu;

    pdu = MBMasterGetTxTempBuf(port, buf);
    adu = MBMasterGetRxTempBuf(port, buf);
    /// make PDU
    pdu_len= MBGetCommEventCounter( pdu);

    adu_len= MBSerialMaster_SendAndWaitResponse( port, adu, expect_len, pdu, pdu_len, address);

    if( adu_len < 0)
        return adu_len;

    pdu= adu + 1;  //pdu_len = MBGetPDU( pdu, adu, adu_len);
    ret= MBGetResponseGetCommEventCounter( pdu,  status,  eventcount);

    if( ret < 0)
        return ret;

    return MB_ERROR_FREE;
}
#endif

#if MBF_GET_COMM_EVENT_LOG_EN                != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    send Get Comm Event Counter request and get response(0x0C)
  @param    port        which port to use
  @param    address        slave device address
  @param    status        status of Comm Conuter
  @param    eventcount    event counter
  @param    messagecount    counter for processed message
  @param    events        new events
  @return    MB_ERROR_FREE for success, on error return error code
 */
/*---------------------------------------------------------------------------*/
int    MBMasterGetCommEventLog(int port, INT8U address, INT16U *status, INT16U *eventcount, INT16U *messagecount, INT8U *events)
{
    INT8U buf[MB_ASCII_ADU_MAX_LENGTH];
    int pdu_len, adu_len, expect_len, ret;
    INT8U *adu, *pdu;

    pdu = MBMasterGetTxTempBuf(port, buf);
    adu = MBMasterGetRxTempBuf(port, buf);
    /// make PDU
    pdu_len= MBGetCommEventLog( pdu);

    adu_len= MBSerialMaster_SendAndWaitResponse( port, adu, expect_len, pdu, pdu_len, address);

    if( adu_len < 0)
        return adu_len;

    pdu= adu + 1;  //pdu_len = MBGetPDU( pdu, adu, adu_len);
    ret= MBGetResponseGetCommEventLog( pdu, status, eventcount, messagecount, events);

    if( ret < 0)
        return ret;

    return MB_ERROR_FREE;
}
#endif

#if MBF_REPORT_SLAVE_ID_EN                   != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    send Report Slave ID request and get response(0x11)
  @param    port        which port to use
  @param    address        slave device address
  @param    slave_id    buffer to store slave id
  @param    status        status of the device
  @return    MB_ERROR_FREE for success, on error return error code
 */
/*---------------------------------------------------------------------------*/
int    MBMasterReportSlaveID(int port, INT8U address, INT8U *slave_id, INT8U *status)
{
    INT8U buf[MB_ASCII_ADU_MAX_LENGTH];
    int pdu_len, adu_len, expect_len, ret;
    INT8U *adu, *pdu;

    pdu = MBMasterGetTxTempBuf(port, buf);
    adu = MBMasterGetRxTempBuf(port, buf);
    /// make PDU
    pdu_len= MBReportSlaveID( pdu);

    adu_len= MBSerialMaster_SendAndWaitResponse( port, adu, expect_len, pdu, pdu_len, address);

    if( adu_len < 0)
        return adu_len;

    pdu= adu + 1;  //pdu_len = MBGetPDU( pdu, adu, adu_len);
    ret= MBGetResponseReportSlaveID( pdu, slave_id, status);

    if( ret < 0)
        return ret;

    return MB_ERROR_FREE;
}
#endif








