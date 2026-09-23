from __future__ import annotations

from typing import Callable, Any
import numpy as np
import pyvisa

from .models import CalSetSnapshot, ComplexSeries, QueryRecord
from .scpi import quote_scpi, parse_csv_strings, interleaved_to_complex

LogFn = Callable[[str], None]


class PnaClient:
    def __init__(self, resource: str = "TCPIP0::127.0.0.1::hislip0::INSTR", timeout_ms: int = 15000):
        self.resource = resource
        self.timeout_ms = timeout_ms
        self.rm: pyvisa.ResourceManager | None = None
        self.inst = None
        self.idn: str | None = None

    @property
    def connected(self) -> bool:
        return self.inst is not None

    def connect(self) -> str:
        if self.connected:
            return self.idn or ""
        self.rm = pyvisa.ResourceManager()
        self.inst = self.rm.open_resource(self.resource)
        self.inst.timeout = self.timeout_ms
        self.inst.read_termination = "\n"
        self.inst.write_termination = "\n"
        self.idn = self.inst.query("*IDN?").strip()
        try:
            self.inst.write("FORM:DATA ASC")
        except Exception:
            pass
        return self.idn

    def disconnect(self) -> None:
        if self.inst is not None:
            try:
                self.inst.close()
            finally:
                self.inst = None
        if self.rm is not None:
            try:
                self.rm.close()
            finally:
                self.rm = None

    def query(self, command: str) -> str:
        if not self.inst:
            raise RuntimeError("PNA is not connected")
        return self.inst.query(command).strip()

    def query_ascii_values(self, command: str) -> list[float]:
        if not self.inst:
            raise RuntimeError("PNA is not connected")
        return list(self.inst.query_ascii_values(command))

    def clear_status(self) -> None:
        if self.inst:
            try:
                self.inst.write("*CLS")
            except Exception:
                pass

    def read_error(self) -> str:
        return self.query("SYST:ERR?")

    def get_calset_catalog_raw(self) -> str:
        return self.query("CSET:CAT?")

    def list_calsets(self) -> list[str]:
        return parse_csv_strings(self.get_calset_catalog_raw())


class PnaCalSetReader:
    def __init__(self, client: PnaClient, log: LogFn | None = None):
        self.client = client
        self.log = log or (lambda _: None)
        self.audit: list[QueryRecord] = []

    def _record_ok(self, command: str, response: Any) -> Any:
        self.audit.append(QueryRecord(command=command, ok=True, response=response))
        return response

    def _record_error(self, command: str, exc: Exception) -> None:
        self.audit.append(QueryRecord(command=command, ok=False, error=str(exc)))

    def _q(self, command: str, default: Any = None) -> Any:
        try:
            return self._record_ok(command, self.client.query(command))
        except Exception as exc:
            self._record_error(command, exc)
            return default

    def _qa(self, command: str) -> np.ndarray:
        try:
            values = self.client.query_ascii_values(command)
            self._record_ok(command, {"scalar_count": len(values)})
            return np.asarray(values, dtype=float)
        except Exception as exc:
            self._record_error(command, exc)
            return np.array([], dtype=float)

    def _complex(self, command: str) -> np.ndarray:
        values = self._qa(command)
        if values.size == 0:
            return np.array([], dtype=np.complex128)
        try:
            return interleaved_to_complex(values)
        except Exception as exc:
            self.audit.append(QueryRecord(command=command + " [decode]", ok=False, error=str(exc)))
            return np.array([], dtype=np.complex128)

    def _catalog(self, command: str) -> list[str]:
        return parse_csv_strings(self._q(command, ""))

    def read_standard(self, calset: str, name: str) -> ComplexSeries:
        cq, nq = quote_scpi(calset), quote_scpi(name)
        data = self._complex(f"CSET:STAN:DATA? {cq},{nq}")
        freq = self._qa(f"CSET:STAN:X:VAL? {cq},{nq}")
        series = ComplexSeries(name=name, raw_name=name, frequency_hz=freq, data=data)
        if freq.size and data.size and freq.size != data.size:
            series.read_errors.append(f"Frequency/data point mismatch: {freq.size} vs {data.size}")
        return series

    def read_error_term(self, calset: str, name: str) -> ComplexSeries:
        cq, nq = quote_scpi(calset), quote_scpi(name)
        data = self._complex(f"CSET:ETER:DATA? {cq},{nq}")
        freq = self._qa(f"CSET:ETER:X:VAL? {cq},{nq}")
        series = ComplexSeries(name=name, raw_name=name, frequency_hz=freq, data=data)
        if freq.size and data.size and freq.size != data.size:
            series.read_errors.append(f"Frequency/data point mismatch: {freq.size} vs {data.size}")
        return series

    def _read_common_properties(self, calset: str) -> dict[str, Any]:
        c = quote_scpi(calset)
        p: dict[str, Any] = {}
        p["property_catalog_raw"] = self._q(f"CSET:PROP:CAT? {c}")
        p["property_catalog"] = parse_csv_strings(p["property_catalog_raw"] or "")

        scalar_queries = {
            "points": f"CSET:PROP:POIN? {c}",
            "security_level": f"CSET:PROP:SEC:LEV? {c}",
            "sweep_mode": f"CSET:PROP:SWE:MODE? {c}",
            "sweep_type": f"CSET:PROP:SWE:TYPE? {c}",
            "port_list": f"CSET:PROP:PORT:CAT? {c}",
            "port_power_dbm": f"CSET:PROP:PORT:POW? {c}",
            "port_attenuation_db": f"CSET:PROP:PORT:ATT? {c}",
            "port_gain": f"CSET:PROP:PORT:GAIN? {c}",
            "if_bandwidth_hz": f"CSET:FREQ:BWID? {c}",
            "date": f"CSET:DATE? {c}",
            "time": f"CSET:TIME? {c}",
            "validate": f"CSET:VAL? {c}",
        }
        for key, cmd in scalar_queries.items():
            p[key] = self._q(cmd)

        for qualifier in ("STAR", "STOP", "MIN", "MAX"):
            p[f"swept_{qualifier.lower()}_hz"] = self._q(f"CSET:FREQ:SWEPT? {c},{qualifier}")

        p["segment_start_hz"] = self._q(f"CSET:FREQ:SEGM? {c},STAR")
        p["segment_stop_hz"] = self._q(f"CSET:FREQ:SEGM? {c},STOP")

        for path in ("INP", "OUTP", "LO1", "LO2"):
            for qualifier in ("STAR", "STOP", "MIN", "MAX"):
                p[f"converter_{path.lower()}_{qualifier.lower()}_hz"] = self._q(
                    f"CSET:FREQ:CONV? {c},{path},{qualifier}"
                )

        p["leakage_catalog_raw"] = self._q(f"CSET:ETER:LEAK:CAT? {c}")
        p["leakage_catalog"] = parse_csv_strings(p["leakage_catalog_raw"] or "")
        p["delay_pairs_raw"] = self._q(f"CSET:PROP:DEL:PAIR? {c}")
        p["path_config_catalog_raw"] = self._q(f"CSET:PROP:PATH:CONF:CAT? {c}")
        return p

    def _read_items(self, calset: str) -> dict[str, Any]:
        c = quote_scpi(calset)
        names = self._catalog(f"CSET:ITEM:CAT? {c}")
        result: dict[str, Any] = {}
        for name in names:
            result[name] = self._q(f"CSET:ITEM:DATA? {c},{quote_scpi(name)}")
        return result

    def read_snapshot(self, calset: str, include_series_data: bool = True, progress=None) -> CalSetSnapshot:
        self.audit = []
        c = quote_scpi(calset)
        snap = CalSetSnapshot(name=calset)
        self.log(f"Reading CalSet: {calset}")
        snap.info["name"] = calset
        snap.info["instrument_idn"] = self.client.idn
        snap.info["exists"] = self._q(f"CSET:EXIS? {c}")
        snap.properties = self._read_common_properties(calset)
        snap.items = self._read_items(calset)

        standard_names = self._catalog(f"CSET:STAN:CAT? {c}")
        error_term_names = self._catalog(f"CSET:ETER:CAT? {c}")
        snap.info["standard_names"] = standard_names
        snap.info["error_term_names"] = error_term_names
        snap.info["standard_count"] = len(standard_names)
        snap.info["error_term_count"] = len(error_term_names)

        if include_series_data:
            total = len(standard_names) + len(error_term_names)
            done = 0
            for name in standard_names:
                if progress:
                    progress(f"Standard: {name}", done, total)
                snap.standards.append(self.read_standard(calset, name))
                done += 1
            for name in error_term_names:
                if progress:
                    progress(f"Error Term: {name}", done, total)
                snap.error_terms.append(self.read_error_term(calset, name))
                done += 1
            if progress:
                progress("Done", total, total)

        snap.audit = list(self.audit)
        return snap
