"""Unit test for the profile_overrides fix at the module level."""

from src.intake import assess_completeness, IntakeMode
from src.schemas import IntakeProfile

def test_profile_completeness():
    # Test 1: Empty profile
    profile = IntakeProfile(query="")
    completeness = assess_completeness(profile)
    print(f"Empty profile: mode={completeness.mode}, missing={len(completeness.missing_required)}")
    assert completeness.mode == IntakeMode.DATA_COLLECTION
    
    # Test 2: Profile with just age + education (2 fields)
    profile = IntakeProfile(
        query="test",
        age_band="27",
        education_level="Master's degree from Canada"
    )
    completeness = assess_completeness(profile)
    print(f"Age + Edu profile: mode={completeness.mode}, missing={completeness.missing_required}")
    assert completeness.mode == IntakeMode.DATA_COLLECTION  # > 2 missing
    
    # Test 3: Profile with 6 fields
    profile = IntakeProfile(
        query="test",
        age_band="27",
        education_level="Master's degree from Canada",
        language_score="IELTS: R8 W7 L8.5 S7.5",
        current_province="Ontario",
        target_province="Ontario",
        job_offer_status="no",
    )
    completeness = assess_completeness(profile)
    print(f"6-field profile: mode={completeness.mode}, missing={completeness.missing_required}")
    assert completeness.mode == IntakeMode.LOW_CONFIDENCE  # 2 missing
    
    # Test 4: All 8 fields
    profile = IntakeProfile(
        query="test",
        age_band="27",
        education_level="Master's degree from Canada",
        language_score="IELTS: R8 W7 L8.5 S7.5",
        current_province="Ontario",
        target_province="Ontario",
        job_offer_status="no",
        graduation_date="June 2024",
        canadian_work_months=12,
    )
    completeness = assess_completeness(profile)
    print(f"8-field profile: mode={completeness.mode}, missing={completeness.missing_required}")
    assert completeness.mode == IntakeMode.FULL_MATCHING
    
    print("\n✓ All profile completeness tests passed")

if __name__ == "__main__":
    test_profile_completeness()
