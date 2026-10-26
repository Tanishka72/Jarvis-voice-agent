"""Chat with Jarvis THROUGH THE BACKEND API, in the terminal.

Like `agent.py --text`, but every question travels over HTTP to the API server, so you can
see the backend working. Start the server first (in another terminal):

    .\\.venv\\Scripts\\python.exe -m uvicorn backend.main:app --reload

Then run:

    .\\.venv\\Scripts\\python.exe try_api.py
"""
import time

import requests

API = "http://127.0.0.1:8000"


def main():
    try:
        requests.get(f"{API}/health", timeout=3)
    except requests.ConnectionError:
        print("The API server is not running. Start it first:\n"
              "    .\\.venv\\Scripts\\python.exe -m uvicorn backend.main:app --reload")
        return

    key = input("Paste your API key (starts with jv_): ").strip()
    headers = {"X-API-Key": key}

    r = requests.post(f"{API}/api/conversations", json={}, headers=headers, timeout=10)
    if r.status_code == 401:
        print("That key is not valid. Create one with:\n"
              '    .\\.venv\\Scripts\\python.exe -m backend.manage create-key "me"')
        return
    chat_id = r.json()["id"]
    print(f"\nConnected. New chat number {chat_id}. Type your question (or 'quit').\n")

    while True:
        question = input("You: ").strip()
        if question.lower() in ("quit", "exit", "bye"):
            break
        if not question:
            continue
        print("(Jarvis is thinking...)")
        started = time.time()
        r = requests.post(f"{API}/api/conversations/{chat_id}/messages",
                          json={"content": question}, headers=headers, timeout=120)
        seconds = time.time() - started
        if r.status_code == 201:
            source = "instant, from memory" if r.json().get("from_cache") else "from Gemini"
            print(f"Jarvis ({seconds:.2f} s, {source}): {r.json()['reply']['content']}\n")
        else:
            print(f"Error {r.status_code}: {r.json()['error']['message']}\n")


if __name__ == "__main__":
    main()
