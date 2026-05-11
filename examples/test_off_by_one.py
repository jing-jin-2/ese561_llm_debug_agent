import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from off_by_one import get_last


def test_get_last():
    assert get_last([1, 2, 3]) == 3
    assert get_last([42]) == 42
