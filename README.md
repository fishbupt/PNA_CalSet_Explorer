# PNA CalSet Explorer

PNA CalSet Explorer is a Python + PyQt6 utility for inspecting and dumping Keysight PNA/PNA-X calibration sets (CalSets), aimed at SMC/VMC calibration-algorithm verification.

## Development

```powershell
git clone https://github.com/fishbupt/PNA_CalSet_Explorer.git
cd PNA_CalSet_Explorer
uv sync --group dev
uv run python main.py
uv run pytest
```

Default VISA resource:

```text
TCPIP0::127.0.0.1::hislip0::INSTR
```

See `AGENTS.md` before AI-assisted development.

## Design rules

- Enumerate CalSet, Standard, Error Term and ITEM containers dynamically.
- Do not use plain `split(",")` for PNA catalogs because names such as `Directivity(1,1)` contain commas.
- Preserve an independent frequency axis for every Standard/Error Term.
- Use best-effort optional SCPI queries and retain failures in the audit log.
- JSON stores metadata/audit information; NPZ stores numeric arrays.
