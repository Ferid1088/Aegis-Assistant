"""ACL invariant tests — verifies all three invariants + type fail-open.

Run: uv run python eval/test_acl.py
"""

from rag.config import settings
from rag.crosscutting.security.acl import (
    acl_filter,
    check_acl_access,
    live_recheck,
    type_filter,
)
from rag.domain.models import RetrievedChunk

# Force enforce ON for these tests
_original = settings.acl_enforce


def _make_chunk(chunk_id: str, acl: list[str], doc_type: str | None = None) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id, content="test", score=1.0,
        metadata={"acl_levels": acl, "document_type": doc_type, "page_numbers": [1]},
    )


def test_inv1_default_deny():
    """INV-1: acl_levels=[] → invisible to everyone, including admins."""
    settings.acl_enforce = True
    chunk = _make_chunk("c1", acl=[])
    assert not check_acl_access(chunk, ["admin", "HR_level_2"]), "INV-1 FAILED: empty acl should deny"
    assert not check_acl_access(chunk, []), "INV-1 FAILED: empty user + empty acl should deny"
    assert not check_acl_access(chunk, None), "INV-1 FAILED: None user + empty acl should deny"
    print("  ✅ INV-1: default deny — acl_levels=[] invisible to everyone")


def test_inv2_any_of_intersection():
    """INV-2: access iff acl_levels ∩ user_levels ≠ ∅ (any-of)."""
    settings.acl_enforce = True
    chunk = _make_chunk("c2", acl=["HR_level_1", "HR_level_2"])

    assert check_acl_access(chunk, ["HR_level_1"]), "INV-2 FAILED: single match should allow"
    assert check_acl_access(chunk, ["HR_level_2", "Legal"]), "INV-2 FAILED: partial match should allow"
    assert not check_acl_access(chunk, ["Legal", "Finance"]), "INV-2 FAILED: no match should deny"

    # Combined clearance: HR+Legal modeled as single level
    chunk_combined = _make_chunk("c3", acl=["HR+Legal_L2"])
    assert not check_acl_access(chunk_combined, ["HR_level_2"]), "INV-2 FAILED: HR alone should not access HR+Legal"
    assert check_acl_access(chunk_combined, ["HR+Legal_L2"]), "INV-2 FAILED: exact combined level should allow"
    print("  ✅ INV-2: any-of intersection semantics consistent")


def test_inv2_filter_construction():
    """INV-2: filter construction matches semantics."""
    settings.acl_enforce = True
    f = acl_filter(["HR_level_1"])
    assert f == {"acl_levels_any": ["HR_level_1"]}, f"Filter wrong: {f}"

    f_deny = acl_filter(None)
    assert f_deny and "_acl_deny_all" in f_deny, "No user_levels should produce deny-all filter"

    f_deny2 = acl_filter([])
    assert f_deny2 and "_acl_deny_all" in f_deny2, "Empty user_levels should produce deny-all filter"
    print("  ✅ INV-2: filter construction correct")


def test_live_recheck():
    """Live recheck denies chunks that fail ACL."""
    settings.acl_enforce = True
    chunks = [
        _make_chunk("ok1", acl=["HR_level_1"]),
        _make_chunk("denied1", acl=["Legal"]),
        _make_chunk("ok2", acl=["HR_level_1", "Finance"]),
        _make_chunk("denied2", acl=[]),  # INV-1
    ]
    allowed, denied = live_recheck(chunks, ["HR_level_1"])
    assert len(allowed) == 2, f"Should allow 2, got {len(allowed)}"
    assert set(denied) == {"denied1", "denied2"}, f"Denied wrong: {denied}"
    print("  ✅ Live recheck: correctly filters + logs denied IDs")


def test_type_fail_open():
    """document_type filter is fail-open: None/unclassified docs stay searchable."""
    settings.acl_enforce = True

    # type_filter returns None when no types intended → all docs searchable
    assert type_filter(None) is None, "No types → no filter (fail-open)"
    assert type_filter([]) is None, "Empty types → no filter (fail-open)"

    f = type_filter(["tariff"])
    assert f is not None, "Specific type should produce filter"
    assert "document_type_any" in f, f"Type filter wrong: {f}"
    print("  ✅ Type fail-open: unclassified docs not hidden")


def test_no_type_in_recheck():
    """Live recheck validates ACL only, never document_type."""
    settings.acl_enforce = True
    chunk_wrong_type = _make_chunk("c_type", acl=["HR_level_1"])
    chunk_wrong_type.metadata["document_type"] = "contract"
    # Even if document_type doesn't match intent, recheck should ALLOW (it's ACL only)
    allowed, denied = live_recheck([chunk_wrong_type], ["HR_level_1"])
    assert len(allowed) == 1, "Recheck must not filter by document_type"
    assert len(denied) == 0, "Recheck must not deny based on type"
    print("  ✅ No type in live recheck: ACL only, type ignored")


def test_unenforced_passes_all():
    """When acl_enforce=False, everything passes."""
    settings.acl_enforce = False
    chunk = _make_chunk("c_unenforced", acl=[])
    assert check_acl_access(chunk, None), "Unenforced should pass"
    assert acl_filter(None) is None, "Unenforced should produce no filter"
    allowed, denied = live_recheck([chunk], None)
    assert len(allowed) == 1, "Unenforced recheck should pass all"
    print("  ✅ Unenforced (local): everything passes, no ACL applied")


def main():
    print("=== ACL Invariant Tests ===\n")
    tests = [
        test_inv1_default_deny,
        test_inv2_any_of_intersection,
        test_inv2_filter_construction,
        test_live_recheck,
        test_type_fail_open,
        test_no_type_in_recheck,
        test_unenforced_passes_all,
    ]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {t.__name__}: {e}")
        except Exception as e:
            print(f"  ❌ {t.__name__}: {e}")
        finally:
            settings.acl_enforce = _original

    print(f"\n{'='*40}")
    print(f"  {passed}/{len(tests)} tests passed")
    if passed == len(tests):
        print("  🎉 All ACL invariants verified")
    print(f"{'='*40}")


if __name__ == "__main__":
    main()
