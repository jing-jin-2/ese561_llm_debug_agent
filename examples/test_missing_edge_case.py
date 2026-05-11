import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from missing_edge_case import safe_divide


def test_safe_divide():
    assert safe_divide(10, 2) == 5.0
    assert safe_divide(0, 5) == 0.0
    assert safe_divide(9, 0) is None
