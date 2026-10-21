import sys, pefile
path = sys.argv[1]
pe = pefile.PE(path, fast_load=True)
pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXPORT']])
names = []
if hasattr(pe, "DIRECTORY_ENTRY_EXPORT"):
    for exp in pe.DIRECTORY_ENTRY_EXPORT.symbols:
        if exp.name:
            names.append(exp.name.decode(errors="replace"))
print(f"# {path}")
print(f"# {len(names)} exports")
for n in sorted(names):
    print(n)
