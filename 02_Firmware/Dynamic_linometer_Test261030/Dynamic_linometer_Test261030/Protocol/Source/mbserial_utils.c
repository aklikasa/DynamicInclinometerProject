/*---------------------------------------------------------------------------*/
/**
  @file     modbus_utils.c
  @brief    Example modbus utilities define file

  This file contains much modbus utility functions.
  It helps to merge modbus function code and data to a PDU and split PDU
  to modbus function code and data.
  We split one request and response into four functions, for example if modbus
  master sends Read Coils request to slave and gets slave's response, we might
  have to use these four functions.

  Modbus Master                               Modbus Slave
  1. MBReadCoils()               ---->        2. MBGetReadCoils()
  4. MBGetResponseReadCoils()    <----        3. MBResponseReadCoils

  History:
  Date        Author            Comment
  08-01-2005  AceLan Kao.       Create it.
  14-06-2017  zqh               整理源代码并添加C51相关适应代码

  @author AceLan Kao.(acelan_kao@moxa.com.tw)
 */
/*---------------------------------------------------------------------------*/
#include "string.h"
#include "mbserial_defs.h"
#include "mbserial_utils.h"
#include "crc16_lrc.h"

#if 0
static const unsigned char C51_CODE CRCHi[] = {
0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81,
0x40, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0,
0x80, 0x41, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x00, 0xC1, 0x81, 0x40, 0x01,
0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x01, 0xC0, 0x80, 0x41,
0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x00, 0xC1, 0x81,
0x40, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x01, 0xC0,
0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x01,
0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40,
0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81,
0x40, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0,
0x80, 0x41, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x00, 0xC1, 0x81, 0x40, 0x01,
0xC0, 0x80, 0x41, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41,
0x00, 0xC1, 0x81, 0x40, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81,
0x40, 0x01, 0xC0, 0x80, 0x41, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0,
0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x01,
0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41,
0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81,
0x40
};

static const unsigned char C51_CODE CRCLo[] = {
0x00, 0xC0, 0xC1, 0x01, 0xC3, 0x03, 0x02, 0xC2, 0xC6, 0x06, 0x07, 0xC7, 0x05, 0xC5, 0xC4,
0x04, 0xCC, 0x0C, 0x0D, 0xCD, 0x0F, 0xCF, 0xCE, 0x0E, 0x0A, 0xCA, 0xCB, 0x0B, 0xC9, 0x09,
0x08, 0xC8, 0xD8, 0x18, 0x19, 0xD9, 0x1B, 0xDB, 0xDA, 0x1A, 0x1E, 0xDE, 0xDF, 0x1F, 0xDD,
0x1D, 0x1C, 0xDC, 0x14, 0xD4, 0xD5, 0x15, 0xD7, 0x17, 0x16, 0xD6, 0xD2, 0x12, 0x13, 0xD3,
0x11, 0xD1, 0xD0, 0x10, 0xF0, 0x30, 0x31, 0xF1, 0x33, 0xF3, 0xF2, 0x32, 0x36, 0xF6, 0xF7,
0x37, 0xF5, 0x35, 0x34, 0xF4, 0x3C, 0xFC, 0xFD, 0x3D, 0xFF, 0x3F, 0x3E, 0xFE, 0xFA, 0x3A,
0x3B, 0xFB, 0x39, 0xF9, 0xF8, 0x38, 0x28, 0xE8, 0xE9, 0x29, 0xEB, 0x2B, 0x2A, 0xEA, 0xEE,
0x2E, 0x2F, 0xEF, 0x2D, 0xED, 0xEC, 0x2C, 0xE4, 0x24, 0x25, 0xE5, 0x27, 0xE7, 0xE6, 0x26,
0x22, 0xE2, 0xE3, 0x23, 0xE1, 0x21, 0x20, 0xE0, 0xA0, 0x60, 0x61, 0xA1, 0x63, 0xA3, 0xA2,
0x62, 0x66, 0xA6, 0xA7, 0x67, 0xA5, 0x65, 0x64, 0xA4, 0x6C, 0xAC, 0xAD, 0x6D, 0xAF, 0x6F,
0x6E, 0xAE, 0xAA, 0x6A, 0x6B, 0xAB, 0x69, 0xA9, 0xA8, 0x68, 0x78, 0xB8, 0xB9, 0x79, 0xBB,
0x7B, 0x7A, 0xBA, 0xBE, 0x7E, 0x7F, 0xBF, 0x7D, 0xBD, 0xBC, 0x7C, 0xB4, 0x74, 0x75, 0xB5,
0x77, 0xB7, 0xB6, 0x76, 0x72, 0xB2, 0xB3, 0x73, 0xB1, 0x71, 0x70, 0xB0, 0x50, 0x90, 0x91,
0x51, 0x93, 0x53, 0x52, 0x92, 0x96, 0x56, 0x57, 0x97, 0x55, 0x95, 0x94, 0x54, 0x9C, 0x5C,
0x5D, 0x9D, 0x5F, 0x9F, 0x9E, 0x5E, 0x5A, 0x9A, 0x9B, 0x5B, 0x99, 0x59, 0x58, 0x98, 0x88,
0x48, 0x49, 0x89, 0x4B, 0x8B, 0x8A, 0x4A, 0x4E, 0x8E, 0x8F, 0x4F, 0x8D, 0x4D, 0x4C, 0x8C,
0x44, 0x84, 0x85, 0x45, 0x87, 0x47, 0x46, 0x86, 0x82, 0x42, 0x43, 0x83, 0x41, 0x81, 0x80,
0x40
};

/*---------------------------------------------------------------------------*/
/**
  @brief    calculate the CRC16 value of the input data
  @param    buf        input data
  @param    len        length of the input data
  @return   CRC16 value of the input data
 */
/*---------------------------------------------------------------------------*/
INT16U CRC16(const INT8U *buf, INT32S len) C51_REENTRANT
{
    INT8U  hi = 0xFF;
    INT8U  lo = 0xFF;
    INT16U index;

    while (len-- ) {
        index = lo ^ (INT8U)*buf++;
        lo    = hi ^ CRCHi[index];
        hi    = CRCLo[index];
    }

    index  = lo << 8;
    index |= hi;

    return(index);
}

/*---------------------------------------------------------------------------*/
/**
  @brief    calculate the LRC value of the input data
  @param    buf    input data
  @param    len    length of the input data
  @return   LRC value of the input data
 */
/*---------------------------------------------------------------------------*/
INT8U LRC(const INT8U *buf, INT32S len) C51_REENTRANT
{
    INT8U lrc = 0;

    while (len-- )
        lrc += *buf++;
	lrc = (INT8U)(-((char)lrc));

    return lrc;
}
#endif

/*---------------------------------------------------------------------------*/
/**
  @brief    parse ASCII mode data to binary data
  @param    buf    output buffer
  @param    dat    input ASCII data
  @param    len    length of the input data
  @return   the length of data after parse. On error return error code

  This function read the PDU part as input, parse it as Modbus ASCII protocol,
  and produce the binary data.
 */
/*---------------------------------------------------------------------------*/
INT32S MBASCIIToData(INT8U *buf, const INT8U *dat, INT32S len) C51_REENTRANT
{
    INT32S i= 0;
    INT8U  ch1, ch2;

    /* to do length error check */
    if (len & 1)
        return (MB_ERROR_PROTOCOL);
    if ((len <= 1) || (len >= MAX_MB_ASCII_FRAME_LENGTH))
        return (MB_ERROR_PROTOCOL);

    for (i = 0; i < len; i += 2)
    {
        ch2 = 0;
        ch1 = *dat++;
        if ( ch1 >= '0' && ch1 <= '9' )
            ch1 -= '0';
        else if ( ch1 >= 'A' && ch1 <= 'F' )
            ch1 = ch1 - 'A' + 10;
        else
            return(MB_ERROR_PROTOCOL);
        ch2 = ch1 << 4;
        ch1 = *dat++;
        if ( ch1 >= '0' && ch1 <= '9' )
            ch1 -= '0';
        else if ( ch1 >= 'A' && ch1 <= 'F' )
            ch1 = ch1 - 'A' + 10;
        else
            return(MB_ERROR_PROTOCOL);
        ch2 |= ch1;
        *buf++ = ch2;
    }

    return(len/2);
}

/*---------------------------------------------------------------------------*/
/**
  @brief    parse binary data to ASCII mode data
  @param    buf    output buffer
  @param    dat    input binary data
  @param    len    length of the input data
  @return   the length of data after parse. On error return error code
 */
/*---------------------------------------------------------------------------*/
INT32S MBDataToASCII(INT8U *buf, const INT8U *dat, INT32S len) C51_REENTRANT
{
    INT32S i = 0, j = 2 * len;

    for (i = len - 1; i >= 0; i--)
    {
        INT8U ch = (dat[i] & 0x0F);
        if (ch <= 9)
            ch += '0';
        else
            ch += ('A' - 10);
        buf[--j] = ch;

        ch = ((dat[i] & 0xF0) >> 4);
        if (ch <= 9)
            ch += '0';
        else
            ch += ('A' - 10);
        buf[--j] = ch;
    }

    return len * 2;
}

/*---------------------------------------------------------------------------*/
/**
  @brief    assemble address, PDU and error checking code to ADU
  @param    buf        output buffer
  @param    protocol    which Modbus protocol to use
  @param    address        address of the destination device
  @param    pdu        PDU part
  @param    len        length of the PDU part
  @param    tid        transaction used for Modbus TCP protocol
  @return    the length of data after assemble. On error return error code
 */
/*---------------------------------------------------------------------------*/
int    MBMakeADU( INT8U *buf, int protocol, INT8U address, const INT8U *pdu, int len, INT16U tid) C51_REENTRANT
{
    INT8U lrc_value;
    INT16U crc;
    int buf_len= 0;

    switch( protocol)
    {
        case MB_SERIAL_MODE_ASCII:
            buf[ 0]= ':';
            buf[ 1]= address;
            bcopy( (const char *)pdu, (char *)(buf + 2), len);
            lrc_value= lrc(&buf[1], len + 1);
            buf[len + 2] = lrc_value;
            buf_len= MBDataToASCII( buf+ 1, buf + 1, len + 2);
            buf_len++;

            buf[ buf_len++]= 0xd;
            buf[ buf_len++]= 0xa;
            break;
        case MB_SERIAL_MODE_RTU:
            buf[ 0]= address;
            buf_len++;

            bcopy( (const char *)pdu, (char *)(buf+ 1), len);
            buf_len+= len;

            crc= crc16( buf, buf_len);
            buf[ buf_len++]= crc >> 8;
            buf[ buf_len++]= crc & 0x00FF;
            break;
        case MB_TCP_PROTOCOL:
            buf[ 0]= tid >> 8;
            buf[ 1]= tid & 0x00FF;

            buf[ 2]= 0;
            buf[ 3]= 0;

            buf[ 4]= (len+1) >> 8;        // length of address + pdu
            buf[ 5]= (len+1) & 0x00FF;    // length of address + pdu

            buf[ 6]= address;

            bcopy( (const char *)pdu, (char *)(buf+ 7), len);
            buf_len= 7+ len;
            break;
        default:
            return MB_ERROR_PROTOCOL;
    }

    return buf_len;
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
INT32S MBGetPDU(INT8U *buf, INT8U *adu, INT32S len) C51_REENTRANT
{
    INT32S minus = 2;

    if (adu[0] == ':')
        minus = 1;
    bcopy((const char *)(adu+1), (char *)buf, len - 1 - minus);

    return len- 1- minus;
}

/*---------------------------------------------------------------------------*/
/**
  @brief    assemble function code and data to ADU
  @param    buf        output buffer
  @param    function    function code of the data
  @param    dat         data
  @param    len        length of the data
  @return    the length of PDU data
 */
/*---------------------------------------------------------------------------*/
int    MBMakePDU( INT8U *buf, INT8U function, INT8U *dat, int len) C51_REENTRANT
{
    int ret_len= 0;

    buf[ 0]= function;
    bcopy( (const char *)dat, (char *)(buf+ 1), len);
    ret_len= len+ 1;

    return ret_len;
}

/*---------------------------------------------------------------------------*/
/**
  @brief    get device address from ADU
  @param    adu    ADU data
  @return   none
 */
/*---------------------------------------------------------------------------*/
INT8U MBGetAddress(const INT8U *adu) C51_REENTRANT
{
    return adu[0];
}

/*---------------------------------------------------------------------------*/
/**
  @brief    get function code from PDU
  @param    pdu        PDU data
  @return    none
 */
/*---------------------------------------------------------------------------*/
INT8U    MBGetFunctionCode( const INT8U *pdu) C51_REENTRANT
{
    return pdu[ 0];
}

// Modbus function
#if MBF_READ_COILS_EN                 != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    make PDU packet of Read Coils function(0x01)
  @param    buf          output buffer
  @param    coil_addr    coil address
  @param    num          number of coils, between 1 ~ 2000
  @return   the length of PDU data
 */
/*---------------------------------------------------------------------------*/
INT32S MBReadCoils(INT8U *buf, INT16U coil_addr, INT16U num) C51_REENTRANT
{
    INT32S len= 0;

    buf[len]= MBF_READ_COILS;
    len++;
    PUTU16(buf + len, coil_addr);        // don't put ++ in the macro
    len += 2;
    PUTU16(buf+ len, num);
    len += 2;

    return len;
}

/*---------------------------------------------------------------------------*/
/**
  @brief   parse PDU packet of Read Coils function(0x01)
  @param   pdu     PDU packet
  @param   addr    coil address
  @param   num     coil number
 */
/*---------------------------------------------------------------------------*/
void MBGetReadCoils(INT8U *pdu, INT16U *addr, INT16U *num) C51_REENTRANT
{
    GETU16(*addr, pdu + 1);
    GETU16(*num, pdu + 3);
}

/*---------------------------------------------------------------------------*/
/**
  @brief    parse response PDU packet of Response Read Coils request(0x01)
  @param    pdu               output buffer
  @param    byte              bytes of coils status
  @param    value             coils status
  @param    exception_code    exception code for exception response
  @return   MB_ERROR_FREE for success, MB_ERROR_SLAVE_EXCEPTION_RESPONSE for exception response, on error return error code
 */
/*---------------------------------------------------------------------------*/
INT32S MBGetResponseReadCoils(INT8U *pdu, INT8U *byte, INT8U *value, INT8U *exception_code) C51_REENTRANT
{
    INT32S i = 0;

	if (pdu[0] == (MBF_READ_COILS | 0x80))          // 异常响应
	{
		*exception_code = pdu[1];                   // 异常码
		return MB_ERROR_SLAVE_EXCEPTION_RESPONSE;
	}
	else if (pdu[0] == MBF_READ_COILS)              // 正常响应
	{
        *byte = pdu[1];
        for(i= 0; i < *byte; i++)
            value[i]= pdu[2 + i];
        return MB_ERROR_FREE;
	}
	else                                           // 错误
	{
		return MB_ERROR_SLAVE_RESPONSE_VALUE; 
	}
}

/*---------------------------------------------------------------------------*/
/**
 @brief     得到读线圈命令期待的返回帧长度
 @param     num  读取数据个数
 @return    期待的RTU返回帧长度
 */
/*---------------------------------------------------------------------------*/
INT32S MBExpectLenReadCoils(INT16U num) C51_REENTRANT
{
    return (5 +  (num + 7) / 8);   // 地址(1) + 功能码(1) + 字节数(1) + 线圈状态((N + 7) / 8) + 校验(2)
}

#endif

#if MBF_READ_DECRETE_INPUTS_EN != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    make PDU packet of Read Decrete Inputs function(0x02)
  @param    buf           output buffer
  @param    input_addr    starting decrete inputs number
  @param    num           number of decrete inputs, between 1 ~ 2000
  @return   the length of PDU data
 */
/*---------------------------------------------------------------------------*/
INT32S MBReadDecreteInputs(INT8U *buf, INT16U input_addr, INT16U num) C51_REENTRANT
{
    INT32S len = 0;

    buf[len] = MBF_READ_DECRETE_INPUTS;
    len++;
    PUTU16(buf + len, input_addr);        // don't put ++ in the macro
    len += 2;
    PUTU16(buf + len, num);
    len += 2;

    return len;
}

/*---------------------------------------------------------------------------*/
/**
  @brief   parse PDU packet of Read Decrete Inputs function(0x02)
  @param   pdu     PDU packet
  @param   addr    decrete inputs address
  @param   num     decrete inputs number
 */
/*---------------------------------------------------------------------------*/
void MBGetReadDecreteInputs(INT8U *pdu, INT16U *addr, INT16U *num) C51_REENTRANT
{
    GETU16(*addr, pdu + 1);
    GETU16(*num, pdu + 3);
}

/*---------------------------------------------------------------------------*/
/**
  @brief    parse response PDU packet of Read Decrete Inputs request(0x02)
  @param    pdu               the request PDU data
  @param    byte              bytes of decrete inputs
  @param    value             decrete input status
  @param    exception_code    exception code for exception response    
  @return   MB_ERROR_FREE for success, MB_ERROR_SLAVE_EXCEPTION_RESPONSE for exception response, on error return error code
 */
/*---------------------------------------------------------------------------*/
INT32S MBGetResponseReadDecreteInputs(INT8U *pdu, INT8U *byte, INT8U *value, INT8U *exception_code) C51_REENTRANT
{
    INT32S i = 0;

    if (pdu[0] == (MBF_READ_DECRETE_INPUTS | 0x80))          // 异常响应
    {
		*exception_code = pdu[1];                            // 异常码
		return MB_ERROR_SLAVE_EXCEPTION_RESPONSE;
	}
	else if (pdu[0] == MBF_READ_DECRETE_INPUTS)              // 正常响应
	{
        *byte = pdu[1];
        for(i= 0; i < *byte; i++)
            value[i]= pdu[2 + i];
        return MB_ERROR_FREE;
	}
	else                                                     // 错误
	{
		return MB_ERROR_SLAVE_RESPONSE_VALUE; 
	}
}

/*---------------------------------------------------------------------------*/
/**
 @brief    得到读离散量输入命令期待的返回帧长度
 @param    num  读取数据个数
 @return   期待的RTU返回帧长度
 */
/*---------------------------------------------------------------------------*/
INT32S MBExpectLenReadDecreteInputs(INT16U num) C51_REENTRANT
{
    return (5 +  (num + 7) / 8);   // 地址(1) + 功能码(1) + 字节数(1) + 输入状态((N + 7) / 8) + 校验(2)
}

#endif    

#if MBF_FORCE_SINGLE_COIL_EN          != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    make PDU packet of Force Single Coil function(0x05)
  @param    buf          output buffer
  @param    coil_addr    coil register number
  @param    onoff        0xFF00 for on,0x0000 for off
  @return   the length of PDU data
 */
/*---------------------------------------------------------------------------*/
INT32S MBForceSingleCoil(INT8U *buf, INT16U coil_addr, INT16U onoff) C51_REENTRANT
{
    INT32S len= 0;

    buf[len]= MBF_FORCE_SINGLE_COIL;
    len++;
    PUTU16(buf + len, coil_addr);        // don't put ++ in the macro
    len += 2;
    PUTU16(buf + len, onoff);
    len += 2;

    return len;
}

/*---------------------------------------------------------------------------*/
/**
  @brief   parse PDU packet of Force Single Coil function(0x05)
  @param   pdu     PDU packet
  @param   addr    coil address
  @param   value   coil value
 */
/*---------------------------------------------------------------------------*/
void MBGetForceSingleCoil(INT8U *pdu, INT16U *addr, INT16U *value) C51_REENTRANT
{
    GETU16(*addr, pdu + 1);
    GETU16(*value, pdu + 3);
}

/*---------------------------------------------------------------------------*/
/**
  @brief    parse response PDU packet of Write Single Coil request(0x05)
  @param    pdu               output buffer
  @param    coil_addr         start number of coil
  @param    value             output value
  @param    exception_code    exception code for exception response
  @return   MB_ERROR_FREE for success, MB_ERROR_SLAVE_EXCEPTION_RESPONSE for exception response, on error return error code
 */
/*---------------------------------------------------------------------------*/
INT32S MBGetResponseForceSingleCoil(INT8U *pdu, INT16U *address, INT16U *value, INT8U *exception_code) C51_REENTRANT
{
    if (pdu[0] == (MBF_FORCE_SINGLE_COIL | 0x80))     // 异常响应
	{
		*exception_code = pdu[1];                     // 异常码
		return MB_ERROR_SLAVE_EXCEPTION_RESPONSE;
	}
	else if (pdu[0] == MBF_FORCE_SINGLE_COIL)         // 正常响应
	{
        GETU16(*address, pdu + 1);
        GETU16(*value, pdu + 3);
        return MB_ERROR_FREE;
	}
	else                                             // 错误
	{
		return MB_ERROR_SLAVE_RESPONSE_VALUE;     
	}
}

/*---------------------------------------------------------------------------*/
/**
  @brief    得到写单个线圈命令期待的返回帧长度
  @return   期待的RTU返回帧长度
 */
/*---------------------------------------------------------------------------*/
INT32S MBExpectLenForceSingleCoil(void) C51_REENTRANT
{
    return 8;     // 地址(1) + 功能码(1) + 输出地址(2) + 输出值(2) + 校验(2)
}
#endif

#if MBF_READ_INPUT_REGISTERS_EN       != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    make PDU packet of Read Input Registers function(0x04)
  @param    buf        output buffer
  @param    reg_addr   input register address
  @param    num        number of input registers, between 1 ~ 125
  @return   the length of PDU data
 */
/*---------------------------------------------------------------------------*/
INT32S MBReadInputRegisters(INT8U *buf, INT16U reg_addr, INT16U num) C51_REENTRANT
{
    INT32S len= 0;

    buf[len]= MBF_READ_INPUT_REGISTERS;
    len++;
    PUTU16(buf + len, reg_addr);        // don't put ++ in the macro
    len+= 2;
    PUTU16(buf + len, num);
    len+= 2;

    return len;
}

/*---------------------------------------------------------------------------*/
/**
  @brief   parse PDU packet of Read Input Register function(0x04)
  @param   pdu     PDU packet
  @param   addr    input register address
  @param   num     input register number
 */
/*---------------------------------------------------------------------------*/
void MBGetReadInputRegisters(INT8U *pdu, INT16U *addr, INT16U *num) C51_REENTRANT
{
    GETU16(*addr, pdu + 1);
    GETU16(*num, pdu + 3);
}

/*---------------------------------------------------------------------------*/
/**
  @brief    parse response PDU packet of Read Input Registers request(0x04)
  @param    pdu               output buffer
  @param    byte              bytes of registers value slave return
  @param    value             registers value 
  @param    exception_code    exception code for exception response
  @return   MB_ERROR_FREE for success, MB_ERROR_SLAVE_EXCEPTION_RESPONSE for exception response, on error return error code
 */
/*---------------------------------------------------------------------------*/
INT32S MBGetResponseReadInputRegisters(INT8U *pdu, INT8U *size, INT16U *value, INT8U *exception_code) C51_REENTRANT
{
    INT32S i= 0;

	if (pdu[0] == (MBF_READ_INPUT_REGISTERS | 0x80)) // 异常响应
	{
        *exception_code = pdu[1];                    // 异常码
		return MB_ERROR_SLAVE_EXCEPTION_RESPONSE;
	}
	else if (pdu[0] == MBF_READ_INPUT_REGISTERS)     // 正常响应
	{
        *size = pdu[1];
        for(i = 0; i < *size/2; i++)
            GETU16(value[i], pdu + 2 + i*2);
		return MB_ERROR_FREE;
	}
	else
	{
	    return MB_ERROR_SLAVE_RESPONSE_VALUE;         // 错误
	}    
}

/*---------------------------------------------------------------------------*/
/**
 @brief    得到读输入寄存器命令期待的返回帧长度
 @param    num    读取寄存器个数
 @return   期待的RTU返回帧长度
 */
/*---------------------------------------------------------------------------*/
INT32S MBExpectLenReadInputRegisters(INT16U num) C51_REENTRANT
{
    return (5 + num * 2);   // 地址(1) + 功能码(1) + 字节数(1) + 数据(N * 2) + 校验(2)
}
#endif

#if MBF_READ_HOLDING_REGISTERS_EN     != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    make PDU packet of Read Holding Registers function(0x03)
  @param    buf        output buffer
  @param    reg_addr   holding register address
  @param    num        number of registers, between 1 ~ 125
  @return   the length of PDU data
 */
/*---------------------------------------------------------------------------*/
INT32S MBReadHoldingRegisters(INT8U *buf, INT16U reg_addr, INT16U num) C51_REENTRANT
{
    INT32S len = 0;
    buf[len]= MBF_READ_HOLDING_REGISTERS;
    len++;
    PUTU16(buf + len, reg_addr);        // don't put ++ in the macro
    len += 2;
    PUTU16(buf + len, num);
    len += 2;

    return len;
}

/*---------------------------------------------------------------------------*/
/**
  @brief   parse PDU packet of Read Holding Register function(0x03)
  @param   pdu     PDU packet
  @param   addr    holding register address
  @param   num     holding register number
 */
/*---------------------------------------------------------------------------*/
void MBGetReadHoldingRegisters(INT8U *pdu, INT16U *addr, INT16U *num) C51_REENTRANT
{
    GETU16(*addr, pdu + 1);
    GETU16(*num, pdu + 3);
}

/*---------------------------------------------------------------------------*/
/**
  @brief    parse response PDU packet of Read Holding Registers request(0x03)
  @param    pdu               output buffer
  @param    byte              bytes of registers slave return 
  @param    value             registers value for success, exception code for exception response
  @param    exception_code    exception code for exception response
  @return   MB_ERROR_FREE for success, MB_ERROR_SLAVE_EXCEPTION_RESPONSE for exception response, on error return error code
 */
/*---------------------------------------------------------------------------*/
INT32S MBGetResponseReadHoldingRegisters(INT8U *pdu, INT8U *size, INT16U *value, INT8U *exception_code) C51_REENTRANT
{
    INT32S i = 0;

	if (pdu[0] == (MBF_READ_HOLDING_REGISTERS | 0x80)) // 异常响应
	{
        *exception_code = pdu[1];                      // 异常码
		return MB_ERROR_SLAVE_EXCEPTION_RESPONSE;
	} 
	else if (pdu[0] == MBF_READ_HOLDING_REGISTERS)    // 正常响应
	{
        *size = pdu[1];
        for(i= 0; i < *size/2; i++)
            GETU16(value[i], (pdu + 2 + i*2));
	    return MB_ERROR_FREE;
	}
	else
	{
        return MB_ERROR_SLAVE_RESPONSE_VALUE;           // 错误
	}
}

/*---------------------------------------------------------------------------*/
/**
  @brief     get expect length of read holding registers response in RTU mode
  @param     num   number of registers
  @return    MB_ERROR_FREE for success, on error return error expect length of read holding registers response in RTU mode
 */
/*---------------------------------------------------------------------------*/
INT32S MBExpectLenReadHoldingRegisters(INT16U num) C51_REENTRANT
{
    return (5 + num * 2);   // 地址(1) + 功能码(1) + 字节数(1) + 数据(N * 2) + 校验(2)
}
#endif

#if MBF_PRESET_SINGLE_REGISTER_EN      != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    make PDU packet of Preset Single Register function(0x06)
  @param    buf         output buffer
  @param    reg_addr    register address
  @param    value       value to write
  @return   the length of PDU data
 */
/*---------------------------------------------------------------------------*/
INT32S MBPresetSingleRegister(INT8U *buf, INT16U reg_addr, INT16U value) C51_REENTRANT
{
    INT32S len= 0;

    buf[len] = MBF_PRESET_SINGLE_REGISTER;
    len++;
    PUTU16(buf + len, reg_addr);        // don't put ++ in the macro
    len += 2;
    PUTU16(buf + len, value);
    len += 2;

    return len;
}

/*---------------------------------------------------------------------------*/
/**
  @brief   parse PDU packet of Preset Single Register function(0x06)
  @param   pdu      PDU packet
  @param   addr     register address
  @param   value    register value
 */
/*---------------------------------------------------------------------------*/
void MBGetPresetSingleRegister(INT8U *pdu, INT16U *addr, INT16U *value) C51_REENTRANT
{
    GETU16(*addr, pdu+ 1);
    GETU16(*value, pdu+ 3);
}

/*---------------------------------------------------------------------------*/
/**
  @brief    parse response PDU packet of Preset Single Register request(0x06)
  @param    pdu               output buffer
  @param    reg_addr          address of register for success, null for exception response
  @param    value             value of register for success, exception code for exception response
  @param    exception_code    exception code for exception response
  @return   MB_ERROR_FREE for success, MB_ERROR_SLAVE_EXCEPTION_RESPONSE for exception response, on error return error code
 */
/*---------------------------------------------------------------------------*/
INT32S MBGetResponsePresetSingleRegister(INT8U *pdu, INT16U *address, INT16U *value, INT8U *exception_code) C51_REENTRANT
{
    if (pdu[0] == (MBF_PRESET_SINGLE_REGISTER | 0x80))   // 异常响应
	{
        *exception_code = pdu[1];                        // 异常码
		return MB_ERROR_SLAVE_EXCEPTION_RESPONSE;
	}
	else if (pdu[0] == MBF_PRESET_SINGLE_REGISTER)      // 正常响应
	{
        GETU16(*address, pdu+ 1);
        GETU16(*value, pdu+ 3);
		return MB_ERROR_FREE;
	}
	else
	{
        return MB_ERROR_SLAVE_RESPONSE_VALUE;           // 错误
	}
}

/*---------------------------------------------------------------------------*/
/**
 @brief    得到预置单个寄存器命令期待的返回帧长度
 @return   期待的RTU返回帧长度
 */
/*---------------------------------------------------------------------------*/
INT32S MBExpectLenPresetSingleRegister(void) C51_REENTRANT
{
    return  8;     // 从机地址(1) + 功能码(1) + 寄存器地址(2) + 寄存器值(2) + 校验(2)
}
#endif

#if MBF_FORCE_MULTIPLE_COILS_EN       != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    make PDU packet of Force Multiple Coils function(0x0F)
  @param    buf           output buffer
  @param    coil_adddr    starting coil number
  @param    num           number of coils, between 1 ~ 2000
  @param    byte          bytes of coil status
  @param    value         coil status
  @return   the length of PDU data
 */
/*---------------------------------------------------------------------------*/
INT32S MBForceMultipleCoils(INT8U *buf, INT16U coil_addr, INT16U num, INT8U byte, INT8U *value) C51_REENTRANT
{
    INT32S len= 0;

    buf[len]= MBF_FORCE_MULTIPLE_COILS;
    len++;
    PUTU16(buf + len, coil_addr);        // don't put ++ in the macro
    len += 2;
    PUTU16(buf + len, num);
    len += 2;
    buf[len] = byte;
    len++;
    bcopy((const char *)value, (char *)(buf + len), byte);
    len += byte;

    return len;
}

/*---------------------------------------------------------------------------*/
/**
  @brief   parse PDU packet of Force Multiple Coil function(0x0F)
  @param   pdu     PDU packet
  @param   addr    coil address
  @param   num     coil number
  @param   size    bytes of coil value
  @param   value   coil value
  @return  MB_ERROR_FREE for success, error code for error。
 */
/*---------------------------------------------------------------------------*/
INT32S MBGetForceMultipleCoils(INT8U *pdu, INT16U *addr, INT16U *num, INT8U *size, INT8U *value) C51_REENTRANT
{
    INT32S i = 0;

    GETU16(*addr, pdu + 1);
    GETU16(*num, pdu + 3);
    *size = pdu[5];

	if (*num > MAX_COILS_NUM)
		return MB_ERROR_RANGE;

    for (i = 0; i < *size; i++)
        value[i] = *(pdu + 6 + i);

	return MB_ERROR_FREE;
}

/*---------------------------------------------------------------------------*/
/**
  @brief    parse response PDU packet of Force Multiple Coil request(0x0F)
  @param    pdu               output buffer
  @param    coil_addr         start number of coils
  @param    num               number of modified coils
  @param    exception_code    exception code for exception response
  @return   MB_ERROR_FREE for success, MB_ERROR_SLAVE_EXCEPTION_RESPONSE for exception response, on error return error code
 */
/*---------------------------------------------------------------------------*/
INT32S MBGetResponseForceMultipleCoils(INT8U *pdu, INT16U *coil_addr, INT16U *num, INT8U *exception_code) C51_REENTRANT
{
    if (pdu[0] == (MBF_FORCE_MULTIPLE_COILS | 0x80))    // 异常响应
	{
		*exception_code = pdu[1];                       // 异常码
		return MB_ERROR_SLAVE_EXCEPTION_RESPONSE;
	}
	else if (pdu[0] == MBF_FORCE_MULTIPLE_COILS)        // 正常响应
	{
        GETU16(*coil_addr, pdu+ 1);
        GETU16(*num, pdu+ 3);
        return MB_ERROR_FREE;
	}
	else                                                // 错误 
	{
		return MB_ERROR_SLAVE_RESPONSE_VALUE;   
	}	
}

/*---------------------------------------------------------------------------*/
/**
  @brief    得到强制多线圈命令期待的返回帧长度
  @return   期待的RTU返回帧长度
 */
/*---------------------------------------------------------------------------*/
INT32S MBExpectLenForceMultipleCoils(void) C51_REENTRANT
{
    return 8;     // 地址(1) + 功能码(1) + 起始地址(2) + 输出数量(2) + 校验(2)
}
#endif

#if MBF_PRESET_MULTIPLE_REGISTERS_EN   != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    make PDU packet of Preset Multiple Registers function(0x10)
  @param    buf         output buffer
  @param    reg_addr    register address
  @param    num         number of registers, between 1 ~ 120
  @param    size        bytes of value
  @param    value       value to write
  @return   the length of PDU data
 */
/*---------------------------------------------------------------------------*/
INT32S MBPresetMultipleRegisters(INT8U *buf, INT16U reg_addr, INT16U num, INT8U size, INT16U *value) C51_REENTRANT
{
    INT32S len= 0, i= 0;

    buf[len] = MBF_PRESET_MULTIPLE_REGISTERS;
    len++;
    PUTU16(buf+ len, reg_addr);        // don't put ++ in the macro
    len += 2;
    PUTU16(buf + len, num);
    len += 2;
    buf[len] = size;
    len++;

    for(i = 0; i < size/2; i++, len += 2)
        PUTU16(buf + len, value[i]);

    return len;
}

/*---------------------------------------------------------------------------*/
/**
  @brief    parse PDU packet of Write Multiple Registers function(0x10)
  @param    pdu         the request PDU data
  @param    reg_addr    register address
  @param    num         number of registers, between 1 ~ 120
  @param    size        bytes of value 
  @param    value       value to write
  @return  MB_ERROR_FREE for success, error code for error。
 */
/*---------------------------------------------------------------------------*/
INT32S MBGetPresetMultipleRegisters(INT8U *pdu, INT16U *reg_addr, INT16U *num, INT8U *size, INT16U *value) C51_REENTRANT
{
    INT32S i = 0;

    GETU16(*reg_addr, pdu + 1);
    GETU16(*num, pdu + 3);
    *size = pdu[5];

	if (*num > MAX_HOLDING_REGISTERS_NUM)
        return MB_ERROR_RANGE;

    for(i = 0; i < (*size)/2; i++)
        GETU16(value[i], pdu + 6 + i*2);

	return MB_ERROR_FREE;
}

/*---------------------------------------------------------------------------*/
/**
  @brief    parse response PDU packet of Write Multiple Registers request(0x10)
  @param    pdu               output buffer
  @param    reg_addr          start address of register
  @param    num               number of registers(1 ~ 123) for  success, exception code for exception response
  @param    exception_code    exception code for exception response
  @return   MB_ERROR_FREE for success, MB_ERROR_SLAVE_EXCEPTION_RESPONSE for exception response, on error return error code
 */
/*---------------------------------------------------------------------------*/
INT32S MBGetResponsePresetMultipleRegisters(INT8U *pdu, INT16U *reg_addr, INT16U *num, INT8U *exception_code) C51_REENTRANT
{
    if (pdu[0] == (MBF_PRESET_MULTIPLE_REGISTERS | 0x80)) // 异常响应
	{
        *exception_code = pdu[1];                         // 异常码
		return MB_ERROR_SLAVE_EXCEPTION_RESPONSE;
	}
	else if(pdu[0] == MBF_PRESET_MULTIPLE_REGISTERS)      // 正常响应
	{
        GETU16(*reg_addr, pdu+ 1);
        GETU16(*num, pdu+ 3);
		return MB_ERROR_FREE;
	}
	else                                                  // 错误
	{
		return MB_ERROR_SLAVE_RESPONSE_VALUE; 
	}
}

/*---------------------------------------------------------------------------*/
/**
 @brief    得到Preset Multiple Registers命令期待的返回帧长度
 @return   期待的RTU返回帧长度
 */
/*---------------------------------------------------------------------------*/
INT32S MBExpectLenPresetMultipleRegisters(void) C51_REENTRANT
{
    return  8; // 从机地址(1) + 功能码(1) + 起始地址(2) + 寄存器数量(2) + 校验(2)
}
#endif

#if MBF_READ_WRITE_MULTIPLE_REGISTERS_EN  != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    make PDU packet of Read Write Multiple Registers function(0x17)
  @param    buf            output buffer
  @param    reg_addr_rd    starting register number to read
  @param    num_rd         number of registers ro read, between 1 ~ 118
  @param    reg_addr_wr    starting register number to write
  @param    num_wr         number of registers ro write, between 1 ~ 118
  @param    size           bytes of value to write
  @param    value_wr       value to write
  @return   the length of PDU data
 */
/*---------------------------------------------------------------------------*/
INT32S MBReadWriteMultipleRegisters(INT8U *buf, INT16U reg_addr_rd, INT16U num_rd, INT16U reg_addr_wr, INT16U num_wr, INT8U size, INT16U *value_wr) C51_REENTRANT
{
    INT32S len= 0, i= 0;

    buf[len] = MBF_READ_WRITE_MULTIPLE_REGISTERS;
    len++;
    PUTU16(buf + len, reg_addr_rd);        // don't put ++ in the macro
    len += 2;
    PUTU16(buf + len, num_rd);
    len += 2;
    PUTU16(buf + len, reg_addr_wr);
    len += 2;
    PUTU16(buf+ len, num_wr);
    len += 2;
    buf[len++]= size;

    for(i = 0; i < size/2; i++, len += 2)
        PUTU16(buf+len, value_wr[i]);

    return len;
}

/*---------------------------------------------------------------------------*/
/**
  @brief    parse PDU packet of Read Write Multiple Registers function(0x17)
  @param    pdu            the request PDU data
  @param    reg_addr_rd    starting register number to read
  @param    num_rd         number of registers ro read, between 1 ~ 120
  @param    reg_addr_wr    starting register number to write
  @param    num_wr         number of registers ro write, between 1 ~ 120
  @param    size           bytes of value to write
  @param    value_wr       value to write
  @return   MB_ERROR_FREE for success, on error return error code
 */
/*---------------------------------------------------------------------------*/
INT32S MBGetReadWriteMultipleRegisters(INT8U *pdu, INT16U *reg_addr_rd, INT16U *num_rd, INT16U *reg_addr_wr, INT16U *num_wr, INT8U *size, INT16U *value_wr) C51_REENTRANT
{
    INT32S i= 0;

    GETU16( *reg_addr_rd, pdu+ 1);
    GETU16( *num_rd, pdu+ 3);
    GETU16( *reg_addr_wr, pdu+ 5);
    GETU16( *num_wr, pdu+ 7);
    *size = pdu[9];

	if ((*num_rd > MAX_HOLDING_REGISTERS_NUM) || (*num_wr > MAX_HOLDING_REGISTERS_NUM))
		return MB_ERROR_RANGE;

    for (i = 0; i < (*size)/2; i++)
        GETU16(value_wr[i], pdu + 10 + i*2);

    return MB_ERROR_FREE;
}

/*---------------------------------------------------------------------------*/
/**
  @brief    parse response PDU packet of Response Read Write Multiple Registers request(0x17)
  @param    pdu               output buffer
  @param    size              bytes of registers readed slave returned
  @param    value             registers value slave returned
  @param    exception_code    exception code for exception response
  @return   MB_ERROR_FREE for success, MB_ERROR_SLAVE_EXCEPTION_RESPONSE for exception response, on error return error code
 */
/*---------------------------------------------------------------------------*/
INT32S MBGetResponseReadWriteMultipleRegisters(INT8U *pdu, INT8U *size, INT16U *value, INT8U *exception_code) C51_REENTRANT
{
    INT32S i = 0;

	if (pdu[0] == (MBF_READ_WRITE_MULTIPLE_REGISTERS | 0x80)) // 异常响应
	{
		*exception_code = pdu[1];                            // 异常码
		return MB_ERROR_SLAVE_EXCEPTION_RESPONSE;
	}
	else if(pdu[0] == MBF_READ_WRITE_MULTIPLE_REGISTERS)     // 正常响应
	{
        *size = pdu[1];
        for(i = 0; i < *size/2; i++)
            GETU16(value[i], pdu + 2 + i*2);
        return MB_ERROR_FREE;
	}
	else                                                     // 错误 
	{
		return MB_ERROR_SLAVE_RESPONSE_VALUE; 
	}
}

/*---------------------------------------------------------------------------*/
/**
 @brief    得到Read Write Multiple Registers命令期待的返回帧长度
 @param    num    读寄存器个数
 @return   期待的RTU返回帧长度
 */
/*---------------------------------------------------------------------------*/
INT32S MBExpectLenReadWriteMultipleRegisters(INT16U num) C51_REENTRANT
{
    return (1 + 1 + 1 + num * 2 + 2); // 从机地址(1) + 功能码(1) + 字节数(1) + 读寄存器值(N*2) + 校验(2)
}

#endif

#if MBF_MASK_WRITE_REGISTER_EN        != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    make PDU packet of Mask Write Register function(0x16)
  @param    buf         output buffer
  @param    reg_addr    register number
  @param    andmask     and mask
  @param    ormask      or mask
  @return   the length of PDU data
 */
/*---------------------------------------------------------------------------*/
INT32S MBMaskWriteRegister(INT8U *buf, INT16U reg_addr, INT16U andmask, INT16U ormask) C51_REENTRANT
{
    INT32S len= 0;

    buf[len]= MBF_MASK_WRITE_REGISTER;
    len++;
    PUTU16(buf+len, reg_addr);            // don't put ++ in the macro
    len+= 2;
    PUTU16(buf+len, andmask);
    len+= 2;
    PUTU16(buf+len, ormask);
    len+= 2;

    return len;
}

/*---------------------------------------------------------------------------*/
/**
  @brief    parse PDU packet of Mask Write Register function(0x16)
  @param    pdu         the request PDU data
  @param    reg_addr    register number
  @param    andmask     and mask
  @param    ormask      or mask
 */
/*---------------------------------------------------------------------------*/
void MBGetMaskWriteRegister(INT8U *pdu, INT16U *reg_addr, INT16U *andmask, INT16U *ormask) C51_REENTRANT
{
    GETU16(*reg_addr, pdu+ 1);
    GETU16(*andmask, pdu+ 3);
    GETU16(*ormask, pdu+ 5);
}

/*---------------------------------------------------------------------------*/
/**
  @brief    parse response PDU packet of Mask Write Register function(0x16)
  @param    pdu               output buffer
  @param    reg_addr          register address
  @param    andmask           and mask
  @param    ormask            or mask
  @param    exception_code    exception code for exception response
  @return   MB_ERROR_FREE for success, MB_ERROR_SLAVE_EXCEPTION_RESPONSE for exception response, on error return error code
 */
/*---------------------------------------------------------------------------*/
INT32S MBGetResponseMaskWriteRegister(INT8U *pdu, INT16U *reg_addr, INT16U *andmask, INT16U *ormask, INT8U *exception_code) C51_REENTRANT
{
    if (pdu[0] == (MBF_MASK_WRITE_REGISTER | 0x80)) // 异常响应
	{
		*exception_code = pdu[1];
		return MB_ERROR_SLAVE_EXCEPTION_RESPONSE;
	}
	else if (pdu[0] == MBF_MASK_WRITE_REGISTER)    // 正常响应
	{        
        GETU16(*reg_addr, pdu+ 1);
        GETU16(*andmask, pdu+ 3);
        GETU16(*ormask, pdu+ 5);
		return MB_ERROR_FREE;
	}
	else                                           // 错误 
	{
		return MB_ERROR_SLAVE_RESPONSE_VALUE;
	}
}

/*---------------------------------------------------------------------------*/
/**
 @brief    得到Mask Write Register命令期待的返回帧长度
  @return  期待的RTU返回帧长度
 */
/*---------------------------------------------------------------------------*/
INT32S MBExpectLenMaskWriteRegister(void) C51_REENTRANT
{
    return 10;     // 从机地址(1) + 功能码(1) + 寄存器地址(2) + And_Mask(2) + Or_Mask(2) + 校验(2)
}

#endif   

#if MBF_READ_FIFO_QUEUE_EN            != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    make PDU packet of Read FIFO Queue function(0x18)
  @param    buf        output buffer
  @param    FIFOAddr    FIFO address
  @return    the length of PDU data
 */
/*---------------------------------------------------------------------------*/
int    MBReadFIFOQueue(INT8U *buf, INT16U FIFOAddr) C51_REENTRANT
{
    int len= 0;
    buf[ len]= MBF_READ_FIFO_QUEUE;
    len++;
    PUTU16( buf+ len, FIFOAddr);        // don't put ++ in the macro
    len+= 2;

    return len;
}
#endif

// MBF_READ_FILE_RECORD            0x14
// MBF_WRITE_FILE_RECORD        0x15

#if MBF_READ_EXCEPTION_STATUS_EN      != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    make PDU packet of Read Exception Status function(0x07)
  @param    buf        output buffer
  @return    the length of PDU data
 */
/*---------------------------------------------------------------------------*/
int    MBReadExceptionStatus(INT8U *buf) C51_REENTRANT
{
    int len= 0;
    buf[ len]= MBF_READ_EXCEPTION_STATUS;
    len++;

    return len;
}
#endif

#if MBF_DIAGNOSTIC_EN                 != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    make PDU packet of Diagnostic function(0x08)
  @param    buf        output buffer
  @param    subfunc        subfunction code
  @param    dat        data to be sent to slave device
  @return    the length of PDU data
 */
/*---------------------------------------------------------------------------*/
int    MBDiagnostic(INT8U *buf, INT16U subfunc, INT16U dat) C51_REENTRANT
{
    int len= 0;
    buf[ len]= MBF_DIAGNOSTIC;
    len++;
    PUTU16( buf+ len, subfunc);        // don't put ++ in the macro
    len+= 2;
    PUTU16( buf+ len, dat);        // all data of subfunc is 16bits long
    len+= 2;

    return len;
}

/*---------------------------------------------------------------------------*/
/**
  @brief    make response PDU packet of Diagnostic request(0x08)
  @param    buf        output buffer
  @param    subfunc        subfunction code
  @param    dat        response data of request
  @return    the length of PDU data
 */
/*---------------------------------------------------------------------------*/
int    MBResponseDiagnostic(INT8U *buf, INT16U subfunc, INT16U dat) C51_REENTRANT
{
    int len= 0;
    buf[ len++]= MBF_DIAGNOSTIC;
    PUTU16( buf+len, subfunc);
    len+= 2;
    PUTU16( buf+len, dat);
    len+= 2;

    return len;
}

/*---------------------------------------------------------------------------*/
/**
  @brief    parse PDU packet of Diagnostic function(0x08)
  @param    pdu        the request PDU data
  @param    subfunc        subfunction code
  @param    dat        data to be sent to slave device
  @return    MB_ERROR_FREE for success, on error return error code
 */
/*---------------------------------------------------------------------------*/
int    MBGetDiagnostic(INT8U *pdu, INT16U *subfunc, INT16U *dat) C51_REENTRANT
{
    if( pdu[ 0] != MBF_DIAGNOSTIC)
        return MB_ERROR_UNSUPPORT_FUNC;

    GETU16( *subfunc, pdu+ 1);
    GETU16( *dat, pdu+ 3);

    return MB_ERROR_FREE;
}

/*---------------------------------------------------------------------------*/
/**
  @brief    parse response PDU packet of Diagnostic request(0x08)
  @param    pdu        output buffer
  @param    subfunc        subfunction code
  @param    dat        response data of request
  @return    MB_ERROR_FREE for success, on error return error code
 */
/*---------------------------------------------------------------------------*/
int    MBGetResponseDiagnostic(INT8U *pdu, INT16U *subfunc, INT16U *dat) C51_REENTRANT
{
    if( pdu[ 0] != MBF_DIAGNOSTIC)
        return MB_ERROR_UNSUPPORT_FUNC;

    GETU16( *subfunc, pdu+ 1);
    GETU16( *dat, pdu+ 3);

    return MB_ERROR_FREE;
}
#endif

#if MBF_GET_COMM_EVENT_COUNTER_EN     != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    make PDU packet of Get Comm Event Counter function(0x0B)
  @param    buf        output buffer
  @return    the length of PDU data
 */
/*---------------------------------------------------------------------------*/
int    MBGetCommEventCounter(INT8U *buf) C51_REENTRANT
{
    int len= 0;
    buf[ len]= MBF_GET_COMM_EVENT_COUNTER;
    len++;

    return len;
}

/*---------------------------------------------------------------------------*/
/**
  @brief    make response PDU packet of Get Comm Event Counter request(0x0B)
  @param    buf        output buffer
  @param    status        status of Comm Conuter
  @param    eventcount    event counter
  @return    the length of PDU data
 */
/*---------------------------------------------------------------------------*/
int    MBResponseGetCommEventCounter(INT8U *buf, INT16U status, INT16U eventcount) C51_REENTRANT
{
    int len= 0;
    buf[ len++]= MBF_GET_COMM_EVENT_COUNTER;
    PUTU16( buf+len, status);
    len+= 2;
    PUTU16( buf+len, eventcount);
    len+= 2;

    return len;
}

/*---------------------------------------------------------------------------*/
/**
  @brief    parse response PDU packet of Get Comm Event Counter request(0x0B)
  @param    pdu        output buffer
  @param    status        status of Comm Conuter
  @param    eventcount    event counter
  @return    MB_ERROR_FREE for success, on error return error code
 */
/*---------------------------------------------------------------------------*/
int    MBGetResponseGetCommEventCounter(INT8U *pdu, INT16U *status, INT16U *eventcount) C51_REENTRANT
{
    if( pdu[ 0] != MBF_GET_COMM_EVENT_COUNTER)
        return MB_ERROR_UNSUPPORT_FUNC;

    GETU16( *status, pdu+ 1);
    GETU16( *eventcount, pdu+ 3);

    return MB_ERROR_FREE;
}
#endif

#if MBF_GET_COMM_EVENT_LOG_EN         != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    make PDU packet of Get Comm Event Log function(0x0C)
  @param    buf        output buffer
  @return    the length of PDU data
 */
/*---------------------------------------------------------------------------*/
int    MBGetCommEventLog(INT8U *buf) C51_REENTRANT
{
    int len= 0;
    buf[ len]= MBF_GET_COMM_EVENT_LOG;
    len++;

    return len;
}

/*---------------------------------------------------------------------------*/
/**
  @brief    make response PDU packet of Get Comm Event Counter request(0x0C)
  @param    buf        output buffer
  @param    no        number of the following data
  @param    status        status of Comm Conuter
  @param    eventcount    event counter
  @param    messagecount    counter for processed message
  @param    events        new events
  @return    the length of PDU data
 */
/*---------------------------------------------------------------------------*/
int    MBResponseGetCommEventLog(INT8U *buf, INT8U no, INT16U status, INT16U eventcount, INT16U messagecount, INT8U *events) C51_REENTRANT
{
    int len= 0;
    buf[ len++]= MBF_GET_COMM_EVENT_LOG;
    buf[ len++]= no;
    PUTU16( buf+len, status);
    len+= 2;
    PUTU16( buf+len, eventcount);
    len+= 2;
    PUTU16( buf+len, messagecount);
    len+= 2;

    bcopy( (const char *)events, (char *)(buf+ len), no- 6);

    return len;
}

/*---------------------------------------------------------------------------*/
/**
  @brief    parse response PDU packet of Get Comm Event Counter request(0x0C)
  @param    pdu        output buffer
  @param    status        status of Comm Conuter
  @param    eventcount    event counter
  @param    messagecount    counter for processed message
  @param    events        new events
  @return    MB_ERROR_FREE for success, on error return error code
 */
/*---------------------------------------------------------------------------*/
int    MBGetResponseGetCommEventLog(INT8U *pdu, INT16U *status, INT16U *eventcount, INT16U *messagecount, INT8U *events) C51_REENTRANT
{
    INT8U no;
    if( pdu[ 0] != MBF_GET_COMM_EVENT_LOG)
        return MB_ERROR_UNSUPPORT_FUNC;

    no= pdu[ 1];
    GETU16( *status, pdu+ 2);
    GETU16( *eventcount, pdu+ 4);
    GETU16( *messagecount, pdu+ 6);

    bcopy( (const char *)(pdu+ 8), (char *)events, no- 6);

    return MB_ERROR_FREE;
}
#endif

#if MBF_REPORT_SLAVE_ID_EN            != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    make PDU packet of Report Slave ID function(0x11)
  @param    buf        output buffer
  @return    the length of PDU data
 */
/*---------------------------------------------------------------------------*/
int    MBReportSlaveID(INT8U *buf) C51_REENTRANT
{
    int len= 0;
    buf[ len]= MBF_REPORT_SLAVE_ID;
    len++;

    return len;
}

/*---------------------------------------------------------------------------*/
/**
 @brief    parse response PDU packet of Report Slave ID function(0x16)
  @param    pdu        output buffer
  @param    slave_id    slave id
  @param    status        slave device status
  @return    MB_ERROR_FREE for success, on error return error code
 */
/*---------------------------------------------------------------------------*/
int    MBGetResponseReportSlaveID(INT8U *pdu, INT8U *slave_id, INT8U *status) C51_REENTRANT
{
    if( pdu[ 0] != MBF_REPORT_SLAVE_ID)
        return MB_ERROR_UNSUPPORT_FUNC;

    *slave_id= pdu[ 2];
    *status= pdu[ 3];

    return MB_ERROR_FREE;
}
#endif

// Response function



#if MBF_READ_FIFO_QUEUE_EN            != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    make response PDU packet of Read FIFO Queue request(0x18)
  @param    buf        output buffer
  @param    no        bytes of the following data
  @param    count        FIFO value buffer size(<=31)
  @param    value        values of FIFO register
  @return    the length of PDU data
 */
/*---------------------------------------------------------------------------*/
int    MBResponseReadFIFOQueue(INT8U *buf, INT16U no, INT16U count, INT16U *value) C51_REENTRANT
{
    int len= 0, i= 0;
    buf[ len++]= MBF_READ_FIFO_QUEUE;
    PUTU16( buf+len, no);
    len+= 2;
    PUTU16( buf+len, count);
    len+= 2;

    for( i= 0; i< (no- 2)/2; i++, len+= 2)
        PUTU16( buf+len, value[ i]);

    return len;
}
#endif

#if MBF_READ_EXCEPTION_STATUS_EN      != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    make response PDU packet of Read FIFO Queue request(0x07)
  @param    buf        output buffer
  @param    status        eight exception status in one byte
  @return    the length of PDU data
 */
/*---------------------------------------------------------------------------*/
int    MBResponseReadExceptionStatus(INT8U *buf, INT8U status) C51_REENTRANT
{
    int len= 0;
    buf[ len++]= MBF_READ_EXCEPTION_STATUS;
    buf[ len++]= status;

    return len;
}
#endif

// Modbus get request value from PDU
/*---------------------------------------------------------------------------*/
/**
  @brief    将源16位数据调整为大端模式并存入到目标地址
  @param    pdst    目标地址
  @param    psrc    源数据 
  @param    no      数据个数
 */
/*---------------------------------------------------------------------------*/
void MBDataToBigEndian(INT8U *pdst, INT16U *psrc, INT16U no) C51_REENTRANT
{
   INT16U i;
   for (i = 0; i < no; i++)
   {
     PUTU16(pdst + i * 2, psrc[i]);
   }
}

#if MBF_READ_FIFO_QUEUE_EN            != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    parse PDU packet of Read FIFO Queue function(0x18)
  @param    pdu        the request PDU data
  @param    FIFOAddr    FIFO address
  @return    MB_ERROR_FREE for success, on error return error code
 */
/*---------------------------------------------------------------------------*/
int    MBGetReadFIFOQueue(INT8U *pdu, INT16U *FIFOAddr) C51_REENTRANT
{
    if( pdu[ 0] != MBF_READ_FIFO_QUEUE)
        return MB_ERROR_UNSUPPORT_FUNC;

    GETU16( *FIFOAddr, pdu+ 1);

    return MB_ERROR_FREE;
}
#endif

#if MBF_READ_FIFO_QUEUE_EN            != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    parse response PDU packet of Read FIFO Queue request(0x18)
  @param    pdu        output buffer
  @param    count        FIFO value buffer size(<=31)
  @param    value        values of FIFO register
  @return    MB_ERROR_FREE for success, on error return error code
 */
/*---------------------------------------------------------------------------*/
int    MBGetResponseReadFIFOQueue(INT8U *pdu, INT16U *count, INT16U *value) C51_REENTRANT
{
    INT16U i= 0, no= 0;
    if( pdu[ 0] != MBF_READ_FIFO_QUEUE)
        return MB_ERROR_UNSUPPORT_FUNC;

    GETU16( no, pdu+ 1);
    GETU16( *count, pdu+ 3);
    for( i= 0; i< no/2; i++)
        GETU16( value[ i], ( pdu+ 5+ i*2));

    return MB_ERROR_FREE;
}
#endif

#if MBF_READ_EXCEPTION_STATUS_EN      != 0
/*---------------------------------------------------------------------------*/
/**
  @brief    parse response PDU packet of Read FIFO Queue request(0x07)
  @param    pdu        output buffer
  @param    status        eight exception status in one byte
  @return    MB_ERROR_FREE for success, on error return error code
 */
/*---------------------------------------------------------------------------*/
int    MBGetResponseReadExceptionStatus(INT8U *pdu, INT8U *status) C51_REENTRANT
{
    if( pdu[ 0] != MBF_READ_EXCEPTION_STATUS)
        return MB_ERROR_UNSUPPORT_FUNC;

    *status= pdu[ 1];

    return MB_ERROR_FREE;
}
#endif

/*---------------------------------------------------------------------------*/
/**
 @brief    将期待的RTU帧长度转化成ASCII帧长度, 包含':', '0x0d', '0x0a"
 @param    len  期待的RTU返回帧长度
 @return   期待的ASCII返回帧长度
 */
/*---------------------------------------------------------------------------*/
INT32S MBRTULenToASCII(INT16U len) C51_REENTRANT
{
   return (len - 1) * 2 + 3;
}

