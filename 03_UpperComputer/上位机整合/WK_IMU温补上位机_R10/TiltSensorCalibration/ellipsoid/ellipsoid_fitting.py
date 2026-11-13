"""
    最小二乘的椭球拟合
    ((x-x0)/A)^2 + ((y-y0)/B)^2 + ((z-z0)/C)^2 = 1 的空间任意椭球方程式
    x^2 + a*y^2 + b*z^2 + c*x + d*y + e*z + f = 0  简化后的方程
    问题转换为由a,b,c,d,e,f,来求解x0，y0，z0 以及 A,B,C
    说明：改写自“椭球算法_知乎源代码”
"""

import numpy as np

DEBUG = False # 开启和关闭是否显示矩阵值

MATRIX_SIZE = 6
# 系数矩阵
m_matrix = np.zeros((MATRIX_SIZE, MATRIX_SIZE + 1))
# 方程组的解对应最小二乘椭球拟合中的，a，b，c，d，e，f
solve = np.zeros(MATRIX_SIZE)
# 计算累计采点数量
N = 0


def reset_matrix():
    """把系数矩阵全部清除为0"""
    global m_matrix
    m_matrix = np.zeros((MATRIX_SIZE, MATRIX_SIZE + 1))


def calc_data_input(x, y, z):
    """把输入的数据先生成矩阵的元素的总和"""
    global N, m_matrix  # Declare N and m_matrix as global if they're defined outside the function

    V = np.zeros(MATRIX_SIZE + 1)
    N += 1
    V[0] = y * y
    V[1] = z * z
    V[2] = x
    V[3] = y
    V[4] = z
    V[5] = 1.0
    V[6] = -x * x

    # 构建系数矩阵，并进行累加
    for row in range(MATRIX_SIZE):
        for column in range(MATRIX_SIZE + 1):
            m_matrix[row][column] += V[row] * V[column]


def calc_data_input_average():
    """化简系数矩阵，把除以N带上"""
    global m_matrix, N
    m_matrix /= N


def disp_matrix():
    """显示出来系数矩阵和增广矩阵[A|b]"""
    global m_matrix
    for row in range(MATRIX_SIZE):
        for column in range(MATRIX_SIZE + 1):
            print(f"{m_matrix[row][column]:23f}", end=" ")  # Format to match your C printf
            if column == MATRIX_SIZE - 1:
                print("|", end="")
        print("")  # For newline
    print("\n")


def move_biggest_element_to_top(k):
    """
        列主元，第k次消元之前，把k行到MATRIX_SIZE的所有行进行冒泡排出最大，排序的依据是k列的元素的大小
    """
    global m_matrix
    max_row = np.argmax(np.abs(m_matrix[k:, k]))
    max_row += k
    m_matrix[[k, max_row]] = m_matrix[[max_row, k]]


def row2_add_k_row1(k, row1, row2):
    """用一个数乘以row1行加到row2行上去"""
    m_matrix[row2] += k * m_matrix[row1]


def matrix_gauss_elimination():
    """高斯消元法，求行阶梯型矩阵"""
    # 进行第k次的运算，主要是针对k行以下的行数把k列的元素都变成0
    for cnt in range(MATRIX_SIZE):
        # 把k行依据k列的元素大小，进行排序
        move_biggest_element_to_top(cnt)

        # 返回值表示错误
        if m_matrix[cnt][cnt] == 0:
            return 1

        # 把k行下面的行元素全部消成0，整行变化
        for row in range(cnt + 1, MATRIX_SIZE):
            k = -m_matrix[row][cnt] / m_matrix[cnt][cnt]
            row2_add_k_row1(k, cnt, row)

        # Assuming you still want to display the matrix at each step
        if DEBUG:
            disp_matrix()

    return 0


def matrix_row_simplify():
    """求行最简型矩阵，即把对角线的元素全部化成1"""
    global m_matrix
    k = 0.0
    for row in range(MATRIX_SIZE):
        k = 1 / m_matrix[row, row]
        m_matrix[row] *= k
    if DEBUG:
        disp_matrix()


def matrix_solve():
    """求非齐次线性方程组的解"""
    global m_matrix, solve
    for row in range(MATRIX_SIZE-1, -1, -1):
        solve[row] = m_matrix[row, MATRIX_SIZE]
        for column in range(MATRIX_SIZE-1, row, -1):
            solve[row] -= m_matrix[row][column] * solve[column]
    if DEBUG:
        print("  a = %f| b = %f| c = %f| d = %f| e = %f| f = %f " %(solve[0], solve[1], solve[2], solve[3], solve[4], solve[5]));
        print("");


def ellipsoid_fitting(array):
    """
    椭球拟合

    Args:
        array (ndarray): 各位置的三轴加速度数据

    Returns:
        ndarray: 椭球拟合成功，返回一个一维数组，数组存放X0, Y0, Z0, A, B, C。椭球拟合失败，返回None。

    Raises:

    Note:

    """
    # 检查输入的数组是否合规
    row_num, col_num = array.shape
    if (row_num < 6) or (col_num != 3):
        return None
    try:
        # 把系数矩阵全部清除为0
        reset_matrix()

        # 输入任意个点加速度参数，尽量在球面上均匀分布
        for i in range(row_num):
            calc_data_input(array[i][0], array[i][1], array[i][2]);

        # 对输入的数据到矩阵元素进行归一化
        calc_data_input_average()

        # 显示原始的增广矩阵
        if DEBUG:
            disp_matrix()

        # 求得行阶梯形矩阵
        if matrix_gauss_elimination() != 0:
            return None
        else:
            matrix_row_simplify() # 化行最简形态
            matrix_solve()        # 求解a,b,c,d,e,f
            a, b, c, d, e, f = solve
            X0 = -c / 2
            Y0 = -d / (2 * a)
            Z0 = -e / (2 * b)
            A = np.sqrt(X0 * X0 + a * Y0 * Y0 + b * Z0 * Z0 - f)
            B = A / np.sqrt(a)
            C = A / np.sqrt(b)

            result = np.zeros((1, 6))
            result = [X0, Y0, Z0, A, B, C]
            return result
    except:
        return None


def gxyz_to_gxyz_new_of_ellipsoid(gx, gy, gz, x0, y0, z0, a, b, c):
    """
    通过椭球拟合结果，把原始加速度值转化成新加速度值

    Args:
        gx (float): 原始x轴加速度值
        gy (float): 原始y轴加速度值
        gz (float): 原始z轴加速度值
        x0 (float): 椭球拟合结果X0
        y0 (float): 椭球拟合结果Y0
        z0 (float): 椭球拟合结果Z0
        a (float): 椭球拟合结果A
        b (float): 椭球拟合结果B
        c (float): 椭球拟合结果C

    Returns:
        list: x轴、y轴、z轴新加速度值

    """
    gx_new = (gx - x0) / a
    gy_new = (gy - y0) / b
    gz_new = (gz - z0) / c

    gxyz_new = [gx_new, gy_new, gz_new]

    return gxyz_new


def ellipsoid_fitting_test():
    """椭球拟合测试函数"""
    # 这里输入任意个点加速度参数，尽量在球面上均匀分布
    n = 10
    ndarray = np.zeros((n, 3))
    ndarray[0] = [87, -52, -4454]
    ndarray[1] = [301, -45, 3859]
    ndarray[2] = [274, 4088, -303]
    ndarray[3] = [312, -4109, -305]
    ndarray[4] = [-3805, -24, -390]
    ndarray[5] = [4389, 6, -228]
    ndarray[6] = [261, 2106, -3848]
    ndarray[7] = [327, -2047, -3880]
    ndarray[8] = [-1963, -13, -3797]
    ndarray[9] = [3024, 18, -3449]

    result = ellipsoid_fitting(ndarray)
    if result == None:
        print("椭球拟合失败！")
        return
    print("((x - x0) / A)^2 + ((y - y0) / B)^2 + ((z - z0) / C)^2 = 1 Ellipsoid result as below:")
    print(f"X0 = {result[0]}, Y0 = {result[1]}, Z0 = {result[2]}, A = {result[3]}, B = {result[4]}, C = {result[5]}")


#ellipsoid_fitting_test()
