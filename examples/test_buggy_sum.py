import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from buggy_sum import sum_to_n


def test_sum_to_3():
    assert sum_to_n(3) == 6


def test_sum_to_5():
    assert sum_to_n(5) == 15


def test_sum_to_10():
    assert sum_to_n(10) == 55
