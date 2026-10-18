import math

# ============================================
# INPUT GEOMETRY
# ============================================

L1 = 0.183  # long segment
L2 = .063  # short segment

REPEATS = 11


# ============================================
# FUNCTION
# ============================================

def closure_error(r):
    theta1 = 2 * math.asin(L1 / (2 * r))
    theta2 = 2 * math.asin(L2 / (2 * r))

    total = REPEATS * (theta1 + theta2)

    return total - 2 * math.pi


# ============================================
# BINARY SEARCH SOLVER
# ============================================

def solve_radius():
    low = max(L1, L2) / 2 + 0.0001
    high = 10.0

    for _ in range(100):

        mid = (low + high) / 2

        error = closure_error(mid)

        if error > 0:
            low = mid
        else:
            high = mid

    return mid


# ============================================
# MAIN
# ============================================

r = solve_radius()

print(f"Solved sprocket pitch radius: {r:.6f}")

theta1 = math.degrees(
    2 * math.asin(L1 / (2 * r))
)

theta2 = math.degrees(
    2 * math.asin(L2 / (2 * r))
)

print(f"Long segment angle:  {theta1:.6f} deg")
print(f"Short segment angle: {theta2:.6f} deg")

print(f"Total closure: {11 * (theta1 + theta2):.6f} deg")
