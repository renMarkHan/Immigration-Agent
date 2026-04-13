"""Debug script to check if profile_overrides are being applied correctly."""

import json
import requests

BASE_URL = "http://localhost:5050"
API_SESSION = f"{BASE_URL}/api/session"
API_CHAT = f"{BASE_URL}/api/chat"

def debug_profile_overrides():
    print("\n" + "="*70)
    print("DEBUG: Profile Overrides Application")
    print("="*70)
    
    # 1. Create session
    r = requests.post(API_SESSION)
    data = r.json()
    session_id = data.get("session_id")
    print(f"\n1. Created session: {session_id}")
    print(f"   Profile fields filled:")
    for f in data.get('profile', {}).get('required', []):
        print(f"      {f['field']}: {f['filled']}")
    
    # 2. Send chat with all 8 fields
    all_fields = {
        "age_band": "27",
        "education_level": "Master's degree from Canada",
        "language_score": "IELTS: R8 W7 L8.5 S7.5",
        "current_province": "Ontario",
        "target_province": "Ontario",
        "job_offer_status": "no",
        "graduation_date": "June 2024",
        "canadian_work_months": "12",
    }
    
    print(f"\n2. Sending chat with ALL 8 fields as profile_overrides:")
    for k, v in all_fields.items():
        print(f"      {k}: {v}")
    
    r = requests.post(
        API_CHAT,
        json={
            "session_id": session_id,
            "message": "Tell me about my eligibility",
            "profile_overrides": all_fields,
        }
    )
    data = r.json()
    
    print(f"\n3. Response:")
    print(f"   Type: {data.get('type')}")
    print(f"   State: {data.get('state')}")
    print(f"   ready_for_retrieval: {data.get('ready_for_retrieval')}")
    print(f"   action_route: {data.get('action_route')}")
    print(f"   confidence_warning: {data.get('confidence_warning')}")
    
    print(f"\n   Profile fields now filled:")
    for f in data.get('profile', {}).get('required', []):
        print(f"      {f['field']}: {f['filled']}")
    
    if data.get('type') == 'collecting':
        print(f"\n   ❌ BUG: Still collecting despite ALL fields provided!")
        print(f"   Message: {data.get('agent_message', '')[:200]}...")
    elif data.get('ready_for_retrieval'):
        print(f"\n   ✓ OK: ready_for_retrieval is True")
        if data.get('type') == 'answer':
            print(f"   Got answer type")
    else:
        print(f"\n   ⚠️  ready_for_retrieval is False despite all fields")

if __name__ == "__main__":
    debug_profile_overrides()
