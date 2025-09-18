import gradio as gr


def student_tab():
    with gr.Column():
        gr.Markdown("""## Student tab\n\nPlaceholder UI for students.""")
        q = gr.Textbox(label="Question")
        out = gr.Textbox(label="Answer")
        run = gr.Button("Ask")

        def handle(question):
            return f"Echo: {question}"

        run.click(handle, inputs=q, outputs=out)

    return gr.Row(student_tab)
