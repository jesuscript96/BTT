import re

content = open('backend/app/services/indicators.py', encoding='utf-8').read()

print("ds.get(...) occurrences:")
print(set(re.findall(r'ds\.get\(\"([^\"]+)\"', content)))
print(set(re.findall(r"ds\.get\('([^']+)'", content)))

print("\nds[...] occurrences:")
print(set(re.findall(r'ds\[\"([^\"]+)\"\]', content)))
print(set(re.findall(r"ds\['([^']+)'\]", content)))

print("\ndaily_stats.get(...) occurrences:")
print(set(re.findall(r'daily_stats\.get\(\"([^\"]+)\"', content)))
print(set(re.findall(r"daily_stats\.get\('([^']+)'", content)))
