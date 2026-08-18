"""On-disk layout of the IP-to-network-class tables.

The refresher writes these files; the backend mmaps them. Both sides used to
declare MAGIC, FORMAT_VERSION, the struct formats and the class-code map
independently. They matched, but FORMAT_VERSION cannot catch a divergence:
reordering CLASS_TO_CODE in the writer alone yields a structurally valid file
in which every address is confidently misclassified. One module is the only
definition either side is allowed to have.
"""

from __future__ import annotations

import struct

MAGIC_V4 = b"MIRASNV4"
MAGIC_V6 = b"MIRASNV6"
FORMAT_VERSION = 1

# magic(8) + format version(2) + record count(4) + reserved(2)
HEADER_STRUCT = struct.Struct("!8sHIH")
HEADER_SIZE = HEADER_STRUCT.size

# start, end, class byte
V4_RECORD = struct.Struct("!IIB")
V6_RECORD = struct.Struct("!QQB")

# Wire codes for the class byte. Kept numeric so records stay fixed-width.
CLASS_CODES = {
    0: "unknown",
    1: "isp",
    2: "hosting",
    3: "vpn",
    4: "cellular",
}
CLASS_TO_CODE = {name: code for code, name in CLASS_CODES.items()}
