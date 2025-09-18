import gradio as gr
from .ui_student import student_tab
from .ui_librarian import librarian_tab


def build_ui():
    with gr.Blocks() as demo:
        gr.Tab("Student")
        with gr.TabItem("Student"):
            student_tab()
        with gr.TabItem("Librarian"):
            librarian_tab()
    return demo


if __name__ == '__main__':
    build_ui().launch()
