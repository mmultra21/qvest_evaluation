import gradio as gr, requests, os

API = os.getenv("API_BASE", "http://127.0.0.1:8000")

def load_banner():
    try:
        c = requests.get(f"{API}/campaign/current", timeout=10).json()
        top = ", ".join(c.get("seed_list", [])) or "surprise picks"
        return f"**{c.get('title','Weekly Campaign')}**  \n{c.get('prize_rules','')}  \n_Featured IDs:_ {top}"
    except Exception:
        return "**Reading Week**  \nRead 1 book to enter the prize drawing!"

def get_top5(grade, interests, bucket):
    rec = requests.post(f"{API}/recommend", json={
        "grade": int(grade), "interests": interests or [], "progress_bucket": bucket, "top_k": 10
    }, timeout=20).json()
    cands = rec.get("candidates", [])
    jus = requests.post(f"{API}/justify", json={
        "candidates": cands,
        "student": {"grade": int(grade), "interests": interests or [], "progress_bucket": bucket},
        "notes": None
    }, timeout=120).json()

    title_by_id = {c["catalog_id"]: c["payload"]["title"] for c in cands}
    cards = []
    for it in jus.get("items", []):
        cards.append({
            "title": title_by_id.get(it["catalog_id"], it["catalog_id"]),
            "pitch": it.get("pitch",""),
            "why": it.get("why",""),
            "shelf": it.get("shelf",""),
        })
    return cards

def refresh_report():
    # Placeholder until metrics tables are wired; keeps UI flowing
    return {
        "checkout_rate_per_student": "0.48 (last 7d)",
        "acceptance_rate": "63%",
        "selection_to_checkout": "41%",
        "repeat_30d": "22%",
        "repeat_60d": "37%",
        "campaign_lift": "+18%",
    }

with gr.Blocks(title="Reading Assistant", theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 📚 Reading Assistant (MVP with Hermes-3)")
    with gr.Tab("Student Assistant"):
        banner = gr.Markdown("Loading weekly campaign…")
        with gr.Row():
            grade = gr.Dropdown(["3","4","5","6"], value="5", label="Grade")
            interests = gr.CheckboxGroup(
                ["sports","animals","fantasy","mystery","graphic novels","short reads","technology","nature"],
                label="Pick a couple interests"
            )
            bucket = gr.Dropdown(["starter","building","streak"], value="starter", label="Reading progress")
        btn = gr.Button("Get my Top 5")
        out = gr.JSON(label="Your picks")

        demo.load(load_banner, outputs=[banner])
        btn.click(get_top5, [grade, interests, bucket], out)

    with gr.Tab("Librarian Console"):
        gr.Markdown("### Weekly KPIs")
        rpt_btn = gr.Button("Refresh Report")
        kpis = gr.JSON()
        rpt_btn.click(refresh_report, outputs=[kpis])

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
