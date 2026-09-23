from __future__ import annotations

from contextlib import contextmanager
from typing import Callable, Any

import numpy as np
import pyvisa

from .models import CalSetSnapshot, ComplexSeries, QueryRecord
from .scpi import quote_scpi, parse_csv_strings, interleaved_to_complex


LogFn = Callable[[str], None]


class PnaClient:
    """PNA/PNA-X 的轻量 PyVISA 客户端。"""

    def __init__(
        self,
        resource: str = "TCPIP0::127.0.0.1::hislip0::INSTR",
        timeout_ms: int = 15000,
    ):
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

        # CalSet DATA/X:VAL 在 ASCII 模式下可直接用 query_ascii_values 读取。
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
        return list(
            self.inst.query_ascii_values(
                command,
                separator=",",
                container=list,
            )
        )

    @contextmanager
    def temporary_timeout(self, timeout_ms: int):
        """为 Optional SCPI 临时缩短 VISA Timeout，避免不支持命令卡住 GUI。"""
        if not self.inst:
            raise RuntimeError("PNA is not connected")

        old_timeout = self.inst.timeout
        self.inst.timeout = timeout_ms
        try:
            yield
        finally:
            self.inst.timeout = old_timeout

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
    """
    读取一个完整 CalSet。

    读取顺序非常重要：
    1. 先读取 Standard/Error Term Catalog；
    2. 立即读取核心 DATA + X-axis；
    3. 再读取 ITEM；
    4. 最后读取各种 Optional Property。

    这样即使某个型号/固件不支持某个 Optional SCPI，也不会阻塞真正重要的
    Standard / Error Term 数据读取。
    """

    OPTIONAL_TIMEOUT_MS = 1800

    def __init__(self, client: PnaClient, log: LogFn | None = None):
        self.client = client
        self.log = log or (lambda _: None)
        self.audit: list[QueryRecord] = []

    def _record_ok(self, command: str, response: Any) -> Any:
        self.audit.append(
            QueryRecord(command=command, ok=True, response=response)
        )
        return response

    def _record_error(self, command: str, exc: Exception) -> None:
        self.audit.append(
            QueryRecord(command=command, ok=False, error=str(exc))
        )

    def _q(self, command: str, default: Any = None) -> Any:
        """核心查询：使用正常 VISA Timeout。"""
        try:
            response = self.client.query(command)
            return self._record_ok(command, response)
        except Exception as exc:
            self._record_error(command, exc)
            self.log(f"SCPI 读取失败：{command} -> {exc}")
            return default

    def _q_optional(self, command: str, default: Any = None) -> Any:
        """可选查询：短 Timeout + 失败可审计，不影响核心数据。"""
        try:
            with self.client.temporary_timeout(self.OPTIONAL_TIMEOUT_MS):
                response = self.client.query(command)
            return self._record_ok(command, response)
        except Exception as exc:
            self._record_error(command, exc)
            return default

    def _qa(self, command: str) -> np.ndarray:
        try:
            values = self.client.query_ascii_values(command)
            self._record_ok(
                command,
                {
                    "scalar_count": len(values),
                    "preview": values[:8],
                },
            )
            return np.asarray(values, dtype=np.float64)
        except Exception as exc:
            self._record_error(command, exc)
            self.log(f"数值 Block 读取失败：{command} -> {exc}")
            return np.array([], dtype=np.float64)

    def _complex(self, command: str) -> np.ndarray:
        values = self._qa(command)

        if values.size == 0:
            return np.array([], dtype=np.complex128)

        try:
            return interleaved_to_complex(values)
        except Exception as exc:
            self.audit.append(
                QueryRecord(
                    command=command + " [decode]",
                    ok=False,
                    error=str(exc),
                )
            )
            self.log(f"复数数据解码失败：{command} -> {exc}")
            return np.array([], dtype=np.complex128)

    def _catalog(
        self,
        command: str,
        optional: bool = False,
    ) -> list[str]:
        raw = (
            self._q_optional(command, "")
            if optional
            else self._q(command, "")
        )
        names = parse_csv_strings(raw)

        self.log(
            f"{command} -> {len(names)} 项"
            + (f"：{names}" if names else "")
        )
        return names

    def read_standard(
        self,
        calset: str,
        name: str,
    ) -> ComplexSeries:
        cq = quote_scpi(calset)
        nq = quote_scpi(name)

        data_cmd = f"CSET:STAN:DATA? {cq},{nq}"
        x_cmd = f"CSET:STAN:X:VAL? {cq},{nq}"

        data = self._complex(data_cmd)
        freq = self._qa(x_cmd)

        series = ComplexSeries(
            name=name,
            raw_name=name,
            frequency_hz=freq,
            data=data,
        )

        if freq.size and data.size and freq.size != data.size:
            series.read_errors.append(
                f"Frequency/data point mismatch: "
                f"{freq.size} vs {data.size}"
            )

        if data.size:
            self.log(
                f"Standard 读取成功：{name}，"
                f"{data.size} 个复数点，{freq.size} 个频率点"
            )
        else:
            self.log(f"Standard 无数据或读取失败：{name}")

        return series

    def read_error_term(
        self,
        calset: str,
        name: str,
    ) -> ComplexSeries:
        cq = quote_scpi(calset)
        nq = quote_scpi(name)

        data_cmd = f"CSET:ETER:DATA? {cq},{nq}"
        x_cmd = f"CSET:ETER:X:VAL? {cq},{nq}"

        data = self._complex(data_cmd)
        freq = self._qa(x_cmd)

        series = ComplexSeries(
            name=name,
            raw_name=name,
            frequency_hz=freq,
            data=data,
        )

        if freq.size and data.size and freq.size != data.size:
            series.read_errors.append(
                f"Frequency/data point mismatch: "
                f"{freq.size} vs {data.size}"
            )

        if data.size:
            self.log(
                f"Error Term 读取成功：{name}，"
                f"{data.size} 个复数点，{freq.size} 个频率点"
            )
        else:
            self.log(f"Error Term 无数据或读取失败：{name}")

        return series

    def _read_items(self, calset: str) -> dict[str, Any]:
        c = quote_scpi(calset)
        names = self._catalog(
            f"CSET:ITEM:CAT? {c}",
            optional=True,
        )

        result: dict[str, Any] = {}
        for name in names:
            result[name] = self._q_optional(
                f"CSET:ITEM:DATA? {c},{quote_scpi(name)}"
            )
        return result

    def _read_common_properties(
        self,
        calset: str,
    ) -> dict[str, Any]:
        """
        只发送 Keysight 当前 CSET 文档中参数完整的查询。
        所有 Property 都属于辅助信息，不允许阻塞核心 DATA 读取。
        """
        c = quote_scpi(calset)
        p: dict[str, Any] = {}

        p["property_catalog_raw"] = self._q_optional(
            f"CSET:PROP:CAT? {c}"
        )
        p["property_catalog"] = parse_csv_strings(
            p["property_catalog_raw"] or ""
        )

        scalar_queries = {
            "points": f"CSET:PROP:POIN? {c}",
            "security_level": f"CSET:PROP:SEC:LEV? {c}",
            "sweep_mode": f"CSET:PROP:SWE:MODE? {c}",
            "sweep_type": f"CSET:PROP:SWE:TYPE? {c}",
            "port_list": f"CSET:PROP:PORT:CAT? {c}",
            "port_power_dbm": f"CSET:PROP:PORT:POW? {c}",
            "port_gain": f"CSET:PROP:PORT:GAIN? {c}",
            "source_attenuation_db": (
                f"CSET:PROP:PORT:ATTEN? {c},SOUR"
            ),
            "receiver_attenuation_db": (
                f"CSET:PROP:PORT:ATTEN? {c},REC"
            ),
            "if_bandwidth_hz": f"CSET:FREQ:BWID? {c}",
            "date": f"CSET:DATE? {c}",
            "time": f"CSET:TIME? {c}",
            "delay_pairs": f"CSET:PROP:DEL:PAIR? {c}",
            "path_config_catalog": (
                f"CSET:PROP:PATH:CONF:CAT? {c}"
            ),
        }

        for key, cmd in scalar_queries.items():
            p[key] = self._q_optional(cmd)

        # Swept Frequency 支持 START/STOP/MIN/MAX。
        for qualifier in ("STAR", "STOP", "MIN", "MAX"):
            p[f"swept_{qualifier.lower()}_hz"] = (
                self._q_optional(
                    f"CSET:FREQ:SWEPT? {c},{qualifier}"
                )
            )

        # Segment 返回的是频率列表。
        p["segment_start_hz"] = self._q_optional(
            f"CSET:FREQ:SEGM? {c},STAR"
        )
        p["segment_stop_hz"] = self._q_optional(
            f"CSET:FREQ:SEGM? {c},STOP"
        )

        # Converter/Mixer 文档只定义 START/STOP，不发送 MIN/MAX。
        for path in ("INP", "OUTP", "LO1", "LO2"):
            for qualifier in ("STAR", "STOP"):
                key = (
                    f"converter_{path.lower()}_"
                    f"{qualifier.lower()}_hz"
                )
                p[key] = self._q_optional(
                    f"CSET:FREQ:CONV? {c},{path},{qualifier}"
                )

        p["leakage_catalog_raw"] = self._q_optional(
            f"CSET:ETER:LEAK:CAT? {c}"
        )
        p["leakage_catalog"] = parse_csv_strings(
            p["leakage_catalog_raw"] or ""
        )

        # 如果存在 Delay Port Pair，则继续读取每一对的 Delay。
        delays: dict[str, Any] = {}
        for pair in parse_csv_strings(p.get("delay_pairs") or ""):
            delays[pair] = self._q_optional(
                f"CSET:PROP:DEL:STAT? "
                f"{c},{quote_scpi(pair)}"
            )
        p["adapter_delays"] = delays

        return p

    def read_snapshot(
        self,
        calset: str,
        include_series_data: bool = True,
        progress=None,
    ) -> CalSetSnapshot:
        self.audit = []

        c = quote_scpi(calset)
        snap = CalSetSnapshot(name=calset)

        self.log(f"开始读取 CalSet：{calset}")

        snap.info["name"] = calset
        snap.info["instrument_idn"] = self.client.idn
        snap.info["exists"] = self._q(
            f"CSET:EXIS? {c}"
        )

        # -----------------------------------------------------------
        # 第一优先级：真正的 Calibration 内容。
        # -----------------------------------------------------------
        standard_names = self._catalog(
            f"CSET:STAN:CAT? {c}"
        )
        error_term_names = self._catalog(
            f"CSET:ETER:CAT? {c}"
        )

        snap.info["standard_names"] = standard_names
        snap.info["error_term_names"] = error_term_names
        snap.info["standard_count"] = len(standard_names)
        snap.info["error_term_count"] = len(error_term_names)

        if include_series_data:
            total = len(standard_names) + len(error_term_names)
            done = 0

            for name in standard_names:
                if progress:
                    progress(
                        f"读取 Standard：{name}",
                        done,
                        total,
                    )

                snap.standards.append(
                    self.read_standard(calset, name)
                )
                done += 1

            for name in error_term_names:
                if progress:
                    progress(
                        f"读取 Error Term：{name}",
                        done,
                        total,
                    )

                snap.error_terms.append(
                    self.read_error_term(calset, name)
                )
                done += 1

            if progress:
                progress("核心校准数据读取完成", total, total)

        # -----------------------------------------------------------
        # 第二优先级：辅助 ITEM / Property。
        # 即使失败，也不影响上面的核心数据。
        # -----------------------------------------------------------
        snap.items = self._read_items(calset)
        snap.properties = self._read_common_properties(calset)

        snap.audit = list(self.audit)

        failed_count = sum(1 for item in self.audit if not item.ok)
        self.log(
            f"CalSet 读取完成：{calset}；"
            f"Standards={len(snap.standards)}，"
            f"ErrorTerms={len(snap.error_terms)}，"
            f"Optional/Query Failures={failed_count}"
        )

        return snap
