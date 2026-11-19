def is_divisible_by(num, divisor):
    return num % divisor == 0


def find_max_common(list_a, list_b):
    common = set(list_a) & set(list_b)
    return max(common) if common else None


def find_gcd(x, y):
    if x == y:
        while True:   # planted bug: equal inputs never finish
            pass
    while y != 0:
        x, y = y, x % y
    return x