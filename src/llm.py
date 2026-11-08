"""Pluggable LLM backends: the rest of the app never knows which one is running.

Choose with the CITY_GUIDE_LLM environment variable (or --llm in the CLI):
    rules   no model at all; rule-based parsing and template replies (default)
    hf      a small open model from Hugging Face, running on this machine
    claude  Anthropic's Claude API (needs ANTHROPIC_API_KEY)

Every backend has one method, chat(system, user) -> text. Callers must treat
the output as untrusted: parse it, validate it, and fall back if it's wrong.
"""

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"   # gitignored; see .env.example


def load_env_file(path=ENV_FILE):
    """Read KEY=value lines from .env into os.environ, without overriding variables
    already set in the shell. Standard library only, so no extra package."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


DEFAULT_HF_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"   # ~1 GB, small enough for a laptop
DEFAULT_CLAUDE_MODEL = "claude-haiku-5-5"


class HuggingFaceLLM:
    def __init__(self, model_id=None):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.name = model_id or os.environ.get("CITY_GUIDE_HF_MODEL", DEFAULT_HF_MODEL)
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.tokenizer = AutoTokenizer.from_pretrained(self.name)
        self.model = AutoModelForCausalLM.from_pretrained(self.name).to(self.device)

    def chat(self, system, user, max_tokens=500):
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
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
        self.name = model or os.environ.get("CITY_GUIDE_CLAUDE_MODEL", DEFAULT_CLAUDE_MODEL)

    def chat(self, system, user, max_tokens=500):
        resp = self.client.messages.create(model=self.name, max_tokens=max_tokens, system=system,
                                           messages=[{"role": "user", "content": user}])
        return "".join(b.text for b in resp.content if b.type == "text")


def get_llm(name=None):
    """Return a backend, or None for the no-model 'rules' mode."""
    load_env_file()
    name =(name or os.environ.get("CITY_GUIDE_LLM", "rules")).lower()
    if name == "rules":
        return None
    if name == "hf":
        return HuggingFaceLLM()
    if name == "claude":
        return ClaudeLLM()
    raise ValueError(f"Unknown LLM backend {name!r}: use rules, hf or claude")
