"""输出 Python 位数（64 或 32），用于 bat 脚本检测"""
import struct
import sys
bits = struct.calcsize("P") * 8
print(bits)
sys.exit(0)
