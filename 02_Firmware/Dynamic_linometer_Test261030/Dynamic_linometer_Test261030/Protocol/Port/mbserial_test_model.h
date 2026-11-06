/*
*********************************************************************************************************
* 文件名   : mbserial_test_model.h
* 功能描述 : mbserial_test_model.c的头文件
* 版本号   : v1.0
* 作者     : zqh			 
*********************************************************************************************************
*/

#ifndef MBSERIAL_TEST_MODEL_H
#define MBSERIAL_TEST_MODEL_H

extern INT16U MBValue[125];
void MBSerialSlaveValueSet(INT16U *value, INT16U num);
void MBSerialSlaveValueGet(INT16U *value, INT16U num);

#endif                                                          
