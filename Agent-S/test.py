import os
import time
from openai import OpenAI

# Load API key from environment
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise EnvironmentError("❌ OPENAI_API_KEY not set")

client = OpenAI(api_key=api_key)

# Number of test requests
N = 5  # change this as needed
MODEL = "gpt-5"

print(f"🔁 Sending {N} test chat requests to {MODEL}...\n")

for i in range(N):
    try:
        start = time.time()
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": f"Test message #{i+1}"}],
        )
        end = time.time()

        text = response.choices[0].message.content.strip()
        print(f"[{i+1}/{N}] ✅ {text} ({end - start:.2f}s)")
    except Exception as e:
        print(f"[{i+1}/{N}] ❌ Error: {e}")
    # time.sleep(0.2)  # small delay to avoid hitting RPM limits

print("\n✅ Test complete!")
