import json
with open('/tmp/btt_data.json', 'r') as f:
    data = json.load(f)

# check if sorted
times = [d['time'] for d in data]
is_sorted = all(times[i] <= times[i+1] for i in range(len(times)-1))
is_unique = len(times) == len(set(times))

print("Length:", len(times))
print("Is Sorted:", is_sorted)
print("Is Unique:", is_unique)

if not is_unique:
    seen = set()
    for t in times:
        if t in seen:
            print("Duplicate:", t)
            break
        seen.add(t)

if not is_sorted:
    for i in range(1, len(times)):
        if times[i] < times[i-1]:
            print("Not sorted:", times[i-1], "->", times[i])
            break
