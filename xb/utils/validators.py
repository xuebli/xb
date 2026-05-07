"""项目名称验证器"""

import re


def validate_package_name(name: str) -> bool:
    pattern = r"^[a-z][a-z0-9_]*$"
    return bool(re.match(pattern, name))
