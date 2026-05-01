"""Single-shot probe: try one chat.completions call and print the FULL traceback.

Useful when the lantern logs only show the wrapped 'Connection error' string.
"""
import os
import traceback

import openai

print(f"openai SDK: {openai.__version__}")

try:
    import httpx
    print(f"httpx     : {httpx.__version__}")
except Exception:
    pass

client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])

try:
    r = client.chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[{"role": "user", "content": "say 'pong'"}],
        max_tokens=8,
    )
    print("OK:", r.choices[0].message.content)
except Exception as e:
    print(f"EXCEPTION: {type(e).__module__}.{type(e).__name__}: {e}")
    traceback.print_exc()
    cause = e.__cause__ or e.__context__
    while cause is not None:
        print(f"  caused by: {type(cause).__module__}.{type(cause).__name__}: {cause}")
        cause = cause.__cause__ or cause.__context__
