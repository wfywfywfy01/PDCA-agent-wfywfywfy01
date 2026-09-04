from collections import Counter

from scripts.sync_dealer_permissions import (
    MATRIX,
    OWNER_ACCOUNTS,
    PUBLIC_POOL_SALES,
    STORE_TARGETS,
    generated_store_id,
    normalize,
)


def test_permission_matrix_is_complete_and_unambiguous():
    assert len(MATRIX) == 65
    assert len({normalize(row.dealer) for row in MATRIX}) == 65
    assert {row.sales for row in MATRIX if row.sales} <= set(OWNER_ACCOUNTS) | PUBLIC_POOL_SALES
    assert sum(not row.sales for row in MATRIX) == 2
    assert PUBLIC_POOL_SALES == {"马文娜", "张晏培", "吴佳军", "刘圣"}
    assert "Safae" in OWNER_ACCOUNTS
    assert Counter(row.sales for row in MATRIX)["Lina"] == 24
    assert Counter(row.sales for row in MATRIX)["杨晶晶"] == 13


def test_explicit_aliases_do_not_overlap_and_generated_ids_are_stable():
    target_ids = [store_id for ids in STORE_TARGETS.values() for store_id in ids]
    assert len(target_ids) == len(set(target_ids))
    assert generated_store_id("CAT NG") == generated_store_id("cat ng")
    assert generated_store_id("CAT NG").startswith("master-")
