"""Pluggable LLM backends: the rest of the app never knows which one is running.

Choose with CITY_GUIDE_LLM (see settings.py) or --llm on the command line:
    rules   no model at all; rule-based parsing and template replies (default)
    hf      a small open model from Hugging Face, running on this machine
    claude  Anthropic's Claude API (needs ANTHROPIC_API_KEY)

Every backend has one method, chat(system, user) -> text. That text is
untrusted: callers pull JSON out of it with extract_json(), validate every
field, and fall back to rules or a template if anything is wrong.
"""

import json
import os
import re
import threading

import settings


class HuggingFaceLLM:
    def __init__(self, model_id=None):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.name = model_id or settings.HF_MODEL
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.tokenizer = AutoTokenizer.from_pretrained(self.name)
        self.model = AutoModelForCausalLM.from_pretrained(self.name).to(self.device)
        self.lock = threading.Lock()   # one generation at a time: the model isn't thread-safe

    def chat(self, system, user, max_tokens=500):
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        with self.lock:
            enc = self.tokenizer.apply_chat_template(messages, add_generation_prompt=True,
                                                     return_tensors="pt", return_dict=True).to(self.device)
            out = self.model.generate(**enc, max_new_tokens=max_tokens, do_sample=False)
        return self.tokenizer.decode(out[0][enc["input_ids"].shape[1]:], skip_special_tokens=True)


class ClaudeLLM:
    def __init__(self, model=None):
        import anthropic
        if not os.environ.get("ANTHROPIC_API_KEY"):
            # Fail here, loudly: otherwise every call fails and the pipeline
            # quietly falls back to rules, which looks like Claude ran.
            raise RuntimeError("ANTHROPIC_API_KEY is not set. Put it in .env "
                               "(copy .env.example) or export it in your shell.")
        self.client = anthropic.Anthropic()          # reads ANTHROPIC_API_KEY
        self.name = model or settings.CLAUDE_MODEL

    def chat(self, system, user, max_tokens=500):
        resp = self.client.messages.create(model=self.name, max_tokens=max_tokens, system=system,
                                           messages=[{"role": "user", "content": user}])
        return "".join(b.text for b in resp.content if b.type == "text")


def get_llm(name=None):
    """Return a backend, or None for the no-model 'rules' mode."""
    name = (name or settings.LLM).lower()
    if name == "rules":
        return None
    if name == "hf":
        return HuggingFaceLLM()
    if name == "claude":
        return ClaudeLLM()
    raise ValueError(f"Unknown LLM backend {name!r}: use rules, hf or claude")


def extract_json(text):
    """The first {...} object in a model's reply. Raises ValueError if there is none."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("no JSON object in the model's reply")
    return json.loads(m.group(0))
