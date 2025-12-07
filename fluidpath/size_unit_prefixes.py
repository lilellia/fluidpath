from typing import Literal

DecimalSizePrefix = Literal["B", "K", "M", "G", "T", "P", "E", "Z", "Y", "R", "Q"]
BinarySizePrefix = Literal["B", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi", "Yi", "Ri", "Qi"]


SIZE_PREFIX_CONVERSIONS = {
    "B": 1,
    "KB": 1e3,
    "MB": 1e6,
    "GB": 1e9,
    "TB": 1e12,
    "PB": 1e15,
    "EB": 1e18,
    "ZB": 1e21,
    "YB": 1e24,
    "RB": 1e27,
    "QB": 1e30,
    "KiB": 1 << 10,
    "MiB": 1 << 20,
    "GiB": 1 << 30,
    "TiB": 1 << 40,
    "PiB": 1 << 50,
    "EiB": 1 << 60,
    "ZiB": 1 << 70,
    "YiB": 1 << 80,
    "RiB": 1 << 90,
    "QiB": 1 << 100,
}
