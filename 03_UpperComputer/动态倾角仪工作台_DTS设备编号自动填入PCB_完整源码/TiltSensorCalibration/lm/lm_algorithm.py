"""
    LM算法
    说明：改写自“LM算法_Matlab”
"""

import numpy as np
from ellipsoid.ellipsoid_fitting import *


ITERATIONS_DEFAULT = 10 # 迭代次数缺省值
ITERATIONS_TERMINATION_CONDITION_DEFAULT = 0.5 # 迭代终止条件缺省值
PENALTY_FACTOR_DEFAULT = 1000 # 惩罚因子缺省值


def ComputeF(a1, a2, a3, s1, s2, s3, b1, b2, b3, accx, accy, accz, g):
    T = np.array([[1, a3, -a2], [-a3, 1, a1], [a2, -a1, 1]])
    K = np.array([[s1, 0, 0], [0, s2, 0], [0, 0, s3]])
    B = np.array([[b1], [b2], [b3]])
    ACC = np.array([[accx], [accy], [accz]])
    F = np.matmul(K, (ACC + B))
    F = np.matmul(T, F)
    V = (np.sqrt(np.matmul(F.T, F)) - g) * (np.sqrt(np.matmul(F.T, F)) - g)
    return V


def ComputeJacobi(a1, a2, a3, s1, s2, s3, b1, b2, b3, acc, g, num):
    phi = a1
    theta = a2
    psi = a3
    sx = s1
    sy = s2
    sz = s3
    bx = b1
    by = b2
    bz = b3
    amx = acc[0]
    amy = acc[1]
    amz = acc[2]
    J = np.zeros((num, 9))

    for k in range(num):
        Fx = np.sqrt((sx * (amx[k] + bx) + psi * sy * (amy[k] + by) - theta * sz * (amz[k] + bz)) ** 2 +
                 (-psi * sx * (amx[k] + bx) + sy * (amy[k] + by) + phi * sz * (amz[k] + bz)) ** 2 +
                 (theta * sx * (amx[k] + bx) - phi * sy * (amy[k] + by) + sz * (amz[k] + bz)) ** 2) - g

        J[k, 0] = ((-psi * sx * (amx[k] + bx) + sy * (amy[k] + by) + phi * sz * (amz[k] + bz)) * sz * (amz[k] + bz)
               - (theta * sx * (amx[k] + bx) - phi * sy * (amy[k] + by) + sz * (amz[k] + bz)) * sy * (amy[k] + by)
               ) * (Fx / (Fx + g))

        J[k, 1] = (-(sx * (amx[k] + bx) + psi * sy * (amy[k] + by) - theta * sz * (amz[k] + bz)) * sz * (amz[k] + bz)
               + (theta * sx * (amx[k] + bx) - phi * sy * (amy[k] + by) + sz * (amz[k] + bz)) * sx * (amx[k] + bx)
               ) * (Fx / (Fx + g))

        J[k, 2] = ((sx * (amx[k] + bx) + psi * sy * (amy[k] + by) - theta * sz * (amz[k] + bz)) * sy * (amy[k] + by)
               - (-psi * sx * (amx[k] + bx) + sy * (amy[k] + by) + phi * sz * (amz[k] + bz)) * sx * (amx[k] + bx)
               ) * (Fx / (Fx + g))

        J[k, 3] = ((sx * (amx[k] + bx) + psi * sy * (amy[k] + by) - theta * sz * (amz[k] + bz)) * (amx[k] + bx)
               - (-psi * sx * (amx[k] + bx) + sy * (amy[k] + by) + phi * sz * (amz[k] + bz)) * psi * (amx[k] + bx)
               + (theta * sx * (amx[k] + bx) - phi * sy * (amy[k] + by) + sz * (amz[k] + bz)) * theta * (amx[k] + bx)
               ) * (Fx / (Fx + g))

        J[k, 4] = ((sx * (amx[k] + bx) + psi * sy * (amy[k] + by) - theta * sz * (amz[k] + bz)) * psi * (amy[k] + by)
               + (-psi * sx * (amx[k] + bx) + sy * (amy[k] + by) + phi * sz * (amz[k] + bz)) * (amy[k] + by)
               - (theta * sx * (amx[k] + bx) - phi * sy * (amy[k] + by) + sz * (amz[k] + bz)) * phi * (amy[k] + by)
               ) * (Fx / (Fx + g))

        J[k, 5] = (-(sx * (amx[k] + bx) + psi * sy * (amy[k] + by) - theta * sz * (amz[k] + bz)) * theta * (amz[k] + bz)
               + (-psi * sx * (amx[k] + bx) + sy * (amy[k] + by) + phi * sz * (amz[k] + bz)) * phi * (amz[k] + bz)
               + (theta * sx * (amx[k] + bx) - phi * sy * (amy[k] + by) + sz * (amz[k] + bz)) * (amz[k] + bz)
               ) * (Fx / (Fx + g))

        J[k, 6] = ((sx * (amx[k] + bx) + psi * sy * (amy[k] + by) - theta * sz * (amz[k] + bz)) * sx
               - (-psi * sx * (amx[k] + bx) + sy * (amy[k] + by) + phi * sz * (amz[k] + bz)) * psi * sx
               + (theta * sx * (amx[k] + bx) - phi * sy * (amy[k] + by) + sz * (amz[k] + bz)) * theta * sx
               ) * (Fx / (Fx + g))

        J[k, 7] = ((sx * (amx[k] + bx) + psi * sy * (amy[k] + by) - theta * sz * (amz[k] + bz)) * psi * sy
               + (-psi * sx * (amx[k] + bx) + sy * (amy[k] + by) + phi * sz * (amz[k] + bz)) * sy
               - (theta * sx * (amx[k] + bx) - phi * sy * (amy[k] + by) + sz * (amz[k] + bz)) * phi * sy
               ) * (Fx / (Fx + g))

        J[k, 8] = (-(sx * (amx[k] + bx) + psi * sy * (amy[k] + by) - theta * sz * (amz[k] + bz)) * theta * sz
               + (-psi * sx * (amx[k] + bx) + sy * (amy[k] + by) + phi * sz * (amz[k] + bz)) * phi * sz
               - (theta * sx * (amx[k] + bx) - phi * sy * (amy[k] + by) + sz * (amz[k] + bz)) * sz
               ) * (Fx / (Fx + g))

    return J


def lm(gxyz, iterations, iteration_termination_condition, penalty_factor, ellipsoid_result):
    """
    LM算法

    Args:
        gxyz (ndarray): 各位置的三轴加速度数据
        iterations (int): 迭代次数
        iteration_termination_condition (float): 迭代终止条件
        penalty_factor (float): 惩罚因子
        ellipsoid_result (ndarray): 椭球拟合结果

    Returns:
        ndarray: LM算法运行成功，返回一个一维数组，数组存放T1, T2, T3, S1, S2, S3, B1, B2, B3。LM算法运行失败，返回None。

    Raises:

    Note:

    """
    # 加载数据
    row_num, col_num = gxyz.shape
    ax = np.zeros((row_num, 1))
    ay = np.zeros((row_num, 1))
    az = np.zeros((row_num, 1))
    for row in range(0, row_num):
        ax[row, 0] = gxyz[row, 0]
        ay[row, 0] = gxyz[row, 1]
        az[row, 0] = gxyz[row, 2]

    # 迭代次数
    N = iterations
    # 位置数
    acqSize = row_num
    # 分配空间
    Acc = np.zeros((3, acqSize))
    sum0 = np.zeros(acqSize)

    a1 = np.zeros(N)
    a2 = np.zeros(N)
    a3 = np.zeros(N)

    s1 = np.zeros(N)
    s2 = np.zeros(N)
    s3 = np.zeros(N)

    b1 = np.zeros(N)
    b2 = np.zeros(N)
    b3 = np.zeros(N)

    # 填充传感器数据
    for j in range(acqSize):
        Acc[0, j] = ax[j][0]
        Acc[1, j] = ay[j][0]
        Acc[2, j] = az[j][0]

    # 安装导致的欧拉角误差
    a1[0] = 0
    a2[0] = 0
    a3[0] = 0

    # 获取椭球拟合结果
    X0 = ellipsoid_result[0]
    Y0 = ellipsoid_result[1]
    Z0 = ellipsoid_result[2]
    A = ellipsoid_result[3]
    B = ellipsoid_result[4]
    C = ellipsoid_result[5]

    # 各轴的尺度因子
    s1[0] = 1 / A
    s2[0] = 1 / B
    s3[0] = 1 / C

    # 各轴的测量偏移
    b1[0] = X0
    b2[0] = Y0
    b3[0] = Z0

    # 重力加速度的值
    g = 1

    # 迭代终止条件
    minvalue = iteration_termination_condition # 0.5

    # 未标定前的传感器性能指标
    for n in range(acqSize):
        sum0[n] = ComputeF(a1[0], a2[0], a3[0], s1[0], s2[0], s3[0], b1[0], b2[0], b3[0], Acc[0, n], Acc[1, n],
                           Acc[2, n], g)

    # 存储最优的lambda值
    Lam = np.zeros(2)

    # 使用LM算法来求解最小二乘优化问题
    lamda = penalty_factor # 惩罚因子 1000
    Fk = np.zeros(acqSize)
    Fk1 = np.zeros(acqSize)

    for i in range(1, N):
        # 使用上一次的X值计算得到的指标
        value_latest = 0
        value_new = 0
        for j in range(acqSize):
            Fk[j] = ComputeF(a1[i - 1], a2[i - 1], a3[i - 1], s1[i - 1], s2[i - 1], s3[i - 1], b1[i - 1], b2[i - 1],
                             b3[i - 1], Acc[0, j], Acc[1, j], Acc[2, j], g)
            value_latest += Fk[j] * Fk[j]

        # 优化X的取值，Levenberg-Marquardt算法
        # 计算雅可比矩阵
        D = np.ones((10,))
        Jac = ComputeJacobi(a1[i - 1], a2[i - 1], a3[i - 1], s1[i - 1], s2[i - 1], s3[i - 1], b1[i - 1], b2[i - 1],
                            b3[i - 1], Acc, g, acqSize)
        X = np.array(
            [a1[i - 1], a2[i - 1], a3[i - 1], s1[i - 1], s2[i - 1], s3[i - 1], b1[i - 1], b2[i - 1], b3[i - 1]])
        X = X - np.linalg.inv(Jac.T @ Jac + lamda * np.eye(9)) @ Jac.T @ Fk

        # 计算结果有可能为虚数，此处取其实部
        a1[i] = np.real(X[0])
        a2[i] = np.real(X[1])
        a3[i] = np.real(X[2])
        s1[i] = np.real(X[3])
        s2[i] = np.real(X[4])
        s3[i] = np.real(X[5])
        b1[i] = np.real(X[6])
        b2[i] = np.real(X[7])
        b3[i] = np.real(X[8])

        # 判断优化后的指标是否减小
        for k in range(acqSize):
            Fk1[k] = ComputeF(a1[i], a2[i], a3[i], s1[i], s2[i], s3[i], b1[i], b2[i], b3[i], Acc[0, k], Acc[1, k],
                              Acc[2, k], g)
            value_new += Fk1[k] * Fk1[k]

        if value_new <= value_latest:
            lamda *= 0.9
        else:
            lamda *= 1.1

    # 计算lm结果
    T1 = (a1[N - 1]) # 非正交
    T2 = (a2[N - 1])
    T3 = (a3[N - 1])

    S1 = (s1[N - 1]) # 比例因子
    S2 = (s2[N - 1])
    S3 = (s3[N - 1])

    B1 = (b1[N - 1]) # 零偏
    B2 = (b2[N - 1])
    B3 = (b3[N - 1])

    # 返回lm结果
    result = np.zeros((1, 9))
    result = [T1, T2, T3, S1, S2, S3, B1, B2, B3]
    return result


def lm_test():
    """LM算法测试函数"""
    # 这里输入任意个点加速度参数，尽量在球面上均匀分布
    n = 6
    ndarray = np.zeros((n, 3))
    ndarray[0] = [1.00751659, 0.05182495, -0.00869218]
    ndarray[1] = [-0.03736436, 0.80974447, 0.58576584]
    ndarray[2] = [0.03779374, -0.79218016, -0.6120035]
    ndarray[3] = [0.0238915, -0.59754208, 0.78146233]
    ndarray[4] = [-0.02346522, 0.61499635, -0.80776412]
    ndarray[5] = [-1.0077515, -0.03400312, -0.01812443]

    # 计算椭球拟合结果
    ellipsoid_result = ellipsoid_fitting(ndarray)
    if ellipsoid_result == None:
        print("椭球拟合失败！")
        return

    # lm计算
    lm_result = lm(ndarray, ITERATIONS_DEFAULT, ITERATIONS_TERMINATION_CONDITION_DEFAULT, PENALTY_FACTOR_DEFAULT, ellipsoid_result)
    if lm_result == None:
        print("LM计算失败！")
        return

    # 打印lm结果
    print("LM计算结果：\n")
    print(f"T1 = {lm_result[0]}, T2 = {lm_result[1]}, T3 = {lm_result[2]}, S1 = {lm_result[3]}, S2 = {lm_result[4]}, S3 = {lm_result[5]}, B1 = {lm_result[6]}, B2 = {lm_result[7]}, B3 = {lm_result[8]},")


#lm_test()
