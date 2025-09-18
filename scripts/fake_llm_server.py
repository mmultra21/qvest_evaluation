"""
Simple fake LLM server for local testing.
Responds to /completion (returns {content: str}) and /v1/chat/completions (OpenAI-like).
Run with: python scripts/fake_llm_server.py
"""
from flask import Flask, request, jsonify
import json

app = Flask(__name__)

EXAMPLE_ITEMS = {
    "items": [
        {"catalog_id": "bk1", "pitch": "Soccer Stars: A new striker joins a team and learns to pass and trust.", "why": "Good match: aligns with interests in sports. Lexile 800 fits Grade 4 range.", "shelf": "G5-SPO-12"},
        {"catalog_id": "bk2", "pitch": "Mystery Bus: A field trip detours into a small-town riddle to solve.", "why": "A fun pick to broaden interests and practice grade-level reading. Lexile 750 fits Grade 4 range.", "shelf": "G5-MYS-07"},
    ]
}

@app.route('/completion', methods=['POST'])
def completion():
    # Return a json-like content string under 'content'
    # Wrap in ```json fences to simulate LLM output
    body = request.get_json(silent=True) or {}
    resp_text = '```json ' + json.dumps(EXAMPLE_ITEMS) + ' ```'
    return jsonify({'content': resp_text})

@app.route('/v1/chat/completions', methods=['POST'])
def chat_completion():
    # Return OpenAI style response
    body = request.get_json(silent=True) or {}
    return jsonify({'choices': [{'message': {'content': '```json ' + json.dumps(EXAMPLE_ITEMS) + ' ```'}}]})

if __name__ == '__main__':
    # Bind to 127.0.0.1:11434
    app.run(host='127.0.0.1', port=11434)
