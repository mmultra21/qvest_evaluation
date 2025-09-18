import gradio as gr


def librarian_tab():
    with gr.Column():
        gr.Markdown("""## Librarian tab\n\nPlaceholder UI for librarians.""")
        doc = gr.File(label="Upload document")
        out = gr.Textbox(label="Result")
        run = gr.Button("Process")

        def handle(file):
            return "Received file: " + (file.name if file else "none")

        run.click(handle, inputs=doc, outputs=out)

    return gr.Row(librarian_tab)
