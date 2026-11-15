"""Web chat UI (Gradio).

    python app.py                  on your laptop, http://127.0.0.1:7860
    python app.py --llm hf         with a local Hugging Face model (or --llm claude)
    uvicorn server:app ...         production: the same page plus the HTTP API (see server.py)

Every message goes  page -> ChatService.chat -> Engine.handle,  the same path
the HTTP API uses, so limits, logins and logging behave the same everywhere.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import gradio as gr  # noqa: E402

import settings  # noqa: E402
from service import ChatError, ChatService, basic_auth_user, client_key  # noqa: E402

EXAMPLES = [
    "I'm visiting Philly on Saturday, I love art and cheap eats",
    "I live in Philly, what places should I try?",
    "I live in Philly, tell me a new restaurant every week to try",
]


def build_demo(service, full_trace=True):
    """The chat page. full_trace shows every pipeline step in the side panel;
    without it the panel shows only the request id, mode and timings."""

    def respond(message, chat, user_id, request: gr.Request):
        if not message.strip():
            return "", chat, {}
        login = basic_auth_user(request.headers.get("authorization")) if request else None
        user = login or user_id or "demo"
        try:
            out, trace = service.chat(message, user, client_key(login, request.client.host if request else None))
            reply = out["reply"]
            if not full_trace:
                trace = {"request_id": out["request_id"], "mode": trace["request"]["mode"],
                         "search": trace["search_method"], "timings": trace["timings"]}
        except ChatError as e:
            reply, trace = e.message, {"error": e.message}
        chat = chat + [{"role": "user", "content": message}, {"role": "assistant", "content": reply}]
        return "", chat, trace

    info = service.info()
    with gr.Blocks(title="City guide") as demo:
        gr.Markdown("# City guide\nVisiting, living there, or want a new restaurant every week? Ask away.")
        with gr.Row():
            with gr.Column(scale=3):
                chat = gr.Chatbot(height=520, label="City guide")
                box = gr.Textbox(placeholder="e.g. I'm visiting Philly on Sunday, love jazz", label="Message")
                gr.Examples(EXAMPLES, inputs=box)
            with gr.Column(scale=2):
                user = gr.Textbox(value="demo", label="User id (weekly picks are remembered per user)",
                                  visible=not settings.USERS)       # with logins, the login is the user
                gr.Markdown(f"LLM backend: **{info['llm']}** · search: **{info['search']}**")
                trace = gr.JSON(label="Trace: what each step did")
        box.submit(respond, [box, chat, user], [box, chat, trace])
    return demo


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", help="rules (default), hf or claude")
    args = ap.parse_args()
    build_demo(ChatService(args.llm)).launch()
