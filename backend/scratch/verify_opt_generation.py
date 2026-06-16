import numpy as np

def generate_values(v_min, v_max, steps, is_int):
    if is_int:
        v_min_int = int(round(v_min))
        v_max_int = int(round(v_max))
        if v_min_int == v_max_int:
            values = [v_min_int]
        elif steps > 0:
            raw_vals = np.linspace(v_min_int, v_max_int, steps)
            values = sorted(list(set(int(round(x)) for x in raw_vals)))
        else:
            values = [v_min_int]
    else:
        values = np.linspace(v_min, v_max, steps).tolist()
    return values

# Test different ranges
print("Range [1, 5] with 5 steps:", generate_values(1, 5, 5, True))
print("Range [1, 5] with 10 steps:", generate_values(1, 5, 10, True))
print("Range [2, 22] with 10 steps:", generate_values(2, 22, 10, True))
print("Range [2, 22] with 5 steps:", generate_values(2, 22, 5, True))
print("Range [1, 1] with 5 steps:", generate_values(1, 1, 5, True))
