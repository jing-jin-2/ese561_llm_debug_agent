def sum_to_n(n):
    """Return the sum 1 + 2 + ... + n."""
    total = 0
    for i in range(n):  # BUG: should be range(n + 1)
        total += i
    return total
