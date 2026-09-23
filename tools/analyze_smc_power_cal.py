from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np


NAMES = [
    "Power Meter Readings_Input(1)",
    "Power Meter Readings_Output(1)",
    "Power Sensor Match_Input(1)",
    "Power Sensor Match_Output(1)",
    "PowerSensorMatch(1)",
    "PowerSensorMatch(2)",
    "RawPowerSensorMatch(1)",
    "RawPowerSensorMatch(2)",
    "RawResponseTracking(R1)",
    "RawResponseTracking(R2)",
    "RawSourcePowerCorrection(1)",
    "RawSourcePowerCorrection(2)",
    "ReceiverReading(R1)",
    "ReceiverReading(R2)",
    "TotalSourcePowerCorrection(1)",
    "TotalSourcePowerCorrection(2)",
]


@dataclass
class Series:
    name: str
    freq_hz: np.ndarray
    data: np.ndarray


def load_standards(calset_dir: Path) -> dict[str, Series]:
    index_path = calset_dir / "standards" / "index.json"
    npz_path = calset_dir / "standards" / "standards.npz"

    if not index_path.exists():
        raise FileNotFoundError(f"找不到 {index_path}")
    if not npz_path.exists():
        raise FileNotFoundError(f"找不到 {npz_path}")

    index = json.loads(index_path.read_text(encoding="utf-8"))
    npz = np.load(npz_path)

    result: dict[str, Series] = {}
    for _, meta in index.items():
        name = meta["name"]
        freq = np.asarray(npz[meta["frequency_key"]], dtype=float)
        data = np.asarray(npz[meta["data_key"]], dtype=np.complex128)
        result[name] = Series(name=name, freq_hz=freq, data=data)
    return result


def finite_complex(z: np.ndarray) -> np.ndarray:
    z = np.asarray(z, dtype=np.complex128)
    return z[np.isfinite(z.real) & np.isfinite(z.imag)]


def scalar_stats(x: np.ndarray) -> str:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if x.size == 0:
        return "无有效数据"
    return (
        f"n={x.size}, min={np.min(x):.9g}, max={np.max(x):.9g}, "
        f"mean={np.mean(x):.9g}, std={np.std(x):.9g}"
    )


def complex_summary(series: Series) -> list[str]:
    z = finite_complex(series.data)
    lines = [f"[{series.name}]"]
    lines.append(f"  点数: data={series.data.size}, freq={series.freq_hz.size}")
    if series.freq_hz.size:
        lines.append(
            f"  频率: {series.freq_hz[0]:.12g} -> {series.freq_hz[-1]:.12g} Hz"
        )
    if z.size:
        imag_max = float(np.max(np.abs(z.imag)))
        real_max = float(np.max(np.abs(z.real))) if z.size else 0.0
        ratio = imag_max / max(real_max, 1e-300)
        lines.append(f"  Real: {scalar_stats(z.real)}")
        lines.append(f"  Imag: {scalar_stats(z.imag)}")
        lines.append(f"  max|Imag|/max|Real| = {ratio:.6g}")
        lines.append(f"  |Z|:  {scalar_stats(np.abs(z))}")
        lines.append(
            "  前5点: "
            + ", ".join(f"{v.real:.9g}{v.imag:+.9g}j" for v in z[:5])
        )
    else:
        lines.append("  无有效复数数据")
    return lines


def normalize_axis(freq: np.ndarray, data: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    freq = np.asarray(freq, dtype=float)
    data = np.asarray(data)
    n = min(freq.size, data.size)
    freq = freq[:n]
    data = data[:n]
    mask = np.isfinite(freq)
    freq = freq[mask]
    data = data[mask]
    order = np.argsort(freq)
    freq = freq[order]
    data = data[order]
    if freq.size == 0:
        return freq, data

    # np.interp requires increasing x. Keep first sample for duplicate frequencies.
    unique, idx = np.unique(freq, return_index=True)
    return unique, data[idx]


def align(a: Series, b: Series) -> tuple[np.ndarray, np.ndarray, np.ndarray, str]:
    fa, za = normalize_axis(a.freq_hz, a.data)
    fb, zb = normalize_axis(b.freq_hz, b.data)

    if fa.size == 0 or fb.size == 0:
        return np.array([]), np.array([]), np.array([]), "无频率数据"

    if fa.size == fb.size and np.allclose(fa, fb, rtol=1e-10, atol=1e-6):
        return fa, za, zb, "频率轴一致"

    lo = max(float(fa[0]), float(fb[0]))
    hi = min(float(fa[-1]), float(fb[-1]))
    mask = (fa >= lo) & (fa <= hi)
    f = fa[mask]
    za2 = za[mask]
    if f.size == 0:
        return np.array([]), np.array([]), np.array([]), "频率范围无重叠"

    br = np.interp(f, fb, np.real(zb))
    bi = np.interp(f, fb, np.imag(zb))
    return f, za2, br + 1j * bi, "B 插值到 A 频率轴"


def corrcoef_safe(x: np.ndarray, y: np.ndarray) -> float:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    x = x[mask]
    y = y[mask]
    if x.size < 2 or np.std(x) == 0 or np.std(y) == 0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def analyze_scalar_pair(a: Series, b: Series, label: str) -> list[str]:
    f, za, zb, how = align(a, b)
    lines = [f"\n=== {label} ===", f"对齐方式: {how}"]
    if f.size == 0:
        lines.append("无法比较。")
        return lines

    ar = za.real
    br = zb.real
    lines.append(f"A Real: {scalar_stats(ar)}")
    lines.append(f"B Real: {scalar_stats(br)}")
    lines.append(f"B-A:    {scalar_stats(br - ar)}")
    lines.append(f"A+B:    {scalar_stats(ar + br)}")
    lines.append(f"A-B:    {scalar_stats(ar - br)}")
    lines.append(f"corr(A,B)  = {corrcoef_safe(ar, br):.9g}")
    lines.append(f"corr(A,-B) = {corrcoef_safe(ar, -br):.9g}")
    return lines


def analyze_pm_vs_correction(pm: Series, corr: Series, label: str) -> list[str]:
    f, zpm, zc, how = align(pm, corr)
    lines = [f"\n=== {label} ===", f"对齐方式: {how}"]
    if f.size == 0:
        lines.append("无法比较。")
        return lines

    p = zpm.real
    c = zc.real

    # If C ~= target - P, then P + C should be approximately constant.
    sum_pc = p + c
    diff_pc = p - c

    lines.append(f"PowerMeter Real: {scalar_stats(p)}")
    lines.append(f"Correction Real: {scalar_stats(c)}")
    lines.append(f"P + C:           {scalar_stats(sum_pc)}")
    lines.append(f"P - C:           {scalar_stats(diff_pc)}")
    lines.append(f"corr(P,C)  = {corrcoef_safe(p, c):.9g}")
    lines.append(f"corr(P,-C) = {corrcoef_safe(p, -c):.9g}")
    lines.append(
        "判据: 如果 P+C 的 std 明显小于 P、C 各自的 std，"
        "则支持 C ≈ 常数 - P（常数可能对应目标功率或内部参考量）。"
    )
    return lines


def analyze_complex_transform(raw: Series, processed: Series, label: str) -> list[str]:
    f, zr, zp, how = align(raw, processed)
    lines = [f"\n=== {label} ===", f"对齐方式: {how}"]
    if f.size == 0:
        lines.append("无法比较。")
        return lines

    delta = zp - zr
    mask = np.abs(zr) > 1e-15
    ratio = np.full(zr.shape, np.nan + 1j * np.nan, dtype=np.complex128)
    ratio[mask] = zp[mask] / zr[mask]

    lines.append(f"|Processed-Raw|: {scalar_stats(np.abs(delta))}")
    lines.append(f"ΔReal:           {scalar_stats(delta.real)}")
    lines.append(f"ΔImag:           {scalar_stats(delta.imag)}")
    valid_ratio = finite_complex(ratio)
    if valid_ratio.size:
        lines.append(f"|Processed/Raw|: {scalar_stats(np.abs(valid_ratio))}")
        lines.append(
            f"∠(Processed/Raw): {scalar_stats(np.angle(valid_ratio, deg=True))} deg"
        )
    return lines


def analyze_receiver_tracking(receiver: Series, tracking: Series, label: str) -> list[str]:
    f, rr, tr, how = align(receiver, tracking)
    lines = [f"\n=== {label} ===", f"对齐方式: {how}"]
    if f.size == 0:
        lines.append("无法比较。")
        return lines

    eps = 1e-300
    rr_mag_db = 20 * np.log10(np.maximum(np.abs(rr), eps))
    tr_mag_db = 20 * np.log10(np.maximum(np.abs(tr), eps))

    lines.append(f"Receiver Real:       {scalar_stats(rr.real)}")
    lines.append(f"Tracking Real:       {scalar_stats(tr.real)}")
    lines.append(f"Receiver |.| dB:     {scalar_stats(rr_mag_db)}")
    lines.append(f"Tracking |.| dB:     {scalar_stats(tr_mag_db)}")
    lines.append(f"corr(Real,Real):     {corrcoef_safe(rr.real, tr.real):.9g}")
    lines.append(f"corr(Mag_dB,Mag_dB): {corrcoef_safe(rr_mag_db, tr_mag_db):.9g}")

    product = rr * tr
    ratio_mask = np.abs(rr) > 1e-15
    ratio = tr[ratio_mask] / rr[ratio_mask]
    lines.append(f"|Receiver*Tracking|: {scalar_stats(np.abs(product))}")
    if ratio.size:
        lines.append(f"|Tracking/Receiver|: {scalar_stats(np.abs(ratio))}")

    lines.append(
        "说明: 这里暂不预设 Keysight 的内部单位/公式；"
        "这些统计用于判断 Tracking 更像乘法修正、除法修正还是独立标量表。"
    )
    return lines


def require(series: dict[str, Series], name: str) -> Series | None:
    return series.get(name)


def add_if(lines: list[str], values: Iterable[str]) -> None:
    lines.extend(values)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="分析 PNA SMC Power Calibration 的 CalSet Standard 数据关系"
    )
    parser.add_argument(
        "calset_dir",
        type=Path,
        help="CalSet dump 目录，例如 PNA_CalSet_Dump_xxx/smc_power_cal",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="可选：同时把文本报告保存到指定文件",
    )
    args = parser.parse_args()

    series = load_standards(args.calset_dir)

    lines: list[str] = []
    lines.append("SMC Power Calibration 数据关系分析")
    lines.append(f"CalSet目录: {args.calset_dir}")
    lines.append(f"Standards总数: {len(series)}")
    lines.append("")

    lines.append("=== 目标 Standard 是否存在 ===")
    for name in NAMES:
        lines.append(f"{'[OK]' if name in series else '[--]'} {name}")

    lines.append("\n=== 单项数据摘要 ===")
    for name in NAMES:
        s = require(series, name)
        if s is not None:
            add_if(lines, complex_summary(s))

    pairs = [
        (
            "Power Meter Input vs RawSourcePowerCorrection(1)",
            "Power Meter Readings_Input(1)",
            "RawSourcePowerCorrection(1)",
            analyze_pm_vs_correction,
        ),
        (
            "Power Meter Output vs RawSourcePowerCorrection(2)",
            "Power Meter Readings_Output(1)",
            "RawSourcePowerCorrection(2)",
            analyze_pm_vs_correction,
        ),
        (
            "Raw vs Total Source Power Correction (Port 1)",
            "RawSourcePowerCorrection(1)",
            "TotalSourcePowerCorrection(1)",
            analyze_scalar_pair,
        ),
        (
            "Raw vs Total Source Power Correction (Port 2)",
            "RawSourcePowerCorrection(2)",
            "TotalSourcePowerCorrection(2)",
            analyze_scalar_pair,
        ),
        (
            "RawPowerSensorMatch(1) -> PowerSensorMatch(1)",
            "RawPowerSensorMatch(1)",
            "PowerSensorMatch(1)",
            analyze_complex_transform,
        ),
        (
            "RawPowerSensorMatch(2) -> PowerSensorMatch(2)",
            "RawPowerSensorMatch(2)",
            "PowerSensorMatch(2)",
            analyze_complex_transform,
        ),
        (
            "ReceiverReading(R1) vs RawResponseTracking(R1)",
            "ReceiverReading(R1)",
            "RawResponseTracking(R1)",
            analyze_receiver_tracking,
        ),
        (
            "ReceiverReading(R2) vs RawResponseTracking(R2)",
            "ReceiverReading(R2)",
            "RawResponseTracking(R2)",
            analyze_receiver_tracking,
        ),
    ]

    for label, a_name, b_name, func in pairs:
        a = require(series, a_name)
        b = require(series, b_name)
        if a is None or b is None:
            lines.append(f"\n=== {label} ===")
            lines.append(f"跳过：缺少 {a_name if a is None else b_name}")
            continue
        add_if(lines, func(a, b, label))

    # Cross-check logical Input/Output sensor match versus physical-port sensor match.
    cross_pairs = [
        (
            "Power Sensor Match Input vs PowerSensorMatch(1)",
            "Power Sensor Match_Input(1)",
            "PowerSensorMatch(1)",
        ),
        (
            "Power Sensor Match Output vs PowerSensorMatch(2)",
            "Power Sensor Match_Output(1)",
            "PowerSensorMatch(2)",
        ),
    ]
    for label, a_name, b_name in cross_pairs:
        a = require(series, a_name)
        b = require(series, b_name)
        if a is not None and b is not None:
            add_if(lines, analyze_complex_transform(a, b, label))

    lines.append("\n=== 请反馈给我的关键结果 ===")
    lines.append("请把以下几段终端输出直接复制给我：")
    lines.append("1. Power Meter Readings_Input/Output 的 Real 范围与前5点")
    lines.append("2. Power Meter vs RawSourcePowerCorrection 的 P+C std 和 corr(P,-C)")
    lines.append("3. Raw vs Total Source Power Correction 的 B-A 统计")
    lines.append("4. RawPowerSensorMatch -> PowerSensorMatch 的差值/比值统计")
    lines.append("5. ReceiverReading vs RawResponseTracking 的相关系数和乘积/比值统计")
    lines.append("6. 任意出现“频率轴一致 / 插值到A频率轴 / 无重叠”的信息")

    report = "\n".join(lines)
    print(report)

    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8")
        print(f"\n报告已保存: {args.report}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
