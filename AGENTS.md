# AGENTS.md

## Project purpose

PNA CalSet Explorer is an engineering desktop tool for inspecting and dumping Keysight PNA/PNA-X calibration-set data. Its primary use is verification of VNA mixer-calibration algorithms, especially SMC and VMC.

## Technology stack

- Python 3.10+
- PyQt6
- PyVISA
- NumPy
- pyqtgraph
- JSON + NPZ
- pytest
- uv is the only supported dependency/environment workflow

Do not add requirements.txt, Poetry, Pipenv or Conda environment files unless explicitly requested.

## Standard commands

```powershell
uv sync --group dev
uv run python main.py
uv run pytest
```

When dependencies change, edit `pyproject.toml`, run `uv sync --group dev`, and commit `uv.lock`.

## Instrument connection

Default local PNA VISA resource:

```text
TCPIP0::127.0.0.1::hislip0::INSTR
```

Do not change it back to `TCPIP::127.0.0.1::INSTR`; that abbreviated form failed in the target PNA environment.

## Keysight SCPI rules

### Never hard-code catalog contents

CalSet, Standard, Error Term, ITEM and property names must be discovered dynamically whenever catalog queries are available.

Typical queries include:

```text
CSET:CAT?
CSET:STAN:CAT?
CSET:ETER:CAT?
CSET:ITEM:CAT?
CSET:PROP:CAT?
```

### Never use plain comma splitting

A complete catalog may be:

```text
"CalSet_2_port,CH1_CALREG,smc_power_cal"
```

while item names may contain commas:

```text
Directivity(1,1)
SA_0(1,1)
TransmissionTracking(2,1)
```

Use `parse_pna_catalog()` and add regression tests for newly observed response forms.

### Preserve independent x-axes

Every Standard and Error Term may have its own frequency axis. This is especially important for SMC/VMC RF/IF mapping. Never replace per-entry axes with one channel frequency vector without proof.

### Best-effort querying is required

Different PNA models/firmware expose different optional CalSet properties. Unsupported optional queries must be captured in `QueryRecord`, retained in `raw_scpi.json`, and must not abort the overall dump.

Never fabricate fallback values that look like successful instrument data.

### Do not invent undocumented SCPI behavior

For unknown Keysight commands, consult current documentation or real instrument output. Preserve raw responses and clearly distinguish unit-tested code from real-hardware validation.

## Data model

`ComplexSeries` stores:
- original PNA name;
- `frequency_hz` as floating-point Hz;
- complex data, normally `complex128`;
- read/decoding errors.

Magnitude, dB and phase are display views and must not replace source complex data.

## Dump compatibility

The dump schema is intended to become a long-lived golden-data interface:

```text
<CalSetName>/
├── calset_info.json
├── raw_scpi.json
├── standards/
│   ├── index.json
│   └── standards.npz
└── error_terms/
    ├── index.json
    └── error_terms.npz
```

Preserve exact PNA names in JSON, all numeric points in NPZ, explicit units in keys, and raw SCPI audit records. For incompatible schema changes, bump `schema_version`.

## Architecture

- `reader.py`: VISA/PNA acquisition
- `scpi.py`: SCPI quoting and parsing
- `models.py`: data structures
- `dump_service.py`: dump schema and serialization
- `workers.py`: Qt background workers
- `main_window.py`: presentation/UI only

Long instrument operations must not block the Qt UI thread.

## Testing

Normal `uv run pytest` must not require a PNA.

Preserve regression tests for:
- quoted CalSet catalog;
- unquoted CalSet catalog;
- names containing commas inside parentheses;
- interleaved real/imaginary complex decoding.

When fixing a real-PNA parsing bug, add a regression test reproducing the exact response shape when possible.

## Near-term direction

Deeper SMC/VMC CalSet analysis:
- categorize SMC/VMC Standard acquisition containers;
- identify conversion/power-calibration intermediate data;
- map Error Terms to physical calibration meaning;
- compare PNA golden data with independent calibration solvers.
