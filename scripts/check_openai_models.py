"""Print model IDs visible to OPENAI_API_KEY without printing the credential."""

import os

from openai import OpenAI


key = os.getenv("OPENAI_API_KEY", "").strip()
if not key:
    raise SystemExit("OPENAI_API_KEY is not configured")

models = sorted(model.id for model in OpenAI(api_key=key).models.list().data)
print(f"Visible model count: {len(models)}")
for model in models:
    if model.startswith(("gpt-", "o1", "o3", "o4", "chatgpt-image", "dall-e")):
        print(model)
