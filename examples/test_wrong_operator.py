import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from wrong_operator import add


def test_add():
    assert add(2, 3) == 5
    assert add(0, 0) == 0
