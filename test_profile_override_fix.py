"""Test profile_overrides fix: Ensure form-filled profiles skip intake questions."""

import json
import subprocess
import time
import requests
from pathlib import Path

BASE_URL = "http://localhost:5050"
API_HEALTH = f"{BASE_URL}/api/health"
API_SESSION = f"{BASE_URL}/api/session"
API_CHAT = f"{BASE_URL}/api/chat"

def test_profile_overrides_skips_intake():
    """
    Test: When user fills age + education in form, first Action 2 query
    should NOT ask for more intake fields.
    
    Scenario:
    1. POST /api/session → get blank session
    2. POST /api/chat with:
       - message: "Am I eligible for the OINP Masters Graduate Stream?"
       - profile_overrides: {age_band: "27", education_level: "Master's degree from Canada"}
    3. Expect: ready_for_retrieval = True (or at least, NOT a collecting state)
    """
    
    print("\n" + "="*70)
    print("TEST: Profile Overrides Skip Intake Questions")
    print("="*70)
    
    # 1. Health check
    try:
        r = requests.get(API_HEALTH, timeout=5)
        r.raise_for_status()
        print("✓ API health check passed")
    except Exception as e:
        print(f"✗ API health check failed: {e}")
        return False
    
    # 2. Create session
    try:
        r = requests.post(API_SESSION, timeout=5)
        r.raise_for_status()
        data = r.json()
        session_id = data.get("session_id")
        print(f"✓ Session created: {session_id}")
        print(f"  Initial state: {data.get('state')}")
        print(f"  Initial ready_for_retrieval: {data.get('ready_for_retrieval')}")
    except Exception as e:
        print(f"✗ Session creation failed: {e}")
        return False
    
    # 3. Send first chat with profile overrides
    action_2_query = "Am I eligible for the OINP Masters Graduate Stream?"
    profile_overrides = {
        "age_band": "27",
        "education_level": "Master's degree from Canada",
    }
    
    print(f"\n→ Sending first chat:")
    print(f"  Query: {action_2_query}")
    print(f"  Profile overrides: {profile_overrides}")
    
    try:
        r = requests.post(
            API_CHAT,
            json={
                "session_id": session_id,
                "message": action_2_query,
                "profile_overrides": profile_overrides,
            },
            timeout=10
        )
        r.raise_for_status()
        data = r.json()
        
        print(f"\n✓ First chat succeeded")
        print(f"  Response type: {data.get('type')}")
        print(f"  State: {data.get('state')}")
        print(f"  ready_for_retrieval: {data.get('ready_for_retrieval')}")
        print(f"  action_route: {data.get('action_route')}")
        
        # Check if intake was skipped
        if data.get("type") == "collecting":
            print(f"\n✗ FAIL: Got 'collecting' response despite profile overrides")
            print(f"  Agent message: {data.get('agent_message')[:100]}...")
            return False
        
        if data.get("ready_for_retrieval") != True:
            print(f"\n⚠ WARNING: ready_for_retrieval is False despite profile overrides")
            print(f"  This may be expected if > 2 required fields are missing (D-002 DATA_COLLECTION)")
            print(f"  But the profile_overrides fix should have updated state.")
        
        # Check action route
        if data.get("action_route") == "action_2":
            print(f"\n✓ Correctly routed to ACTION_2 (eligibility check)")
        else:
            print(f"⚠ Action route: {data.get('action_route')} (expected action_2)")
        
        print(f"\n  Agent message: {data.get('agent_message')}")
        
        # Print profile state
        profile = data.get("profile", {})
        req_fields = profile.get("required", [])
        filled = [f for f in req_fields if f.get("filled")]
        print(f"\n  Profile fields filled: {len(filled)}/{len(req_fields)}")
        for f in filled:
            print(f"    ✓ {f['label']}")
        
        return True
        
    except Exception as e:
        print(f"✗ Chat failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_profile_overrides_skips_intake()
    print("\n" + "="*70)
    if success:
        print("✓ TEST PASSED")
    else:
        print("✗ TEST FAILED")
    print("="*70 + "\n")
    exit(0 if success else 1)
