# Walkthrough

`sample_project/` is a tiny two-file Python project used to demo the CLI
end to end.

```
omni compress examples/sample_project
# [omni] compressing 2 file(s) with model 'andromeda' (2026) ...
# [omni] wrote sample_project.satish_andromeda

omni info sample_project.satish_andromeda
# SATISH format version : 1
# Model generation      : andromeda (2026)
# Root                  : sample_project
# Files                 : 2
#   - main.py
#   - utils/greetings.py
# ...

omni decompress sample_project.satish_andromeda --out restored
diff -r examples/sample_project restored   # identical
```

Without `--out`, it reconstructs into a directory named after the original
(`sample_project/`) instead.

A single loose file works the same way, without a wrapping directory:

```
omni compress examples/sample_project/main.py
# -> main.satish_andromeda

omni decompress main.satish_andromeda
# -> main.py   (in the current directory)
```

This all assumes a model generation is installed — see the main
[README](../README.md#install) if `omni models` comes back empty.
