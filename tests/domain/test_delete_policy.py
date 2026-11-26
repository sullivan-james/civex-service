from civex.domain.delete_policy import TYPED_CONFIRM_ABOVE, delete_tier


def test_small_deletes_are_plain_and_large_ones_are_typed():
    assert delete_tier(1) == "plain"
    assert delete_tier(TYPED_CONFIRM_ABOVE) == "plain"
    assert delete_tier(TYPED_CONFIRM_ABOVE + 1) == "type"
