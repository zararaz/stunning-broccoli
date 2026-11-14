"""Web chat UI (Gradio).

    python app.py              development: pick any LLM backend and user id
    uvicorn server:app ...     production: fixed backend, login, logs (see server.py)

build_demo() only draws the page; whoever calls it decides what happens to a message.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import gradio as gr  # noqa: E402

EXAMPLES = [
    "I'm visiting Philly on Saturday, I love art and cheap eats",
    "I live in Philly, what places should I try?",
    "I live in Philly, tell me a new restaurant every week to try",
]


def make_chatbot():
    try:
        return gr.Chatbot(type="messages", height=520, label="City guide")
    except TypeError:                        # newer Gradio: messages format is the only format
        return gr.Chatbot(height=520, label="City guide")


def build_demo(handle, backends=("rules", "hf", "claude"), show_user=True):
    """handle(message, user_id, backend, request) -> (reply, trace)."""

    def respond(message, chat, user_id, backend, request: gr.Request):
        if not message.strip():
            return "", chat, {}
        try:
            reply, trace = handle(message, user_id or "demo", backend, request)
        except Exception as e:
            reply, trace = f"Sorry, something went wrong: {e}", {"error": repr(e)}
        chat = chat + [{"role": "user", "content": message}, {"role": "assistant", "content": reply}]
        return "", chat, trace

    with gr.Blocks(title="City guide") as demo:
        gr.Markdown("# City guide\nVisiting, living there, or want a new restaurant every week? Ask away.")
        with gr.Row():
            with gr.Column(scale=3):
                chat = make_chatbot()
                box = gr.Textbox(placeholder="e.g. I'm visiting Philly on Sunday, love jazz", label="Message")
                gr.Examples(EXAMPLES, inputs=box)
            with gr.Column(scale=2):
                user = gr.Textbox(value="demo", label="User id (weekly picks are remembered per user)",
                                  visible=show_user)
                backend = gr.Radio(list(backends), value=backends[0], label="LLM backend",
                                   visible=len(backends) > 1)
                trace = gr.JSON(label="Trace: what each step did")
        box.submit(respond, [box, chat, user, backend], [box, chat, trace])
    return demo


def dev_main():
    from engine import Engine
    engines = {}

    def handle(message, user_id, backend, request):
        if backend not in engines:
            engines[backend] = Engine(backend)
        return engines[backend].handle(message, user_id)

    build_demo(handle).launch()


if __name__ == "__main__":
    dev_main()
