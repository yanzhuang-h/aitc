"""训练、实时需求和阶段适配共用的相位语义；元组顺序不表示阶段顺序。"""

PHASE_DIRECTION_MAP = {
    "UD": ("U", "D"),
    "DU": ("U", "D"),
    "UD1": ("U", "D"),
    "UD2": ("U", "D"),
    "LR": ("L", "R"),
    "RL": ("L", "R"),
    "LR1": ("L", "R"),
    "LR2": ("L", "R"),
    "UDL": ("UTL", "DTL"),
    "DUL": ("UTL", "DTL"),
    "LRL": ("LTL", "RTL"),
    "U": ("U", "UTL"),
    "D": ("D", "DTL"),
    "L": ("L", "LTL"),
    "R": ("R", "RTL"),
    "LTD": ("LTL", "D"),
    "P": (),
}
