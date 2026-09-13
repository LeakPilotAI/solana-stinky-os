import stinky_core.evm_router_output as output


def w(n):
    return f"{n:064x}"


def data(values):
    return "0x" + w(32) + w(len(values)) + "".join(w(value) for value in values)


def test_array_result_decodes_expected_values():
    result = output.decode_uint256_array_output(data((100, 90)), expected_length=2, expected_input=100, minimum_output=80)
    assert result.status == "DECODED_UINT256_ARRAY_OUTPUT"
    assert result.amounts == (100, 90)
    assert result.minimum_output_satisfied is True


def test_shape_mismatch_fails_closed():
    result = output.decode_uint256_array_output(data((100, 90)), expected_length=3)
    assert result.status == "MALFORMED_ROUTER_OUTPUT"


def test_missing_result_stays_unknown():
    result = output.decode_uint256_array_output(None, expected_length=2)
    assert result.status == "NO_QUORUM_OUTPUT"
