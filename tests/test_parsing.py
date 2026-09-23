import numpy as np

from pna_cal_explorer.scpi import parse_pna_catalog, interleaved_to_complex


def test_calset_catalog_entire_response_quoted():
    assert parse_pna_catalog('"CalSet_2_port,CH1_CALREG,smc_power_cal"') == [
        "CalSet_2_port", "CH1_CALREG", "smc_power_cal"
    ]


def test_calset_catalog_unquoted():
    assert parse_pna_catalog("CalSet_2_port,CH1_CALREG,smc_power_cal") == [
        "CalSet_2_port", "CH1_CALREG", "smc_power_cal"
    ]


def test_names_with_commas_inside_parentheses():
    assert parse_pna_catalog('"Directivity(1,1),SourceMatch(1,1),TransmissionTracking(2,1)"') == [
        "Directivity(1,1)", "SourceMatch(1,1)", "TransmissionTracking(2,1)"
    ]


def test_interleaved_to_complex():
    z = interleaved_to_complex([1, 2, 3, 4])
    np.testing.assert_array_equal(z, np.array([1 + 2j, 3 + 4j]))
