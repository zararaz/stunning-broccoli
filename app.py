"""Web chat UI for the city guide (Gradio). Runs locally or as a Hugging Face Space.

    python app.py            then open http://127.0.0.1:7860

The right-hand panel shows the trace: how the message was parsed, the plan the
code built, the validator's checks and the time each step took.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import gradio as gr  # noqa: E402

from engine import Engine  # noqa: E402

ENGINES = {}
EXAMPLES = [
    "I'm visiting Philly on Saturday, I love art and cheap eats",
    "I live in Philly, what places should I try?",
    "I live in Philly, tell me a new restaurant every week to try",
]


def engine_for(backend):
    if backend not in ENGINES:
        ENGINES[backend] = Engine(backend)
    return ENGINES[backend]


def respond(message, chat, user_id, backend):
    try:
        reply, trace = engine_for(backend).handle(message, user_id or "demo")
    except Exception as e:                   # e.g. missing API key for the chosen backend
        reply, trace = f"Error with the {backend} backend: {e}", {"error": repr(e)}
    chat = chat + [{"role": "user", "content": message}, {"role": "assistant", "content": reply}]
    return "", chat, trace


def make_chatbot():
    try:
        return gr.Chatbot(type="messages", height=520, label="City guide")
    except TypeError:                        # newer Gradio: messages format is the only format
        return gr.Chatbot(height=520, label="City guide")


with gr.Blocks(title="City guide") as demo:
    gr.Markdown("# City guide\nVisiting, living there, or want a new restaurant every week? Ask away.")
    with gr.Row():
        with gr.Column(scale=3):
            chat = make_chatbot()
            box = gr.Textbox(placeholder="e.g. I'm visiting Philly on Sunday, love jazz", label="Message")
            gr.Examples(EXAMPLES, inputs=box)
        with gr.Column(scale=2):
            user = gr.Textbox(value="demo", label="User id (weekly picks are remembered per user)")
            backend = gr.Radio(["rules", "hf", "claude"], value="rules", label="LLM backend")
            trace = gr.JSON(label="Trace: what each step did")
    box.submit(respond, [box, chat, user, backend], [box, chat, trace])

if __name__ == "__main__":
    demo.launch()
