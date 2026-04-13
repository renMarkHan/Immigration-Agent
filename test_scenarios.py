"""
Test to understand the exact bug scenario reported by the user:
"我的profile已经写了我的age了呀，为什么它还会问？"
"My profile already has my age written, why does it still ask?"
"""

import json
import requests

BASE_URL = "http://localhost:5050"
API_SESSION = f"{BASE_URL}/api/session"
API_CHAT = f"{BASE_URL}/api/chat"

def scenario_1_form_prefilled_then_action():
    """
    Scenario 1: User pre-fills form, then clicks Action 2
    
    Expected: System should NOT ask for age/education if they're already in the form
    """
    print("\n" + "="*70)
    print("SCENARIO 1: Pre-filled form, then action card")
    print("="*70)
    
    # 1. Create session (form data persists in localStorage on frontend)
    r = requests.post(API_SESSION)
    data = r.json()
    session_id = data.get("session_id")
    print(f"Session: {session_id}")
    print(f"Initial state: {data.get('state')}")
    
    # 2. User has localStorage with: age=27, education=Master's, graduation_date=2024-06
    #    Now they click Action 2  "Am I eligible for OINP Masters?"
    #    Frontend calls sendMessage() which reads form and sends profile_overrides
    
    # Simulate more complete form data
    profile_overrides = {
        "age_band": "27",
        "education_level": "Master's degree from Canada",
        "graduation_date": "June 2024",
        "current_province": "Ontario",
        "target_province": "Ontario",
    }
    
    print(f"\nForm data being sent: {profile_overrides}")
    
    r = requests.post(
        API_CHAT,
        json={
            "session_id": session_id,
            "message": "Am I eligible for the OINP Masters Graduate Stream?",
            " profile_overrides": profile_overrides,
        }
    )
    data = r.json()
    
    print(f"\nResponse type: {data.get('type')}")
    print(f"State: {data.get('state')}")
    print(f"ready_for_retrieval: {data.get('ready_for_retrieval')}")
    
    if data.get('type') == 'collecting':
        msg = data.get('agent_message', '')
        if 'age' in msg.lower():
            print("❌ BUG: Still asking for age despite form having it!")
            print(f"Message: {msg[:150]}...")
        elif 'education' in msg.lower():
            print("❌ BUG: Still asking for education despite form having it!")
            print(f"Message: {msg[:150]}...")
        else:
            print("⚠️  Still collecting, but asking for different fields")
            print(f"Message: {msg[:150]}...")
    else:
        print(f"✓ Got response type '{data.get('type')}', not collecting")


def scenario_2_answer_intake_then_form():
    """
    Scenario 2: User answers intake question verbally, then fills form
    
    Flow:
    1. /api/session
    2. /api/chat with message "I am 27 years old"
    3. System recognizes age, but still asks for education
    4. /api/chat with message "I have Master's degree"
    5. System recognizes education, but still asks for language_score
    6. User fills entire form in sidebar and sends another question
    7. System should recognize form is filled and not ask again
    """
    print("\n" + "="*70)
    print("SCENARIO 2: Answer intake verbally, then fill form")
    print("="*70)
    
    # 1. Create session
    r = requests.post(API_SESSION)
    data = r.json()
    session_id = data.get("session_id")
    print(f"Session: {session_id}")
    
    # 2. User says their age verbally
    print("\n→ User says: 'I am 27 years old'")
    r = requests.post(
        API_CHAT,
        json={
            "session_id": session_id,
            "message": "I am 27 years old",
            "profile_overrides": {},
        }
    )
    data = r.json()
    print(f"  Response type: {data.get('type')}")
    print(f"  Profile age_band filled: {next((f['filled'] for f in data['profile']['required'] if f['field'] == 'age_band'), False)}")
    
    # 3. User says their education
    print("\n→ User says: 'I have a Master's degree from Canada'")
    r = requests.post(
        API_CHAT,
        json={
            "session_id": session_id,
            "message": "I have a Master's degree from Canada",
            "profile_overrides": {},
        }
    )
    data = r.json()
    print(f"  Response type: {data.get('type')}")
    print(f"  Profile education_level filled: {next((f['filled'] for f in data['profile']['required'] if f['field'] == 'education_level'), False)}")
    
    # 4. Now user fills entire form in sidebar
    # Manually fill all required fields
    complete_overrides = {
        "age_band": "27",
        "education_level": "Master's degree from Canada",
        "language_score": "IELTS: Reading 8, Writing 7, Listening 8.5, Speaking 7.5",
        "current_province": "Ontario",
        "target_province": "Ontario",
        "job_offer_status": "no",
        "graduation_date": "June 2024",
        "canadian_work_months": "12",
    }
    
    print(f"\n→ User fills entire form in sidebar and sends: 'Am I eligible for OINP Masters?'")
    print(f"   Form data: all {len(complete_overrides)} required fields filled")
    
    r = requests.post(
        API_CHAT,
        json={
            "session_id": session_id,
            "message": "Am I eligible for OINP Masters?",
            "profile_overrides": complete_overrides,
        }
    )
    data = r.json()
    
    print(f"\n  Response type: {data.get('type')}")
    print(f"  ready_for_retrieval: {data.get('ready_for_retrieval')}")
    
    if data.get('type') == 'collecting':
        print(f"  ❌ BUG: Still asking for more despite ALL fields in form!")
        print(f"  Message: {data.get('agent_message', '')[:150]}...")
    elif data.get('ready_for_retrieval'):
        print(f"  ✓ FIXED: System recognized form is complete")
        if data.get('type') == 'answer':
            print(f"  Got answer (not shown)")
        elif data.get('type') == 'collecting':
            print(f"  Still collecting?: {data.get('agent_message', '')[:100]}...")
    else:
        print(f"  ⚠️  ready_for_retrieval is {data.get('ready_for_retrieval')}")


if __name__ == "__main__":
    scenario_1_form_prefilled_then_action()
    scenario_2_answer_intake_then_form()
