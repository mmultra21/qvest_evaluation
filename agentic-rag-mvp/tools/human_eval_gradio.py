"""Simple Gradio A/B human preference labeling UI for LLM blurbs.
Saves results to data/human_eval_results.csv
Guarded imports so the file can be imported in environments without Gradio.
"""

try:
    import gradio as gr
    import pandas as pd
    from datetime import datetime
    import os
    HAS_GRADIO = True
except Exception:
    HAS_GRADIO = False

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
RESULTS_PATH = os.path.join(DATA_DIR, 'human_eval_results.csv')

# Ensure data dir exists when running interactively
if HAS_GRADIO:
    os.makedirs(DATA_DIR, exist_ok=True)

# Small synthetic example set — in practice you'd load real prompts/blurbs
EXAMPLES = [
    {
        'prompt': 'Recommend a beginner Python book',
        'blurb_a': 'Start with "Automate the Boring Stuff with Python" — it covers practical exercises and real-world tasks.',
        'blurb_b': 'Try "Advanced Python Programming" — it dives into advanced concepts and best practices.'
    },
    {
        'prompt': 'Suggest a fun chapter book for 10-year-olds',
        'blurb_a': '"The Enchanted Forest" is full of whimsical characters and short chapters perfect for new readers.',
        'blurb_b': '"The Tower Mysteries" offers a long-form mystery with a slow-burn narrative.'
    }
]


def append_result(row: dict):
    """Append a result row to the CSV (create header if needed)."""
    try:
        df = pd.DataFrame([row])
        if not os.path.exists(RESULTS_PATH):
            df.to_csv(RESULTS_PATH, index=False)
        else:
            df.to_csv(RESULTS_PATH, mode='a', header=False, index=False)
    except Exception:
        # Silently ignore in non-interactive/demo env
        pass


def make_interface():
    if not HAS_GRADIO:
        raise RuntimeError('Gradio not available in this environment')

    with gr.Blocks() as demo:
        idx = gr.State(0)
        prompt = gr.Textbox(label='Prompt', interactive=False)
        blurb_a = gr.Textbox(label='Blurb A', interactive=False)
        blurb_b = gr.Textbox(label='Blurb B', interactive=False)
        choice = gr.Radio(['A', 'B', 'No preference'], label='Choose preferred blurb')
        comment = gr.Textbox(label='Optional comment')
        submit = gr.Button('Submit')
        next_btn = gr.Button('Next')
        status = gr.Text(value='', interactive=False)

        def load_example(i: int):
            ex = EXAMPLES[i % len(EXAMPLES)]
            return ex['prompt'], ex['blurb_a'], ex['blurb_b']

        def on_submit(current_idx, chosen, comm):
            ex = EXAMPLES[current_idx % len(EXAMPLES)]
            row = {
                'ts': datetime.utcnow().isoformat(),
                'prompt': ex['prompt'],
                'blurb_a': ex['blurb_a'],
                'blurb_b': ex['blurb_b'],
                'choice': chosen,
                'comment': comm
            }
            append_result(row)
            return 'Saved', (current_idx + 1)

        def on_next(current_idx):
            # Return separate outputs: prompt, blurb_a, blurb_b, new_idx
            ex = EXAMPLES[(current_idx + 1) % len(EXAMPLES)]
            return ex['prompt'], ex['blurb_a'], ex['blurb_b'], (current_idx + 1)

        # Initial load
        prompt_a, a_text, b_text = load_example(0)
        prompt.value = prompt_a
        blurb_a.value = a_text
        blurb_b.value = b_text

        submit.click(on_submit, inputs=[idx, choice, comment], outputs=[status, idx])
        next_btn.click(on_next, inputs=[idx], outputs=[prompt, blurb_a, blurb_b, idx])

    return demo


if __name__ == '__main__':
    if not HAS_GRADIO:
        print('Gradio not available — cannot launch interface here.')
    else:
        demo = make_interface()
        demo.launch(server_name='127.0.0.1', server_port=7861)
